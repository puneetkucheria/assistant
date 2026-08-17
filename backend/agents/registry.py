"""Assistant registry — small indirection so multiple assistants can coexist.

Today only the Azure DevOps assistant exists. Adding a new assistant is a
matter of (a) implementing a tool module under ``backend.tools`` that
exposes a ``build_*_tools()`` list, (b) writing a system prompt under
``backend/agents/prompts/<name>.txt``, and (c) adding an entry to the
``_REGISTRY`` dict below. No changes to ``chat.py`` or ``main.py`` required.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable

from langchain_core.tools import BaseTool

from backend.tools.ado_tools import build_ado_tools


PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


@dataclass(frozen=True)
class AssistantDef:
    name: str
    title: str
    description: str
    system_prompt_loader: Callable[[], str]
    tool_loader: Callable[[], list[BaseTool]]


def _load_prompt(name: str) -> str:
    path = PROMPT_DIR / f"{name}.txt"
    template = path.read_text(encoding="utf-8")
    return template


def _ado_prompt() -> str:
    from backend.config import get_settings
    return _load_prompt("ado").format(project=get_settings().azure_devops_project)


_REGISTRY: dict[str, AssistantDef] = {
    "ado": AssistantDef(
        name="ado",
        title="Azure DevOps Assistant",
        description="Read, search, create, and update work items in Azure DevOps.",
        system_prompt_loader=_ado_prompt,
        tool_loader=build_ado_tools,
    ),
}


def list_assistants() -> list[dict]:
    return [
        {"name": d.name, "title": d.title, "description": d.description}
        for d in _REGISTRY.values()
    ]


@lru_cache
def get_assistant(name: str) -> AssistantDef:
    if name not in _REGISTRY:
        raise KeyError(f"unknown assistant: {name!r}")
    return _REGISTRY[name]


DEFAULT_ASSISTANT = "ado"
