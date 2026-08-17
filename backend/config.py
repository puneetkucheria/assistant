"""Application settings loaded from environment / .env file."""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed config for the assistant backend.

    Values are read from environment variables or the .env file at the
    project root. Sensible defaults are provided where possible so the
    app starts even with empty optional values.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- LLM ---
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # --- Azure DevOps ---
    azure_devops_org: str = ""
    azure_devops_project: str = ""
    azure_devops_pat: str = ""
    azure_devops_default_area: Optional[str] = None

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8000
    allowed_cidr: Optional[str] = None

    # --- App ---
    cors_origin: Optional[str] = None
    app_name: str = "My Assistant"

    # --- Utility flags ---
    @property
    def azure_devops_is_configured(self) -> bool:
        return bool(self.azure_devops_org and self.azure_devops_project and self.azure_devops_pat)

    @property
    def openai_is_configured(self) -> bool:
        return bool(self.openai_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
