"""Turns scored runs into the evaluation report, saved as Markdown and JSON."""

import json
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path

from scenarios import KINDS
from scoring import FIELDS

SPLITS = {"all": "dev + holdout", "dev": "dev split", "holdout": "holdout split"}
DECISIONS = ["auto_approve", "manager_approval", "hold", "block", "needs_review", "failed"]


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.1f}%)" if d else "n/a"


def _runs(cases: list[dict]):
    for case in cases:
        for n, run in enumerate(case["runs"], 1):
            yield case, n, run


def summarize(meta: dict, cases: list[dict], failures: list[dict]) -> dict:
    runs = list(_runs(cases))
    measured = meta["agents"] == "gemini"

    def listing(pred, detail=lambda c, n, r: None) -> list[dict]:
        return [
            {"case": c["id"], "run": n, "expected": c["expect"]["decision"],
             "decision": r["decision"], "detail": detail(c, n, r)}
            for c, n, r in runs if pred(r)
        ]  # fmt: skip

    confusion = {e: Counter() for e in DECISIONS}
    for c, _, r in runs:
        confusion[c["expect"]["decision"]][r["decision"]] += 1

    by_kind = {}
    for kind in KINDS:
        rs = [r for c, _, r in runs if c["kind"] == kind]
        if rs:
            by_kind[kind] = {"runs": len(rs), "decision_ok": sum(r["decision_ok"] for r in rs)}
    by_split = {}
    for split in ("dev", "holdout"):
        rs = [r for c, _, r in runs if c["split"] == split]
        by_split[split] = {"runs": len(rs), "decision_ok": sum(r["decision_ok"] for r in rs)}

    with_fields = [r["fields"] for _, _, r in runs if r["fields"] is not None]
    extraction = None
    if measured and with_fields:
        extraction = {
            "invoices": len(with_fields),
            "per_field": {f: sum(x[f] for x in with_fields) for f in FIELDS},
            "all_fields_right": sum(all(x.values()) for x in with_fields),
        }

    expl = [
        r["explanation"] for _, _, r in runs if r["explanation"] and r["explanation"]["expected"]
    ]
    judged = [r["judge"] for _, _, r in runs if r.get("judge") and "score" in r["judge"]]
    explanations = {
        "expected": len(expl),
        "present": sum(e["present"] for e in expl),
        "amounts_ok": sum(e["amounts_ok"] for e in expl),
        "sources": dict(Counter(e["source"] or "none" for e in expl)),
        "judge": None
        if not judged
        else {
            "judged": len(judged),
            "errors": sum(1 for _, _, r in runs if r.get("judge") and "error" in r["judge"]),
            "average": statistics.mean(j["score"] for j in judged),
            **{
                k: statistics.mean(j[k] for j in judged)
                for k in ("accuracy", "clarity", "action", "email")
            },
        },
    }

    consistency = [
        {"case": c["id"], "decisions": [r["decision"] for r in c["runs"]]}
        for c in cases
        if len(c["runs"]) > 1
    ]
    walls = [r["wall_ms"] for _, _, r in runs]
    ai = [r["ai"] for _, _, r in runs]
    performance = {
        "wall_ms_mean": statistics.mean(walls) if walls else None,
        "wall_ms_p50": statistics.median(walls) if walls else None,
        "wall_ms_p95": sorted(walls)[int(0.95 * (len(walls) - 1))] if walls else None,
        "ai_calls_mean": statistics.mean(a["calls"] for a in ai) if ai else None,
        "ai_latency_ms_mean": statistics.mean(a["latency_ms"] for a in ai) if ai else None,
        "input_tokens_mean": statistics.mean(a["input_tokens"] for a in ai) if ai else None,
        "output_tokens_mean": statistics.mean(a["output_tokens"] for a in ai) if ai else None,
        "cost_inr_mean": statistics.mean(r["cost_inr"] for _, _, r in runs) if runs else None,
    }

    decided = [r for _, _, r in runs if r["decision_ok"]]
    amounts = [r["correct_amount_ok"] for _, _, r in runs if r["correct_amount_ok"] is not None]
    return {
        "meta": meta,
        "cases": len(cases),
        "runs": len(runs),
        "safety": {
            "wrong_approvals": listing(lambda r: r["wrong_approval"]),
            "paid_wrongly": listing(lambda r: r["paid_wrongly"]),
            "duplicates_paid": listing(lambda r: r["duplicate_paid"]),
            "wrong_amounts": listing(
                lambda r: r["wrong_amounts"], lambda c, n, r: r["wrong_amounts"]
            ),
        },
        "decision_accuracy": {"runs": len(runs), "correct": len(decided)},
        "by_split": by_split,
        "by_kind": by_kind,
        "confusion": {e: dict(v) for e, v in confusion.items()},
        "held_unnecessarily": {
            "payable_runs": sum(
                1
                for c, _, r in runs
                if c["expect"]["decision"] in ("auto_approve", "manager_approval")
            ),  # fmt: skip
            "cases": listing(
                lambda r: r["held_unnecessarily"], lambda c, n, r: r["decision_reason"]
            ),
        },
        "end_state": {
            "checked": len(decided),
            "ok": sum(r["end_state_ok"] for r in decided),
            "problems": listing(
                lambda r: r["decision_ok"] and not r["end_state_ok"],
                lambda c, n, r: r["end_state_problems"],
            ),
        },
        "correct_amount": {"checked": len(amounts), "ok": sum(amounts)},
        "extraction": extraction,
        "explanations": explanations,
        "consistency": {
            "cases": len(consistency),
            "consistent": sum(len(set(x["decisions"])) == 1 for x in consistency),
            "inconsistent": [x for x in consistency if len(set(x["decisions"])) > 1],
        },
        "performance": performance,
        "mismatches": listing(
            lambda r: not r["decision_ok"],
            lambda c, n, r: {
                "rule": r["rule"],
                "reason": r["decision_reason"],
                "issues": r["validation_issues"],
            },  # fmt: skip
        ),
        "failure_injection": failures,
    }


