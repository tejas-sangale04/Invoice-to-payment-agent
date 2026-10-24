"""Running an ADK agent once, synchronously, for the pipeline (which runs in a worker thread)."""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from typing import TypeVar

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, ValidationError

APP_NAME = "invoiceflow"
M = TypeVar("M", bound=BaseModel)


class AgentTimeout(Exception):
    pass


@dataclass
class AgentReply:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


async def _run(agent: LlmAgent, prompt: str) -> AgentReply:
    sessions = InMemorySessionService()
    session_id = uuid.uuid4().hex
    await sessions.create_session(app_name=APP_NAME, user_id="agent", session_id=session_id)
    runner = Runner(agent=agent, app_name=APP_NAME, session_service=sessions)
    message = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
    reply = AgentReply("")
    async for event in runner.run_async(
        user_id="agent", session_id=session_id, new_message=message
    ):
        if event.usage_metadata:
            reply.input_tokens += event.usage_metadata.prompt_token_count or 0
            reply.output_tokens += event.usage_metadata.candidates_token_count or 0
        if event.is_final_response() and event.content and event.content.parts:
            reply.text += "".join(p.text or "" for p in event.content.parts)
    return reply


def run_agent(agent: LlmAgent, prompt: str, timeout_seconds: float) -> AgentReply:
    """Run the agent (including any tool calls) to its final answer."""
    started = time.monotonic()
    try:
        reply = asyncio.run(asyncio.wait_for(_run(agent, prompt), timeout_seconds))
    except TimeoutError as exc:
        raise AgentTimeout(f"Gemini did not answer within {timeout_seconds:.0f}s") from exc
    reply.latency_ms = int((time.monotonic() - started) * 1000)
    return reply


def parse_json(text: str, model: type[M]) -> tuple[M | None, str | None]:
    """Validate the model's text against `model`. Never returns partially valid data."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        cleaned = cleaned.rsplit("```", 1)[0]
    try:
        return model.model_validate(json.loads(cleaned)), None
    except json.JSONDecodeError as exc:
        return None, f"The response was not valid JSON ({exc.msg})"
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()[:10]
        )
        return None, f"The response did not match the schema: {problems}"
