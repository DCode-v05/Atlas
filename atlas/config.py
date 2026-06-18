"""Runtime configuration for Atlas.

Settings come from environment variables (prefixed ``ATLAS_``) and an optional
``.env`` file. Atlas runs real **Mistral on Amazon Bedrock** — AWS credentials
are **required**; without them the app refuses to start (no simulated fallback).
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

    # Cron simulation. Two modes, selected by ``cron_loop``:
    #   • burst (default): when toggled on it runs a single ~15s burst
    #     (``cron_burst_seconds``) of autonomous goals, then auto-stops.
    #   • continuous (``ATLAS_CRON_LOOP=true``): keeps launching goals until
    #     toggled off.
    # Either way goals are balanced across departments and paced gently so the
    # rate-limited LLM isn't hammered.
    cron_burst_seconds: float = 15.0  # length of a burst (spec: "on for 15 seconds")
    cron_loop: bool = False           # False = 15s burst; True = continuous
    cron_goal_seconds: float = 30.0   # inter-goal gap in continuous mode
    cron_tick_seconds: float = 1.0    # countdown-tick cadence for the UI
    cron_max_inflight: int = 2        # load-shed: max concurrent goal scenarios

    # Human-in-the-loop: 0 disables the auto-decision timeout (operator decides).
    hitl_timeout_seconds: float = 0.0

    # Server bind.
    host: str = "0.0.0.0"
    port: int = 8000

    # ─── Amazon Bedrock (Mistral) — REQUIRED ──────────────────────────────────
    aws_region: str = Field(
        default="us-east-1",
        validation_alias=AliasChoices("AWS_REGION", "AWS_DEFAULT_REGION", "ATLAS_AWS_REGION"),
    )
    # Preferred: a Bedrock API key (bearer token). boto3 reads AWS_BEARER_TOKEN_BEDROCK.
    bedrock_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AWS_BEARER_TOKEN_BEDROCK", "ATLAS_BEDROCK_API_KEY"),
    )
    # Fallback: classic AWS access key / secret (conventional names; boto3 reads them).
    aws_access_key_id: str | None = Field(
        default=None, validation_alias=AliasChoices("AWS_ACCESS_KEY_ID", "ATLAS_AWS_ACCESS_KEY_ID")
    )
    aws_secret_access_key: str | None = Field(
        default=None, validation_alias=AliasChoices("AWS_SECRET_ACCESS_KEY", "ATLAS_AWS_SECRET_ACCESS_KEY")
    )
    aws_session_token: str | None = Field(
        default=None, validation_alias=AliasChoices("AWS_SESSION_TOKEN", "ATLAS_AWS_SESSION_TOKEN")
    )
    # Bedrock Mistral model ids (must be enabled in your account + region).
    bedrock_reasoning_model: str = "mistral.mistral-large-2402-v1:0"
    bedrock_phrasing_model: str = "mistral.mistral-large-2402-v1:0"

    # Throttling — protects against Bedrock rate limits. ``rpm`` is the per-model
    # steady refill; ``burst`` caps the instantaneous burst so calls are paced.
    bedrock_rpm: int = 22
    bedrock_burst: int = 5
    bedrock_max_concurrency: int = 2


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
