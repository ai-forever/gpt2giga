"""Typed, secret-reference-only MCP authoring inputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from gpt2giga_harness.secrets import (
    SecretReference,
    SecretReferenceKind,
    secret_reference_from_dict,
    secret_reference_to_dict,
)


MCP_AUTHORING_SCHEMA_VERSION = 1
MAX_MCP_ARGUMENTS = 128
MAX_MCP_SECRET_BINDINGS = 32
_ENVIRONMENT_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
_HEADER_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,127}\Z")
_SHELLS = {"bash", "cmd", "dash", "fish", "powershell", "pwsh", "sh", "zsh"}
_SHELL_COMMAND_FLAGS = {"-c", "/c", "-command"}
_FORBIDDEN_EXECUTABLE_CHARACTERS = frozenset("\0\n\r;&|`")
_TRANSPORTS_BY_TARGET = {
    "codex-mcp": frozenset({"stdio", "streamable_http"}),
    "claude-mcp": frozenset({"stdio", "streamable_http"}),
    "gemini-mcp": frozenset({"stdio", "streamable_http", "sse"}),
    "harness-managed-mcp": frozenset({"stdio", "streamable_http"}),
}
_CWD_TARGETS = frozenset({"codex-mcp", "gemini-mcp", "harness-managed-mcp"})


class MCPAuthoringTransport(str, Enum):
    """User-facing MCP transport choices."""

    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"
    SSE = "sse"


@dataclass(frozen=True)
class MCPAuthoringConfiguration:
    """One canonical typed MCP authoring configuration."""

    transport: MCPAuthoringTransport
    executable: str | None = None
    argv: tuple[str, ...] = ()
    cwd: str | None = None
    url: str | None = None
    environment: Mapping[str, SecretReference] = field(default_factory=dict)
    headers: Mapping[str, SecretReference] = field(default_factory=dict)
    schema_version: int = MCP_AUTHORING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MCP_AUTHORING_SCHEMA_VERSION:
            raise ValueError("unsupported MCP authoring schema_version")
        if not isinstance(self.transport, MCPAuthoringTransport):
            raise ValueError("MCP authoring transport is invalid")
        object.__setattr__(self, "environment", dict(sorted(self.environment.items())))
        object.__setattr__(self, "headers", dict(sorted(self.headers.items())))

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical API and durable-preview representation."""
        base: dict[str, Any] = {
            "schema_version": self.schema_version,
            "transport": self.transport.value,
        }
        if self.transport is MCPAuthoringTransport.STDIO:
            base["stdio"] = {
                "executable": self.executable,
                "argv": list(self.argv),
                "cwd": self.cwd,
                "environment": {
                    name: secret_reference_to_dict(reference)
                    for name, reference in self.environment.items()
                },
            }
        else:
            base["remote"] = {
                "url": self.url,
                "headers": {
                    name: secret_reference_to_dict(reference)
                    for name, reference in self.headers.items()
                },
            }
        return base


def mcp_authoring_configuration_from_dict(
    value: Mapping[str, Any],
    *,
    target_id: str,
) -> MCPAuthoringConfiguration:
    """Parse typed input or a bounded legacy alias into one strict contract."""
    if not isinstance(value, Mapping):
        raise ValueError("raw MCP configuration must be an object")
    if target_id not in _TRANSPORTS_BY_TARGET:
        raise ValueError("raw MCP target is unsupported")
    configuration = (
        _parse_typed_configuration(value)
        if "stdio" in value or "remote" in value or "schema_version" in value
        else _parse_legacy_configuration(value)
    )
    if configuration.transport.value not in _TRANSPORTS_BY_TARGET[target_id]:
        raise ValueError(
            f"{target_id} does not support {configuration.transport.value} MCP"
        )
    if configuration.cwd is not None and target_id not in _CWD_TARGETS:
        raise ValueError(f"{target_id} does not support an MCP stdio cwd")
    if target_id != "harness-managed-mcp":
        references = (
            *configuration.environment.values(),
            *configuration.headers.values(),
        )
        if any(
            reference.kind is not SecretReferenceKind.ENVIRONMENT
            for reference in references
        ):
            raise ValueError(
                f"{target_id} supports only environment-backed MCP secret references"
            )
        if any(
            name != reference.name
            for name, reference in configuration.environment.items()
        ):
            raise ValueError(
                f"{target_id} cannot alias an MCP environment secret reference"
            )
    return configuration


