"""Dashboard metrics (Setup guide, Section 10), worked out from what is stored in Firestore."""

from collections import Counter
from datetime import datetime, timedelta, timezone

from google.cloud import firestore

from app.core.config import get_settings
from app.models.dashboard import DailyCount, DashboardMetrics
from app.models.invoice import Decision
from app.models.invoice import InvoiceStatus as S
from app.pipeline.decide import STATUS_FOR

IST = timezone(timedelta(hours=5, minutes=30))
DAYS = 14
MAX_INVOICES = 10_000  # read in one pass; past this the dashboard needs stored aggregates

FIELDS = [
    "invoice_id",
    "duplicate_of",
    "status",
    "decision",
    "created_at",
    "status_times",
    "extracted.total_paise",
    "match_result.difference_paise",
    "ai_usage",
    "step_ms",
    "processing_attempts",
]


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def ai_cost_paise(input_tokens: int, output_tokens: int) -> float:
    s = get_settings()
    usd = (
        input_tokens * s.gemini_input_usd_per_mtok + output_tokens * s.gemini_output_usd_per_mtok
    ) / 1_000_000
    return usd * s.usd_to_inr * 100


def metrics(db: firestore.Client, now: datetime | None = None) -> DashboardMetrics:
    s = get_settings()
    docs = [
        d.to_dict() for d in db.collection("invoices").select(FIELDS).limit(MAX_INVOICES).stream()
    ]
    decided = [d for d in docs if d.get("decision")]
    by_id = {d["invoice_id"]: d for d in docs}

    def total_of(d: dict) -> int:
        return (d.get("extracted") or {}).get("total_paise") or 0

    saved = blocked = blocked_paise = 0
    seconds, calls, tokens, latency, cost = [], [], [], [], []
    steps: dict[str, list[float]] = {}
    for d in decided:
        decision = Decision(d["decision"])
        difference = ((d.get("match_result") or {}).get("difference_paise")) or 0
        status = S(d["status"])
        if difference > 0 and status in (S.on_hold, S.posted):
            saved += difference
        if decision == Decision.block:
            blocked += 1
            # A copy of the same file is blocked before it is read: use the original's total.
            original = by_id.get(d.get("duplicate_of") or "", {})
            blocked_paise += total_of(d) or total_of(original)

        times = d.get("status_times") or {}
        start, end = times.get(S.received.value), times.get(STATUS_FOR[decision].value)
        if start and end and end >= start:
            seconds.append((end - start).total_seconds())

        usage = d.get("ai_usage") or {}
        if usage.get("calls"):
            calls.append(usage["calls"])
            tokens.append(usage.get("input_tokens", 0) + usage.get("output_tokens", 0))
            latency.append(usage.get("latency_ms", 0) / 1000)
            cost.append(ai_cost_paise(usage.get("input_tokens", 0), usage.get("output_tokens", 0)))
        for step, ms in (d.get("step_ms") or {}).items():
            steps.setdefault(step, []).append(ms / 1000)

    ledger = [
        e.to_dict() for e in db.collection("ledger_entries").select(["amount_paise"]).stream()
    ]

    today = (now or datetime.now(IST)).astimezone(IST).date()
    days = [today - timedelta(days=n) for n in range(DAYS - 1, -1, -1)]
    uploaded = Counter(d["created_at"].astimezone(IST).date() for d in docs)
    decided_on = Counter()
    for d in decided:
        when = (d.get("status_times") or {}).get(STATUS_FOR[Decision(d["decision"])].value)
        if when:
            decided_on[when.astimezone(IST).date()] += 1

    return DashboardMetrics(
        invoices_uploaded=len(docs),
        invoices_processed=len(decided),
        decision_counts=dict(Counter(d["decision"] for d in decided)),
        status_counts=dict(Counter(d["status"] for d in docs)),
        waiting_for_approval=sum(1 for d in docs if d["status"] == S.pending_approval.value),
        posted_count=len(ledger),
        posted_paise=sum(e["amount_paise"] for e in ledger),
        money_saved_paise=saved,
        duplicates_blocked=blocked,
        duplicates_blocked_paise=blocked_paise,
        avg_processing_seconds=_avg(seconds),
        avg_step_seconds={k: _avg(v) for k, v in sorted(steps.items())},
        avg_ai_calls=_avg(calls),
        avg_tokens=_avg(tokens),
        avg_ai_latency_seconds=_avg(latency),
        avg_ai_cost_paise=_avg(cost),
        ai_price_note=f"{s.gemini_model} at ${s.gemini_input_usd_per_mtok:g} input and "
        f"${s.gemini_output_usd_per_mtok:g} output per million tokens, Rs {s.usd_to_inr:g} per $",
        retried_invoices=sum(1 for d in docs if (d.get("processing_attempts") or 0) > 1),
        daily=[
            DailyCount(date=day.isoformat(), uploaded=uploaded[day], decided=decided_on[day])
            for day in days
        ],
    )
