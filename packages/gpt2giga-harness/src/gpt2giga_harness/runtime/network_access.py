"""Fail-closed scoped network authority for Harness-owned transports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import hashlib
import ipaddress
import json
import re
from typing import Any, Iterable
from urllib.parse import urlsplit

from gpt2giga_harness.runtime.authority import (
    AuthorityGrant,
    AuthorityScope,
    NetworkTarget,
)
from gpt2giga_harness.runtime.policy import EnforcementLevel


NETWORK_ACCESS_SCHEMA_VERSION = 1
DEFAULT_MAX_REQUEST_BODY_BYTES = 64 * 1024
DEFAULT_MAX_RESPONSE_BODY_BYTES = 1024 * 1024
HARD_MAX_REQUEST_BODY_BYTES = 1024 * 1024
HARD_MAX_RESPONSE_BODY_BYTES = 16 * 1024 * 1024
MAX_REDIRECT_HOPS = 5
MAX_RESOLVED_ADDRESSES = 32
MAX_URL_LENGTH = 4096
MAX_PURPOSE_LENGTH = 128
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DNS_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_PURPOSE_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_WRITE_METHODS = frozenset({"DELETE", "PATCH", "POST", "PUT"})


class NetworkAccessDenied(PermissionError):
    """Content-free denial raised before a network side effect."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class NetworkMethodClass(str, Enum):
    """Method classes admitted independently by a network grant."""

    SAFE = "safe"
    WRITE = "write"


@dataclass(frozen=True)
class ScopedNetworkRequest:
    """One exact request intent without retaining headers or body content."""

    url: str
    method: str
    purpose: str
    request_body_bytes: int = 0
    request_body_sha256: str | None = None
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BODY_BYTES
    redirect_policy: str = "deny"
    redirect_hops: int = 0
    schema_version: int = NETWORK_ACCESS_SCHEMA_VERSION
    target: NetworkTarget = field(init=False)
    scope: AuthorityScope = field(init=False)
    preview_sha256: str = field(init=False)
    url_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != NETWORK_ACCESS_SCHEMA_VERSION:
            raise ValueError("unsupported network access schema_version")
        parsed = _canonical_url(self.url)
        method = str(self.method).strip().upper()
        method_class = _method_class(method)
        purpose = _purpose(self.purpose)
        request_bytes = _bounded_size(
            self.request_body_bytes,
            "network request body",
            hard_limit=HARD_MAX_REQUEST_BODY_BYTES,
        )
        response_bytes = _bounded_size(
            self.max_response_bytes,
            "network response body",
            hard_limit=HARD_MAX_RESPONSE_BODY_BYTES,
            allow_zero=False,
        )
        body_sha256 = _optional_sha256(self.request_body_sha256)
        redirect_hops = _bounded_size(
            self.redirect_hops,
            "network redirect hops",
            hard_limit=MAX_REDIRECT_HOPS,
        )
        if (request_bytes == 0) != (body_sha256 is None):
            raise ValueError(
                "network request body sha256 must match the declared body size"
            )
        if method_class is NetworkMethodClass.SAFE and request_bytes:
            raise ValueError("safe network methods cannot include a request body")
        target = NetworkTarget(
            host=parsed["host"],
            port=parsed["port"],
            protocol=parsed["scheme"],
            redirect_policy=self.redirect_policy,
        )
        scope = AuthorityScope(
            target=target,
            operations=(f"request.{method_class.value}",),
        )
        preview = {
            "schema_version": self.schema_version,
            "scope_sha256": scope.scope_sha256,
            "method": method,
            "method_class": method_class.value,
            "purpose": purpose,
            "request_body_bytes": request_bytes,
            "request_body_sha256": body_sha256,
            "max_response_bytes": response_bytes,
        }
        canonical_url = parsed["url"]
        object.__setattr__(self, "url", canonical_url)
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "purpose", purpose)
        object.__setattr__(self, "request_body_bytes", request_bytes)
        object.__setattr__(self, "request_body_sha256", body_sha256)
        object.__setattr__(self, "max_response_bytes", response_bytes)
        object.__setattr__(self, "redirect_hops", redirect_hops)
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "preview_sha256", _json_hash(preview))
        object.__setattr__(
            self,
            "url_sha256",
            hashlib.sha256(canonical_url.encode("utf-8")).hexdigest(),
        )

    @property
    def method_class(self) -> NetworkMethodClass:
        """Return the exact method class bound into the authority scope."""
        return _method_class(self.method)

    @property
    def origin(self) -> str:
        """Return the canonical public origin without a path or query."""
        target = self.target.to_dict()
        return f"{target['protocol']}://{_url_host(target['host'])}:{target['port']}"

    def with_redirect(self, url: str) -> ScopedNetworkRequest:
        """Create a same-intent redirect request for mandatory revalidation."""
        return ScopedNetworkRequest(
            url=url,
            method=self.method,
            purpose=self.purpose,
            request_body_bytes=self.request_body_bytes,
            request_body_sha256=self.request_body_sha256,
            max_response_bytes=self.max_response_bytes,
            redirect_policy=self.target.redirect_policy,
            redirect_hops=self.redirect_hops + 1,
        )


