"""Fail-closed normalization of reviewed federated MCP catalog entries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any
from urllib.parse import urlsplit

from gpt2giga_harness.claude_mcp_target import (
    CLAUDE_MCP_TARGET_ID,
    ClaudeMCPServerSpec,
    ClaudeMCPTransport,
)
from gpt2giga_harness.codex_mcp_target import (
    CODEX_MCP_TARGET_ID,
    CodexMCPDefaultApproval,
    CodexMCPServerSpec,
    CodexMCPTransport,
)
from gpt2giga_harness.gemini_mcp_target import (
    GEMINI_MCP_TARGET_ID,
    GeminiMCPServerSpec,
    GeminiMCPTransport,
)
from gpt2giga_harness.integration_catalog import (
    CatalogEntry,
    CatalogSourceType,
)
from gpt2giga_harness.integration_packages import (
    InstallationScope,
    IntegrationCompatibility,
    IntegrationComponent,
    IntegrationComponentType,
    IntegrationPackage,
    IntegrationPolicyClass,
    IntegrationRequirement,
    IntegrationRequirementType,
    IntegrationSourceType,
    IntegrationTargetOverlay,
    IntegrationUpdatePolicy,
)
from gpt2giga_harness.mcp import MCPTransport, ToolServerDescriptor
from gpt2giga_harness.secrets import (
    SecretReference,
    SecretReferenceKind,
    secret_reference_to_dict,
)
from gpt2giga_harness.tools import PolicyDecision, ToolExecutionPolicy


HARNESS_MANAGED_MCP_TARGET_ID = "harness-managed-mcp"
_TARGET_IDS = (
    CODEX_MCP_TARGET_ID,
    CLAUDE_MCP_TARGET_ID,
    GEMINI_MCP_TARGET_ID,
    HARNESS_MANAGED_MCP_TARGET_ID,
)
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_EXACT_VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+~-]{0,127}\Z")
_ENV_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
_HEADER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,127}\Z")
_SHELLS = {"bash", "cmd", "dash", "fish", "powershell", "pwsh", "sh", "zsh"}
_IMPLICIT_INSTALLERS = {"bunx", "dnx", "npx", "pipx", "pnpx", "uvx"}
_GIT_COMMIT_RE = re.compile(r"(?:commit[:~-]?)?[0-9a-f]{40,64}\Z")


class ExternalMCPSelectionKind(str, Enum):
    """Executable source families admitted from official Registry metadata."""

    PACKAGE = "package"
    GIT = "git"
    REMOTE = "remote"


@dataclass(frozen=True)
class ExternalMCPArtifactResolution:
    """Reviewed immutable package or Git artifact without downloaded bytes."""

    registry_type: str
    identifier: str
    version: str
    immutable_ref: str
    integrity: str
    download_origin: str

    def __post_init__(self) -> None:
        if self.registry_type not in {"npm", "pypi", "nuget", "oci", "mcpb", "git"}:
            raise ValueError("external MCP artifact registry type is unsupported")
        if not self.identifier.strip() or any(
            character in self.identifier for character in ("\0", "\n", "\r")
        ):
            raise ValueError("external MCP artifact identifier is invalid")
        if (
            not _EXACT_VERSION_RE.fullmatch(self.version)
            or self.version.lower() == "latest"
            or any(character in self.version for character in ("*", "^", "<", ">"))
        ):
            raise ValueError("external MCP artifact version must be exact")
        if not self.immutable_ref.strip() or self.immutable_ref.lower() in {
            "latest",
            "main",
            "master",
            "head",
        }:
            raise ValueError("external MCP artifact ref must be immutable")
        if self.registry_type == "git" and not _GIT_COMMIT_RE.fullmatch(
            self.immutable_ref
        ):
            raise ValueError("external MCP Git ref must be an exact commit")
        if not _SHA256_RE.fullmatch(self.integrity):
            raise ValueError("external MCP artifact requires SHA-256 integrity")
        object.__setattr__(
            self,
            "download_origin",
            _canonical_https_origin(self.download_origin),
        )


@dataclass(frozen=True)
class ExternalMCPToolPolicy:
    """Portable tool policy retained without discovered tool content."""

    include_tools: tuple[str, ...] = ()
    exclude_tools: tuple[str, ...] = ()
    default: PolicyDecision = PolicyDecision.ASK

    def __post_init__(self) -> None:
        include = _normalized_names(self.include_tools, "included tool")
        exclude = _normalized_names(self.exclude_tools, "excluded tool")
        if set(include) & set(exclude):
            raise ValueError("external MCP tool policy filters overlap")
        if not isinstance(self.default, PolicyDecision):
            raise ValueError("external MCP default tool policy is invalid")
        object.__setattr__(self, "include_tools", include)
        object.__setattr__(self, "exclude_tools", exclude)


@dataclass(frozen=True)
class ExternalMCPSelection:
    """Explicit operator selection for one Registry package, Git source, or remote."""

    kind: ExternalMCPSelectionKind
    index: int = 0
    artifact: ExternalMCPArtifactResolution | None = None
    launch_argv: tuple[str, ...] = ()
    environment: Mapping[str, SecretReference] = field(default_factory=dict)
    headers: Mapping[str, SecretReference] = field(default_factory=dict)
    timeout_seconds: int = 10
    tool_policy: ExternalMCPToolPolicy = field(default_factory=ExternalMCPToolPolicy)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ExternalMCPSelectionKind):
            raise ValueError("external MCP selection kind is invalid")
        if (
            isinstance(self.index, bool)
            or not isinstance(self.index, int)
            or self.index < 0
        ):
            raise ValueError("external MCP selection index is invalid")
        if not 1 <= self.timeout_seconds <= 3600:
            raise ValueError("external MCP timeout is invalid")
        object.__setattr__(self, "launch_argv", _validate_argv(self.launch_argv))
        object.__setattr__(
            self,
            "environment",
            _validate_secret_bindings(self.environment, _ENV_RE, "environment"),
        )
        object.__setattr__(
            self,
            "headers",
            _validate_secret_bindings(self.headers, _HEADER_RE, "header"),
        )
        if self.kind is ExternalMCPSelectionKind.REMOTE:
            if self.artifact is not None or self.launch_argv or self.environment:
                raise ValueError("remote MCP selection cannot contain package fields")
        elif self.artifact is None or not self.launch_argv:
            raise ValueError("package and Git MCP selections require artifact and argv")


@dataclass(frozen=True)
class ExternalMCPDescriptor:
    """Canonical reviewed MCP descriptor shared by every target projection."""

    id: str
    official_name: str
    version: str
    title: str
    description: str
    catalog_id: str
    immutable_ref: str
    content_hash: str
    transport: MCPTransport
    command: str | None
    args: tuple[str, ...]
    url: str | None
    environment: Mapping[str, SecretReference]
    headers: Mapping[str, SecretReference]
    artifact: ExternalMCPArtifactResolution | None
    network_origins: tuple[str, ...]
    timeout_seconds: int
    tool_policy: ExternalMCPToolPolicy
    discovery_source_id: str | None = None

    @property
    def semantic_hash(self) -> str:
        """Return a deterministic content hash without resolving secrets."""
        return _json_hash(external_mcp_descriptor_to_dict(self))

    def to_harness_descriptor(
        self, *, trusted: bool = False, enabled: bool = False
    ) -> ToolServerDescriptor:
        """Project into the existing managed MCP descriptor/snapshot contract."""
        return ToolServerDescriptor(
            id=self.id,
            title=self.title,
            description=self.description,
            transport=self.transport,
            command=self.command,
            args=self.args,
            url=self.url,
            environment=self.environment,
            headers=self.headers,
            source=f"official-mcp-registry:{self.catalog_id}",
            trusted=trusted,
            enabled=enabled,
            timeout_seconds=float(self.timeout_seconds),
            harnesses=("codex-cli", "claude-code", "gemini-cli"),
            execution_policy=ToolExecutionPolicy(
                id=f"external-mcp-{self.semantic_hash[:16]}",
                default=self.tool_policy.default,
            ),
        )

    def to_integration_package(self) -> IntegrationPackage:
        """Declare every reviewed effect without authorizing installation."""
        requirements: list[IntegrationRequirement] = []
        if self.artifact is not None:
            requirements.append(
                IntegrationRequirement(
                    id="artifact",
                    type=IntegrationRequirementType.PACKAGE,
                    classification=IntegrationPolicyClass.EXPLICIT_APPROVAL,
                    reason="Acquire the reviewed immutable MCP artifact.",
                    locator=(
                        f"{self.artifact.registry_type}:{self.artifact.identifier}"
                        f"@{self.artifact.version}"
                    ),
                    checksum=self.artifact.integrity,
                )
            )
        if self.command is not None:
            requirements.append(
                IntegrationRequirement(
                    id="command",
                    type=IntegrationRequirementType.COMMAND,
                    classification=IntegrationPolicyClass.EXPLICIT_APPROVAL,
                    reason="Start the reviewed MCP server with exact argv.",
                    argv=(self.command, *self.args),
                    environment=tuple(self.environment),
                )
            )
        for index, origin in enumerate(self.network_origins, start=1):
            requirements.append(
                IntegrationRequirement(
                    id=f"network-{index}",
                    type=IntegrationRequirementType.NETWORK,
                    classification=IntegrationPolicyClass.EXPLICIT_APPROVAL,
                    reason="Use a declared MCP artifact or server origin.",
                    locator=origin,
                )
            )
        for index, name in enumerate(
            sorted(set(self.environment) | set(self.headers)), start=1
        ):
            requirements.append(
                IntegrationRequirement(
                    id=f"secret-{index}",
                    type=IntegrationRequirementType.SECRET,
                    classification=IntegrationPolicyClass.EXPLICIT_APPROVAL,
                    reason=f"Resolve the reviewed secret reference for {name}.",
                    secret_owner="gpt2giga-harness",
                )
            )
        requirements.append(
            IntegrationRequirement(
                id="target-config-write",
                type=IntegrationRequirementType.PERMISSION,
                classification=IntegrationPolicyClass.EXPLICIT_APPROVAL,
                reason="Write only the selected target configuration under N4-02 ownership.",
            )
        )
        source_type = (
            IntegrationSourceType.GIT
            if self.artifact is not None and self.artifact.registry_type == "git"
            else IntegrationSourceType.PACKAGE
            if self.artifact is not None
            else IntegrationSourceType.RAW_MCP
        )
        source = (
            self.artifact.identifier if self.artifact is not None else str(self.url)
        )
        requirement_ids = tuple(item.id for item in requirements)
        return IntegrationPackage(
            id=self.id,
            version=self.version,
            publisher="official-mcp-registry",
            license="NOASSERTION",
            source_type=source_type,
            source=source,
            immutable_ref=(
                self.artifact.immutable_ref
                if self.artifact is not None
                else self.immutable_ref
            ),
            checksum=(
                self.artifact.integrity
                if self.artifact is not None
                else f"sha256:{self.content_hash}"
            ),
            components=(
                IntegrationComponent(
                    id="portable-mcp",
                    type=IntegrationComponentType.MCP,
                    portable=True,
                ),
            ),
            requirements=tuple(requirements),
            overlays=tuple(
                IntegrationTargetOverlay(
                    target_id=target_id,
                    component_ids=("portable-mcp",),
                    requirement_ids=requirement_ids,
                )
                for target_id in _TARGET_IDS
            ),
            compatibility=tuple(
                IntegrationCompatibility(target_id=target_id)
                for target_id in _TARGET_IDS
            ),
            scopes=(InstallationScope.MANAGED_HOME, InstallationScope.PROJECT),
            update_policy=IntegrationUpdatePolicy.PINNED,
            verification_steps=("bounded-native-discovery", "content-free-probe"),
            rollback_steps=("transactional-owner-restore",),
        )


@dataclass(frozen=True)
class ExternalMCPTargetPreview:
    """Deterministic target result including unsupported capability evidence."""

    plan_id: str
    target_id: str
    descriptor_sha256: str
    supported: bool
    error_code: str | None
    configuration: Mapping[str, Any]
    commands: tuple[tuple[str, ...], ...]
    packages: tuple[Mapping[str, str], ...]
    network_origins: tuple[str, ...]
    filesystem_permissions: tuple[str, ...]
    secret_references: tuple[Mapping[str, Any], ...]
    native_consent_required: bool
    restart_required: bool
    install_authorized: bool = False


def normalize_external_mcp_candidate(
    official_entry: CatalogEntry,
    selection: ExternalMCPSelection,
    *,
    discovery_entry: CatalogEntry | None = None,
) -> ExternalMCPDescriptor:
    """Normalize one reviewed official pin; discovery metadata remains non-authoritative."""
    server = _official_server(official_entry)
    discovery_source_id = _validate_discovery(discovery_entry, official_entry)
    name = str(server["name"])
    title = str(server.get("title") or name.rsplit("/", 1)[-1])
    description = str(server["description"])
    environment: Mapping[str, SecretReference]
    headers: Mapping[str, SecretReference]
    artifact = selection.artifact
    command: str | None = None
    args: tuple[str, ...] = ()
    url: str | None = None
    origins: set[str] = set()

    if selection.kind is ExternalMCPSelectionKind.REMOTE:
        remote = _selected_record(server, "remotes", selection.index)
        if remote.get("type") != "streamable-http":
            raise ValueError("external MCP remote transport is unsupported")
        if remote.get("variables"):
            raise ValueError("external MCP URL templates require an explicit handoff")
        url = _canonical_https_url(remote.get("url"))
        environment = {}
        headers = _declared_secret_bindings(
            remote.get("headers", ()), selection.headers, "header"
        )
        origins.add(_origin(url))
        transport = MCPTransport.STREAMABLE_HTTP
    else:
        if selection.kind is ExternalMCPSelectionKind.PACKAGE:
            package = _selected_record(server, "packages", selection.index)
            _match_package_resolution(package, artifact)
            declared_environment = package.get("environmentVariables", ())
            if package.get("packageArguments") or package.get("runtimeArguments"):
                raise ValueError(
                    "external MCP templated package arguments require an explicit handoff"
                )
        else:
            _match_git_resolution(server, artifact)
            declared_environment = ()
        _validate_launch_binding(selection.launch_argv, artifact)
        environment = _declared_secret_bindings(
            declared_environment, selection.environment, "environment"
        )
        if selection.headers:
            raise ValueError("stdio MCP selection cannot contain headers")
        headers = {}
        command, *raw_args = selection.launch_argv
        args = tuple(raw_args)
        origins.add(artifact.download_origin)
        transport = MCPTransport.STDIO

    return ExternalMCPDescriptor(
        id=_target_safe_id(name),
        official_name=name,
        version=str(server["version"]),
        title=title,
        description=description,
        catalog_id=official_entry.catalog_id,
        immutable_ref=str(official_entry.immutable_ref),
        content_hash=official_entry.content_hash,
        transport=transport,
        command=command,
        args=args,
        url=url,
        environment=environment,
        headers=headers,
        artifact=artifact,
        network_origins=tuple(sorted(origins)),
        timeout_seconds=selection.timeout_seconds,
        tool_policy=selection.tool_policy,
        discovery_source_id=discovery_source_id,
    )


def project_external_mcp_target(
    descriptor: ExternalMCPDescriptor, target_id: str
) -> ExternalMCPTargetPreview:
    """Create one exact target preview without installation or provider I/O."""
    if target_id not in _TARGET_IDS:
        raise ValueError("external MCP target is unsupported")
    error_code: str | None = None
    configuration: Mapping[str, Any] = {}
    native = target_id != HARNESS_MANAGED_MCP_TARGET_ID
    if native and any(
        reference.kind is not SecretReferenceKind.ENVIRONMENT
        for reference in (
            *descriptor.environment.values(),
            *descriptor.headers.values(),
        )
    ):
        error_code = "target.secret_backend_unsupported"
    elif native and any(
        name != reference.name for name, reference in descriptor.environment.items()
    ):
        error_code = "target.environment_alias_unsupported"
    elif target_id == CLAUDE_MCP_TARGET_ID and (
        descriptor.tool_policy.include_tools
        or descriptor.tool_policy.exclude_tools
        or descriptor.tool_policy.default is not PolicyDecision.ASK
    ):
        error_code = "target.tool_policy_unsupported"
    elif target_id in {CODEX_MCP_TARGET_ID, GEMINI_MCP_TARGET_ID} and (
        descriptor.tool_policy.default is PolicyDecision.DENY
        or (
            target_id == GEMINI_MCP_TARGET_ID
            and descriptor.tool_policy.default is PolicyDecision.ALLOW
        )
    ):
        error_code = "target.default_policy_unsupported"
    else:
        configuration = _target_configuration(descriptor, target_id)

    artifact = descriptor.artifact
    packages = (
        (
            {
                "registry_type": artifact.registry_type,
                "identifier": artifact.identifier,
                "version": artifact.version,
                "immutable_ref": artifact.immutable_ref,
                "integrity": artifact.integrity,
                "download_origin": artifact.download_origin,
            },
        )
        if artifact is not None
        else ()
    )
    secrets = tuple(
        {
            "field": field,
            "name": name,
            "reference": secret_reference_to_dict(reference),
        }
        for field, bindings in (
            ("environment", descriptor.environment),
            ("header", descriptor.headers),
        )
        for name, reference in sorted(bindings.items())
    )
    payload = {
        "target_id": target_id,
        "descriptor_sha256": descriptor.semantic_hash,
        "supported": error_code is None,
        "error_code": error_code,
        "configuration": configuration,
        "commands": (
            [[descriptor.command, *descriptor.args]] if descriptor.command else []
        ),
        "packages": list(packages),
        "network_origins": list(descriptor.network_origins),
        "filesystem_permissions": [
            "write:harness-private-artifact-cache" if artifact is not None else "none",
            f"write:{target_id}:managed-configuration",
        ],
        "secret_references": list(secrets),
        "native_consent_required": native,
        "restart_required": native,
        "install_authorized": False,
    }
    return ExternalMCPTargetPreview(
        plan_id=f"plan_{_json_hash(payload)}",
        target_id=target_id,
        descriptor_sha256=descriptor.semantic_hash,
        supported=error_code is None,
        error_code=error_code,
        configuration=configuration,
        commands=(
            ((descriptor.command, *descriptor.args),) if descriptor.command else ()
        ),
        packages=packages,
        network_origins=descriptor.network_origins,
        filesystem_permissions=tuple(payload["filesystem_permissions"]),
        secret_references=secrets,
        native_consent_required=native,
        restart_required=native,
    )


def external_mcp_descriptor_to_dict(
    descriptor: ExternalMCPDescriptor,
) -> dict[str, Any]:
    """Serialize one descriptor without resolving any secret reference."""
    artifact = descriptor.artifact
    return {
        "schema_version": 1,
        "id": descriptor.id,
        "official_name": descriptor.official_name,
        "version": descriptor.version,
        "title": descriptor.title,
        "description": descriptor.description,
        "catalog_id": descriptor.catalog_id,
        "immutable_ref": descriptor.immutable_ref,
        "content_hash": descriptor.content_hash,
        "transport": descriptor.transport.value,
        "command": descriptor.command,
        "args": list(descriptor.args),
        "url": descriptor.url,
        "environment": {
            key: secret_reference_to_dict(value)
            for key, value in sorted(descriptor.environment.items())
        },
        "headers": {
            key: secret_reference_to_dict(value)
            for key, value in sorted(descriptor.headers.items())
        },
        "artifact": (
            {
                "registry_type": artifact.registry_type,
                "identifier": artifact.identifier,
                "version": artifact.version,
                "immutable_ref": artifact.immutable_ref,
                "integrity": artifact.integrity,
                "download_origin": artifact.download_origin,
            }
            if artifact is not None
            else None
        ),
        "network_origins": list(descriptor.network_origins),
        "timeout_seconds": descriptor.timeout_seconds,
        "tool_policy": {
            "include_tools": list(descriptor.tool_policy.include_tools),
            "exclude_tools": list(descriptor.tool_policy.exclude_tools),
            "default": descriptor.tool_policy.default.value,
        },
        "discovery_source_id": descriptor.discovery_source_id,
        "install_authorized": False,
    }


def _official_server(entry: CatalogEntry) -> Mapping[str, Any]:
    if (
        entry.source_type is not CatalogSourceType.OFFICIAL_MCP_REGISTRY
        or entry.mcp_response is None
        or not entry.pinned
        or entry.immutable_ref is None
    ):
        raise ValueError(
            "external MCP normalization requires an official immutable pin"
        )
    server = entry.mcp_response.get("server")
    if not isinstance(server, Mapping):
        raise ValueError("official MCP server metadata is invalid")
    return server


def _validate_discovery(
    discovery: CatalogEntry | None, official: CatalogEntry
) -> str | None:
    if discovery is None:
        return None
    metadata = discovery.federated
    if (
        discovery.source_type is not CatalogSourceType.FEDERATED_CATALOG
        or metadata is None
        or metadata.component != "mcp"
        or metadata.canonical_package_id != official.package_id
        or discovery.package_id != official.package_id
        or discovery.package is not None
        or discovery.pinned
        or discovery.install_authorized
    ):
        raise ValueError("federated MCP discovery identity does not match official pin")
    return discovery.source_id


def _selected_record(
    server: Mapping[str, Any], field_name: str, index: int
) -> Mapping[str, Any]:
    records = server.get(field_name)
    if not isinstance(records, list) or not records or len(records) > 64:
        raise ValueError(f"official MCP {field_name} are unavailable or invalid")
    if index >= len(records) or not isinstance(records[index], Mapping):
        raise ValueError(f"official MCP {field_name} selection is invalid")
    return records[index]


def _match_package_resolution(
    package: Mapping[str, Any], artifact: ExternalMCPArtifactResolution | None
) -> None:
    if artifact is None:
        raise ValueError("external MCP package resolution is required")
    transport = package.get("transport")
    if not isinstance(transport, Mapping) or transport.get("type") != "stdio":
        raise ValueError("external MCP package transport is unsupported")
    if (
        package.get("registryType") != artifact.registry_type
        or package.get("identifier") != artifact.identifier
        or package.get("version") != artifact.version
    ):
        raise ValueError("external MCP artifact does not match official package pin")
    declared_hash = package.get("fileSha256")
    if declared_hash is not None and f"sha256:{declared_hash}" != artifact.integrity:
        raise ValueError("external MCP artifact integrity conflicts with official pin")


def _match_git_resolution(
    server: Mapping[str, Any], artifact: ExternalMCPArtifactResolution | None
) -> None:
    if artifact is None or artifact.registry_type != "git":
        raise ValueError("external MCP Git resolution is required")
    repository = server.get("repository")
    if not isinstance(repository, Mapping) or repository.get("source") != "github":
        raise ValueError("official MCP Git repository is unavailable")
    if _canonical_git_url(repository.get("url")) != _canonical_git_url(
        artifact.identifier
    ):
        raise ValueError("external MCP Git artifact does not match official identity")
    if artifact.version != server.get("version"):
        raise ValueError(
            "external MCP Git artifact version does not match official pin"
        )


def _validate_launch_binding(
    argv: Sequence[str], artifact: ExternalMCPArtifactResolution | None
) -> None:
    if artifact is None:
        raise ValueError("external MCP launch artifact is required")
    executable = argv[0]
    basename = PurePosixPath(executable.replace("\\", "/")).name.lower()
    if basename in _IMPLICIT_INSTALLERS:
        raise ValueError("external MCP implicit installer commands are forbidden")
    if not PurePosixPath(executable).is_absolute():
        raise ValueError("external MCP executable path must be absolute")
    if artifact.version not in executable:
        raise ValueError("external MCP executable path must bind the exact version")


def _declared_secret_bindings(
    declarations: Any,
    bindings: Mapping[str, SecretReference],
    field_name: str,
) -> Mapping[str, SecretReference]:
    if not isinstance(declarations, (list, tuple)):
        raise ValueError(f"official MCP {field_name} declarations are invalid")
    declared: dict[str, Mapping[str, Any]] = {}
    for item in declarations:
        if not isinstance(item, Mapping):
            raise ValueError(f"official MCP {field_name} declaration is invalid")
        name = item.get("name")
        pattern = _HEADER_RE if field_name == "header" else _ENV_RE
        if not isinstance(name, str) or not pattern.fullmatch(name) or name in declared:
            raise ValueError(f"official MCP {field_name} declaration name is invalid")
        declared[name] = item
    if set(bindings) - set(declared):
        raise ValueError(f"external MCP {field_name} binding is undeclared")
    for name, item in declared.items():
        required = item.get("isRequired") is True
        secret = item.get("isSecret") is True
        default = item.get("default")
        if secret and default not in {None, "<redacted>"}:
            raise ValueError("official MCP metadata retained a secret value")
        if (required or secret) and name not in bindings:
            raise ValueError(f"external MCP {field_name} reference is required")
    return dict(sorted(bindings.items()))


def _target_configuration(
    descriptor: ExternalMCPDescriptor, target_id: str
) -> Mapping[str, Any]:
    env_names = tuple(reference.name for reference in descriptor.environment.values())
    header_names = tuple(
        (name, reference.name) for name, reference in descriptor.headers.items()
    )
    if target_id == HARNESS_MANAGED_MCP_TARGET_ID:
        return external_mcp_descriptor_to_dict(descriptor)
    if target_id == CODEX_MCP_TARGET_ID:
        server = CodexMCPServerSpec(
            name=descriptor.id,
            transport=(
                CodexMCPTransport.STDIO
                if descriptor.transport is MCPTransport.STDIO
                else CodexMCPTransport.STREAMABLE_HTTP
            ),
            command=descriptor.command,
            args=descriptor.args,
            env_vars=env_names,
            url=descriptor.url,
            env_http_headers=header_names,
            startup_timeout_sec=descriptor.timeout_seconds,
            tool_timeout_sec=descriptor.timeout_seconds,
            enabled_tools=descriptor.tool_policy.include_tools,
            disabled_tools=descriptor.tool_policy.exclude_tools,
            default_tools_approval_mode=(
                CodexMCPDefaultApproval.APPROVE
                if descriptor.tool_policy.default is PolicyDecision.ALLOW
                else CodexMCPDefaultApproval.PROMPT
            ),
        )
        return _native_spec_to_dict(server)
    if target_id == CLAUDE_MCP_TARGET_ID:
        server = ClaudeMCPServerSpec(
            name=descriptor.id,
            transport=(
                ClaudeMCPTransport.STDIO
                if descriptor.transport is MCPTransport.STDIO
                else ClaudeMCPTransport.HTTP
            ),
            command=descriptor.command,
            args=descriptor.args,
            env_vars=env_names,
            url=descriptor.url,
            env_http_headers=header_names,
        )
        return _native_spec_to_dict(server)
    server = GeminiMCPServerSpec(
        name=descriptor.id,
        transport=(
            GeminiMCPTransport.STDIO
            if descriptor.transport is MCPTransport.STDIO
            else GeminiMCPTransport.HTTP
        ),
        command=descriptor.command,
        args=descriptor.args,
        env_vars=env_names,
        url=descriptor.url,
        env_http_headers=header_names,
        timeout_ms=descriptor.timeout_seconds * 1000,
        description=descriptor.description,
        include_tools=descriptor.tool_policy.include_tools,
        exclude_tools=descriptor.tool_policy.exclude_tools,
    )
    return _native_spec_to_dict(server)


def _native_spec_to_dict(server: Any) -> dict[str, Any]:
    result = {
        "name": server.name,
        "transport": server.transport.value,
        "command": server.command,
        "args": list(server.args),
        "env_vars": list(server.env_vars),
        "url": server.url,
        "env_http_headers": [list(item) for item in server.env_http_headers],
        "enabled": server.enabled,
    }
    for field_name in (
        "startup_timeout_sec",
        "tool_timeout_sec",
        "timeout_ms",
        "description",
        "enabled_tools",
        "disabled_tools",
        "include_tools",
        "exclude_tools",
        "default_tools_approval_mode",
    ):
        if hasattr(server, field_name):
            value = getattr(server, field_name)
            if isinstance(value, Enum):
                value = value.value
            elif isinstance(value, tuple):
                value = list(value)
            result[field_name] = value
    return result


def _validate_argv(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("external MCP command must use explicit argv")
    normalized = tuple(values)
    if any(
        not isinstance(item, str)
        or not item
        or any(character in item for character in ("\0", "\n", "\r"))
        for item in normalized
    ):
        raise ValueError("external MCP argv is invalid")
    if normalized:
        executable = PurePosixPath(normalized[0].replace("\\", "/")).name.lower()
        if executable in _IMPLICIT_INSTALLERS:
            raise ValueError("external MCP implicit installer commands are forbidden")
        if (
            executable in _SHELLS
            and len(normalized) > 1
            and normalized[1]
            in {
                "-c",
                "/c",
                "-command",
            }
        ):
            raise ValueError("external MCP shell command strings are forbidden")
    return normalized


def _validate_secret_bindings(
    bindings: Mapping[str, SecretReference], pattern: re.Pattern[str], field_name: str
) -> Mapping[str, SecretReference]:
    if not isinstance(bindings, Mapping):
        raise ValueError(f"external MCP {field_name} bindings must be an object")
    normalized: dict[str, SecretReference] = {}
    for name, reference in bindings.items():
        if not isinstance(name, str) or not pattern.fullmatch(name):
            raise ValueError(f"external MCP {field_name} binding name is invalid")
        if not isinstance(reference, SecretReference):
            raise ValueError(f"external MCP {field_name} values must be SecretRef")
        normalized[name] = reference
    return dict(sorted(normalized.items()))


def _normalized_names(values: Sequence[str], label: str) -> tuple[str, ...]:
    normalized = tuple(sorted(set(values)))
    if any(
        not isinstance(value, str)
        or not value
        or len(value) > 256
        or any(character.isspace() for character in value)
        for value in normalized
    ):
        raise ValueError(f"external MCP {label} is invalid")
    return normalized


def _target_safe_id(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._:@+~-]+", "-", name).strip("-")[:180]
    if not slug:
        raise ValueError("official MCP name cannot form a target identity")
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
    return f"external-mcp-{slug}-{digest}"


def _canonical_https_url(value: Any) -> str:
    if not isinstance(value, str) or "{" in value or "}" in value:
        raise ValueError("external MCP URL must be exact")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("external MCP URL must be canonical HTTPS")
    return value


def _canonical_https_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("external MCP download origin must be canonical HTTPS")
    return f"https://{parsed.netloc}"


def _canonical_git_url(value: Any) -> str:
    url = _canonical_https_url(value)
    parsed = urlsplit(url)
    if parsed.hostname != "github.com":
        raise ValueError("external MCP Git source must be GitHub HTTPS")
    path = parsed.path.rstrip("/").removesuffix(".git")
    if len(path.strip("/").split("/")) != 2:
        raise ValueError("external MCP Git repository URL is invalid")
    return f"https://github.com{path}"


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = [
    "HARNESS_MANAGED_MCP_TARGET_ID",
    "ExternalMCPArtifactResolution",
    "ExternalMCPDescriptor",
    "ExternalMCPSelection",
    "ExternalMCPSelectionKind",
    "ExternalMCPTargetPreview",
    "ExternalMCPToolPolicy",
    "external_mcp_descriptor_to_dict",
    "normalize_external_mcp_candidate",
    "project_external_mcp_target",
]
