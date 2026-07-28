"""Single-issuer OIDC BFF and private remote UI session state."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
import base64
import json
import os
from pathlib import Path
import secrets
import stat
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    Request as URLRequest,
    build_opener,
)
from uuid import uuid4

import jwt

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.sessions.locking import exclusive_file_lock

REMOTE_TRANSACTION_COOKIE = "gpt2giga_oidc_transaction"
REMOTE_LOGIN_TTL_SECONDS = 5 * 60
REMOTE_CLOCK_SKEW_SECONDS = 60
_SCHEMA_VERSION = 1
_MAX_PRIVATE_STATE_BYTES = 2 * 1024 * 1024
_BACKCHANNEL_EVENT = "http://schemas.openid.net/event/backchannel-logout"


class RemoteIdentityError(RuntimeError):
    """Raised when remote identity configuration or evidence fails closed."""


@dataclass(frozen=True)
class RemoteOIDCSettings:
    """Validated deployment-owned identity boundary."""

    issuer: str
    client_id: str
    client_secret: str
    public_origin: str
    roles: Mapping[str, str]
    trusted_proxies: frozenset[str]
    absolute_ttl_seconds: int
    idle_ttl_seconds: int

    @property
    def callback_uri(self) -> str:
        """Return the one exact registered callback URI."""
        return f"{self.public_origin}/auth/oidc/callback"

    @property
    def post_logout_uri(self) -> str:
        """Return the one exact post-logout URI."""
        return f"{self.public_origin}/"

    @classmethod
    def from_config(cls, config: HarnessConfig) -> "RemoteOIDCSettings":
        """Build a strict remote profile or reject partial/unsafe input."""
        values = (
            config.ui_oidc_issuer,
            config.ui_oidc_client_id,
            config.ui_oidc_client_secret,
            config.ui_oidc_public_origin,
        )
        if not all(values):
            raise RemoteIdentityError(
                "Remote UI requires issuer, client ID, client secret, and public origin"
            )
        issuer = _https_url(str(config.ui_oidc_issuer), allow_path=True)
        public_origin = _https_url(str(config.ui_oidc_public_origin), allow_path=False)
        if public_origin.endswith("/"):
            public_origin = public_origin[:-1]
        roles = dict(config.ui_oidc_role_map)
        if not roles or any(
            role not in {"viewer", "operator"} for role in roles.values()
        ):
            raise RemoteIdentityError(
                "Remote UI requires a non-empty exact viewer/operator role map"
            )
        trusted_proxies = frozenset(
            _validated_proxy(value) for value in config.ui_trusted_proxies
        )
        absolute_ttl = config.ui_remote_absolute_ttl_seconds
        idle_ttl = config.ui_remote_idle_ttl_seconds
        if absolute_ttl < 300 or absolute_ttl > 24 * 60 * 60:
            raise RemoteIdentityError(
                "Remote absolute session lifetime must be between 300 and 86400 seconds"
            )
        if idle_ttl < 60 or idle_ttl > absolute_ttl:
            raise RemoteIdentityError(
                "Remote idle session lifetime must be between 60 seconds and the absolute lifetime"
            )
        return cls(
            issuer=issuer,
            client_id=str(config.ui_oidc_client_id),
            client_secret=str(config.ui_oidc_client_secret),
            public_origin=public_origin,
            roles=roles,
            trusted_proxies=trusted_proxies,
            absolute_ttl_seconds=absolute_ttl,
            idle_ttl_seconds=idle_ttl,
        )


@dataclass(frozen=True)
class LoginTransaction:
    """One-use browser-bound OIDC transaction."""

    state: str
    nonce: str
    verifier: str
    binding: str
    redirect_path: str
    expires_at: float

    @property
    def challenge(self) -> str:
        """Return the RFC 7636 S256 code challenge."""
        digest = sha256(self.verifier.encode()).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


@dataclass(frozen=True)
class RemoteActor:
    """Validated stable remote principal and authorization role."""

    actor_id: str
    issuer: str
    subject: str
    role: str
    issuer_session_id: str | None
    authentication_time: float


@dataclass(frozen=True)
class RemoteBrowserSession:
    """Opaque session material and content-free audit identity."""

    token: str
    session_id: str
    actor: RemoteActor
    expires_at: float
    idle_expires_at: float


@dataclass(frozen=True)
class OIDCMetadata:
    """Admitted subset of one issuer discovery document."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    end_session_endpoint: str | None


