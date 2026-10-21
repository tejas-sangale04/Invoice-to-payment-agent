"""Extraction Agent: Gemini (via Google ADK) reads an invoice PDF or image into LlmInvoice.

The agent only reads. It never calculates or decides anything: code converts and checks its
output (app/pipeline/validate.py), and invalid output is never used.
"""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from google.adk.agents import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import ValidationError

from app.agents.schemas import LlmInvoice
from app.core.config import get_settings

APP_NAME = "invoiceflow"

INSTRUCTION = """
You read supplier invoices for an Indian accounts-payable team. You will receive one invoice
as a PDF or image. Return ONLY a JSON object matching the response schema.

Rules:
1. Copy what is printed. Never calculate, correct, round or fill in a value that is not
   printed. If a value is not on the invoice, use null.
2. Money: rupees exactly as printed, e.g. "3,000.00". Do not convert to paise.
3. Quantities: the number only, e.g. "50" or "2.5". Put the unit (L, kg, pcs) in "unit".
4. unit_price and amount are BEFORE tax. tax_rate is the total GST percent for that line
   (for CGST 9% + SGST 9% use "18").
5. CGST and SGST are for intra-state supply, IGST for inter-state. Copy only the ones printed.
6. invoice_date in YYYY-MM-DD. Indian invoices usually print dates day first (20/10/2026 is
   20 October 2026).
7. po_number is the BUYER's purchase order number (often labelled PO, P.O. No, Order No).
   Do not use the supplier's own invoice, challan or reference numbers.
8. field_confidence: for each field, how sure you are (0 to 1) that you read it correctly.
   If a field is clearly not printed and you returned null, that is a confident reading: 1.0.
   Use low values for blurry, cut-off or ambiguous text. Be honest; low confidence sends the
   invoice to a person, which is safe.
""".strip()


class ExtractionTimeout(Exception):
    """Gemini did not answer in time. Raised so the background task retries."""


@dataclass
class ExtractionCall:
    parsed: LlmInvoice | None
    error: str | None  # why the output could not be used, fed back on the retry
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


class Extractor(Protocol):
    def extract(
        self, data: bytes, mime_type: str, feedback: str | None = None
    ) -> ExtractionCall: ...


def parse_output(text: str) -> tuple[LlmInvoice | None, str | None]:
    """Validate the model's text against the schema. Never returns partially valid data."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        cleaned = cleaned.rsplit("```", 1)[0]
    try:
        return LlmInvoice.model_validate(json.loads(cleaned)), None
    except json.JSONDecodeError as exc:
        return None, f"The response was not valid JSON ({exc.msg})"
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()[:10]
        )
        return None, f"The response did not match the schema: {problems}"


def build_agent(model: str | BaseLlm) -> LlmAgent:
    return LlmAgent(
        name="extraction_agent",
        model=model,
        instruction=INSTRUCTION,
        output_schema=LlmInvoice,
        generate_content_config=types.GenerateContentConfig(temperature=0),
    )


class GeminiExtractor:
    def __init__(self, model: str | BaseLlm, timeout_seconds: float) -> None:
        self.agent = build_agent(model)
        self.timeout = timeout_seconds

    async def _run(self, data: bytes, mime_type: str, feedback: str | None) -> ExtractionCall:
        sessions = InMemorySessionService()
        session_id = uuid.uuid4().hex
        await sessions.create_session(app_name=APP_NAME, user_id="agent", session_id=session_id)
        runner = Runner(agent=self.agent, app_name=APP_NAME, session_service=sessions)

        prompt = "Read this invoice."
        if feedback:
            prompt += (
                "\n\nYour previous reading of this same invoice failed these checks:\n"
                f"{feedback}\n\nLook at the invoice again carefully and return a corrected "
                "reading. Still copy only what is printed: if the invoice itself is wrong, "
                "keep the printed values and lower the confidence of the affected fields."
            )
        message = types.Content(
            role="user",
            parts=[
                types.Part.from_text(text=prompt),
                types.Part.from_bytes(data=data, mime_type=mime_type),
            ],
        )

        text, input_tokens, output_tokens = "", 0, 0
        async for event in runner.run_async(
            user_id="agent", session_id=session_id, new_message=message
        ):
            if event.usage_metadata:
                input_tokens += event.usage_metadata.prompt_token_count or 0
                output_tokens += event.usage_metadata.candidates_token_count or 0
            if event.is_final_response() and event.content and event.content.parts:
                text += "".join(p.text or "" for p in event.content.parts)
        parsed, error = parse_output(text)
        return ExtractionCall(parsed, error, input_tokens, output_tokens)

    def extract(self, data: bytes, mime_type: str, feedback: str | None = None) -> ExtractionCall:
        started = time.monotonic()
        try:
            call = asyncio.run(asyncio.wait_for(self._run(data, mime_type, feedback), self.timeout))
        except TimeoutError as exc:
            raise ExtractionTimeout(f"Gemini did not answer within {self.timeout:.0f}s") from exc
        call.latency_ms = int((time.monotonic() - started) * 1000)
        return call


@lru_cache
def get_extractor() -> Extractor | None:
    """None when extraction is switched off (local dev without Google Cloud credentials)."""
    s = get_settings()
    if s.extractor == "disabled":
        return None
    return GeminiExtractor(s.gemini_model, s.gemini_timeout_seconds)
