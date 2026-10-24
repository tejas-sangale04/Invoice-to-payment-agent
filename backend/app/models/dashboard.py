from pydantic import BaseModel


class DailyCount(BaseModel):
    date: str  # YYYY-MM-DD, India time
    uploaded: int
    decided: int


class DashboardMetrics(BaseModel):
    """Computed from the invoices and ledger in Firestore; nothing here is estimated except
    the AI cost, which is the recorded tokens at the configured prices."""

    invoices_uploaded: int
    invoices_processed: int  # reached a decision
    decision_counts: dict[str, int]
    status_counts: dict[str, int]
    waiting_for_approval: int
    posted_count: int
    posted_paise: int
    # Overcharges not paid: the difference on invoices on hold, plus the part above the PO
    # price that was not posted for invoices posted at the PO price.
    money_saved_paise: int
    duplicates_blocked: int
    duplicates_blocked_paise: int
    avg_processing_seconds: float | None  # upload to decision
    avg_step_seconds: dict[str, float]
    avg_ai_calls: float | None
    avg_tokens: float | None
    avg_ai_latency_seconds: float | None
    avg_ai_cost_paise: float | None
    ai_price_note: str
    retried_invoices: int  # needed more than one processing attempt
    daily: list[DailyCount]
