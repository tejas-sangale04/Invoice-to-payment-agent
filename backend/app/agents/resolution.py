"""Resolution Agent: Gemini (via Google ADK) looks for the purchase order of an invoice that has
no PO number, using a search tool over the supplier's open POs.

It only proposes. Code checks the proposal (app/pipeline/resolve.py), and an invoice matched
this way always goes to a manager.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from google.adk.agents import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field

from app.agents.runtime import parse_json, run_agent
from app.core.config import get_settings

INSTRUCTION = """
You find the buyer's purchase order (PO) for a supplier invoice that has no PO number printed
on it. You get the invoice as JSON. Use the search_open_purchase_orders tool to look through
the supplier's open POs; you may call it more than once, for example with one item name, or
without filters.

A PO fits when every invoice line is on it (names can differ in wording, e.g. "Milk" and
"Full cream milk"), in the same unit, and each billed quantity is no more than "can_bill_now"
(received and not yet billed) for that line. Only if no PO fits that way, use "can_still_bill"
(ordered and not yet billed) instead. Prefer a PO ordered on or before the invoice date.

If exactly one PO fits, return it. If none fits, or more than one fits and nothing tells them
apart, return null: a person will choose. Never guess.

Return ONLY a JSON object: {"po_number": "PO-12" or null, "reasoning": "one or two sentences
naming the lines and quantities that fit, or why none does"}.
""".strip()


class LlmResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    po_number: str | None = None
    reasoning: str = Field(default="", description="Why this PO, or why none")


@dataclass
class ResolutionCall:
    parsed: LlmResolution | None
    error: str | None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


SearchTool = Callable[..., dict]


class Resolver(Protocol):
    def resolve(self, invoice: dict, search: SearchTool) -> ResolutionCall: ...


class GeminiResolver:
    def __init__(self, model: str | BaseLlm, timeout_seconds: float) -> None:
        self.model = model
        self.timeout = timeout_seconds

    def resolve(self, invoice: dict, search: SearchTool) -> ResolutionCall:
        # The tool is bound to this invoice's supplier, so the agent is built per call.
        agent = LlmAgent(
            name="resolution_agent",
            model=self.model,
            instruction=INSTRUCTION,
            tools=[search],
            generate_content_config=types.GenerateContentConfig(temperature=0),
        )
        prompt = "Invoice:\n" + json.dumps(invoice, indent=2, ensure_ascii=False)
        reply = run_agent(agent, prompt, self.timeout)
        parsed, error = parse_json(reply.text, LlmResolution)
        return ResolutionCall(
            parsed, error, reply.input_tokens, reply.output_tokens, reply.latency_ms
        )


@lru_cache
def get_resolver() -> Resolver | None:
    """None when the agents are switched off; invoices without a PO number go to a person."""
    s = get_settings()
    return GeminiResolver(s.gemini_model, s.gemini_timeout_seconds) if s.agents_enabled else None
