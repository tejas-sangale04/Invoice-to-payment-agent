"""Explanation Agent: Gemini (via Google ADK) explains why an invoice wasn't paid automatically
and drafts an email to the supplier.

It only writes. The facts it gets, including every amount, come from code (match_result and
the decision); code then checks the text before it is used (app/pipeline/explain.py).
"""

import json
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
You write for an Indian accounts-payable team. Code has already checked a supplier invoice and
decided it can't be paid automatically. You get the facts as JSON. Return ONLY a JSON object
matching the response schema.

Rules:
1. Use only the facts given. Never calculate, round, convert or invent a number, date, name,
   PO or reason. Write every amount exactly as it appears in the facts, e.g. "Rs 4,050.00".
2. explanation: 2 to 4 short sentences in plain English for a manager: what is wrong, what it
   means in money, and what happens next (from "next_step"). Mention every amount listed in
   "amounts_to_mention".
3. supplier_email: only if "write_supplier_email" is true, otherwise null. A short, polite
   plain-text email to the supplier. First line "Subject: ...". Mention the invoice number,
   the PO if there is one, every amount in "amounts_to_mention", and ask for exactly what
   "supplier_action" says. Describe problems only as in "problems_for_supplier": never mention
   our internal checks, other invoices or the agent. Sign off as "Accounts Payable". No
   placeholders such as [Name].
4. Never say the invoice is approved or will be paid. If "rejected" is true, the supplier email
   says plainly that the invoice has been rejected and will not be paid as it stands, then
   asks for what "supplier_action" says.
""".strip()


class LlmExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    explanation: str = Field(description="2 to 4 sentences for the manager")
    supplier_email: str | None = Field(
        default=None, description="Email to the supplier, or null when not asked for"
    )


@dataclass
class ExplanationCall:
    parsed: LlmExplanation | None
    error: str | None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


class Explainer(Protocol):
    def explain(self, facts: dict, feedback: str | None = None) -> ExplanationCall: ...


class GeminiExplainer:
    def __init__(self, model: str | BaseLlm, timeout_seconds: float) -> None:
        self.agent = LlmAgent(
            name="explanation_agent",
            model=model,
            instruction=INSTRUCTION,
            output_schema=LlmExplanation,
            generate_content_config=types.GenerateContentConfig(temperature=0),
        )
        self.timeout = timeout_seconds

    def explain(self, facts: dict, feedback: str | None = None) -> ExplanationCall:
        prompt = "Facts:\n" + json.dumps(facts, indent=2, ensure_ascii=False)
        if feedback:
            prompt += (
                "\n\nYour previous answer failed these checks:\n"
                f"{feedback}\n\nWrite it again, using only the facts above."
            )
        reply = run_agent(self.agent, prompt, self.timeout)
        parsed, error = parse_json(reply.text, LlmExplanation)
        return ExplanationCall(
            parsed, error, reply.input_tokens, reply.output_tokens, reply.latency_ms
        )


@lru_cache
def get_explainer() -> Explainer | None:
    """None when the agents are switched off; the template is used instead."""
    s = get_settings()
    return GeminiExplainer(s.gemini_model, s.gemini_timeout_seconds) if s.agents_enabled else None
