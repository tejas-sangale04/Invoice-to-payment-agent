import json
import logging

from app.core.logging import JsonFormatter, log_context


def line(message: str, **extra) -> dict:
    record = logging.LogRecord("app", logging.INFO, __file__, 1, message, None, None)
    for k, v in extra.items():
        setattr(record, k, v)
    return json.loads(JsonFormatter().format(record))


def test_pipeline_context_is_on_every_line() -> None:
    assert "invoice_id" not in line("outside")
    with log_context(invoice_id="INV-7"), log_context(step="extracting"):
        entry = line("inside")
    assert (entry["invoice_id"], entry["step"]) == ("INV-7", "extracting")
    assert "invoice_id" not in line("after")


def test_extra_fields_win_over_the_context() -> None:
    with log_context(invoice_id="INV-7"):
        assert line("x", invoice_id="INV-8")["invoice_id"] == "INV-8"