def resolve_mcp_authoring_cwd(root: Path, cwd: str | None) -> str | None:
    """Resolve a portable relative cwd without escaping its selected root."""
    if cwd is None:
        return None
    resolved_root = root.resolve()
    candidate = (resolved_root / Path(cwd)).resolve()
    if not candidate.is_relative_to(resolved_root):
        raise ValueError("MCP stdio cwd escapes the selected target root")
    return str(candidate)


def _parse_typed_configuration(
    value: Mapping[str, Any],
) -> MCPAuthoringConfiguration:
    allowed = {"schema_version", "transport", "stdio", "remote"}
    _reject_unknown(value, allowed, "MCP authoring configuration")
    schema_version = value.get("schema_version", MCP_AUTHORING_SCHEMA_VERSION)
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != MCP_AUTHORING_SCHEMA_VERSION
    ):
        raise ValueError("unsupported MCP authoring schema_version")
    transport = _transport(value.get("transport"))
    if transport is MCPAuthoringTransport.STDIO:
        if "remote" in value:
            raise ValueError("stdio MCP input cannot contain remote fields")
        stdio = value.get("stdio")
        if not isinstance(stdio, Mapping):
            raise ValueError("stdio MCP input is required")
        _reject_unknown(
            stdio,
            {"executable", "argv", "cwd", "environment"},
            "stdio MCP input",
        )
        executable = _executable(stdio.get("executable"))
        argv = _argv(stdio.get("argv", ()), executable=executable)
        return MCPAuthoringConfiguration(
            transport=transport,
            executable=executable,
            argv=argv,
            cwd=_cwd(stdio.get("cwd")),
            environment=_secret_bindings(
                stdio.get("environment", {}),
                pattern=_ENVIRONMENT_NAME_RE,
                field_name="environment",
            ),
        )
    if "stdio" in value:
        raise ValueError("remote MCP input cannot contain stdio fields")
    remote = value.get("remote")
    if not isinstance(remote, Mapping):
        raise ValueError("remote MCP input is required")
    _reject_unknown(
        remote,
        {"url", "headers", "authorization"},
        "remote MCP input",
    )
    headers = _secret_bindings(
        remote.get("headers", {}),
        pattern=_HEADER_NAME_RE,
        field_name="header",
        case_insensitive=True,
    )
    authorization = remote.get("authorization")
    if authorization is not None:
        if any(name.lower() == "authorization" for name in headers):
            raise ValueError("remote MCP authorization is duplicated")
        if not isinstance(authorization, Mapping):
            raise ValueError("remote MCP authorization must be a secret reference")
        headers = {
            **headers,
            "Authorization": secret_reference_from_dict(authorization),
        }
    return MCPAuthoringConfiguration(
        transport=transport,
        url=_https_url(remote.get("url")),
        headers=headers,
    )


def _parse_legacy_configuration(
    value: Mapping[str, Any],
) -> MCPAuthoringConfiguration:
    """Preserve the existing machine payload as a strict compatibility alias."""
    allowed = {"transport", "command", "args", "env_vars", "url"}
    _reject_unknown(value, allowed, "legacy MCP configuration")
    transport = _transport(value.get("transport"))
    if transport is MCPAuthoringTransport.STDIO:
        executable = _executable(value.get("command"))
        argv = _argv(value.get("args", ()), executable=executable)
        env_vars = value.get("env_vars", ())
        if not isinstance(env_vars, Sequence) or isinstance(
            env_vars, (str, bytes, bytearray)
        ):
            raise ValueError("legacy MCP env_vars must be a list")
        environment: dict[str, SecretReference] = {}
        for raw_name in env_vars:
            name = str(raw_name)
            if not _ENVIRONMENT_NAME_RE.fullmatch(name) or name in environment:
                raise ValueError("legacy MCP env_vars contain an invalid name")
            environment[name] = SecretReference(
                kind=SecretReferenceKind.ENVIRONMENT,
                name=name,
            )
        return MCPAuthoringConfiguration(
            transport=transport,
            executable=executable,
            argv=argv,
            environment=environment,
        )
    if value.get("command") is not None or value.get("args") or value.get("env_vars"):
        raise ValueError("legacy remote MCP input cannot contain stdio fields")
    return MCPAuthoringConfiguration(
        transport=transport,
        url=_https_url(value.get("url")),
    )