@dataclass(frozen=True)
class ReviewedDomainRule:
    """One reviewed allowlist entry bound to explicit purposes and expiry."""

    pattern: str
    purposes: tuple[str, ...]
    reviewed_by: str
    expires_at: str

    def __post_init__(self) -> None:
        pattern = _domain_pattern(self.pattern)
        purposes = tuple(sorted({_purpose(item) for item in self.purposes}))
        if not purposes:
            raise ValueError("reviewed domain rule requires purposes")
        reviewer = _purpose(self.reviewed_by)
        _timestamp(self.expires_at, "reviewed domain rule expires_at")
        object.__setattr__(self, "pattern", pattern)
        object.__setattr__(self, "purposes", purposes)
        object.__setattr__(self, "reviewed_by", reviewer)

    def admits(self, host: str, purpose: str, *, now: str) -> bool:
        """Return whether this unexpired rule covers one host and purpose."""
        if _timestamp(self.expires_at, "reviewed domain rule expires_at") <= _timestamp(
            now,
            "network access time",
        ):
            return False
        if _purpose(purpose) not in self.purposes:
            return False
        canonical_host = _canonical_host(host)
        if self.pattern.startswith("**."):
            base = self.pattern[3:]
            return canonical_host == base or canonical_host.endswith(f".{base}")
        if self.pattern.startswith("*."):
            base = self.pattern[2:]
            return canonical_host != base and canonical_host.endswith(f".{base}")
        return canonical_host == self.pattern

    def to_dict(self) -> dict[str, Any]:
        """Serialize one content-free reviewed rule."""
        return {
            "pattern": self.pattern,
            "purposes": list(self.purposes),
            "reviewed_by": self.reviewed_by,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True)