JSONFetcher = Callable[[str, str, Mapping[str, str], bytes | None], Mapping[str, Any]]


class RemoteOIDCClient:
    """Fetch metadata/tokens and validate signed OIDC evidence."""

    def __init__(
        self,
        settings: RemoteOIDCSettings,
        *,
        fetch_json: JSONFetcher | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self._fetch_json = fetch_json or _fetch_json
        self._clock = clock
        self._metadata: OIDCMetadata | None = None
        self._jwks: Mapping[str, Any] | None = None

    def authorization_url(self, transaction: LoginTransaction) -> str:
        """Create the exact Authorization Code + PKCE request URL."""
        metadata = self.metadata()
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.settings.client_id,
                "redirect_uri": self.settings.callback_uri,
                "scope": "openid",
                "state": transaction.state,
                "nonce": transaction.nonce,
                "code_challenge": transaction.challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{metadata.authorization_endpoint}?{query}"

    def exchange_code(self, *, code: str, transaction: LoginTransaction) -> RemoteActor:
        """Exchange one code and validate the returned ID token."""
        if not code or len(code) > 4096:
            raise RemoteIdentityError("OIDC callback code is invalid")
        metadata = self.metadata()
        basic = base64.b64encode(
            f"{self.settings.client_id}:{self.settings.client_secret}".encode()
        ).decode()
        response = self._fetch_json(
            "POST",
            metadata.token_endpoint,
            {
                "Accept": "application/json",
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            urlencode(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.settings.callback_uri,
                    "code_verifier": transaction.verifier,
                }
            ).encode(),
        )
        id_token = response.get("id_token")
        if not isinstance(id_token, str) or len(id_token) > 32 * 1024:
            raise RemoteIdentityError("OIDC token response is missing an ID token")
        claims = self._decode(id_token)
        if claims.get("nonce") != transaction.nonce:
            raise RemoteIdentityError("OIDC nonce validation failed")
        return self._actor_from_claims(claims)

    def validate_backchannel_logout(self, token: str) -> Mapping[str, Any]:
        """Validate one signed back-channel logout token."""
        if not token or len(token) > 32 * 1024:
            raise RemoteIdentityError("OIDC logout token is invalid")
        claims = self._decode(token, require_subject=False)
        events = claims.get("events")
        if not isinstance(events, dict) or _BACKCHANNEL_EVENT not in events:
            raise RemoteIdentityError("OIDC logout event is invalid")
        if "nonce" in claims or not isinstance(claims.get("jti"), str):
            raise RemoteIdentityError("OIDC logout claims are invalid")
        if not isinstance(claims.get("sid"), str) and not isinstance(
            claims.get("sub"), str
        ):
            raise RemoteIdentityError("OIDC logout subject is missing")
        return claims

    def metadata(self) -> OIDCMetadata:
        """Load and pin one bounded discovery document."""
        if self._metadata is not None:
            return self._metadata
        discovery = (
            f"{self.settings.issuer}/.well-known/openid-configuration"
            if not self.settings.issuer.endswith("/")
            else f"{self.settings.issuer}.well-known/openid-configuration"
        )
        payload = self._fetch_json(
            "GET", discovery, {"Accept": "application/json"}, None
        )
        if payload.get("issuer") != self.settings.issuer:
            raise RemoteIdentityError(
                "OIDC discovery issuer does not match configuration"
            )
        algorithms = payload.get("id_token_signing_alg_values_supported")
        if not isinstance(algorithms, list) or "RS256" not in algorithms:
            raise RemoteIdentityError("OIDC issuer does not advertise admitted RS256")
        response_types = payload.get("response_types_supported")
        if not isinstance(response_types, list) or "code" not in response_types:
            raise RemoteIdentityError(
                "OIDC issuer does not advertise Authorization Code flow"
            )
        challenge_methods = payload.get("code_challenge_methods_supported")
        if not isinstance(challenge_methods, list) or "S256" not in challenge_methods:
            raise RemoteIdentityError("OIDC issuer does not advertise PKCE S256")
        self._metadata = OIDCMetadata(
            issuer=self.settings.issuer,
            authorization_endpoint=_issuer_endpoint(
                _required_text(payload, "authorization_endpoint"),
                issuer=self.settings.issuer,
            ),
            token_endpoint=_issuer_endpoint(
                _required_text(payload, "token_endpoint"),
                issuer=self.settings.issuer,
            ),
            jwks_uri=_issuer_endpoint(
                _required_text(payload, "jwks_uri"),
                issuer=self.settings.issuer,
            ),
            end_session_endpoint=(
                _issuer_endpoint(
                    str(payload["end_session_endpoint"]),
                    issuer=self.settings.issuer,
                )
                if isinstance(payload.get("end_session_endpoint"), str)
                else None
            ),
        )
        return self._metadata

    def _decode(
        self,
        token: str,
        *,
        require_subject: bool = True,
    ) -> Mapping[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise RemoteIdentityError("OIDC token header is invalid") from exc
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise RemoteIdentityError("OIDC token algorithm or key ID is not admitted")
        key = self._signing_key(str(header["kid"]), refresh=False)
        required_claims = ["exp", "iat", "iss", "aud"]
        if require_subject:
            required_claims.append("sub")
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                audience=self.settings.client_id,
                issuer=self.settings.issuer,
                leeway=REMOTE_CLOCK_SKEW_SECONDS,
                options={"require": required_claims},
            )
        except jwt.InvalidSignatureError:
            key = self._signing_key(str(header["kid"]), refresh=True)
            try:
                claims = jwt.decode(
                    token,
                    key=key,
                    algorithms=["RS256"],
                    audience=self.settings.client_id,
                    issuer=self.settings.issuer,
                    leeway=REMOTE_CLOCK_SKEW_SECONDS,
                    options={"require": required_claims},
                )
            except jwt.PyJWTError as exc:
                raise RemoteIdentityError("OIDC token validation failed") from exc
        except jwt.PyJWTError as exc:
            raise RemoteIdentityError("OIDC token validation failed") from exc
        azp = claims.get("azp")
        audience = claims.get("aud")
        if (
            azp is not None
            and azp != self.settings.client_id
            or isinstance(audience, list)
            and len(audience) > 1
            and azp != self.settings.client_id
        ):
            raise RemoteIdentityError("OIDC authorized party validation failed")
        return claims

    def _signing_key(self, kid: str, *, refresh: bool) -> Any:
        if refresh or self._jwks is None:
            metadata = self.metadata()
            self._jwks = self._fetch_json(
                "GET", metadata.jwks_uri, {"Accept": "application/json"}, None
            )
        keys = self._jwks.get("keys") if self._jwks is not None else None
        if not isinstance(keys, list):
            raise RemoteIdentityError("OIDC JWKS is invalid")
        for value in keys:
            if isinstance(value, dict) and value.get("kid") == kid:
                try:
                    return jwt.PyJWK.from_dict(value, algorithm="RS256").key
                except (jwt.PyJWTError, ValueError) as exc:
                    raise RemoteIdentityError("OIDC signing key is invalid") from exc
        if not refresh:
            return self._signing_key(kid, refresh=True)
        raise RemoteIdentityError("OIDC signing key is unavailable")

    def _actor_from_claims(self, claims: Mapping[str, Any]) -> RemoteActor:
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject or len(subject) > 512:
            raise RemoteIdentityError("OIDC subject is invalid")
        role = self.settings.roles.get(subject)
        if role not in {"viewer", "operator"}:
            raise RemoteIdentityError("OIDC subject is not mapped to a GigaLoom role")
        issued_at = claims.get("auth_time", claims.get("iat"))
        if not isinstance(issued_at, (int, float)):
            raise RemoteIdentityError("OIDC authentication time is invalid")
        if issued_at > self._clock() + REMOTE_CLOCK_SKEW_SECONDS:
            raise RemoteIdentityError("OIDC authentication time is outside clock skew")
        sid = claims.get("sid")
        if sid is not None and (not isinstance(sid, str) or len(sid) > 512):
            raise RemoteIdentityError("OIDC issuer session ID is invalid")
        return RemoteActor(
            actor_id=_actor_id(self.settings.issuer, subject),
            issuer=self.settings.issuer,
            subject=subject,
            role=role,
            issuer_session_id=sid,
            authentication_time=float(issued_at),
        )


class RemoteIdentityStore:
    """Persist hashed remote sessions, transactions, and revocation state."""

    def __init__(
        self,
        data_dir: str | Path,
        settings: RemoteOIDCSettings,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.root = Path(data_dir).expanduser() / "ui_access"
        self.path = self.root / "remote_state.json"
        self.settings = settings
        self._clock = clock

    def begin_login(self, redirect_path: str) -> LoginTransaction:
        """Persist a browser-bound, one-use login transaction."""
        transaction = LoginTransaction(
            state=secrets.token_urlsafe(32),
            nonce=secrets.token_urlsafe(32),
            verifier=secrets.token_urlsafe(64),
            binding=secrets.token_urlsafe(32),
            redirect_path=_safe_redirect(redirect_path),
            expires_at=self._clock() + REMOTE_LOGIN_TTL_SECONDS,
        )
        with self._state_lock():
            state = self._load()
            self._prune(state)
            state["transactions"].append(
                {
                    "state_digest": _digest(transaction.state),
                    "binding_digest": _digest(transaction.binding),
                    "nonce": transaction.nonce,
                    "verifier": transaction.verifier,
                    "redirect_path": transaction.redirect_path,
                    "expires_at": transaction.expires_at,
                }
            )
            state["transactions"] = state["transactions"][-32:]
            self._write(state)
        return transaction

    def consume_login(self, state_value: str, binding: str | None) -> LoginTransaction:
        """Consume exactly one matching unexpired transaction before exchange."""
        if not state_value or not binding:
            raise RemoteIdentityError("OIDC login transaction is missing")
        state_digest = _digest(state_value)
        binding_digest = _digest(binding)
        with self._state_lock():
            state = self._load()
            self._prune(state)
            match: Mapping[str, Any] | None = None
            retained = []
            for record in state["transactions"]:
                if secrets.compare_digest(
                    record["state_digest"], state_digest
                ) and secrets.compare_digest(record["binding_digest"], binding_digest):
                    match = record
                else:
                    retained.append(record)
            state["transactions"] = retained
            self._write(state)
        if match is None:
            raise RemoteIdentityError("OIDC login transaction is invalid or replayed")
        return LoginTransaction(
            state=state_value,
            nonce=str(match["nonce"]),
            verifier=str(match["verifier"]),
            binding=binding,
            redirect_path=str(match["redirect_path"]),
            expires_at=float(match["expires_at"]),
        )

    def issue_session(self, actor: RemoteActor) -> RemoteBrowserSession:
        """Create one opaque session while persisting only its digest."""
        now = self._clock()
        session = RemoteBrowserSession(
            token=secrets.token_urlsafe(32),
            session_id=f"uis_{uuid4().hex}",
            actor=actor,
            expires_at=now + self.settings.absolute_ttl_seconds,
            idle_expires_at=now + self.settings.idle_ttl_seconds,
        )
        with self._state_lock():
            state = self._load()
            self._prune(state)
            state["sessions"].append(_session_record(session, now))
            state["sessions"] = state["sessions"][-512:]
            self._write(state)
        return session

    def authenticate(self, token: str | None) -> RemoteBrowserSession | None:
        """Validate and touch one non-revoked session and current role mapping."""
        if not token:
            return None
        now = self._clock()
        digest = _digest(token)
        with self._state_lock():
            state = self._load()
            self._prune(state)
            record = next(
                (
                    item
                    for item in state["sessions"]
                    if secrets.compare_digest(item["digest"], digest)
                ),
                None,
            )
            if record is None:
                return None
            current_role = self.settings.roles.get(record["subject"])
            if current_role != record["role"]:
                state["sessions"].remove(record)
                self._write(state)
                return None
            record["last_seen_at"] = now
            record["idle_expires_at"] = min(
                record["expires_at"], now + self.settings.idle_ttl_seconds
            )
            self._write(state)
        actor = RemoteActor(
            actor_id=str(record["actor_id"]),
            issuer=self.settings.issuer,
            subject=str(record["subject"]),
            role=str(record["role"]),
            issuer_session_id=record["issuer_session_id"],
            authentication_time=float(record["authentication_time"]),
        )
        return RemoteBrowserSession(
            token=token,
            session_id=str(record["session_id"]),
            actor=actor,
            expires_at=float(record["expires_at"]),
            idle_expires_at=float(record["idle_expires_at"]),
        )

    def revoke_session(self, token: str | None) -> bool:
        """Revoke the presented remote session."""
        if not token:
            return False
        digest = _digest(token)
        return self._remove_sessions(
            lambda record: secrets.compare_digest(record["digest"], digest)
        )

    def revoke_actor(self, actor_id: str) -> int:
        """Revoke every session for one stable actor identifier."""
        return self._remove_sessions(lambda record: record["actor_id"] == actor_id)

    def revoke_all(self) -> int:
        """Rotate the deployment session generation and revoke all sessions."""
        with self._state_lock():
            state = self._load()
            count = len(state["sessions"])
            state["generation"] += 1
            state["sessions"] = []
            state["transactions"] = []
            self._write(state)
            return count

    def apply_backchannel_logout(self, claims: Mapping[str, Any]) -> int:
        """Apply one non-replayed issuer logout event."""
        jti = str(claims["jti"])
        sid = claims.get("sid")
        subject = claims.get("sub")
        with self._state_lock():
            state = self._load()
            self._prune(state)
            if jti in state["logout_jtis"]:
                raise RemoteIdentityError("OIDC logout token was already used")
            state["logout_jtis"].append(jti)
            state["logout_jtis"] = state["logout_jtis"][-1024:]
            retained = []
            removed = 0
            for record in state["sessions"]:
                matches = (
                    isinstance(sid, str) and record["issuer_session_id"] == sid
                ) or (
                    not isinstance(sid, str)
                    and isinstance(subject, str)
                    and record["subject"] == subject
                )
                if matches:
                    removed += 1
                else:
                    retained.append(record)
            state["sessions"] = retained
            self._write(state)
            return removed

    def _remove_sessions(self, predicate: Callable[[Mapping[str, Any]], bool]) -> int:
        with self._state_lock():
            state = self._load()
            retained = []
            removed = 0
            for record in state["sessions"]:
                if predicate(record):
                    removed += 1
                else:
                    retained.append(record)
            if removed:
                state["sessions"] = retained
                self._write(state)
            return removed

    def _prune(self, state: dict[str, Any]) -> None:
        now = self._clock()
        state["transactions"] = [
            item for item in state["transactions"] if item["expires_at"] > now
        ]
        state["sessions"] = [
            item
            for item in state["sessions"]
            if item["expires_at"] > now and item["idle_expires_at"] > now
        ]

    def _state_lock(self):
        self._ensure_root()
        return exclusive_file_lock(self.path)

    def _ensure_root(self) -> None:
        try:
            status = self.root.lstat()
        except FileNotFoundError:
            self.root.mkdir(parents=True, mode=0o700)
            status = self.root.lstat()
        if not stat.S_ISDIR(status.st_mode) or self.root.is_symlink():
            raise RemoteIdentityError(
                "remote UI identity root must be a private directory"
            )
        try:
            self.root.chmod(0o700)
        except OSError:
            pass

    def _load(self) -> dict[str, Any]:
        try:
            status = self.path.lstat()
        except FileNotFoundError:
            return _empty_state()
        if not stat.S_ISREG(status.st_mode) or self.path.is_symlink():
            raise RemoteIdentityError("remote UI identity state must be a regular file")
        descriptor = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise RemoteIdentityError(
                    "remote UI identity state must be a regular file"
                )
            if hasattr(os, "fchmod"):
                os.fchmod(descriptor, 0o600)
            raw = os.read(descriptor, _MAX_PRIVATE_STATE_BYTES + 1)
        finally:
            os.close(descriptor)
        if len(raw) > _MAX_PRIVATE_STATE_BYTES:
            raise RemoteIdentityError("remote UI identity state is too large")
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RemoteIdentityError("remote UI identity state is invalid") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != _SCHEMA_VERSION
            or not isinstance(payload.get("generation"), int)
            or not isinstance(payload.get("transactions"), list)
            or not isinstance(payload.get("sessions"), list)
            or not isinstance(payload.get("logout_jtis"), list)
        ):
            raise RemoteIdentityError("remote UI identity state is invalid")
        return payload

    def _write(self, payload: Mapping[str, Any]) -> None:
        content = (
            json.dumps(payload, indent=2, sort_keys=True, separators=(",", ": ")) + "\n"
        ).encode()
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, content)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, self.path)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass


