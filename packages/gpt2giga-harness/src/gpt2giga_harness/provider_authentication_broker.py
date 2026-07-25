"""Bounded provider-owned authentication broker with isolated native homes."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import signal
import stat
import subprocess
import threading
import time
from typing import Any, Protocol
from uuid import uuid4

from gpt2giga_harness.cli_capabilities import CliCapabilitySnapshot
from gpt2giga_harness.executables import ExecutableResolution
from gpt2giga_harness.provider_authentication import (
    ProviderAuthenticationEvidence,
    load_provider_authentication_evidence,
)
from gpt2giga_harness.sessions.locking import exclusive_file_lock

AUTH_COMMAND_TIMEOUT_SECONDS = 180.0
AUTH_STATUS_TIMEOUT_SECONDS = 5.0
AUTH_OUTPUT_BYTES = 64 * 1024
_INHERITED_ENVIRONMENT = (
    "PATH",
    "TMPDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "TERM",
    "CODEX_CA_CERTIFICATE",
    "SSL_CERT_FILE",
)
_EXPIRY_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


class ProviderAccountStatus(str, Enum):
    """Public provider-account states admitted by G3-01."""

    LOGGED_OUT = "logged_out"
    PENDING = "pending"
    READY = "ready"
    EXPIRED = "expired"
    REVOKED = "revoked"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ProviderAuthenticationBrokerError(RuntimeError):
    """Base error for bounded provider-owned authentication operations."""


class ProviderAuthenticationConflictError(ProviderAuthenticationBrokerError):
    """Raised when a second login attempts to replace an active one."""


class ProviderAuthenticationOperationError(ProviderAuthenticationBrokerError):
    """Raised when the requested provider operation is not admitted."""


@dataclass(frozen=True)
class AuthenticationCommandResult:
    """Bounded result retained only for immediate status classification."""

    returncode: int
    stdout: bytes = b""
    timed_out: bool = False
    cancelled: bool = False


class AuthenticationCommandRunner(Protocol):
    """Execute one provider-owned command without shell interpolation."""

    def run(
        self,
        argv: Sequence[str],
        *,
        environment: Mapping[str, str],
        cwd: Path,
        timeout_seconds: float,
        cancel_event: threading.Event,
        capture_output: bool,
    ) -> AuthenticationCommandResult:
        """Run one explicit argv in an isolated provider-owned home."""


@dataclass(frozen=True)
class ProviderAccountSnapshot:
    """Content-free account card projection."""

    provider_id: str
    display_name: str
    status: ProviderAccountStatus
    source: str
    checked_at: str
    pinned_cli_version: str
    detected_cli_version: str | None
    version_status: str
    identity_label: str | None
    authentication_method: str | None
    expires_at: str | None
    reason_code: str
    recovery: tuple[str, ...]
    actions: Mapping[str, bool]
    attempt_id: str | None = None
    home_scope: str = "isolated_provider_owned"


@dataclass(frozen=True)
class ProviderSessionBinding:
    """Opaque account and home identity admitted for session continuity."""

    provider_id: str
    account_identity: str
    home_identity: str
    source_identity: str
    identity_evidence: str
    authentication_method: str | None
    observed_at: str
    quota_status: str = "provider_owned_unobserved"
    monetary_cost_status: str = "api_route_separate"
    schema_version: int = 1


@dataclass
class _LoginAttempt:
    id: str
    provider_id: str
    cancel_event: threading.Event
    snapshot: ProviderAccountSnapshot
    thread: threading.Thread | None = None


class BoundedAuthenticationCommandRunner:
    """Subprocess runner that drains but never retains unbounded output."""

    def run(
        self,
        argv: Sequence[str],
        *,
        environment: Mapping[str, str],
        cwd: Path,
        timeout_seconds: float,
        cancel_event: threading.Event,
        capture_output: bool,
    ) -> AuthenticationCommandResult:
        command = tuple(_validated_argument(value) for value in argv)
        stdout_target: Any = subprocess.PIPE if capture_output else subprocess.DEVNULL
        try:
            process = subprocess.Popen(
                command,
                cwd=os.fspath(cwd),
                env=dict(environment),
                stdin=subprocess.DEVNULL,
                stdout=stdout_target,
                stderr=subprocess.DEVNULL,
                shell=False,
                start_new_session=os.name != "nt",
            )
        except OSError:
            return AuthenticationCommandResult(returncode=126)

        output = bytearray()
        reader = None
        if process.stdout is not None:
            reader = threading.Thread(
                target=_drain_output,
                args=(process.stdout, output),
                daemon=True,
                name="gigaloom-provider-auth-output",
            )
            reader.start()

        deadline = time.monotonic() + max(float(timeout_seconds), 0.05)
        timed_out = False
        cancelled = False
        while process.poll() is None:
            if cancel_event.wait(0.05):
                cancelled = True
                _stop_process(process)
                break
            if time.monotonic() >= deadline:
                timed_out = True
                _stop_process(process)
                break
        try:
            returncode = process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            _kill_process(process)
            returncode = process.wait(timeout=1.0)
        if reader is not None:
            reader.join(timeout=1.0)
        return AuthenticationCommandResult(
            returncode=returncode,
            stdout=bytes(output),
            timed_out=timed_out,
            cancelled=cancelled,
        )


class NativeLoginBroker:
    """Guide and observe native login without reading provider credential stores."""

    def __init__(
        self,
        data_dir: str | Path,
        *,
        resolution_provider: Callable[[str], ExecutableResolution],
        capability_provider: Callable[[str], CliCapabilitySnapshot],
        evidence: ProviderAuthenticationEvidence | None = None,
        runner: AuthenticationCommandRunner | None = None,
        login_timeout_seconds: float = AUTH_COMMAND_TIMEOUT_SECONDS,
        status_timeout_seconds: float = AUTH_STATUS_TIMEOUT_SECONDS,
    ) -> None:
        self.root = Path(data_dir).expanduser().resolve() / "provider_authentication"
        self.resolution_provider = resolution_provider
        self.capability_provider = capability_provider
        self.evidence = evidence or load_provider_authentication_evidence()
        self.runner = runner or BoundedAuthenticationCommandRunner()
        self.login_timeout_seconds = max(float(login_timeout_seconds), 0.05)
        self.status_timeout_seconds = max(float(status_timeout_seconds), 0.05)
        self._contracts = {
            str(item["harness_id"]): item for item in self.evidence.providers
        }
        self._attempts: dict[str, _LoginAttempt] = {}
        self._latest: dict[str, ProviderAccountSnapshot] = {}
        self._lock = threading.RLock()

    def list_accounts(self) -> dict[str, Any]:
        """Return all reviewed account cards after bounded status observation."""
        return {
            "schema_version": 1,
            "credential_values_readable": False,
            "real_native_homes_accessed": False,
            "accounts": [
                provider_account_snapshot_to_dict(self.status(provider_id))
                for provider_id in self._contracts
            ],
        }

    def status(self, provider_id: str) -> ProviderAccountSnapshot:
        """Return the current attempt or observe status when no attempt exists."""
        contract = self._contract(provider_id)
        with self._lock:
            attempt = self._attempts.get(provider_id)
            if attempt is not None:
                return attempt.snapshot
        snapshot = self._observe_status(contract)
        with self._lock:
            self._latest[provider_id] = snapshot
        return snapshot

    def refresh(self, provider_id: str) -> ProviderAccountSnapshot:
        """Explicitly replace the latest attempt outcome with provider status."""
        contract = self._contract(provider_id)
        with self._lock:
            attempt = self._attempts.get(provider_id)
            if (
                attempt is not None
                and attempt.snapshot.status is ProviderAccountStatus.PENDING
            ):
                raise ProviderAuthenticationConflictError(
                    "provider login is still pending"
                )
        snapshot = self._observe_status(contract, ignore_pending=True)
        with self._lock:
            self._attempts.pop(provider_id, None)
            self._latest[provider_id] = snapshot
        return snapshot

    def session_binding(self, provider_id: str) -> ProviderSessionBinding | None:
        """Return an opaque binding only when provider status is currently ready."""
        snapshot = self.status(provider_id)
        if snapshot.status is not ProviderAccountStatus.READY:
            return None
        key = self._binding_identity_key()
        home_identity = _opaque_identity(
            "home",
            key,
            provider_id,
            os.fspath(self._home(provider_id)),
        )
        identity_label = snapshot.identity_label or "identity-undisclosed"
        identity_evidence = (
            "provider_reported"
            if snapshot.identity_label is not None
            else "isolated_home_scoped"
        )
        account_identity = _opaque_identity(
            "account",
            key,
            provider_id,
            home_identity,
            self._binding_generation(provider_id).hex(),
            identity_label,
            snapshot.authentication_method or "method-undisclosed",
        )
        source_identity = _opaque_identity(
            "source",
            key,
            provider_id,
            snapshot.source,
            snapshot.pinned_cli_version,
            snapshot.detected_cli_version or "version-undetected",
            snapshot.version_status,
        )
        return ProviderSessionBinding(
            provider_id=provider_id,
            account_identity=account_identity,
            home_identity=home_identity,
            source_identity=source_identity,
            identity_evidence=identity_evidence,
            authentication_method=snapshot.authentication_method,
            observed_at=snapshot.checked_at,
        )

    def start(self, provider_id: str) -> ProviderAccountSnapshot:
        """Start one bounded provider-owned login attempt in the background."""
        contract = self._contract(provider_id)
        resolution, capability, unavailable = self._admission(contract)
        if unavailable is not None:
            raise ProviderAuthenticationOperationError(unavailable.reason_code)
        command = _operation_command(provider_id, "start")
        if command is None:
            raise ProviderAuthenticationOperationError("login_start_unavailable")
        assert resolution is not None
        assert capability is not None
        with self._lock:
            current = self._attempts.get(provider_id)
            if (
                current is not None
                and current.snapshot.status is ProviderAccountStatus.PENDING
            ):
                raise ProviderAuthenticationConflictError(
                    "provider login is already pending"
                )
            attempt_id = f"login_{uuid4().hex}"
            pending = self._snapshot(
                contract,
                capability=capability,
                status=ProviderAccountStatus.PENDING,
                source=_source(provider_id, "start"),
                reason_code="provider_login_pending",
                attempt_id=attempt_id,
            )
            attempt = _LoginAttempt(
                id=attempt_id,
                provider_id=provider_id,
                cancel_event=threading.Event(),
                snapshot=pending,
            )
            self._attempts[provider_id] = attempt
            self._latest[provider_id] = pending
            thread = threading.Thread(
                target=self._run_login,
                args=(attempt, resolution, command),
                daemon=True,
                name=f"gigaloom-login-{provider_id}",
            )
            attempt.thread = thread
            thread.start()
            return pending

    def cancel(self, provider_id: str) -> ProviderAccountSnapshot:
        """Cancel the exact pending broker attempt, if any."""
        contract = self._contract(provider_id)
        with self._lock:
            attempt = self._attempts.get(provider_id)
            if (
                attempt is None
                or attempt.snapshot.status is not ProviderAccountStatus.PENDING
            ):
                raise ProviderAuthenticationOperationError("provider_login_not_pending")
            attempt.cancel_event.set()
            cancelled = _finished_attempt(
                attempt.snapshot,
                status=ProviderAccountStatus.LOGGED_OUT,
                reason_code="provider_login_cancelled",
                recovery=tuple(contract["recovery"]),
            )
            attempt.snapshot = cancelled
            self._latest[provider_id] = cancelled
            return cancelled

    def logout(self, provider_id: str) -> ProviderAccountSnapshot:
        """Run the reviewed provider-owned logout command in the isolated home."""
        contract = self._contract(provider_id)
        with self._lock:
            attempt = self._attempts.get(provider_id)
            if (
                attempt is not None
                and attempt.snapshot.status is ProviderAccountStatus.PENDING
            ):
                raise ProviderAuthenticationConflictError(
                    "provider login is still pending"
                )
        resolution, capability, unavailable = self._admission(contract)
        if unavailable is not None:
            raise ProviderAuthenticationOperationError(unavailable.reason_code)
        command = _operation_command(provider_id, "logout")
        if command is None:
            raise ProviderAuthenticationOperationError("logout_unavailable")
        assert resolution is not None
        assert capability is not None
        result = self.runner.run(
            (*resolution.command, *command),
            environment=self._isolated_environment(provider_id),
            cwd=self._home(provider_id),
            timeout_seconds=self.status_timeout_seconds,
            cancel_event=threading.Event(),
            capture_output=False,
        )
        self._binding_generation(provider_id, rotate=True)
        if result.timed_out:
            status = ProviderAccountStatus.UNKNOWN
            reason_code = "logout_timed_out"
        elif result.returncode == 0:
            status = ProviderAccountStatus.LOGGED_OUT
            reason_code = "provider_logout_complete"
        else:
            status = ProviderAccountStatus.UNKNOWN
            reason_code = "provider_logout_failed"
        snapshot = self._snapshot(
            contract,
            capability=capability,
            status=status,
            source=_source(provider_id, "logout"),
            reason_code=reason_code,
        )
        with self._lock:
            self._attempts.pop(provider_id, None)
            self._latest[provider_id] = snapshot
        return snapshot

    def _run_login(
        self,
        attempt: _LoginAttempt,
        resolution: ExecutableResolution,
        command: tuple[str, ...],
    ) -> None:
        result = self.runner.run(
            (*resolution.command, *command),
            environment=self._isolated_environment(attempt.provider_id),
            cwd=self._home(attempt.provider_id),
            timeout_seconds=self.login_timeout_seconds,
            cancel_event=attempt.cancel_event,
            capture_output=False,
        )
        contract = self._contract(attempt.provider_id)
        if result.cancelled or attempt.cancel_event.is_set():
            final = _finished_attempt(
                attempt.snapshot,
                status=ProviderAccountStatus.LOGGED_OUT,
                reason_code="provider_login_cancelled",
                recovery=tuple(contract["recovery"]),
            )
        elif result.timed_out:
            final = _finished_attempt(
                attempt.snapshot,
                status=ProviderAccountStatus.UNKNOWN,
                reason_code="provider_login_timed_out",
                recovery=tuple(contract["recovery"]),
            )
        elif result.returncode != 0:
            final = _finished_attempt(
                attempt.snapshot,
                status=ProviderAccountStatus.LOGGED_OUT,
                reason_code="provider_login_failed",
                recovery=tuple(contract["recovery"]),
            )
        else:
            final = self._observe_status(contract, ignore_pending=True)
            if final.status is ProviderAccountStatus.UNKNOWN:
                final = replace(final, reason_code="provider_login_status_unknown")
            self._binding_generation(attempt.provider_id, rotate=True)
        final = replace(final, attempt_id=attempt.id)
        with self._lock:
            current = self._attempts.get(attempt.provider_id)
            if current is attempt:
                attempt.snapshot = final
                self._latest[attempt.provider_id] = final

    def _observe_status(
        self,
        contract: Mapping[str, Any],
        *,
        ignore_pending: bool = False,
    ) -> ProviderAccountSnapshot:
        provider_id = str(contract["harness_id"])
        if not ignore_pending:
            with self._lock:
                attempt = self._attempts.get(provider_id)
                if (
                    attempt is not None
                    and attempt.snapshot.status is ProviderAccountStatus.PENDING
                ):
                    return attempt.snapshot
        resolution, capability, unavailable = self._admission(contract)
        if unavailable is not None:
            return unavailable
        command = _operation_command(provider_id, "status")
        assert capability is not None
        if command is None:
            return self._snapshot(
                contract,
                capability=capability,
                status=ProviderAccountStatus.UNKNOWN,
                source=_source(provider_id, "status"),
                reason_code="machine_status_unavailable",
            )
        assert resolution is not None
        result = self.runner.run(
            (*resolution.command, *command),
            environment=self._isolated_environment(provider_id),
            cwd=self._home(provider_id),
            timeout_seconds=self.status_timeout_seconds,
            cancel_event=threading.Event(),
            capture_output=True,
        )
        status, identity, method, expiry, reason_code = _classify_status(
            provider_id,
            result,
        )
        return self._snapshot(
            contract,
            capability=capability,
            status=status,
            source=_source(provider_id, "status"),
            reason_code=reason_code,
            identity_label=identity,
            authentication_method=method,
            expires_at=expiry,
        )

    def _admission(
        self,
        contract: Mapping[str, Any],
    ) -> tuple[
        ExecutableResolution | None,
        CliCapabilitySnapshot | None,
        ProviderAccountSnapshot | None,
    ]:
        provider_id = str(contract["harness_id"])
        resolution = self.resolution_provider(provider_id)
        capability = self.capability_provider(provider_id)
        exact_pin = (
            resolution.available
            and capability.compatible
            and capability.parsed_version == contract["pinned_cli_version"]
        )
        if exact_pin:
            return resolution, capability, None
        if not resolution.available or capability.status == "missing":
            reason_code = "provider_cli_missing"
        elif capability.parsed_version != contract["pinned_cli_version"]:
            reason_code = "provider_cli_version_drift"
        else:
            reason_code = "provider_cli_capability_unproven"
        return (
            None,
            capability,
            self._snapshot(
                contract,
                capability=capability,
                status=ProviderAccountStatus.UNAVAILABLE,
                source="reviewed_provider_authentication_evidence_v1",
                reason_code=reason_code,
            ),
        )

    def _snapshot(
        self,
        contract: Mapping[str, Any],
        *,
        capability: CliCapabilitySnapshot,
        status: ProviderAccountStatus,
        source: str,
        reason_code: str,
        identity_label: str | None = None,
        authentication_method: str | None = None,
        expires_at: str | None = None,
        attempt_id: str | None = None,
    ) -> ProviderAccountSnapshot:
        provider_id = str(contract["harness_id"])
        exact_pin = (
            capability.compatible
            and capability.parsed_version == contract["pinned_cli_version"]
        )
        start_supported = (
            exact_pin and _operation_command(provider_id, "start") is not None
        )
        status_supported = (
            exact_pin and _operation_command(provider_id, "status") is not None
        )
        logout_supported = (
            exact_pin and _operation_command(provider_id, "logout") is not None
        )
        return ProviderAccountSnapshot(
            provider_id=provider_id,
            display_name=str(contract["display_name"]),
            status=status,
            source=source,
            checked_at=_utc_now(),
            pinned_cli_version=str(contract["pinned_cli_version"]),
            detected_cli_version=capability.parsed_version,
            version_status=(
                "reviewed_pin"
                if exact_pin and capability.compatible
                else capability.version_window_status
            ),
            identity_label=_bounded_text(identity_label),
            authentication_method=_bounded_text(authentication_method),
            expires_at=_expiry(expiry=expires_at),
            reason_code=reason_code,
            recovery=tuple(str(item) for item in contract["recovery"]),
            actions={
                "start": start_supported,
                "status": status_supported,
                "logout": logout_supported,
                "cancel": status is ProviderAccountStatus.PENDING,
            },
            attempt_id=attempt_id,
        )

    def _contract(self, provider_id: str) -> Mapping[str, Any]:
        try:
            return self._contracts[provider_id]
        except KeyError as exc:
            raise ProviderAuthenticationOperationError(
                "provider_authentication_unknown"
            ) from exc

    def _home(self, provider_id: str) -> Path:
        home = self.root / "homes" / provider_id
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            home.chmod(0o700)
        except OSError:
            pass
        return home

    def _isolated_environment(self, provider_id: str) -> dict[str, str]:
        source = os.environ
        environment = {
            name: value
            for name in _INHERITED_ENVIRONMENT
            if (value := source.get(name)) is not None
        }
        home = self._home(provider_id)
        environment.update(
            {
                "HOME": os.fspath(home),
                "NO_COLOR": "1",
                "DO_NOT_TRACK": "1",
            }
        )
        if provider_id == "codex-cli":
            environment["CODEX_HOME"] = os.fspath(home / ".codex")
        elif provider_id == "claude-code":
            environment["CLAUDE_CONFIG_DIR"] = os.fspath(home / ".claude")
        elif provider_id == "gemini-cli":
            environment["GEMINI_CLI_HOME"] = os.fspath(home / ".gemini")
            environment["GEMINI_TELEMETRY_ENABLED"] = "false"
        return environment

    def _binding_identity_key(self) -> bytes:
        path = self.root / "binding_identity.key"
        return self._private_identity_bytes(path)

    def _binding_generation(self, provider_id: str, *, rotate: bool = False) -> bytes:
        path = self.root / "bindings" / f"{provider_id}.generation"
        return self._private_identity_bytes(path, rotate=rotate)

    def _private_identity_bytes(self, path: Path, *, rotate: bool = False) -> bytes:
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with exclusive_file_lock(path):
                file_status = None
                if not rotate:
                    try:
                        file_status = path.lstat()
                    except FileNotFoundError:
                        pass
                if file_status is None:
                    key = secrets.token_bytes(32)
                    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
                    descriptor = os.open(
                        temporary,
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                        0o600,
                    )
                    try:
                        os.write(descriptor, key)
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
                    os.replace(temporary, path)
                else:
                    if not stat.S_ISREG(file_status.st_mode):
                        raise ProviderAuthenticationOperationError(
                            "provider_binding_identity_key_invalid"
                        )
                    descriptor = os.open(
                        path,
                        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    )
                    try:
                        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                            raise ProviderAuthenticationOperationError(
                                "provider_binding_identity_key_invalid"
                            )
                        if hasattr(os, "fchmod"):
                            os.fchmod(descriptor, 0o600)
                        key = os.read(descriptor, 33)
                    finally:
                        os.close(descriptor)
            if len(key) != 32:
                raise ProviderAuthenticationOperationError(
                    "provider_binding_identity_key_invalid"
                )
            return key


def provider_account_snapshot_to_dict(
    snapshot: ProviderAccountSnapshot,
) -> dict[str, Any]:
    """Serialize one account card without commands, paths, or provider output."""
    return {
        "provider_id": snapshot.provider_id,
        "display_name": snapshot.display_name,
        "status": snapshot.status.value,
        "source": snapshot.source,
        "checked_at": snapshot.checked_at,
        "pinned_cli_version": snapshot.pinned_cli_version,
        "detected_cli_version": snapshot.detected_cli_version,
        "version_status": snapshot.version_status,
        "identity_label": snapshot.identity_label,
        "authentication_method": snapshot.authentication_method,
        "expires_at": snapshot.expires_at,
        "reason_code": snapshot.reason_code,
        "recovery": list(snapshot.recovery),
        "actions": dict(snapshot.actions),
        "attempt_id": snapshot.attempt_id,
        "home_scope": snapshot.home_scope,
        "credential_values_readable": False,
    }


def provider_session_binding_to_dict(
    binding: ProviderSessionBinding,
) -> dict[str, Any]:
    """Serialize a path-free binding with separate quota and cost ownership."""
    return {
        "schema_version": binding.schema_version,
        "provider_id": binding.provider_id,
        "account_identity": binding.account_identity,
        "home_identity": binding.home_identity,
        "source_identity": binding.source_identity,
        "identity_evidence": binding.identity_evidence,
        "authentication_method": binding.authentication_method,
        "observed_at": binding.observed_at,
        "quota": {
            "ownership": "provider",
            "status": binding.quota_status,
        },
        "monetary_cost": {
            "ownership": "api_route",
            "status": binding.monetary_cost_status,
        },
    }


def _opaque_identity(prefix: str, key: bytes, *parts: str) -> str:
    payload = "\0".join(parts).encode("utf-8")
    digest = hmac.new(key, payload, hashlib.sha256).hexdigest()[:32]
    return f"{prefix}_{digest}"


def _operation_command(provider_id: str, operation: str) -> tuple[str, ...] | None:
    commands = {
        "codex-cli": {
            "start": ("login",),
            "status": ("login", "status"),
            "logout": ("logout",),
        },
        "claude-code": {
            "start": ("auth", "login"),
            "status": ("auth", "status"),
            "logout": ("auth", "logout"),
        },
        "gemini-cli": {
            "start": None,
            "status": None,
            "logout": None,
        },
    }
    return commands[provider_id][operation]


def _source(provider_id: str, operation: str) -> str:
    command = _operation_command(provider_id, operation)
    if command is None:
        return "reviewed_provider_authentication_evidence_v1"
    executable = {
        "codex-cli": "codex",
        "claude-code": "claude",
        "gemini-cli": "gemini",
    }[provider_id]
    return " ".join((executable, *command))


def _classify_status(
    provider_id: str,
    result: AuthenticationCommandResult,
) -> tuple[ProviderAccountStatus, str | None, str | None, str | None, str]:
    if result.cancelled:
        return ProviderAccountStatus.UNKNOWN, None, None, None, "status_cancelled"
    if result.timed_out:
        return ProviderAccountStatus.UNKNOWN, None, None, None, "status_timed_out"
    if provider_id == "codex-cli":
        if result.returncode == 0:
            method = _codex_auth_method(result.stdout)
            return ProviderAccountStatus.READY, None, method, None, "provider_ready"
        return ProviderAccountStatus.LOGGED_OUT, None, None, None, "provider_logged_out"
    if provider_id == "claude-code":
        return _classify_claude_status(result)
    return ProviderAccountStatus.UNKNOWN, None, None, None, "machine_status_unavailable"


def _classify_claude_status(
    result: AuthenticationCommandResult,
) -> tuple[ProviderAccountStatus, str | None, str | None, str | None, str]:
    if result.returncode not in {0, 1}:
        return ProviderAccountStatus.UNKNOWN, None, None, None, "status_failed"
    try:
        payload = json.loads(result.stdout.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        if result.returncode == 1:
            return (
                ProviderAccountStatus.LOGGED_OUT,
                None,
                None,
                None,
                "provider_logged_out",
            )
        return ProviderAccountStatus.UNKNOWN, None, None, None, "status_malformed"
    if not isinstance(payload, Mapping):
        return ProviderAccountStatus.UNKNOWN, None, None, None, "status_malformed"
    status_value = str(payload.get("status") or "").strip().lower()
    if status_value in {
        ProviderAccountStatus.EXPIRED.value,
        ProviderAccountStatus.REVOKED.value,
    }:
        status = ProviderAccountStatus(status_value)
    elif payload.get("loggedIn") is True and result.returncode == 0:
        status = ProviderAccountStatus.READY
    elif payload.get("loggedIn") is False or result.returncode == 1:
        status = ProviderAccountStatus.LOGGED_OUT
    else:
        status = ProviderAccountStatus.UNKNOWN
    identity = _first_text(payload, "email", "account", "organizationName")
    method = _first_text(payload, "authMethod", "auth_method", "credentialSource")
    if method is not None and method.lower() in {"none", "unknown"}:
        method = None
    expiry = _first_text(payload, "expiresAt", "expires_at")
    return status, identity, method, expiry, _reason_for_status(status)


def _codex_auth_method(output: bytes) -> str | None:
    text = output.decode("utf-8", errors="replace").lower()
    if "api key" in text:
        return "api_key"
    if "chatgpt" in text:
        return "chatgpt"
    if "access token" in text:
        return "access_token"
    return "provider_reported"


def _first_text(payload: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _reason_for_status(status: ProviderAccountStatus) -> str:
    return {
        ProviderAccountStatus.READY: "provider_ready",
        ProviderAccountStatus.LOGGED_OUT: "provider_logged_out",
        ProviderAccountStatus.EXPIRED: "provider_credentials_expired",
        ProviderAccountStatus.REVOKED: "provider_credentials_revoked",
        ProviderAccountStatus.UNKNOWN: "provider_status_unknown",
        ProviderAccountStatus.PENDING: "provider_login_pending",
        ProviderAccountStatus.UNAVAILABLE: "provider_unavailable",
    }[status]


def _finished_attempt(
    snapshot: ProviderAccountSnapshot,
    *,
    status: ProviderAccountStatus,
    reason_code: str,
    recovery: tuple[str, ...],
) -> ProviderAccountSnapshot:
    return replace(
        snapshot,
        status=status,
        checked_at=_utc_now(),
        reason_code=reason_code,
        recovery=recovery,
        actions={**snapshot.actions, "cancel": False},
    )


def _expiry(*, expiry: str | None) -> str | None:
    if expiry is None or not _EXPIRY_PATTERN.fullmatch(expiry):
        return None
    try:
        datetime.fromisoformat(expiry.replace("Z", "+00:00"))
    except ValueError:
        return None
    return expiry


def _bounded_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = "".join(character for character in value if ord(character) >= 32).strip()
    return text[:200] or None


def _validated_argument(value: str) -> str:
    text = str(value)
    if not text or "\x00" in text:
        raise ValueError("authentication command contains an invalid argument")
    return text


def _drain_output(stream: Any, output: bytearray) -> None:
    try:
        while chunk := stream.read(4096):
            if len(output) < AUTH_OUTPUT_BYTES:
                remaining = AUTH_OUTPUT_BYTES - len(output)
                output.extend(chunk[:remaining])
    finally:
        stream.close()


def _stop_process(process: subprocess.Popen[Any]) -> None:
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except (OSError, ProcessLookupError):
        pass


def _kill_process(process: subprocess.Popen[Any]) -> None:
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except (OSError, ProcessLookupError):
        pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "AUTH_COMMAND_TIMEOUT_SECONDS",
    "AUTH_OUTPUT_BYTES",
    "AUTH_STATUS_TIMEOUT_SECONDS",
    "AuthenticationCommandResult",
    "BoundedAuthenticationCommandRunner",
    "NativeLoginBroker",
    "ProviderAccountSnapshot",
    "ProviderAccountStatus",
    "ProviderSessionBinding",
    "ProviderAuthenticationBrokerError",
    "ProviderAuthenticationConflictError",
    "ProviderAuthenticationOperationError",
    "provider_account_snapshot_to_dict",
    "provider_session_binding_to_dict",
]
