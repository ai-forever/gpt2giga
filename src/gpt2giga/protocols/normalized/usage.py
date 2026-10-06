"""Read cache accounting facts from normalized provider usage."""

from gpt2giga.protocols.normalized.models import NormalizedUsage


def cached_input_tokens(usage: NormalizedUsage | None) -> int:
    """Return the cached subset of normalized input tokens."""
    if usage is None:
        return 0
    anthropic = usage.provider_metadata.get("anthropic", {})
    if "cache_read_input_tokens" in anthropic:
        return int(anthropic["cache_read_input_tokens"] or 0)
    extensions = usage.raw_extensions
    for key in ("input_tokens_details", "prompt_tokens_details"):
        details = extensions.get(key)
        if isinstance(details, dict) and "cached_tokens" in details:
            return int(details["cached_tokens"] or 0)
    return int(extensions.get("precached_prompt_tokens") or 0)
