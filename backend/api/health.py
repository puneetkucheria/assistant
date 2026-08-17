"""Health check endpoint."""
from __future__ import annotations

from fastapi import APIRouter

from backend.config import get_settings

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    """Report backend readiness. No external calls — configuration only.

    The frontend uses this to surface whether the user needs to drop keys
    into ``.env`` before the assistant will be functional.
    """
    s = get_settings()
    return {
        "status": "ok",
        "openai": s.openai_is_configured,
        "ado": s.azure_devops_is_configured,
        "app_name": s.app_name,
    }
