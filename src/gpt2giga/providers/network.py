"""Request-scoped destination authorization for reviewed provider profiles."""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass
import ipaddress
import socket
import time
from typing import Protocol
from urllib.parse import urlsplit

from gpt2giga.providers.profiles.models import ProviderProfile


DEFAULT_NETWORK_TICKET_TTL_SECONDS = 30.0


class ProviderNetworkIntent(Protocol):
    """Common outbound intent exposed by every normalized provider adapter."""

    url: str
    method: str
    purpose: str
    request_body_bytes: int
    request_body_sha256: str | None
    max_response_bytes: int


class ProviderNetworkAuthorizationError(ValueError):
    """Bounded failure raised before or at the reviewed transport boundary."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


Address = ipaddress.IPv4Address | ipaddress.IPv6Address
AddressResolver = Callable[[str, int], Collection[str | Address]]
Clock = Callable[[], float]


@dataclass(frozen=True)
class ProviderNetworkAuthorization:
    """Immutable ticket binding one request to its DNS result and byte limits."""

    scheme: str
    host: str
    port: int
    addresses: frozenset[str]
    method: str
    purpose: str
    request_body_bytes: int
    request_body_sha256: str | None
    max_response_bytes: int
    expires_at: float
    _clock: Clock

    @property
    def peer_validation_required(self) -> bool:
        """Require adapters to prove the connected peer for every ticket."""
        return True

    def validate_request_body(
        self,
        *,
        body_bytes: int,
        body_sha256: str | None,
    ) -> None:
        """Reject any body that differs from the authorized request."""
        self._ensure_current()
        if (
            body_bytes != self.request_body_bytes
            or body_sha256 != self.request_body_sha256
        ):
            raise ProviderNetworkAuthorizationError(
                "request_mismatch",
                "Provider request does not match its network authorization.",
            )

    def validate_connected_peer(self, address: str) -> None:
        """Reject DNS rebinding or a transport peer outside the resolved set."""
        self._ensure_current()
        try:
            normalized = str(ipaddress.ip_address(address.split("%", 1)[0]))
        except ValueError as exc:
            raise ProviderNetworkAuthorizationError(
                "destination_mismatch",
                "Provider transport peer does not match its network authorization.",
            ) from exc
        if normalized not in self.addresses:
            raise ProviderNetworkAuthorizationError(
                "destination_mismatch",
                "Provider transport peer does not match its network authorization.",
            )

    def validate_response_body(self, *, body_bytes: int) -> None:
        """Reject a response beyond the exact reviewed ceiling."""
        self._ensure_current()
        if body_bytes > self.max_response_bytes:
            raise ProviderNetworkAuthorizationError(
                "response_too_large",
                "Provider response exceeds its network authorization.",
            )

    def _ensure_current(self) -> None:
        if self._clock() > self.expires_at:
            raise ProviderNetworkAuthorizationError(
                "destination_mismatch",
                "Provider network authorization has expired.",
            )


class ProviderNetworkAuthorizer:
    """Resolve and authorize exact destinations from one immutable profile."""

    def __init__(
        self,
        profile: ProviderProfile,
        *,
        resolver: AddressResolver | None = None,
        clock: Clock = time.monotonic,
        ticket_ttl_seconds: float = DEFAULT_NETWORK_TICKET_TTL_SECONDS,
    ) -> None:
        if ticket_ttl_seconds <= 0:
            raise ValueError("network ticket TTL must be positive")
        self._profile = profile
        self._resolver = resolver or resolve_host_addresses
        self._clock = clock
        self._ticket_ttl_seconds = ticket_ttl_seconds
        destination = urlsplit(profile.base_url)
        self._scheme = destination.scheme
        self._host = _canonical_host(destination.hostname or "")
        self._port = destination.port or (443 if self._scheme == "https" else 80)
        self._base_path = destination.path.rstrip("/")

    def __call__(
        self,
        intent: ProviderNetworkIntent,
    ) -> ProviderNetworkAuthorization:
        """Issue a short-lived ticket for one exact adapter request."""
        destination = urlsplit(intent.url)
        try:
            host = _canonical_host(destination.hostname or "")
            port = destination.port or (443 if destination.scheme == "https" else 80)
        except ValueError as exc:
            raise _destination_mismatch() from exc
        if (
            destination.scheme != self._scheme
            or host != self._host
            or port != self._port
            or destination.username is not None
            or destination.password is not None
            or destination.fragment
            or not _path_is_within(destination.path, self._base_path)
        ):
            raise _destination_mismatch()

        try:
            resolved = frozenset(
                str(_coerce_address(address))
                for address in self._resolver(self._host, self._port)
            )
        except (OSError, ValueError) as exc:
            raise ProviderNetworkAuthorizationError(
                "destination_mismatch",
                "Provider destination could not be authorized.",
            ) from exc
        if not resolved:
            raise ProviderNetworkAuthorizationError(
                "destination_mismatch",
                "Provider destination resolved to no addresses.",
            )
        _validate_resolved_addresses(
            resolved,
            allow_loopback=self._profile.allow_loopback,
        )
        issued_at = self._clock()
        return ProviderNetworkAuthorization(
            scheme=self._scheme,
            host=self._host,
            port=self._port,
            addresses=resolved,
            method=intent.method,
            purpose=intent.purpose,
            request_body_bytes=intent.request_body_bytes,
            request_body_sha256=intent.request_body_sha256,
            max_response_bytes=intent.max_response_bytes,
            expires_at=issued_at + self._ticket_ttl_seconds,
            _clock=self._clock,
        )


def resolve_host_addresses(host: str, port: int) -> tuple[Address, ...]:
    """Resolve all TCP addresses for a reviewed provider destination."""
    addresses: list[Address] = []
    for family, _socktype, _proto, _canonname, sockaddr in socket.getaddrinfo(
        host,
        port,
        type=socket.SOCK_STREAM,
    ):
        if family in {socket.AF_INET, socket.AF_INET6}:
            addresses.append(ipaddress.ip_address(sockaddr[0]))
    return tuple(addresses)


def _validate_resolved_addresses(
    addresses: Collection[str],
    *,
    allow_loopback: bool,
) -> None:
    parsed = tuple(ipaddress.ip_address(address) for address in addresses)
    if allow_loopback:
        valid = all(address.is_loopback for address in parsed)
    else:
        valid = all(
            address.is_global
            and not address.is_multicast
            and not address.is_reserved
            and not address.is_unspecified
            for address in parsed
        )
    if not valid:
        raise ProviderNetworkAuthorizationError(
            "destination_mismatch",
            "Provider destination resolved outside its reviewed network boundary.",
        )


def _coerce_address(value: str | Address) -> Address:
    if isinstance(value, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        return value
    return ipaddress.ip_address(value.split("%", 1)[0])


def _canonical_host(host: str) -> str:
    if not host or "%" in host:
        raise ValueError("invalid provider host")
    return host.rstrip(".").encode("idna").decode("ascii").lower()


def _path_is_within(path: str, base_path: str) -> bool:
    if not base_path:
        return True
    return path == base_path or path.startswith(f"{base_path}/")


def _destination_mismatch() -> ProviderNetworkAuthorizationError:
    return ProviderNetworkAuthorizationError(
        "destination_mismatch",
        "Provider request destination does not match its reviewed profile.",
    )