def _transport(value: Any) -> MCPAuthoringTransport:
    normalized = "streamable_http" if value == "http" else value
    try:
        return MCPAuthoringTransport(str(normalized or ""))
    except ValueError as exc:
        raise ValueError("raw MCP transport is unsupported") from exc


def _executable(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("stdio MCP executable must be text")
    executable = value.strip()
    if (
        not executable
        or len(executable) > 4096
        or any(
            character in executable for character in _FORBIDDEN_EXECUTABLE_CHARACTERS
        )
    ):
        raise ValueError("stdio MCP executable is invalid")
    return executable


def _argv(value: Any, *, executable: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("stdio MCP argv must be a list")
    if len(value) > MAX_MCP_ARGUMENTS:
        raise ValueError("stdio MCP argv is too large")
    argv = tuple(value)
    if any(
        not isinstance(item, str)
        or not item
        or len(item) > 4096
        or any(character in item for character in ("\0", "\n", "\r"))
        for item in argv
    ):
        raise ValueError("stdio MCP argv is invalid")
    basename = PurePosixPath(executable.replace("\\", "/")).name.lower()
    if basename in _SHELLS and argv and argv[0].lower() in _SHELL_COMMAND_FLAGS:
        raise ValueError("stdio MCP shell command strings are forbidden")
    return argv


def _cwd(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("MCP stdio cwd is invalid")
    normalized = value.replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or ".." in path.parts
        or any(character in normalized for character in ("\0", "\n", "\r"))
    ):
        raise ValueError("MCP stdio cwd must be a safe relative path")
    return path.as_posix()


def _https_url(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("remote MCP URL is invalid")
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or any(character in value for character in ("\0", "\n", "\r"))
    ):
        raise ValueError("remote MCP URL must be credential-free HTTPS")
    try:
        port = f":{parsed.port}" if parsed.port is not None else ""
    except ValueError as exc:
        raise ValueError("remote MCP URL port is invalid") from exc
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    return urlunsplit(("https", f"{host}{port}", parsed.path or "/", parsed.query, ""))


def _secret_bindings(
    value: Any,
    *,
    pattern: re.Pattern[str],
    field_name: str,
    case_insensitive: bool = False,
) -> dict[str, SecretReference]:
    if not isinstance(value, Mapping):
        raise ValueError(f"MCP {field_name} references must be an object")
    if len(value) > MAX_MCP_SECRET_BINDINGS:
        raise ValueError(f"MCP {field_name} reference count is too large")
    bindings: dict[str, SecretReference] = {}
    seen: set[str] = set()
    for raw_name, raw_reference in value.items():
        if not isinstance(raw_name, str) or not pattern.fullmatch(raw_name):
            raise ValueError(f"MCP {field_name} name is invalid")
        identity = raw_name.lower() if case_insensitive else raw_name
        if identity in seen:
            raise ValueError(f"MCP {field_name} names contain duplicates")
        if not isinstance(raw_reference, Mapping):
            raise ValueError(f"MCP {field_name} must use a secret reference")
        seen.add(identity)
        bindings[raw_name] = secret_reference_from_dict(raw_reference)
    return dict(sorted(bindings.items()))


def _reject_unknown(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(str(key) for key in set(value) - allowed)
    if unknown:
        raise ValueError(f"{label} contains unknown fields: {', '.join(unknown)}")
