"""The LLM boundary — real Groq, required (no simulated fallback)."""

from atlas.llm.base import LLMProvider

__all__ = ["LLMProvider", "get_provider"]


def get_provider(settings=None, broker=None) -> LLMProvider:
    """Return the real Groq provider. Raises if ``GROQ_API_KEY`` is not set."""
    from atlas.config import get_settings

    settings = settings or get_settings()
    if not settings.groq_api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Atlas runs real Groq agents and has no simulated "
            "fallback — set GROQ_API_KEY (e.g. in a .env file) before starting."
        )
    from atlas.llm.groq_provider import GroqProvider

    return GroqProvider(
        api_key=settings.groq_api_key,
        reasoning_model=settings.groq_reasoning_model,
        phrasing_model=settings.groq_phrasing_model,
        rpm=settings.groq_rpm,
        burst=settings.groq_burst,
        max_concurrency=settings.groq_max_concurrency,
        broker=broker,
    )