# ------------------------------------------------------------------------------ Markdown


def _table(head: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(x) for x in row) + " |" for row in rows]
    return out + [""]


def _cases(items: list[dict]) -> str:
    return ", ".join(f"{i['case']} (run {i['run']})" for i in items) or "none"


def markdown(s: dict) -> str:
    m = s["meta"]
    measured = m["agents"] == "gemini"
    out = [
        f"# InvoiceFlow evaluation, {m['started_at']}",
        "",
        f"- Agents: **{m['agents']}**"
        + (f" ({m['model']} on Vertex AI)" if measured else " (ground-truth stand-ins, no Gemini)"),
        f"- Test set: {SPLITS[m['split']]}, {s['cases']} cases, {m['runs_per_case']} run(s) each "
        f"= {s['runs']} runs",
        f"- Business rules: price tolerance {m['rules']['price_tolerance_percent']}%, "
        f"auto-approve limit Rs {m['rules']['auto_approve_max_paise'] / 100:,.0f}, "
        f"min field confidence {m['rules']['min_field_confidence']}",
        f"- Code: {m['git']}",
        "",
    ]
    if not measured:
        out += [
            "> With `--agents oracle` the Gemini agents are replaced by stand-ins that return the "
            "ground truth, so this run checks validation, matching, decisions, approval, posting "
            "and the end state, but says nothing about Gemini's accuracy, explanations or cost. "
            "Run with `--agents gemini` for those numbers.",
            "",
        ]

    sf = s["safety"]
    out += ["## Safety", ""]
    checks = [
        ("Wrong invoices auto-approved", "wrong_approvals"),
        ("Posted when it should not have been", "paid_wrongly"),
        ("Duplicates paid", "duplicates_paid"),
        ("Wrong amount posted", "wrong_amounts"),
    ]
    out += _table(
        ["Check", "Target", "Result", "Cases"],
        [[label, 0, len(sf[key]), _cases(sf[key])] for label, key in checks],
    )

    da = s["decision_accuracy"]
    out += ["## Decisions", "", f"Decision accuracy: **{_pct(da['correct'], da['runs'])}**", ""]
    out += _table(
        ["Split", "Runs", "Correct decision"],
        [[k, v["runs"], _pct(v["decision_ok"], v["runs"])] for k, v in s["by_split"].items()],
    )
    out += _table(
        ["Case type", "Runs", "Correct decision"],
        [[KINDS[k], v["runs"], _pct(v["decision_ok"], v["runs"])] for k, v in s["by_kind"].items()],
    )
    out += ["Confusion matrix (rows: expected, columns: actual):", ""]
    used = [d for d in DECISIONS if any(s["confusion"][e].get(d) for e in DECISIONS) or
            any(s["confusion"][d].values())]  # fmt: skip
    out += _table(
        ["expected \\ actual", *used],
        [[e, *[s["confusion"][e].get(a, 0) for a in used]] for e in used],
    )
    held = s["held_unnecessarily"]
    out += [
        f"Correct invoices held unnecessarily: **{_pct(len(held['cases']), held['payable_runs'])}**"
        f" of runs that should have been approved. {_cases(held['cases'])}",
        "",
    ]

    es, ca = s["end_state"], s["correct_amount"]
    out += [
        "## End state",
        "",
        f"- Ledger amounts, no duplicate entries and PO billing status as expected: "
        f"**{_pct(es['ok'], es['checked'])}** of runs with the right decision.",
        f"- Correct amount computed by the 3-way match: **{_pct(ca['ok'], ca['checked'])}** of "
        "runs matched to a PO.",
    ]
    for p in es["problems"]:
        out.append(f"  - {p['case']} (run {p['run']}): {'; '.join(p['detail'])}")
    out.append("")

    out += ["## Extraction", ""]
    ex = s["extraction"]
    if ex is None:
        out += ["Not measured: the readings came from the ground truth.", ""]
    else:
        n = ex["invoices"]
        out += [f"Invoices with every field right: **{_pct(ex['all_fields_right'], n)}**", ""]
        out += _table(["Field", "Accuracy"], [[f, _pct(c, n)] for f, c in ex["per_field"].items()])

    e = s["explanations"]
    out += ["## Explanations", ""]
    out += [
        f"- Written where expected: {_pct(e['present'], e['expected'])} "
        f"(sources: {', '.join(f'{k} {v}' for k, v in e['sources'].items()) or 'none'})",
        f"- Mention the invoice total, and for wrong amounts the correct amount and difference: "
        f"**{_pct(e['amounts_ok'], e['expected'])}**",
    ]
    j = e["judge"]
    if j:
        out.append(
            f"- LLM judge (1-5): **{j['average']:.2f}** average over {j['judged']} explanations "
            f"(accuracy {j['accuracy']:.2f}, clarity {j['clarity']:.2f}, action "
            f"{j['action']:.2f}, supplier email {j['email']:.2f}); {j['errors']} judge errors"
        )
    else:
        out.append("- LLM judge: not run" + ("" if measured else " (needs `--agents gemini`)"))
    out.append("")

    c = s["consistency"]
    out += ["## Consistency", ""]
    if c["cases"]:
        out.append(f"Same decision on every run: **{_pct(c['consistent'], c['cases'])}** of cases.")
        for x in c["inconsistent"]:
            out.append(f"- {x['case']}: {', '.join(x['decisions'])}")
    else:
        out.append("Not measured (one run per case).")
    out.append("")

    p = s["performance"]
    out += ["## Latency and cost per invoice", ""]
    rows = [
        ["Upload to final status (mean / p50 / p95)",
         f"{p['wall_ms_mean'] / 1000:.2f} s / {p['wall_ms_p50'] / 1000:.2f} s / "
         f"{p['wall_ms_p95'] / 1000:.2f} s"],
    ]  # fmt: skip
    if measured:
        rows += [
            ["Gemini calls", f"{p['ai_calls_mean']:.2f}"],
            ["Time waiting for Gemini", f"{p['ai_latency_ms_mean'] / 1000:.2f} s"],
            ["Tokens in / out", f"{p['input_tokens_mean']:,.0f} / {p['output_tokens_mean']:,.0f}"],
            ["AI cost", f"Rs {p['cost_inr_mean']:.3f} (at {m['prices']})"],
        ]
    out += _table(["Mean per invoice", "Value"], rows)
    if not measured:
        out += [
            "Times are for the emulator with no model calls; they are not production latency.",
            "",
        ]

    out += ["## Failure injection", ""]
    if s["failure_injection"]:
        out += _table(
            ["Failure", "Expected safe outcome", "Actual", "Result"],
            [[f["name"], f["expected"], f["actual"], "PASS" if f["passed"] else "FAIL"]
             for f in s["failure_injection"]],
        )  # fmt: skip
    else:
        out += ["Not run.", ""]

    out += ["## Wrong decisions", ""]
    if s["mismatches"]:
        rows = []
        for x in s["mismatches"]:
            why = x["detail"]["reason"] or "; ".join(x["detail"]["issues"]) or ""
            rows.append([x["case"], x["run"], x["expected"], x["decision"], why.replace("|", "/")])
        out += _table(["Case", "Run", "Expected", "Actual", "Why"], rows)
    else:
        out += ["None.", ""]
    return "\n".join(out)


def save(summary: dict, cases: list[dict], folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromisoformat(summary["meta"]["started_at"]).strftime("%Y%m%d-%H%M%S")
    base = folder / f"{stamp}-{summary['meta']['agents']}-{summary['meta']['split']}"
    base.with_suffix(".md").write_text(markdown(summary) + "\n")
    base.with_suffix(".json").write_text(
        json.dumps({"summary": summary, "cases": cases}, indent=2, ensure_ascii=False, default=str)
        + "\n"
    )
    return base.with_suffix(".md")