def _empty_state() -> dict[str, Any]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "generation": 1,
        "transactions": [],
        "sessions": [],
        "logout_jtis": [],
    }


def _session_record(session: RemoteBrowserSession, now: float) -> dict[str, Any]:
    return {
        "digest": _digest(session.token),
        "session_id": session.session_id,
        "actor_id": session.actor.actor_id,
        "subject": session.actor.subject,
        "role": session.actor.role,
        "issuer_session_id": session.actor.issuer_session_id,
        "authentication_time": session.actor.authentication_time,
        "created_at": now,
        "last_seen_at": now,
        "expires_at": session.expires_at,
        "idle_expires_at": session.idle_expires_at,
    }


def _actor_id(issuer: str, subject: str) -> str:
    material = issuer.encode() + b"\0" + subject.encode()
    return f"oidc_{sha256(material).hexdigest()}"


def _digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _safe_redirect(value: str) -> str:
    parsed = urlsplit(value or "/cockpit-v2/work")
    if (
        parsed.scheme
        or parsed.netloc
        or "\\" in value
        or not parsed.path.startswith("/cockpit-v2/")
    ):
        return "/cockpit-v2/work"
    return value


def _https_url(value: str, *, allow_path: bool) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
        or (not allow_path and parsed.path not in {"", "/"})
    ):
        raise RemoteIdentityError("OIDC URLs must be exact credential-free HTTPS URLs")
    return value.strip().rstrip("/")


