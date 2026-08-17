"""Chat SSE endpoint.

POST /api/chat
    Body: {"assistant": "ado", "conversation_id": "...", "message": "get me task 123"}
    Returns: text/event-stream (SSE) of agent events.

Event types (see backend.agents.ado_agent.stream_agent_response):
    - session     — emitted first; carries the conversation_id (existing or new)
    - token       — assistant token fragment, accumulated by the frontend
    - tool_start  — LLM requested a tool call
    - tool_end    — tool returned with output
    - done        — end of stream
    - error       — error message (stream ends after)
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.agents.ado_agent import stream_agent_response
from backend.agents.registry import DEFAULT_ASSISTANT, list_assistants
from backend.config import get_settings

router = APIRouter()


class ChatRequest(BaseModel):
    assistant: str = Field(default=DEFAULT_ASSISTANT, description="Assistant name from the registry.")
    conversation_id: Optional[str] = Field(default=None, description="Omit to start a new conversation.")
    message: str = Field(..., min_length=1, description="The user's message text.")


def _sse(event: str, data: dict | str) -> str:
    """Encode one SSE frame."""
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    # split payload across one or more `data:` lines per SSE spec
    lines = payload.splitlines() or [""]
    body = [f"event: {event}"]
    for line in lines:
        body.append(f"data: {line}")
    body.append("")
    body.append("")
    return "\n".join(body)


@router.get("/assistants")
async def get_assistants() -> dict:
    """Listing of available assistants for the sidebar."""
    return {
        "assistants": list_assistants(),
        "default": DEFAULT_ASSISTANT,
        "current_name": get_settings().app_name,
    }


@router.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    async def gen():
        async for event in stream_agent_response(
            assistant_name=req.assistant,
            conversation_id=req.conversation_id,
            user_text=req.message,
        ):
            etype = event.pop("type", "message")
            yield _sse(etype, event)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # disable nginx buffering if proxied
        },
    )
