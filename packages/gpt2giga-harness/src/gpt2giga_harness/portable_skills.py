"""Portable Agent Skills projection and target-scoped installation contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile

import yaml

from gpt2giga_harness.integration_installer import (
    FileInstallMutation,
    InstallationPlan,
    InstallationRequest,
    InstallationTarget,
)
from gpt2giga_harness.integration_packages import (
    InstallationScope,
    IntegrationComponentType,
    IntegrationPackage,
)
from gpt2giga_harness.types import redact_secrets


PORTABLE_SKILL_SCHEMA_VERSION = 1
MAX_SKILL_FILE_BYTES = 1024 * 1024
MAX_SKILL_TOTAL_BYTES = 8 * 1024 * 1024
MAX_PROBE_OUTPUT_CHARS = 8000
SKILL_PROBE_TIMEOUT_SECONDS = 5.0
CODEX_SKILL_TARGET_ID = "codex-skill"
CLAUDE_SKILL_TARGET_ID = "claude-skill"
GEMINI_SKILL_TARGET_ID = "gemini-skill"
_SKILL_NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_METADATA_KEY_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
_VERSION_RE = re.compile(r"(?<!\d)(\d+)\.(\d+)(?:\.(\d+))?")
_CODEX_METADATA = frozenset({"dependencies", "interface", "policy"})
_CLAUDE_METADATA = frozenset(
    {
        "agent",
        "allowed-tools",
        "argument-hint",
        "context",
        "disable-model-invocation",
        "hooks",
        "model",
        "user-invocable",
        "when_to_use",
    }
)


class SkillTargetStatus(str, Enum):
    """Truthful result of one installed-CLI skill capability probe."""

    SUPPORTED = "supported"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


class SkillMetadataDisposition(str, Enum):
    """Whether one provider-specific metadata field was projected."""

    APPLIED = "applied"
    UNSUPPORTED = "unsupported"


class SkillActivationMode(str, Enum):
    """Provider-owned activation behavior after filesystem discovery."""

    IMPLICIT_OR_EXPLICIT = "implicit_or_explicit"
    PROVIDER_CONSENT = "provider_consent"


class SkillDiscoveryStatus(str, Enum):
    """Exact-current state of one generated skill projection."""

    DISCOVERED = "discovered"
    ABSENT = "absent"
    DRIFTED = "drifted"
    BLOCKED = "blocked"


@dataclass(frozen=True, order=True)
class PortableSkillFile:
    """One portable supporting file relative to the skill directory."""

    relative_path: str
    content: bytes
    mode: int = 0o644

    def __post_init__(self) -> None:
        path = _normalize_relative_path(self.relative_path)
        if any(
            path == reserved or path.startswith(f"{reserved}/")
            for reserved in ("SKILL.md", "agents/openai.yaml")
        ):
            raise ValueError("portable skill file path is reserved")
        if not isinstance(self.content, bytes):
            raise TypeError("portable skill file content must be bytes")
        if len(self.content) > MAX_SKILL_FILE_BYTES:
            raise ValueError("portable skill file is too large")
        if self.mode not in {0o600, 0o644, 0o700, 0o755}:
            raise ValueError("portable skill file mode is invalid")
        object.__setattr__(self, "relative_path", path)


@dataclass(frozen=True, order=True)
class SkillMetadataField:
    """One retained provider metadata field with a JSON/YAML-safe value."""

    name: str
    value: object

    def __post_init__(self) -> None:
        if not _METADATA_KEY_RE.fullmatch(self.name):
            raise ValueError("skill metadata field name is invalid")
        object.__setattr__(self, "value", _normalize_metadata_value(self.value))


@dataclass(frozen=True, order=True)
class SkillTargetOverlay:
    """Provider-specific metadata kept separate from the portable core."""

    target_id: str
    fields: tuple[SkillMetadataField, ...]

    def __post_init__(self) -> None:
        _target_contract(self.target_id)
        fields = tuple(sorted(self.fields, key=lambda item: item.name))
        if not fields or any(
            not isinstance(item, SkillMetadataField) for item in fields
        ):
            raise ValueError("skill target overlay fields are invalid")
        names = [item.name for item in fields]
        if len(names) != len(set(names)):
            raise ValueError("skill target overlay fields must be unique")
        for field in fields:
            _validate_supported_metadata(self.target_id, field)
        object.__setattr__(self, "fields", fields)


@dataclass(frozen=True)
class PortableSkill:
    """Agent Skills-compatible core plus explicit target metadata overlays."""

    component_id: str
    name: str
    description: str
    instructions: str
    files: tuple[PortableSkillFile, ...] = ()
    overlays: tuple[SkillTargetOverlay, ...] = ()
    schema_version: int = PORTABLE_SKILL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PORTABLE_SKILL_SCHEMA_VERSION:
            raise ValueError("unsupported portable skill schema_version")
        if not _SKILL_NAME_RE.fullmatch(self.component_id):
            raise ValueError("portable skill component_id is invalid")
        if not _SKILL_NAME_RE.fullmatch(self.name) or len(self.name) > 64:
            raise ValueError("portable skill name is invalid")
        _validate_text(self.description, "portable skill description", max_chars=1024)
        _validate_text(
            self.instructions, "portable skill instructions", max_chars=100_000
        )
        files = tuple(sorted(self.files, key=lambda item: item.relative_path))
        if any(not isinstance(item, PortableSkillFile) for item in files):
            raise TypeError("portable skill files are invalid")
        paths = [item.relative_path for item in files]
        if len(paths) != len(set(paths)):
            raise ValueError("portable skill files must be unique")
        _validate_no_path_collisions(paths)
        if sum(len(item.content) for item in files) > MAX_SKILL_TOTAL_BYTES:
            raise ValueError("portable skill payload is too large")
        overlays = tuple(sorted(self.overlays, key=lambda item: item.target_id))
        if any(not isinstance(item, SkillTargetOverlay) for item in overlays):
            raise TypeError("portable skill overlays are invalid")
        target_ids = [item.target_id for item in overlays]
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("portable skill target overlays must be unique")
        object.__setattr__(self, "files", files)
        object.__setattr__(self, "overlays", overlays)


@dataclass(frozen=True, order=True)
class SkillCommandResult:
    """Bounded subprocess result returned by an injected probe runner."""

    returncode: int
    stdout: str
    stderr: str = ""


SkillCommandRunner = Callable[
    [tuple[str, ...], Mapping[str, str], Path | None, float], SkillCommandResult
]


@dataclass(frozen=True)
class SkillCapabilitySnapshot:
    """Content-free evidence that one current CLI advertises skill discovery."""

    target_id: str
    status: SkillTargetStatus
    version: str | None
    command: tuple[str, ...]
    supports_discovery: bool
    supports_activation: bool
    discovery_method: str
    activation_mode: SkillActivationMode
    reason_code: str | None = None


@dataclass(frozen=True, order=True)
class SkillMetadataReport:
    """One applied or explicitly retained unsupported metadata field."""

    target_id: str
    field_name: str
    value_sha256: str
    disposition: SkillMetadataDisposition
    reason_code: str | None = None


@dataclass(frozen=True, order=True)
class GeneratedSkillFile:
    """One deterministic target-relative output file."""

    relative_path: str
    content: bytes
    mode: int
    sha256: str


@dataclass(frozen=True)
class GeneratedSkillPackage:
    """Target projection with exact files and content-free compatibility facts."""

    target_id: str
    skill_name: str
    status: SkillTargetStatus
    files: tuple[GeneratedSkillFile, ...]
    metadata: tuple[SkillMetadataReport, ...]
    activation_mode: SkillActivationMode
    restart_required: bool
    reason_code: str | None = None


@dataclass(frozen=True)
class SkillDiscoveryResult:
    """Content-free exact-current discovery outcome."""

    target_id: str
    skill_name: str
    status: SkillDiscoveryStatus
    relative_paths: tuple[str, ...]
    reason_code: str | None = None


@dataclass(frozen=True)
class _SkillTargetContract:
    target_id: str
    executable: str
    directory: str
    minimum_version: tuple[int, int, int]
    maximum_version_exclusive: tuple[int, int, int]
    help_tokens: tuple[str, ...]
    metadata_fields: frozenset[str]
    discovery_method: str
    activation_mode: SkillActivationMode
    restart_required: bool


_TARGETS = {
    CODEX_SKILL_TARGET_ID: _SkillTargetContract(
        target_id=CODEX_SKILL_TARGET_ID,
        executable="codex",
        directory=".agents/skills",
        minimum_version=(0, 144, 0),
        maximum_version_exclusive=(1, 0, 0),
        help_tokens=("Codex CLI",),
        metadata_fields=_CODEX_METADATA,
        discovery_method="documented_filesystem",
        activation_mode=SkillActivationMode.IMPLICIT_OR_EXPLICIT,
        restart_required=False,
    ),
    CLAUDE_SKILL_TARGET_ID: _SkillTargetContract(
        target_id=CLAUDE_SKILL_TARGET_ID,
        executable="claude",
        directory=".claude/skills",
        minimum_version=(2, 1, 0),
        maximum_version_exclusive=(3, 0, 0),
        help_tokens=("Skills still resolve", "--disable-slash-commands"),
        metadata_fields=_CLAUDE_METADATA,
        discovery_method="documented_filesystem",
        activation_mode=SkillActivationMode.IMPLICIT_OR_EXPLICIT,
        restart_required=False,
    ),
    GEMINI_SKILL_TARGET_ID: _SkillTargetContract(
        target_id=GEMINI_SKILL_TARGET_ID,
        executable="gemini",
        directory=".gemini/skills",
        minimum_version=(0, 46, 0),
        maximum_version_exclusive=(1, 0, 0),
        help_tokens=("skills <command>", "Manage agent skills"),
        metadata_fields=frozenset(),
        discovery_method="native_cli_list",
        activation_mode=SkillActivationMode.PROVIDER_CONSENT,
        restart_required=False,
    ),
}


def probe_skill_target(
    target_id: str,
    *,
    command: tuple[str, ...] | None = None,
    runner: SkillCommandRunner | None = None,
) -> SkillCapabilitySnapshot:
    """Probe one installed CLI without provider traffic or a real native home."""
    contract = _target_contract(target_id)
    resolved_command = command or (contract.executable,)
    run = runner or _run_command
    with tempfile.TemporaryDirectory(prefix="gpt2giga-skill-probe-") as raw:
        probe_root = Path(raw)
        env = _isolated_env(target_id, probe_root)
        version_result = run(
            (*resolved_command, "--version"), env, None, SKILL_PROBE_TIMEOUT_SECONDS
        )
        help_result = run(
            (*resolved_command, "--help"), env, None, SKILL_PROBE_TIMEOUT_SECONDS
        )
    version_text = _bounded_output(version_result)
    version = _parse_version(version_text)
    if version_result.returncode != 0 or help_result.returncode != 0 or version is None:
        return _capability_failure(contract, resolved_command, "probe_failed")
    if not (contract.minimum_version <= version < contract.maximum_version_exclusive):
        return _capability_failure(
            contract,
            resolved_command,
            "unsupported_version",
            version=_format_version(version),
        )
    help_text = _bounded_output(help_result)
    if not all(
        token.casefold() in help_text.casefold() for token in contract.help_tokens
    ):
        return SkillCapabilitySnapshot(
            target_id=target_id,
            status=SkillTargetStatus.DEGRADED,
            version=_format_version(version),
            command=resolved_command,
            supports_discovery=False,
            supports_activation=False,
            discovery_method=contract.discovery_method,
            activation_mode=contract.activation_mode,
            reason_code="skill_surface_not_advertised",
        )
    return SkillCapabilitySnapshot(
        target_id=target_id,
        status=SkillTargetStatus.SUPPORTED,
        version=_format_version(version),
        command=resolved_command,
        supports_discovery=True,
        supports_activation=True,
        discovery_method=contract.discovery_method,
        activation_mode=contract.activation_mode,
    )


def generate_skill_package(
    skill: PortableSkill,
    capability: SkillCapabilitySnapshot,
) -> GeneratedSkillPackage:
    """Generate one target package without dropping unsupported overlay fields."""
    contract = _target_contract(capability.target_id)
    generated, metadata = _project_skill_content(skill, contract)
    status = capability.status
    reason = capability.reason_code
    if status is SkillTargetStatus.SUPPORTED and not capability.supports_discovery:
        status = SkillTargetStatus.DEGRADED
        reason = "skill_discovery_not_supported"
    if status is SkillTargetStatus.SUPPORTED and not capability.supports_activation:
        status = SkillTargetStatus.DEGRADED
        reason = "skill_activation_not_supported"
    return GeneratedSkillPackage(
        target_id=contract.target_id,
        skill_name=skill.name,
        status=status,
        files=generated,
        metadata=metadata,
        activation_mode=contract.activation_mode,
        restart_required=contract.restart_required,
        reason_code=reason,
    )


def _project_skill_content(
    skill: PortableSkill,
    contract: _SkillTargetContract,
) -> tuple[tuple[GeneratedSkillFile, ...], tuple[SkillMetadataReport, ...]]:
    overlay = next(
        (item for item in skill.overlays if item.target_id == contract.target_id),
        None,
    )
    metadata: list[SkillMetadataReport] = []
    applied: dict[str, object] = {}
    if overlay is not None:
        for field in overlay.fields:
            if field.name in contract.metadata_fields:
                applied[field.name] = field.value
                disposition = SkillMetadataDisposition.APPLIED
                reason = None
            else:
                disposition = SkillMetadataDisposition.UNSUPPORTED
                reason = "target_metadata_unsupported"
            metadata.append(
                SkillMetadataReport(
                    target_id=contract.target_id,
                    field_name=field.name,
                    value_sha256=_metadata_hash(field.value),
                    disposition=disposition,
                    reason_code=reason,
                )
            )
    prefix = f"{contract.directory}/{skill.name}"
    core_metadata: dict[str, object] = {
        "name": skill.name,
        "description": skill.description,
    }
    if contract.target_id == CLAUDE_SKILL_TARGET_ID:
        core_metadata.update(applied)
    generated = [
        _generated_file(
            f"{prefix}/SKILL.md",
            _render_skill_md(core_metadata, skill.instructions),
            0o644,
        )
    ]
    generated.extend(
        _generated_file(f"{prefix}/{item.relative_path}", item.content, item.mode)
        for item in skill.files
    )
    if contract.target_id == CODEX_SKILL_TARGET_ID and applied:
        generated.append(
            _generated_file(
                f"{prefix}/agents/openai.yaml",
                _yaml_bytes(applied),
                0o644,
            )
        )
    projected_files = tuple(sorted(generated, key=lambda item: item.relative_path))
    _validate_no_path_collisions([item.relative_path for item in projected_files])
    return (
        projected_files,
        tuple(metadata),
    )


def build_skill_installation_request(
    package: IntegrationPackage,
    skill: PortableSkill,
    generated: GeneratedSkillPackage,
    *,
    scope: InstallationScope,
    root: str | Path,
) -> InstallationRequest:
    """Bind one supported projection to the existing transactional installer."""
    if generated.status is not SkillTargetStatus.SUPPORTED:
        raise ValueError("skill target capability is not supported")
    contract = _target_contract(generated.target_id)
    expected_files, expected_metadata = _project_skill_content(skill, contract)
    if (
        generated.skill_name != skill.name
        or generated.files != expected_files
        or generated.metadata != expected_metadata
        or generated.activation_mode is not contract.activation_mode
        or generated.restart_required != contract.restart_required
        or generated.reason_code is not None
    ):
        raise ValueError("generated skill package does not match the portable skill")
    if scope not in package.scopes:
        raise ValueError("integration package does not allow the requested scope")
    component = next(
        (item for item in package.components if item.id == skill.component_id),
        None,
    )
    if (
        component is None
        or component.type is not IntegrationComponentType.SKILL
        or not component.portable
    ):
        raise ValueError("integration package does not contain the portable skill")
    compatibility = next(
        (
            item
            for item in package.compatibility
            if item.target_id == generated.target_id
        ),
        None,
    )
    if (
        compatibility is None
        or "skill.discovery" not in compatibility.required_capabilities
    ):
        raise ValueError(
            "integration package does not declare skill discovery compatibility"
        )
    overlay = next(
        (item for item in package.overlays if item.target_id == generated.target_id),
        None,
    )
    if overlay is not None and skill.component_id not in overlay.component_ids:
        raise ValueError("integration target overlay omits the portable skill")
    target = InstallationTarget(
        id=generated.target_id,
        scope=scope,
        root=Path(root),
        owner_id=f"{package.id}:{skill.name}",
    )
    return InstallationRequest(
        package=package,
        target=target,
        mutations=tuple(
            FileInstallMutation(
                relative_path=item.relative_path,
                content=item.content,
                mode=item.mode,
            )
            for item in generated.files
        ),
    )


def discover_generated_skill(
    generated: GeneratedSkillPackage,
    root: str | Path,
) -> SkillDiscoveryResult:
    """Discover an exact target package without reading unrelated native state."""
    if generated.status is not SkillTargetStatus.SUPPORTED:
        return SkillDiscoveryResult(
            target_id=generated.target_id,
            skill_name=generated.skill_name,
            status=SkillDiscoveryStatus.BLOCKED,
            relative_paths=(),
            reason_code=generated.reason_code or "skill_target_not_supported",
        )
    base = Path(root)
    found: list[str] = []
    for item in generated.files:
        path = base / PurePosixPath(item.relative_path)
        if not path.exists():
            return SkillDiscoveryResult(
                target_id=generated.target_id,
                skill_name=generated.skill_name,
                status=SkillDiscoveryStatus.ABSENT,
                relative_paths=tuple(found),
                reason_code="skill_file_missing",
            )
        if _path_is_unsafe(base, PurePosixPath(item.relative_path)):
            return SkillDiscoveryResult(
                target_id=generated.target_id,
                skill_name=generated.skill_name,
                status=SkillDiscoveryStatus.DRIFTED,
                relative_paths=tuple(found),
                reason_code="skill_file_unsafe",
            )
        if hashlib.sha256(path.read_bytes()).hexdigest() != item.sha256:
            return SkillDiscoveryResult(
                target_id=generated.target_id,
                skill_name=generated.skill_name,
                status=SkillDiscoveryStatus.DRIFTED,
                relative_paths=tuple(found),
                reason_code="skill_file_drifted",
            )
        found.append(item.relative_path)
    return SkillDiscoveryResult(
        target_id=generated.target_id,
        skill_name=generated.skill_name,
        status=SkillDiscoveryStatus.DISCOVERED,
        relative_paths=tuple(found),
    )


def generated_skill_verifier(
    generated: GeneratedSkillPackage,
) -> Callable[[Path, InstallationPlan], bool]:
    """Return an installer verifier bound to the exact generated file set."""
    expected_paths = tuple(item.relative_path for item in generated.files)

    def verify(root: Path, plan: InstallationPlan) -> bool:
        planned_paths = tuple(item.relative_path for item in plan.mutations)
        result = discover_generated_skill(generated, root)
        return (
            planned_paths == expected_paths
            and result.status is SkillDiscoveryStatus.DISCOVERED
        )

    return verify


def portable_skill_semantic_hash(skill: PortableSkill) -> str:
    """Return a deterministic hash of the portable core and retained overlays."""
    payload = {
        "schema_version": skill.schema_version,
        "component_id": skill.component_id,
        "name": skill.name,
        "description": skill.description,
        "instructions": skill.instructions,
        "files": [
            {
                "relative_path": item.relative_path,
                "sha256": hashlib.sha256(item.content).hexdigest(),
                "mode": item.mode,
            }
            for item in skill.files
        ],
        "overlays": [
            {
                "target_id": overlay.target_id,
                "fields": [
                    {"name": field.name, "value": field.value}
                    for field in overlay.fields
                ],
            }
            for overlay in skill.overlays
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _generated_file(
    relative_path: str, content: bytes, mode: int
) -> GeneratedSkillFile:
    normalized = _normalize_relative_path(relative_path)
    return GeneratedSkillFile(
        relative_path=normalized,
        content=content,
        mode=mode,
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _render_skill_md(metadata: Mapping[str, object], instructions: str) -> bytes:
    return (
        b"---\n"
        + _yaml_bytes(metadata)
        + b"---\n\n"
        + instructions.rstrip().encode("utf-8")
        + b"\n"
    )


def _yaml_bytes(value: Mapping[str, object]) -> bytes:
    rendered = yaml.safe_dump(
        dict(value),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=True,
    )
    return rendered.encode("utf-8")


def _normalize_metadata_value(value: object) -> object:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        normalized = value
    elif isinstance(value, (list, tuple)):
        normalized = [_normalize_metadata_value(item) for item in value]
    elif isinstance(value, Mapping):
        normalized = {
            str(key): _normalize_metadata_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
        if any(not _METADATA_KEY_RE.fullmatch(key) for key in normalized):
            raise ValueError("skill metadata mapping key is invalid")
    else:
        raise ValueError("skill metadata value is invalid")
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    if len(encoded) > 32_000:
        raise ValueError("skill metadata value is too large")
    return normalized


def _metadata_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_supported_metadata(
    target_id: str,
    field: SkillMetadataField,
) -> None:
    if target_id == CODEX_SKILL_TARGET_ID and field.name in _CODEX_METADATA:
        if not isinstance(field.value, Mapping):
            raise ValueError("Codex skill metadata field must be a mapping")
        return
    if target_id != CLAUDE_SKILL_TARGET_ID or field.name not in _CLAUDE_METADATA:
        return
    if field.name in {"disable-model-invocation", "user-invocable"}:
        if not isinstance(field.value, bool):
            raise ValueError("Claude skill boolean metadata is invalid")
        return
    if field.name == "hooks":
        if not isinstance(field.value, Mapping):
            raise ValueError("Claude skill hooks metadata is invalid")
        return
    if field.name == "allowed-tools":
        if isinstance(field.value, str):
            return
        if not isinstance(field.value, list) or any(
            not isinstance(item, str) or not item for item in field.value
        ):
            raise ValueError("Claude skill allowed-tools metadata is invalid")
        return
    if not isinstance(field.value, str) or not field.value:
        raise ValueError("Claude skill text metadata is invalid")


def _validate_no_path_collisions(paths: list[str]) -> None:
    path_set = set(paths)
    for value in paths:
        current = PurePosixPath(value)
        for parent in current.parents:
            if parent == PurePosixPath("."):
                break
            if parent.as_posix() in path_set:
                raise ValueError("portable skill file paths collide")


def _path_is_unsafe(base: Path, relative_path: PurePosixPath) -> bool:
    if base.is_symlink() or not base.is_dir():
        return True
    current = base
    for part in relative_path.parts[:-1]:
        current /= part
        if current.is_symlink() or not current.is_dir():
            return True
    target = current / relative_path.name
    return target.is_symlink() or not target.is_file()


def _normalize_relative_path(value: str) -> str:
    if not isinstance(value, str) or "\\" in value or "\x00" in value:
        raise ValueError("portable skill path is invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("portable skill path must remain relative")
    return path.as_posix()


def _validate_text(value: str, field_name: str, *, max_chars: int) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > max_chars:
        raise ValueError(f"{field_name} is invalid")
    if "\x00" in value:
        raise ValueError(f"{field_name} is invalid")


def _target_contract(target_id: str) -> _SkillTargetContract:
    try:
        return _TARGETS[target_id]
    except KeyError as exc:
        raise ValueError("unknown portable skill target") from exc


def _capability_failure(
    contract: _SkillTargetContract,
    command: tuple[str, ...],
    reason_code: str,
    *,
    version: str | None = None,
) -> SkillCapabilitySnapshot:
    return SkillCapabilitySnapshot(
        target_id=contract.target_id,
        status=SkillTargetStatus.BLOCKED,
        version=version,
        command=command,
        supports_discovery=False,
        supports_activation=False,
        discovery_method=contract.discovery_method,
        activation_mode=contract.activation_mode,
        reason_code=reason_code,
    )


def _parse_version(value: str) -> tuple[int, int, int] | None:
    match = _VERSION_RE.search(value)
    if match is None:
        return None
    return tuple(int(item or 0) for item in match.groups())  # type: ignore[return-value]


def _format_version(value: tuple[int, int, int]) -> str:
    return ".".join(str(item) for item in value)


def _bounded_output(result: SkillCommandResult) -> str:
    output = f"{result.stdout}\n{result.stderr}"[:MAX_PROBE_OUTPUT_CHARS]
    return str(redact_secrets(output))


def _isolated_env(target_id: str, root: Path) -> dict[str, str]:
    env = {"HOME": str(root), "PATH": os.environ.get("PATH", "")}
    if target_id == CODEX_SKILL_TARGET_ID:
        env["CODEX_HOME"] = str(root / ".codex")
    elif target_id == CLAUDE_SKILL_TARGET_ID:
        env["CLAUDE_CONFIG_DIR"] = str(root / ".claude")
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    else:
        env["GEMINI_CLI_HOME"] = str(root)
    return env


def _run_command(
    argv: tuple[str, ...],
    env: Mapping[str, str],
    cwd: Path | None,
    timeout: float,
) -> SkillCommandResult:
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=dict(env),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return SkillCommandResult(
            returncode=127,
            stdout="",
            stderr=f"{type(exc).__name__} (details omitted)",
        )
    return SkillCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout[:MAX_PROBE_OUTPUT_CHARS],
        stderr=completed.stderr[:MAX_PROBE_OUTPUT_CHARS],
    )
