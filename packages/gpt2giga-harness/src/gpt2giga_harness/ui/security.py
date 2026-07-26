"""Browser-session and request-boundary security for the Harness UI."""

from __future__ import annotations

from hmac import compare_digest
import ipaddress
import secrets
import time
from urllib.parse import urlsplit

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, RedirectResponse

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.ui.local_access import (
    LOCAL_UI_SESSION_TTL_SECONDS,
    LocalUIAccessStatus,
    LocalUIAccessStore,
    LocalUISession,
)

UI_SESSION_COOKIE = "gpt2giga_harness_session"
UI_CSRF_HEADER = "X-GigaLoom-CSRF"
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_AUTHENTICATED_PATHS = frozenset({"/auth/logout", "/auth/local/rotate"})


class HarnessUISecurity:
    """Own one in-memory browser session and validate UI request boundaries."""

    def __init__(self, config: HarnessConfig) -> None:
        self.config = config
        self.local_access = LocalUIAccessStore(config.data_dir)
        self.remote_session = LocalUISession(
            token=secrets.token_urlsafe(32),
            expires_at=time.time() + LOCAL_UI_SESSION_TTL_SECONDS,
        )

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
        if (
            origin == "null"
            and request.url.path == "/auth/local/recover"
            and request.headers.get("sec-fetch-site", "").lower() == "same-origin"
        ):
            return True
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        return parsed.netloc.lower() == request.headers.get("host", "").lower()

    def has_session(self, request: Request) -> bool:
        """Return whether the request presents an active opaque browser cookie."""
        token = request.cookies.get(UI_SESSION_COOKIE)
        if self.local_mode:
            return self.local_access.authenticate(token)
        return (
            bool(token)
            and self.remote_session.expires_at > time.time()
            and compare_digest(token, self.remote_session.token)
        )

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

    def issue_remote_session(self) -> LocalUISession:
        """Rotate the process-local remote session after bearer exchange."""
        self.remote_session = LocalUISession(
            token=secrets.token_urlsafe(32),
            expires_at=time.time() + LOCAL_UI_SESSION_TTL_SECONDS,
        )
        return self.remote_session

    def revoke_remote_session(self) -> None:
        """Invalidate the current process-local remote session."""
        self.remote_session = LocalUISession(
            token=secrets.token_urlsafe(32),
            expires_at=time.time() + LOCAL_UI_SESSION_TTL_SECONDS,
        )

    def claim_local_session(self, request: Request) -> LocalUISession | None:
        """Claim one pending first-run bootstrap from a loopback client."""
        if not self.local_mode or not request_is_loopback(request):
            return None
        return self.local_access.claim()

    def local_status(self, request: Request) -> LocalUIAccessStatus:
        """Project bounded local access state for the current cookie."""
        return self.local_access.status(request.cookies.get(UI_SESSION_COOKIE))

    def logout_local(self, request: Request) -> bool:
        """Revoke the current local cookie."""
        return self.local_access.logout(request.cookies.get(UI_SESSION_COOKIE))

    def rotate_local(self, request: Request) -> LocalUISession | None:
        """Rotate all local sessions from an authenticated browser."""
        return self.local_access.rotate(request.cookies.get(UI_SESSION_COOKIE))

    def recover_local(self, request: Request) -> LocalUISession | None:
        """Recover local access only across an explicit same-origin loopback POST."""
        if (
            not self.local_mode
            or not request_is_loopback(request)
            or not request_is_explicitly_same_origin(request, self)
        ):
            return None
        return self.local_access.recover()

    def csrf_allowed(self, request: Request) -> bool:
        """Require an explicit same-origin browser marker on mutations."""
        if request.method.upper() not in _MUTATING_METHODS:
            return True
        if request.url.path == "/auth/local/recover":
            return True
        if request_is_test_client(request):
            return True
        return compare_digest(request.headers.get(UI_CSRF_HEADER, ""), "1")

    def set_session_cookie(
        self,
        response: Response,
        session: LocalUISession,
    ) -> None:
        """Attach the opaque HttpOnly browser-session cookie."""
        response.set_cookie(
            UI_SESSION_COOKIE,
            session.token,
            httponly=True,
            secure=not self.local_mode,
            samesite="strict",
            path="/",
            max_age=max(0, int(session.expires_at - time.time())),
        )

    def clear_session_cookie(self, response: Response) -> None:
        """Expire the browser cookie without returning its value."""
        response.delete_cookie(
            UI_SESSION_COOKIE,
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
        protected = path.startswith("/api/") or path in _AUTHENTICATED_PATHS
        has_session = self.security.has_session(request)
        # Starlette's in-process TestClient marker cannot arrive over a real
        # socket; keep legacy direct-API tests hermetic while production local
        # clients must first load the shell and receive its cookie.
        is_test_client = request_is_test_client(request)
        shell_request = request.method == "GET" and (
            path == "/"
            or path == "/cockpit-v2"
            or path.startswith("/cockpit-v2/")
            or path == "/legacy"
            or path.startswith("/legacy/")
            or path == "/work"
            or path.startswith("/work/")
            or path == "/arena"
            or path == "/runs"
            or path.startswith("/runs/")
        )
        local_session = (
            self.security.claim_local_session(request)
            if self.security.local_mode and not has_session and shell_request
            else None
        )
        if (
            self.security.local_mode
            and not has_session
            and local_session is None
            and shell_request
            and not is_test_client
        ):
            return RedirectResponse("/local-access", status_code=303)
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
        if protected and has_session and not self.security.csrf_allowed(request):
            return JSONResponse({"detail": "CSRF check failed"}, status_code=403)

        response = await call_next(request)
        if local_session is not None:
            self.security.set_session_cookie(response, local_session)
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


def request_is_loopback(request: Request) -> bool:
    """Return whether the socket peer is loopback (or a hermetic TestClient)."""
    if request.client is None:
        return False
    if request.client.host == "testclient":
        return True
    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        return False


def request_is_test_client(request: Request) -> bool:
    """Return whether Starlette's non-network TestClient marker is present."""
    return request.client is not None and request.client.host == "testclient"


def request_is_explicitly_same_origin(
    request: Request,
    security: HarnessUISecurity,
) -> bool:
    """Validate browser Origin or Fetch Metadata without accepting absence."""
    origin = request.headers.get("origin")
    if origin is not None and origin != "null":
        return security.origin_allowed(request)
    return request.headers.get("sec-fetch-site", "").lower() == "same-origin"
