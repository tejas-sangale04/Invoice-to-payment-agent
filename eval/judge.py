"""LLM judge for explanations (`--agents gemini` only): Gemini scores each explanation and
supplier email against a rubric, given the case's ground truth.

The judge's tokens are not counted in the per-invoice AI cost; the app never pays for them.
"""

import json

from google.adk.agents import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field

from app.agents.runtime import parse_json, run_agent
from app.core.config import get_settings
from app.pipeline.money import rupees

RUBRIC = """
You review explanations written by an accounts-payable assistant for invoices it did not
auto-approve. You get the ground truth for the invoice (what is really wrong with it and the
correct amounts) and what the assistant wrote. Score each criterion from 1 (poor) to 5 (excellent):

- accuracy: every fact and amount agrees with the ground truth; nothing is invented.
- clarity: a manager understands in one read what happened and why.
- action: it says what happens next or what to ask the supplier, and it fits the decision.
- email: the supplier email (if one was needed) is polite, specific (invoice number, PO, the
  amounts) and asks for the right fix. If no email was needed and none was written, score 5;
  if one was needed and is missing, score 1.

Return ONLY a JSON object: {"accuracy": n, "clarity": n, "action": n, "email": n,
"comment": "one sentence on the biggest problem, or 'none'"}.
""".strip()


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accuracy: int = Field(ge=1, le=5)
    clarity: int = Field(ge=1, le=5)
    action: int = Field(ge=1, le=5)
    email: int = Field(ge=1, le=5)
    comment: str = ""

    @property
    def score(self) -> float:
        return (self.accuracy + self.clarity + self.action + self.email) / 4


class Judge:
    def __init__(self, model: str | BaseLlm | None = None) -> None:
        s = get_settings()
        self.timeout = s.gemini_timeout_seconds
        self.agent = LlmAgent(
            name="explanation_judge",
            model=model or s.gemini_model,
            instruction=RUBRIC,
            generate_content_config=types.GenerateContentConfig(temperature=0),
        )

    def __call__(self, truth: dict, explanation: str, email: str | None) -> dict | None:
        expect = truth["expect"]
        facts = {
            "what_is_wrong": truth["description"],
            "correct_decision": expect["decision"],
            "invoice_total": rupees(expect["invoice_total_paise"])
            if expect["invoice_total_paise"] is not None
            else "unreadable",
            "correct_amount": rupees(expect["correct_amount_paise"])
            if expect["correct_amount_paise"] is not None
            else "not applicable",
            # The supplier has something to fix: a wrong amount, or a missing or unknown PO.
            "supplier_email_needed": expect["decision"] == "hold"
            or expect["rule"] in ("price_within_tolerance", "no_matching_po"),
        }
        prompt = (
            "Ground truth:\n" + json.dumps(facts, indent=2) + "\n\nExplanation:\n" + explanation
            + "\n\nSupplier email:\n" + (email or "(none)")
        )  # fmt: skip
        try:
            reply = run_agent(self.agent, prompt, self.timeout)
        except Exception as exc:  # a failed judgement is reported, never fatal
            return {"error": f"{type(exc).__name__}: {exc}"}
        verdict, error = parse_json(reply.text, Verdict)
        if verdict is None:
            return {"error": error}
        return {**verdict.model_dump(), "score": verdict.score}
