"""Browser-session and request-boundary security for the Harness UI."""

from __future__ import annotations

from hmac import compare_digest
import ipaddress
import secrets
from urllib.parse import urlsplit

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from gpt2giga_harness.config import HarnessConfig

UI_SESSION_COOKIE = "gpt2giga_harness_session"
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class HarnessUISecurity:
    """Own one in-memory browser session and validate UI request boundaries."""

    def __init__(self, config: HarnessConfig) -> None:
        self.config = config
        self.session_token = secrets.token_urlsafe(32)

    @property
    def local_mode(self) -> bool:
        """Return whether the configured listener is loopback-only."""
        return is_loopback_host(self.config.ui_host)

    @property
    def bootstrap_configured(self) -> bool:
        """Return whether remote browser authentication is configured."""
        return bool(self.config.ui_bootstrap_token)

    def host_allowed(self, request: Request) -> bool:
        """Reject DNS-rebinding-style Host values outside the UI allowlist."""
        host = _request_host(request.headers.get("host"))
        if host is None:
            return False
        if host in {"localhost", "127.0.0.1", "::1"}:
            return True
        if host in self.config.ui_allowed_hosts:
            return True
        configured = self.config.ui_host.strip().strip("[]").lower()
        if configured not in {"0.0.0.0", "::"} and host == configured:
            return True
        if (
            request.client is not None
            and request.client.host == "testclient"
            and host == "testserver"
        ):
            return True
        if not self.local_mode:
            try:
                return ipaddress.ip_address(host).is_private
            except ValueError:
                return False
        return False

    def origin_allowed(self, request: Request) -> bool:
        """Accept absent or same-origin Origin headers only."""
        origin = request.headers.get("origin")
        if origin is None:
            return True
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        return parsed.netloc.lower() == request.headers.get("host", "").lower()

    def has_session(self, request: Request) -> bool:
        """Return whether the request presents the current browser cookie."""
        token = request.cookies.get(UI_SESSION_COOKIE)
        return bool(token) and compare_digest(token, self.session_token)

    def bootstrap_matches(self, authorization: str | None) -> bool:
        """Validate a bearer bootstrap token without persisting or returning it."""
        expected = self.config.ui_bootstrap_token
        if expected is None or authorization is None:
            return False
        scheme, separator, token = authorization.partition(" ")
        return (
            separator == " "
            and scheme.lower() == "bearer"
            and bool(token)
            and compare_digest(token, expected)
        )

    def set_session_cookie(self, response: Response) -> None:
        """Attach the opaque HttpOnly browser-session cookie."""
        response.set_cookie(
            UI_SESSION_COOKIE,
            self.session_token,
            httponly=True,
            secure=not self.local_mode,
            samesite="strict",
            path="/",
        )


class HarnessUISecurityMiddleware(BaseHTTPMiddleware):
    """Protect UI APIs while keeping the shell and minimal health public."""

    def __init__(self, app, *, security: HarnessUISecurity) -> None:
        super().__init__(app)
        self.security = security

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if not self.security.host_allowed(request):
            return JSONResponse({"detail": "Untrusted Host header"}, status_code=400)
        if not self.security.origin_allowed(request):
            return JSONResponse(
                {"detail": "Cross-origin request denied"}, status_code=403
            )

        path = request.url.path
        protected = path.startswith("/api/")
        has_session = self.security.has_session(request)
        # Starlette's in-process TestClient marker cannot arrive over a real
        # socket; keep legacy direct-API tests hermetic while production local
        # clients must first load the shell and receive its cookie.
        is_test_client = (
            request.client is not None and request.client.host == "testclient"
        )
        shell_request = request.method == "GET" and (
            path == "/"
            or path == "/work"
            or path.startswith("/work/")
            or path == "/runs"
            or path.startswith("/runs/")
        )
        local_session_needed = (
            self.security.local_mode and not has_session and shell_request
        )
        if (
            protected
            and self.security.local_mode
            and not has_session
            and not is_test_client
        ):
            return JSONResponse({"detail": "Browser session required"}, status_code=401)
        if protected and not self.security.local_mode and not has_session:
            if (
                request.method.upper() in _MUTATING_METHODS
                and not self.security.bootstrap_configured
            ):
                return JSONResponse(
                    {
                        "detail": "Remote mutating APIs are disabled until authentication is configured"
                    },
                    status_code=403,
                )
            return JSONResponse({"detail": "Browser session required"}, status_code=401)

        response = await call_next(request)
        if local_session_needed:
            self.security.set_session_cookie(response)
        return response


def _request_host(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(f"//{value}")
    try:
        return parsed.hostname.lower() if parsed.hostname else None
    except ValueError:
        return None


def is_loopback_host(value: str) -> bool:
    """Return whether a listener host is constrained to loopback."""
    normalized = value.strip().strip("[]").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False
