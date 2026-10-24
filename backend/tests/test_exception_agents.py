"""The Explanation and Resolution agents run through the real Google ADK runner, with a scripted
model in place of Gemini (no network)."""

import json
from collections.abc import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from app.agents.explanation import GeminiExplainer
from app.agents.resolution import GeminiResolver


class TurnsLlm(BaseLlm):
    """Replies with the scripted parts in order, one reply per model call."""

    turns: list = []
    requests: list = []

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.requests.append(llm_request)
        yield LlmResponse(
            content=types.Content(role="model", parts=[self.turns.pop(0)]),
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=700, candidates_token_count=80
            ),
        )


def text(value: dict) -> types.Part:
    return types.Part.from_text(text=json.dumps(value))


def test_explainer_sends_the_facts_and_reads_the_answer() -> None:
    answer = {"explanation": "Rs 600.00 too high.", "supplier_email": None}
    llm = TurnsLlm(model="scripted", turns=[text(answer)], requests=[])
    call = GeminiExplainer(llm, timeout_seconds=10).explain({"invoice_no": "SD-1"}, "- too long")
    assert call.error is None
    assert call.parsed.explanation == "Rs 600.00 too high."
    assert (call.input_tokens, call.output_tokens) == (700, 80)
    request = llm.requests[0]
    prompt = request.contents[-1].parts[0].text
    assert '"invoice_no": "SD-1"' in prompt
    assert "Your previous answer failed these checks:\n- too long" in prompt
    assert "Never calculate" in request.config.system_instruction
    assert request.config.temperature == 0


def test_explainer_reports_unusable_output() -> None:
    llm = TurnsLlm(model="scripted", turns=[types.Part.from_text(text="Sure!")], requests=[])
    call = GeminiExplainer(llm, timeout_seconds=10).explain({})
    assert call.parsed is None
    assert "not valid JSON" in call.error


def test_resolver_calls_the_search_tool_then_answers() -> None:
    searched = []

    def search_open_purchase_orders(item_name: str = "", ordered_after: str = "") -> dict:
        """Search open POs."""
        searched.append((item_name, ordered_after))
        return {"purchase_orders": [{"po_number": "PO-7"}]}

    call_tool = types.Part(
        function_call=types.FunctionCall(
            name="search_open_purchase_orders", args={"item_name": "milk"}
        )
    )
    answer = text({"po_number": "PO-7", "reasoning": "Only PO-7 has milk left to bill."})
    llm = TurnsLlm(model="scripted", turns=[call_tool, answer], requests=[])
    call = GeminiResolver(llm, timeout_seconds=10).resolve(
        {"invoice_no": "SD-1"}, search_open_purchase_orders
    )

    assert searched == [("milk", "")]
    assert call.parsed.po_number == "PO-7"
    assert (call.input_tokens, call.output_tokens) == (1400, 160)  # two model calls
    # The tool's result went back to the model on its second call.
    response = llm.requests[1].contents[-1].parts[0].function_response
    assert response.response == {"purchase_orders": [{"po_number": "PO-7"}]}
    tools = llm.requests[0].config.tools[0].function_declarations
    assert [t.name for t in tools] == ["search_open_purchase_orders"]
