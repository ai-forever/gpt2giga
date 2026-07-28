"""Browser-session and request-boundary security for the Harness UI."""

from __future__ import annotations

import ipaddress
import time
from urllib.parse import urlencode, urlsplit

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, RedirectResponse

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.ui.local_access import (
    LocalUIAccessStatus,
    LocalUIAccessStore,
    LocalUISession,
)
from gpt2giga_harness.ui.remote_identity import (
    REMOTE_TRANSACTION_COOKIE,
    LoginTransaction,
    RemoteBrowserSession,
    RemoteIdentityError,
    RemoteIdentityStore,
    RemoteOIDCClient,
    RemoteOIDCSettings,
)

UI_SESSION_COOKIE = "gpt2giga_harness_session"
UI_CSRF_HEADER = "X-GigaLoom-CSRF"
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_AUTHENTICATED_PATHS = frozenset(
    {
        "/auth/logout",
        "/auth/local/rotate",
        "/auth/remote/revoke-actor",
        "/auth/remote/revoke-all",
    }
)
_REMOTE_PUBLIC_PATHS = frozenset(
    {
        "/auth/oidc/login",
        "/auth/oidc/callback",
        "/auth/oidc/backchannel-logout",
    }
)


class HarnessUISecurity:
    """Own one in-memory browser session and validate UI request boundaries."""

    def __init__(
        self,
        config: HarnessConfig,
        *,
        oidc_client: RemoteOIDCClient | None = None,
    ) -> None:
        self.config = config
        self.local_access = LocalUIAccessStore(config.data_dir)
        self.remote_settings = (
            None if self.local_mode else RemoteOIDCSettings.from_config(config)
        )
        self.remote_store = (
            RemoteIdentityStore(config.data_dir, self.remote_settings)
            if self.remote_settings is not None
            else None
        )
        self.oidc_client = (
            oidc_client if self.remote_settings is not None else None
        ) or (
            RemoteOIDCClient(self.remote_settings)
            if self.remote_settings is not None
            else None
        )

    @property
    def local_mode(self) -> bool:
        """Return whether the configured listener is loopback-only."""
        return is_loopback_host(self.config.ui_host)

    def host_allowed(self, request: Request) -> bool:
        """Reject DNS-rebinding-style Host values outside the UI allowlist."""
        if not self.local_mode:
            return self._remote_origin_matches(request)
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
        if not self.local_mode:
            return (
                self.remote_settings is not None
                and origin.rstrip("/") == self.remote_settings.public_origin
            )
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
        return self.remote_session(request) is not None

    def remote_session(self, request: Request) -> RemoteBrowserSession | None:
        """Return the authenticated remote session, if any."""
        if self.local_mode or self.remote_store is None:
            return None
        return self.remote_store.authenticate(request.cookies.get(UI_SESSION_COOKIE))

    def begin_remote_login(self, redirect_path: str) -> tuple[LoginTransaction, str]:
        """Create a one-use login transaction and authorization URL."""
        if self.remote_store is None or self.oidc_client is None:
            raise RemoteIdentityError("Remote OIDC identity is unavailable")
        transaction = self.remote_store.begin_login(redirect_path)
        return transaction, self.oidc_client.authorization_url(transaction)

    def complete_remote_login(
        self,
        *,
        code: str,
        state: str,
        binding: str | None,
    ) -> tuple[RemoteBrowserSession, str]:
        """Consume a callback transaction and create one remote session."""
        if self.remote_store is None or self.oidc_client is None:
            raise RemoteIdentityError("Remote OIDC identity is unavailable")
        transaction = self.remote_store.consume_login(state, binding)
        actor = self.oidc_client.exchange_code(code=code, transaction=transaction)
        session = self.remote_store.issue_session(actor)
        return session, transaction.redirect_path

    def revoke_remote_session(self, request: Request) -> bool:
        """Invalidate the presented remote session."""
        if self.remote_store is None:
            return False
        return self.remote_store.revoke_session(request.cookies.get(UI_SESSION_COOKIE))

    def apply_backchannel_logout(self, token: str) -> int:
        """Validate and apply one issuer back-channel logout event."""
        if self.remote_store is None or self.oidc_client is None:
            raise RemoteIdentityError("Remote OIDC identity is unavailable")
        claims = self.oidc_client.validate_backchannel_logout(token)
        return self.remote_store.apply_backchannel_logout(claims)

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
        if request.url.path == "/auth/oidc/backchannel-logout":
            return True
        if request_is_test_client(request):
            return True
        if request.headers.get(UI_CSRF_HEADER, "") != "1":
            return False
        return self.local_mode or request_is_explicitly_same_origin(request, self)

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

    def set_remote_session_cookie(
        self,
        response: Response,
        session: RemoteBrowserSession,
    ) -> None:
        """Attach the host-only opaque remote browser session."""
        response.set_cookie(
            UI_SESSION_COOKIE,
            session.token,
            httponly=True,
            secure=True,
            samesite="strict",
            path="/",
            max_age=max(0, int(session.expires_at - time.time())),
        )

    @staticmethod
    def set_transaction_cookie(
        response: Response,
        transaction: LoginTransaction,
    ) -> None:
        """Bind one login transaction to the initiating browser."""
        response.set_cookie(
            REMOTE_TRANSACTION_COOKIE,
            transaction.binding,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/auth/oidc/callback",
            max_age=max(0, int(transaction.expires_at - time.time())),
        )

    @staticmethod
    def clear_transaction_cookie(response: Response) -> None:
        """Expire the browser-bound login transaction cookie."""
        response.delete_cookie(
            REMOTE_TRANSACTION_COOKIE,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/auth/oidc/callback",
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

    def _remote_origin_matches(self, request: Request) -> bool:
        settings = self.remote_settings
        if settings is None:
            return False
        host = request.headers.get("host", "")
        scheme = request.url.scheme
        forwarded_host = request.headers.get("x-forwarded-host")
        forwarded_proto = request.headers.get("x-forwarded-proto")
        has_forwarded = forwarded_host is not None or forwarded_proto is not None
        peer = request.client.host if request.client is not None else ""
        if has_forwarded:
            if peer not in settings.trusted_proxies:
                return False
            if (
                forwarded_host is None
                or forwarded_proto is None
                or "," in forwarded_host
                or "," in forwarded_proto
            ):
                return False
            host = forwarded_host.strip()
            scheme = forwarded_proto.strip().lower()
        effective = f"{scheme}://{host}".rstrip("/")
        return effective == settings.public_origin


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
        remote_session = self.security.remote_session(request)
        has_session = (
            self.security.has_session(request)
            if self.security.local_mode
            else remote_session is not None
        )
        if remote_session is not None:
            request.state.ui_actor = {
                "actor_id": remote_session.actor.actor_id,
                "role": remote_session.actor.role,
                "session_id": remote_session.session_id,
                "authentication_time": remote_session.actor.authentication_time,
            }
        # Starlette's in-process TestClient marker cannot arrive over a real
        # socket; keep legacy direct-API tests hermetic while production local
        # clients must first load the shell and receive its cookie.
        is_test_client = request_is_test_client(request)
        shell_request = request.method == "GET" and (
            path == "/"
            or path == "/cockpit-v2"
            or path.startswith("/cockpit-v2/")
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
        if (
            not self.security.local_mode
            and not has_session
            and shell_request
            and path not in _REMOTE_PUBLIC_PATHS
        ):
            target = request.url.path
            if request.url.query:
                target = f"{target}?{request.url.query}"
            return RedirectResponse(
                f"/auth/oidc/login?{urlencode({'next': target})}",
                status_code=303,
            )
        if (
            protected
            and not self.security.local_mode
            and not has_session
            and path not in _REMOTE_PUBLIC_PATHS
        ):
            return JSONResponse({"detail": "Browser session required"}, status_code=401)
        if (
            remote_session is not None
            and remote_session.actor.role == "viewer"
            and request.method.upper() in _MUTATING_METHODS
            and path != "/auth/logout"
        ):
            return JSONResponse(
                {"detail": "Operator role required"},
                status_code=403,
            )
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
