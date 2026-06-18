"""Runtime configuration for Atlas.

Settings come from environment variables (prefixed ``ATLAS_``) and an optional
``.env`` file. ``GROQ_API_KEY`` is **required** — Atlas runs real Groq agents and
has no simulated fallback; without a key the app refuses to start.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ATLAS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Determinism: a single seed drives org generation and the cron sequence.
    seed: int = 42

    # Cron simulation.
    cron_burst_seconds: float = 15.0
    cron_tick_seconds: float = 2.0
    cron_loop: bool = False
    cron_max_inflight: int = 1  # max concurrent simulated scenarios (load-shedding)

    # Human-in-the-loop: 0 disables the auto-decision timeout (operator decides).
    hitl_timeout_seconds: float = 0.0

    # Server bind.
    host: str = "0.0.0.0"
    port: int = 8000

    # Groq — REQUIRED. Conventional un-prefixed name (also read by the SDK).
    groq_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GROQ_API_KEY", "ATLAS_GROQ_API_KEY"),
    )
    groq_reasoning_model: str = "llama-3.3-70b-versatile"
    groq_phrasing_model: str = "llama-3.1-8b-instant"
    # Throttling — protects against Groq rate limits. ``groq_rpm`` is the per-model
    # steady refill (requests/minute; free tier ≈ 30, also bounded by tokens/min).
    # ``groq_burst`` caps the *instantaneous* burst so calls are paced, not fired
    # all at once. Raise both on a paid tier.
    groq_rpm: int = 22
    groq_burst: int = 5
    groq_max_concurrency: int = 2


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
