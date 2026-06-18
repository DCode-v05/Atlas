"""The LLM boundary — real Mistral on Amazon Bedrock, required (no fallback)."""

from atlas.llm.base import LLMProvider

__all__ = ["LLMProvider", "get_provider"]


def get_provider(settings=None, broker=None) -> LLMProvider:
    """Return the real Bedrock (Mistral) provider. Raises if AWS creds are missing."""
    from atlas.config import get_settings

    settings = settings or get_settings()
    has_api_key = bool(settings.bedrock_api_key)
    has_explicit = bool(settings.aws_access_key_id and settings.aws_secret_access_key)
    if not (has_api_key or has_explicit):
        creds = None
        try:
            import boto3

            creds = boto3.Session().get_credentials()
        except Exception:
            creds = None
        if creds is None:
            raise RuntimeError(
                "No Bedrock credentials set. Atlas runs real Mistral via Amazon Bedrock and has no "
                "simulated fallback — set a Bedrock API key (AWS_BEARER_TOKEN_BEDROCK) or "
                "AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY, plus a region (AWS_REGION=us-east-1), "
                "before starting."
            )

    from atlas.llm.bedrock_provider import BedrockProvider

    return BedrockProvider(
        region=settings.aws_region,
        api_key=settings.bedrock_api_key,
        access_key=settings.aws_access_key_id,
        secret_key=settings.aws_secret_access_key,
        session_token=settings.aws_session_token,
        reasoning_model=settings.bedrock_reasoning_model,
        phrasing_model=settings.bedrock_phrasing_model,
        rpm=settings.bedrock_rpm,
        burst=settings.bedrock_burst,
        max_concurrency=settings.bedrock_max_concurrency,
        broker=broker,
    )
