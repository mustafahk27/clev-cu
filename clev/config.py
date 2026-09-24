"""Runtime configuration, loaded from environment variables and `.env`."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DeciderName = Literal["jev", "llm", "mock"]
Mode = Literal["browser", "desktop"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: SecretStr | None = None
    jev_api_key: SecretStr | None = None
    jev_base_url: str | None = None

    planner_model: str = "claude-sonnet-5"
    escalation_model: str = "claude-haiku-4-5-20251001"
    decider: DeciderName = "jev"

    confidence_threshold: float = Field(0.6, ge=0.0, le=1.0)
    margin: float = Field(0.1, ge=0.0, le=1.0)
    max_options: int = Field(200, ge=1, le=248)  # Jev max is 255; leave room for globals
    token_budget: int = Field(24000, gt=0)
    max_steps: int = Field(50, gt=0)

    confirm_destructive: bool = True
    dry_run: bool = False

    jev_price_per_billion_input: float = 42.0
    trace_dir: Path = Path("traces")

    def redacted(self) -> dict:
        """Config as JSON-safe dict with API keys replaced by set/unset."""
        data = self.model_dump(mode="json")
        for key in ("anthropic_api_key", "jev_api_key"):
            data[key] = "set" if getattr(self, key) else "unset"
        return data


def load_settings(**overrides) -> Settings:
    """Load settings from env/.env, applying non-None CLI overrides on top."""
    return Settings(**{k: v for k, v in overrides.items() if v is not None})
