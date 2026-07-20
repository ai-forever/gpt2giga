"""Hosted-fetch adapter for the read-only skills.sh metadata proxy."""

from __future__ import annotations

from urllib import parse as urllib_parse

from gpt2giga_harness.federated_catalog import (
    SKILLS_SH_ORIGIN,
    FederatedFetcher,
    FederatedHTTPResponse,
    FederatedRequest,
    fetch_federated_json,
)


class SkillsCatalogProxyFetcher:
    """Route fixed skills.sh metadata requests through one admitted proxy."""

    def __init__(
        self,
        proxy_origin: str,
        *,
        fetch: FederatedFetcher | None = None,
    ) -> None:
        self.proxy_origin = _canonical_https_origin(proxy_origin)
        self._fetch = fetch or fetch_federated_json

    async def __call__(self, request: FederatedRequest) -> FederatedHTTPResponse:
        upstream = urllib_parse.urlsplit(request.url)
        if f"https://{upstream.hostname}" != SKILLS_SH_ORIGIN:
            raise ValueError("skills proxy client accepts only skills.sh requests")
        if not (
            upstream.path == "/api/v1/skills"
            or upstream.path.startswith("/api/v1/skills/")
        ):
            raise ValueError("skills proxy client path is invalid")
        proxy_url = urllib_parse.urlunsplit(
            (
                "https",
                urllib_parse.urlsplit(self.proxy_origin).netloc,
                upstream.path,
                upstream.query,
                "",
            )
        )
        proxy_request = FederatedRequest(
            method="GET",
            url=proxy_url,
            headers={"Accept": "application/json"},
            timeout_seconds=request.timeout_seconds,
            max_response_bytes=request.max_response_bytes,
        )
        response = await self._fetch(proxy_request)
        if response.redirected or response.final_url != proxy_url:
            return FederatedHTTPResponse(
                status_code=502,
                final_url=request.url,
                headers={},
                body=b'{"error":"proxy.redirect_rejected"}',
            )
        return FederatedHTTPResponse(
            status_code=response.status_code,
            final_url=request.url,
            headers=response.headers,
            body=response.body,
        )


def _canonical_https_origin(value: str) -> str:
    parsed = urllib_parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("skills proxy origin must be a canonical HTTPS origin")
    return urllib_parse.urlunsplit(("https", parsed.netloc, "", "", ""))


__all__ = ["SkillsCatalogProxyFetcher"]
