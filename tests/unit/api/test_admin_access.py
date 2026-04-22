from fastapi import FastAPI, HTTPException
from starlette.requests import Request

from gpt2giga.api.admin.access import (
    get_client_ip,
    verify_admin_ip_allowlist,
)
from gpt2giga.app.dependencies import ensure_runtime_dependencies
from gpt2giga.core.config.settings import ProxyConfig, ProxySettings


def _build_request(
    *,
    allowlist: list[str] | None = None,
    client_host: str = "127.0.0.1",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    app = FastAPI()
    ensure_runtime_dependencies(
        app.state,
        config=ProxyConfig(
            proxy=ProxySettings(logs_ip_allowlist=allowlist or []),
        ),
    )
    return Request(
        {
            "type": "http",
            "app": app,
            "method": "GET",
            "path": "/admin",
            "headers": headers or [],
            "query_string": b"",
            "client": (client_host, 12345),
        }
    )


def test_get_client_ip_prefers_x_forwarded_for():
    request = _build_request(
        headers=[(b"x-forwarded-for", b"10.0.0.5, 172.16.0.1")],
    )

    assert get_client_ip(request) == "10.0.0.5"


def test_verify_admin_ip_allowlist_allows_matching_client():
    request = _build_request(allowlist=["127.0.0.1"])

    verify_admin_ip_allowlist(request)


def test_verify_admin_ip_allowlist_blocks_unknown_client():
    request = _build_request(allowlist=["192.168.1.100"])

    try:
        verify_admin_ip_allowlist(request)
    except HTTPException as exc:
        assert exc.status_code == 403
        assert exc.detail == "Access denied: IP not in admin allowlist"
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Expected HTTPException")
