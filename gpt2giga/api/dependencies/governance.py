"""Request governance dependency for fixed-window limits and quotas."""

from __future__ import annotations

from fastapi import HTTPException
from starlette.requests import Request

from gpt2giga.api.dependencies.auth import resolve_endpoint_id, resolve_requested_model
from gpt2giga.api.gemini.request import GeminiAPIError
from gpt2giga.app.governance import (
    GovernanceContext,
    _coerce_int_value,
    reserve_governance_request_window,
)


def build_governance_verifier(
    *,
    provider_name: str | None = None,
    gemini_style: bool = False,
):
    """Create a dependency that enforces configured request governance rules."""

    async def _verify(request: Request) -> None:
        api_key_context = getattr(request.state, "api_key_context", None)
        context = GovernanceContext(
            provider=provider_name,
            endpoint=resolve_endpoint_id(request),
            model=await resolve_requested_model(request, provider_name=provider_name),
            api_key_name=getattr(api_key_context, "name", None),
        )
        exceeded = reserve_governance_request_window(request.app.state, context)
        if exceeded:
            first = exceeded[0]
            retry_after_seconds = _coerce_int_value(first.get("retry_after_seconds"), 1)
            message = (
                f"Request governance limit exceeded for {first['scope']} "
                f"`{first['subject']}` on {first['dimension']}: "
                f"{first['current_value']}/{first['limit_value']}. "
                f"Retry after {retry_after_seconds}s."
            )
            if gemini_style:
                raise GeminiAPIError(
                    status_code=429,
                    status="RESOURCE_EXHAUSTED",
                    message=message,
                )
            raise HTTPException(
                status_code=429,
                detail=message,
                headers={"Retry-After": str(retry_after_seconds)},
            )

    return _verify
