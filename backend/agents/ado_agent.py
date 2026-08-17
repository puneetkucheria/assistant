"""LangChain agent factory + streaming helper.

Uses ``langchain.agents.create_agent`` (LangChain v1, LangGraph-backed) to
build a tool-calling agent. The compiled graph streams AI message chunks
(via ``stream_mode="messages"``) and emits separate ToolMessage outputs
(via ``stream_mode="updates"``) that we surface to the frontend as
``tool_start`` and ``tool_end`` events over SSE.

Per-conversation memory is **in-process** for the MVP (cleared on
restart). Wrap with a real checkpointer to persist.
"""
from __future__ import annotations

import uuid
from typing import Any, AsyncIterator

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from backend.agents.registry import get_assistant
from backend.config import get_settings


def _build_llm() -> ChatOpenAI:
    settings = get_settings()
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0,
        streaming=True,
    )


def build_agent(assistant_name: str):
    """Return a compiled agent graph for the named assistant."""
    assistant = get_assistant(assistant_name)
    llm = _build_llm()
    tools = assistant.tool_loader()
    system_prompt = assistant.system_prompt_loader()
    return create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
    )


# ---- Per-conversation memory (in-process) ----------------------------------

_sessions: dict[str, dict[str, Any]] = {}


def get_or_create_session(conversation_id: str | None, assistant_name: str) -> tuple[str, list]:
    """Return (conversation_id, prior_messages). Creates a session if needed."""
    if not conversation_id:
        conversation_id = str(uuid.uuid4())
        _sessions[conversation_id] = {
            "id": conversation_id,
            "assistant": assistant_name,
            "messages": [],
        }
        return conversation_id, []
    session = _sessions.get(conversation_id)
    if session is None:
        session = {
            "id": conversation_id,
            "assistant": assistant_name,
            "messages": [],
        }
        _sessions[conversation_id] = session
    return conversation_id, list(session["messages"])


def append_session_message(conversation_id: str, message: Any) -> None:
    session = _sessions.get(conversation_id)
    if session is not None:
        # cap to last 50 messages to avoid runaway memory
        session["messages"].append(message)
        if len(session["messages"]) > 50:
            session["messages"] = session["messages"][-50:]


# ---- Streaming agent execution --------------------------------------------


async def stream_agent_response(
    assistant_name: str,
    conversation_id: str | None,
    user_text: str,
) -> AsyncIterator[dict[str, Any]]:
    """Yield SSE-style event dicts.

    Events:
        {"type": "session",     "conversation_id": "..."}
        {"type": "token",       "text": "He"}
        {"type": "tool_start",  "id":"...", "name":"...", "args": {...}}
        {"type": "tool_end",    "id":"...", "name":"...", "output": "..."}
        {"type": "done"}
        {"type": "error",       "message": "..."}
    """
    conversation_id, prior = get_or_create_session(conversation_id, assistant_name)
    yield {"type": "session", "conversation_id": conversation_id}

    try:
        agent = build_agent(assistant_name)

        # ``messages`` stream yields (chunk, message) tuples — one per token of
        # AI/Tool/Human content. We collect additions to caller_provided prior
        # list so we can persist after the run.
        from langchain_core.messages import HumanMessage, AIMessageChunk, ToolMessage

        new_user_msg = HumanMessage(content=user_text)
        all_messages = prior + [new_user_msg]

        async for chunk, metadata in agent.astream(
            {"messages": all_messages},
            stream_mode="messages",
        ):
            # Token stream from the assistant
            if isinstance(chunk, AIMessageChunk):
                text = chunk.content if isinstance(chunk.content, str) else ""
                if text:
                    yield {"type": "token", "text": text}
                # Tool-call request bundled in the AI message chunk
                if getattr(chunk, "tool_call_chunks", None):
                    for tc in chunk.tool_call_chunks:
                        # tool_call_chunks are partial; surface name only on first chunk
                        if tc.get("name"):
                            yield {
                                "type": "tool_start",
                                "id": tc.get("id") or "",
                                "name": tc.get("name"),
                                "args": tc.get("args") or "",
                            }
            elif isinstance(chunk, ToolMessage):
                name = chunk.name or "tool"
                yield {
                    "type": "tool_end",
                    "id": chunk.tool_call_id or "",
                    "name": name,
                    "output": chunk.content if isinstance(chunk.content, str) else str(chunk.content),
                }

        # Persist session
        append_session_message(conversation_id, new_user_msg)
        yield {"type": "done"}
    except Exception as exc:  # noqa: BLE001
        yield {"type": "error", "message": f"{type(exc).__name__}: {exc}"}