def _issuer_endpoint(value: str, *, issuer: str) -> str:
    endpoint = _https_url(value, allow_path=True)
    parsed_endpoint = urlsplit(endpoint)
    parsed_issuer = urlsplit(issuer)
    if (
        parsed_endpoint.scheme,
        parsed_endpoint.hostname,
        parsed_endpoint.port,
    ) != (
        parsed_issuer.scheme,
        parsed_issuer.hostname,
        parsed_issuer.port,
    ):
        raise RemoteIdentityError(
            "OIDC endpoints must use the configured issuer origin"
        )
    return endpoint


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


def _validated_proxy(value: str) -> str:
    import ipaddress

    try:
        return str(ipaddress.ip_address(value))
    except ValueError as exc:
        raise RemoteIdentityError("trusted proxies must be exact IP addresses") from exc


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise RemoteIdentityError(f"OIDC discovery is missing {key}")
    return value


def _fetch_json(
    method: str,
    url: str,
    headers: Mapping[str, str],
    data: bytes | None,
) -> Mapping[str, Any]:
    request = URLRequest(url, data=data, headers=dict(headers), method=method)
    try:
        with build_opener(_NoRedirectHandler()).open(request, timeout=10) as response:
            if response.status < 200 or response.status >= 300:
                raise RemoteIdentityError("OIDC endpoint returned an error")
            raw = response.read(512 * 1024 + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RemoteIdentityError("OIDC endpoint is unavailable") from exc
    if len(raw) > 512 * 1024:
        raise RemoteIdentityError("OIDC endpoint response is too large")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RemoteIdentityError("OIDC endpoint returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RemoteIdentityError("OIDC endpoint returned an invalid object")
    return payload