class ReviewedDomainProxyPolicy:
    """Optional loopback-only, allowlist-first proxy enforcement policy."""

    enabled: bool = False
    rules: tuple[ReviewedDomainRule, ...] = ()
    listener_host: str = "127.0.0.1"
    max_request_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES
    max_response_body_bytes: int = DEFAULT_MAX_RESPONSE_BODY_BYTES
    schema_version: int = NETWORK_ACCESS_SCHEMA_VERSION
    policy_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != NETWORK_ACCESS_SCHEMA_VERSION:
            raise ValueError("unsupported network proxy schema_version")
        if not isinstance(self.enabled, bool):
            raise ValueError("network proxy enabled must be boolean")
        try:
            listener = ipaddress.ip_address(self.listener_host)
        except ValueError as exc:
            raise ValueError("network proxy listener must be a loopback IP") from exc
        if not listener.is_loopback:
            raise ValueError("network proxy listener must be loopback-only")
        request_limit = _bounded_size(
            self.max_request_body_bytes,
            "network proxy request limit",
            hard_limit=HARD_MAX_REQUEST_BODY_BYTES,
            allow_zero=False,
        )
        response_limit = _bounded_size(
            self.max_response_body_bytes,
            "network proxy response limit",
            hard_limit=HARD_MAX_RESPONSE_BODY_BYTES,
            allow_zero=False,
        )
        rules = tuple(sorted(self.rules, key=lambda item: item.pattern))
        if self.enabled and not rules:
            raise ValueError("enabled network proxy requires a reviewed allowlist")
        if len({item.pattern for item in rules}) != len(rules):
            raise ValueError("network proxy allowlist contains duplicate patterns")
        payload = {
            "schema_version": self.schema_version,
            "enabled": bool(self.enabled),
            "listener_host": listener.compressed,
            "max_request_body_bytes": request_limit,
            "max_response_body_bytes": response_limit,
            "rules": [item.to_dict() for item in rules],
        }
        object.__setattr__(self, "listener_host", listener.compressed)
        object.__setattr__(self, "max_request_body_bytes", request_limit)
        object.__setattr__(self, "max_response_body_bytes", response_limit)
        object.__setattr__(self, "rules", rules)
        object.__setattr__(self, "policy_sha256", _json_hash(payload))

    def admits(self, request: ScopedNetworkRequest, *, now: str) -> bool:
        """Return whether the reviewed allowlist admits one request."""
        if not self.enabled:
            return True
        return any(
            rule.admits(request.target.host, request.purpose, now=now)
            for rule in self.rules
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize auditable proxy policy without credentials or traffic."""
        return {
            "schema_version": self.schema_version,
            "enabled": bool(self.enabled),
            "listener_host": self.listener_host,
            "max_request_body_bytes": self.max_request_body_bytes,
            "max_response_body_bytes": self.max_response_body_bytes,
            "rules": [item.to_dict() for item in self.rules],
            "policy_sha256": self.policy_sha256,
        }


@dataclass(frozen=True)
class NetworkAccessTicket:
    """Pre-connect authorization with transport-layer address pinning."""

    grant_id: str
    scope_sha256: str
    preview_sha256: str
    url_sha256: str
    host: str
    port: int
    protocol: str
    method_class: NetworkMethodClass
    purpose: str
    pinned_addresses: tuple[str, ...]
    request_body_bytes: int
    request_body_sha256: str | None
    max_response_bytes: int
    authorized_at: str
    expires_at: str
    proxy_policy_sha256: str | None
    redirect_revalidated: bool

    def validate_connected_peer(self, address: str, *, now: str) -> dict[str, Any]:
        """Fail closed unless the transport peer matches a preflight address."""
        self._ensure_active(now)
        peer = _public_address(address)
        if peer not in self.pinned_addresses:
            raise NetworkAccessDenied("network_peer_changed_after_resolution")
        return {
            "schema_version": NETWORK_ACCESS_SCHEMA_VERSION,
            "grant_id": self.grant_id,
            "scope_sha256": self.scope_sha256,
            "preview_sha256": self.preview_sha256,
            "url_sha256": self.url_sha256,
            "peer_address_sha256": hashlib.sha256(peer.encode("ascii")).hexdigest(),
            "purpose": self.purpose,
            "redirect_revalidated": self.redirect_revalidated,
            "outcome": "peer_validated",
        }

    def validate_request_body(
        self,
        *,
        body_bytes: int,
        body_sha256: str | None,
        now: str,
    ) -> dict[str, Any]:
        """Fail closed if the actual outbound body differs from the preview."""
        self._ensure_active(now)
        size = _bounded_size(
            body_bytes,
            "network request body",
            hard_limit=HARD_MAX_REQUEST_BODY_BYTES,
        )
        digest = _optional_sha256(body_sha256)
        if size != self.request_body_bytes or digest != self.request_body_sha256:
            raise NetworkAccessDenied("network_request_body_changed_after_review")
        return {
            "schema_version": NETWORK_ACCESS_SCHEMA_VERSION,
            "grant_id": self.grant_id,
            "preview_sha256": self.preview_sha256,
            "request_body_bytes": size,
            "outcome": "request_body_validated",
        }

    def validate_response_body(self, *, body_bytes: int) -> dict[str, Any]:
        """Fail closed when a response exceeds the reviewed read ceiling."""
        if not isinstance(body_bytes, int) or isinstance(body_bytes, bool):
            raise NetworkAccessDenied("network_response_body_size_is_invalid")
        size = body_bytes
        if not 0 <= size <= self.max_response_bytes:
            raise NetworkAccessDenied("network_response_body_exceeds_reviewed_limit")
        return {
            "schema_version": NETWORK_ACCESS_SCHEMA_VERSION,
            "grant_id": self.grant_id,
            "preview_sha256": self.preview_sha256,
            "response_body_bytes": size,
            "outcome": "response_body_validated",
        }

    def _ensure_active(self, now: str) -> None:
        current = _timestamp(now, "network ticket validation time")
        if current < _timestamp(self.authorized_at, "network ticket authorized_at"):
            raise NetworkAccessDenied("network_ticket_clock_moved_backwards")
        if current >= _timestamp(self.expires_at, "network ticket expires_at"):
            raise NetworkAccessDenied("network_ticket_is_expired")

    def audit_receipt(self) -> dict[str, Any]:
        """Return bounded content-free pre-connect evidence."""
        address_set_sha256 = _json_hash({"addresses": list(self.pinned_addresses)})
        return {
            "schema_version": NETWORK_ACCESS_SCHEMA_VERSION,
            "grant_id": self.grant_id,
            "scope_sha256": self.scope_sha256,
            "preview_sha256": self.preview_sha256,
            "url_sha256": self.url_sha256,
            "host": self.host,
            "port": self.port,
            "protocol": self.protocol,
            "method_class": self.method_class.value,
            "purpose": self.purpose,
            "request_body_bytes": self.request_body_bytes,
            "max_response_bytes": self.max_response_bytes,
            "address_count": len(self.pinned_addresses),
            "address_set_sha256": address_set_sha256,
            "authorized_at": self.authorized_at,
            "expires_at": self.expires_at,
            "proxy_policy_sha256": self.proxy_policy_sha256,
            "redirect_revalidated": self.redirect_revalidated,
            "outcome": "authorized_pre_connect",
            "peer_validation_required": True,
        }


def authorize_scoped_network_access(
    request: ScopedNetworkRequest,
    grant: AuthorityGrant,
    *,
    resolved_addresses: Iterable[str],
    now: str,
    sandbox_network_enabled: bool = False,
    proxy_policy: ReviewedDomainProxyPolicy | None = None,
    redirect_from: ScopedNetworkRequest | None = None,
    retry: bool = False,
) -> NetworkAccessTicket:
    """Authorize one request without opening a socket or sending traffic."""
    current_time = _timestamp(now, "network access time")
    if not sandbox_network_enabled:
        raise NetworkAccessDenied("sandbox_network_access_is_disabled")
    if grant.enforcement is not EnforcementLevel.ENFORCED_BY_HARNESS:
        raise NetworkAccessDenied("network_grant_is_not_harness_enforced")
    if grant.revoked_at is not None:
        raise NetworkAccessDenied("network_grant_is_revoked")
    if grant.expires_at is None:
        raise NetworkAccessDenied("network_grant_requires_expiry")
    if _timestamp(grant.expires_at, "network grant expires_at") <= current_time:
        raise NetworkAccessDenied("network_grant_is_expired")
    if retry:
        raise NetworkAccessDenied("network_retry_requires_fresh_authorization")
    if grant.scope.scope_sha256 != request.scope.scope_sha256:
        raise NetworkAccessDenied("network_scope_does_not_match_grant")
    if grant.preview_sha256 != request.preview_sha256:
        raise NetworkAccessDenied("network_preview_does_not_match_grant")

    redirect_revalidated = redirect_from is not None
    if redirect_from is not None:
        if request.redirect_hops != redirect_from.redirect_hops + 1:
            raise NetworkAccessDenied("network_redirect_hop_sequence_is_invalid")
        if grant.scope.target.redirect_policy != "same_origin":
            raise NetworkAccessDenied("network_redirect_is_not_allowed")
        if redirect_from.origin != request.origin:
            raise NetworkAccessDenied("network_redirect_changed_origin")
        if (
            redirect_from.method != request.method
            or redirect_from.purpose != request.purpose
            or redirect_from.preview_sha256 != request.preview_sha256
        ):
            raise NetworkAccessDenied("network_redirect_changed_intent")
    elif request.redirect_hops:
        raise NetworkAccessDenied("network_redirect_origin_is_missing")

    policy = proxy_policy or ReviewedDomainProxyPolicy()
    if request.request_body_bytes > policy.max_request_body_bytes:
        raise NetworkAccessDenied("network_request_body_exceeds_reviewed_limit")
    if request.max_response_bytes > policy.max_response_body_bytes:
        raise NetworkAccessDenied("network_response_body_exceeds_reviewed_limit")
    if not policy.admits(request, now=now):
        raise NetworkAccessDenied("network_destination_is_not_reviewed")

    addresses = _public_addresses(resolved_addresses)
    if not addresses:
        raise NetworkAccessDenied("network_dns_resolution_is_empty")
    literal = _ip_literal(request.target.host)
    if literal is not None and addresses != (literal,):
        raise NetworkAccessDenied("network_literal_resolution_changed_target")

    return NetworkAccessTicket(
        grant_id=grant.id,
        scope_sha256=request.scope.scope_sha256,
        preview_sha256=request.preview_sha256,
        url_sha256=request.url_sha256,
        host=request.target.host,
        port=request.target.port,
        protocol=request.target.protocol,
        method_class=request.method_class,
        purpose=request.purpose,
        pinned_addresses=addresses,
        request_body_bytes=request.request_body_bytes,
        request_body_sha256=request.request_body_sha256,
        max_response_bytes=request.max_response_bytes,
        authorized_at=now,
        expires_at=grant.expires_at,
        proxy_policy_sha256=policy.policy_sha256 if policy.enabled else None,
        redirect_revalidated=redirect_revalidated,
    )


def network_access_manifest() -> dict[str, Any]:
    """Return the source-owned G4-02 security and UX contract."""
    return {
        "schema_version": NETWORK_ACCESS_SCHEMA_VERSION,
        "default_sandbox_network_access": "deny",
        "grant_bindings": [
            "host",
            "port",
            "protocol",
            "method_class",
            "expiry",
            "redirect_policy",
            "purpose",
            "preview_sha256",
        ],
        "reviewed_proxy": {
            "optional": True,
            "listener": "loopback_only",
            "policy": "allowlist_first",
            "global_wildcard_allowed": False,
        },
        "ssrf_controls": [
            "public_ip_only",
            "empty_or_failed_resolution_denied",
            "all_resolved_addresses_classified",
            "transport_peer_must_match_pinned_resolution",
            "same_origin_redirect_revalidation",
        ],
        "bounded_transfer": {
            "default_request_body_bytes": DEFAULT_MAX_REQUEST_BODY_BYTES,
            "default_response_body_bytes": DEFAULT_MAX_RESPONSE_BODY_BYTES,
            "request_body_content": "sha256_only",
        },
        "blanket_internet_switch": False,
        "live_network_side_effect": False,
    }


def _canonical_url(value: str) -> dict[str, Any]:
    text = str(value).strip()
    if not text or len(text) > MAX_URL_LENGTH:
        raise ValueError("network URL length is invalid")
    parsed = urlsplit(text)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("network URL must be canonical HTTPS without credentials")
    try:
        explicit_port = parsed.port
    except ValueError as exc:
        raise ValueError("network URL port is invalid") from exc
    port = explicit_port or 443
    host = _canonical_host(parsed.hostname)
    canonical = f"https://{_url_host(host)}"
    if port != 443:
        canonical = f"{canonical}:{port}"
    canonical = f"{canonical}{parsed.path or '/'}"
    if parsed.query:
        canonical = f"{canonical}?{parsed.query}"
    if text != canonical:
        raise ValueError("network URL must be canonical")
    return {"url": canonical, "scheme": "https", "host": host, "port": port}


def _canonical_host(value: str) -> str:
    text = str(value).strip().lower().rstrip(".")
    if not text or len(text) > 253:
        raise ValueError("network host is invalid")
    try:
        return ipaddress.ip_address(text).compressed
    except ValueError:
        pass
    try:
        ascii_host = text.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("network host is invalid") from exc
    labels = ascii_host.split(".")
    if len(labels) < 2 or any(
        _DNS_LABEL_RE.fullmatch(label) is None for label in labels
    ):
        raise ValueError("network host must be a canonical DNS name or IP literal")
    return ascii_host


def _domain_pattern(value: str) -> str:
    text = str(value).strip().lower()
    if text == "*":
        raise ValueError("global network wildcard is not permitted")
    prefix = ""
    base = text
    for candidate in ("**.", "*."):
        if text.startswith(candidate):
            prefix = candidate
            base = text[len(candidate) :]
            break
    host = _canonical_host(base)
    if prefix and _ip_literal(host) is not None:
        raise ValueError("network wildcard cannot target an IP literal")
    return f"{prefix}{host}"


def _method_class(method: str) -> NetworkMethodClass:
    if method in _SAFE_METHODS:
        return NetworkMethodClass.SAFE
    if method in _WRITE_METHODS:
        return NetworkMethodClass.WRITE
    raise ValueError("network method is unsupported")


def _purpose(value: str) -> str:
    text = str(value).strip()
    if len(text) > MAX_PURPOSE_LENGTH or _PURPOSE_RE.fullmatch(text) is None:
        raise ValueError("network purpose is invalid")
    return text


def _optional_sha256(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    if _SHA256_RE.fullmatch(text) is None:
        raise ValueError("network request body sha256 is invalid")
    return text


def _bounded_size(
    value: int,
    field_name: str,
    *,
    hard_limit: int,
    allow_zero: bool = True,
) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} size is invalid")
    size = value
    minimum = 0 if allow_zero else 1
    if not minimum <= size <= hard_limit:
        raise ValueError(f"{field_name} size is invalid")
    return size


def _public_address(value: str) -> str:
    try:
        address = ipaddress.ip_address(str(value).strip())
    except ValueError as exc:
        raise NetworkAccessDenied(
            "network_resolution_contains_invalid_address"
        ) from exc
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if not address.is_global:
        raise NetworkAccessDenied("network_resolution_contains_non_public_address")
    return address.compressed


def _public_addresses(values: Iterable[str]) -> tuple[str, ...]:
    addresses: set[str] = set()
    for index, item in enumerate(values, start=1):
        if index > MAX_RESOLVED_ADDRESSES:
            raise NetworkAccessDenied("network_resolution_has_too_many_addresses")
        addresses.add(_public_address(item))
    return tuple(sorted(addresses))


def _ip_literal(value: str) -> str | None:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.compressed


def _url_host(value: str) -> str:
    return f"[{value}]" if ":" in value else value


def _timestamp(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{field_name} is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed


def _json_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "DEFAULT_MAX_REQUEST_BODY_BYTES",
    "DEFAULT_MAX_RESPONSE_BODY_BYTES",
    "NETWORK_ACCESS_SCHEMA_VERSION",
    "NetworkAccessDenied",
    "NetworkAccessTicket",
    "NetworkMethodClass",
    "ReviewedDomainProxyPolicy",
    "ReviewedDomainRule",
    "ScopedNetworkRequest",
    "authorize_scoped_network_access",
    "network_access_manifest",
]
