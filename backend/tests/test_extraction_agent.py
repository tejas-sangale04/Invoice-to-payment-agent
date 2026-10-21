"""The Extraction Agent run through the real Google ADK runner, with a scripted model in place
of Gemini (no network)."""

import asyncio
import json
from collections.abc import AsyncGenerator

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from app.agents.extraction import ExtractionTimeout, GeminiExtractor, parse_output
from tests.factories import invoice_json

PDF = b"%PDF-1.7 fake"


class ScriptedLlm(BaseLlm):
    """Stands in for Gemini: replies with fixed text and records each request."""

    reply: str = ""
    delay: float = 0
    requests: list = []

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.requests.append(llm_request)
        if self.delay:
            await asyncio.sleep(self.delay)
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part.from_text(text=self.reply)]),
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=1200, candidates_token_count=300
            ),
        )


def test_reads_invoice_through_adk_and_counts_tokens() -> None:
    llm = ScriptedLlm(model="scripted", reply=json.dumps(invoice_json()), requests=[])
    call = GeminiExtractor(llm, timeout_seconds=10).extract(PDF, "application/pdf")

    assert call.error is None
    assert call.parsed.invoice_no == "SD-1042"
    assert (call.input_tokens, call.output_tokens) == (1200, 300)
    assert call.latency_ms >= 0

    request = llm.requests[0]
    user_parts = request.contents[-1].parts
    assert user_parts[0].text == "Read this invoice."
    assert user_parts[1].inline_data.mime_type == "application/pdf"
    assert user_parts[1].inline_data.data == PDF
    assert "Never calculate" in request.config.system_instruction
    assert request.config.temperature == 0
    assert request.config.response_schema is not None


def test_feedback_is_sent_on_the_corrective_retry() -> None:
    llm = ScriptedLlm(model="scripted", reply=json.dumps(invoice_json()), requests=[])
    GeminiExtractor(llm, timeout_seconds=10).extract(PDF, "application/pdf", "- Total is missing")
    prompt = llm.requests[0].contents[-1].parts[0].text
    assert "failed these checks:\n- Total is missing" in prompt


def test_invalid_output_is_never_used() -> None:
    llm = ScriptedLlm(model="scripted", reply="Sure! The total is 4050.", requests=[])
    call = GeminiExtractor(llm, timeout_seconds=10).extract(PDF, "application/pdf")
    assert call.parsed is None
    assert call.error.startswith("The response was not valid JSON")


def test_timeout_raises_so_the_task_retries() -> None:
    llm = ScriptedLlm(model="scripted", reply="{}", delay=2, requests=[])
    with pytest.raises(ExtractionTimeout):
        GeminiExtractor(llm, timeout_seconds=0.2).extract(PDF, "application/pdf")


def test_parse_output_accepts_fenced_json() -> None:
    parsed, error = parse_output("```json\n" + json.dumps(invoice_json()) + "\n```")
    assert error is None and parsed.total == "Rs. 4,050.00"


@pytest.mark.parametrize(
    ("data", "fragment"),
    [
        (invoice_json(surprise="field"), "surprise: Extra inputs are not permitted"),
        (invoice_json(field_confidence={"totals": 2}), "field_confidence.totals"),
        ({"invoice_no": "x"}, "field_confidence: Field required"),
    ],
)
def test_parse_output_rejects_schema_violations(data: dict, fragment: str) -> None:
    parsed, error = parse_output(json.dumps(data))
    assert parsed is None
    assert fragment in error
