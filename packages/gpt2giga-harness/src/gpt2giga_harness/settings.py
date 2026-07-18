"""Persistent, non-secret Harness defaults owned by the control plane."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping

from gpt2giga_harness.config import (
    DEFAULT_CHAT_MODEL,
    DEFAULT_TITLE_MODEL,
    HarnessConfig,
)
from gpt2giga_harness.sessions.locking import exclusive_file_lock
from gpt2giga_harness.secrets import (
    SecretReference,
    SecretReferenceKind,
    secret_reference_from_dict,
    secret_reference_to_dict,
)


SETTINGS_SCHEMA_VERSION = 1
SECRET_REFERENCE_SETTINGS_SCHEMA_VERSION = 1
_SECRET_REFERENCE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
SETTINGS_FIELDS = frozenset(
    {
        "default_api_mode",
        "default_harness_id",
        "default_model",
        "default_title_model",
        "execution_transport",
        "invocation_mode",
        "mode",
        "permission_profile",
        "stream",
        "workspace_policy",
    }
)


@dataclass(frozen=True)
class HarnessDefaults:
    """Effective defaults copied into newly created sessions and runs."""

    default_harness_id: str = "codex-cli"
    default_model: str | None = DEFAULT_CHAT_MODEL
    default_title_model: str | None = DEFAULT_TITLE_MODEL
    default_api_mode: str = "v2"
    mode: str = "plan"
    execution_transport: str = "native_structured"
    invocation_mode: str = "headless"
    workspace_policy: str = "auto"
    permission_profile: str = "interactive"
    stream: bool = True


@dataclass(frozen=True)
class HarnessDefaultsSnapshot:
    """Effective defaults plus provenance and optimistic-write revision."""

    defaults: HarnessDefaults
    sources: Mapping[str, str]
    locked_fields: tuple[str, ...]
    revision: str


@dataclass(frozen=True)
class SecretReferenceSettingsSnapshot:
    """Persisted reference-only settings plus optimistic-write revision."""

    references: Mapping[str, SecretReference]
    revision: str


class HarnessSettingsStore:
    """Atomically persist reviewed defaults without storing environment values."""

    def __init__(self, data_dir: str | Path, config: HarnessConfig) -> None:
        self.path = Path(data_dir).expanduser() / "settings" / "defaults.json"
        self.lock_path = self.path.with_suffix(".lock")
        self.config = config

    def load(self) -> HarnessDefaultsSnapshot:
        """Read and merge stored values with environment-owned runtime values."""
        with exclusive_file_lock(self.lock_path):
            stored = self._read_unlocked()
        locked = _environment_owned_fields()
        base = HarnessDefaults(
            default_model=self.config.default_model or DEFAULT_CHAT_MODEL,
            default_api_mode=self.config.default_api_mode.value,
        )
        values = asdict(base)
        sources = {field: "built_in" for field in SETTINGS_FIELDS}
        for field, value in stored.items():
            if field in SETTINGS_FIELDS and field not in locked:
                values[field] = value
                sources[field] = "harness_settings"
        for field in locked:
            sources[field] = "environment"
        defaults = HarnessDefaults(**values)
        revision = _revision(defaults, sources)
        return HarnessDefaultsSnapshot(
            defaults=defaults,
            sources=sources,
            locked_fields=tuple(sorted(locked)),
            revision=revision,
        )

    def save(
        self,
        values: Mapping[str, Any],
        *,
        expected_revision: str | None = None,
    ) -> HarnessDefaultsSnapshot:
        """Persist a complete validated settings mapping with conflict detection."""
        with exclusive_file_lock(self.lock_path):
            current = self.load_without_lock()
            if expected_revision and expected_revision != current.revision:
                raise SettingsConflictError("settings revision changed")
            locked = set(current.locked_fields)
            persisted = {
                field: value
                for field, value in values.items()
                if field in SETTINGS_FIELDS and field not in locked
            }
            payload = {
                "schema_version": SETTINGS_SCHEMA_VERSION,
                "defaults": persisted,
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        return self.load()

    def load_without_lock(self) -> HarnessDefaultsSnapshot:
        """Load while the caller already owns the store lock."""
        stored = self._read_unlocked()
        locked = _environment_owned_fields()
        base = HarnessDefaults(
            default_model=self.config.default_model or DEFAULT_CHAT_MODEL,
            default_api_mode=self.config.default_api_mode.value,
        )
        values = asdict(base)
        sources = {field: "built_in" for field in SETTINGS_FIELDS}
        for field, value in stored.items():
            if field in SETTINGS_FIELDS and field not in locked:
                values[field] = value
                sources[field] = "harness_settings"
        for field in locked:
            sources[field] = "environment"
        defaults = HarnessDefaults(**values)
        return HarnessDefaultsSnapshot(
            defaults=defaults,
            sources=sources,
            locked_fields=tuple(sorted(locked)),
            revision=_revision(defaults, sources),
        )

    def _read_unlocked(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, Mapping):
            return {}
        defaults = payload.get("defaults")
        return dict(defaults) if isinstance(defaults, Mapping) else {}


class SettingsConflictError(RuntimeError):
    """Raised when an optimistic settings write uses a stale revision."""


class SecretReferenceSettingsStore:
    """Atomically persist backend secret references without secret values."""

    def __init__(self, data_dir: str | Path) -> None:
        self.path = Path(data_dir).expanduser() / "settings" / "secret_refs.json"
        self.lock_path = self.path.with_suffix(".lock")

    def load(self) -> SecretReferenceSettingsSnapshot:
        """Read strict versioned references without resolving any source."""
        with exclusive_file_lock(self.lock_path):
            references = self._read_unlocked()
        return SecretReferenceSettingsSnapshot(
            references=references,
            revision=_secret_reference_revision(references),
        )

    def save(
        self,
        references: Mapping[str, SecretReference],
        *,
        expected_revision: str | None = None,
    ) -> SecretReferenceSettingsSnapshot:
        """Validate and atomically replace the complete reference mapping."""
        normalized = _validate_secret_reference_settings(references)
        with exclusive_file_lock(self.lock_path):
            current = self._read_unlocked()
            if (
                expected_revision is not None
                and expected_revision != _secret_reference_revision(current)
            ):
                raise SettingsConflictError(
                    "secret reference settings revision changed"
                )
            payload = {
                "schema_version": SECRET_REFERENCE_SETTINGS_SCHEMA_VERSION,
                "references": {
                    name: secret_reference_to_dict(reference)
                    for name, reference in sorted(normalized.items())
                },
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        return self.load()

    def _read_unlocked(self) -> dict[str, SecretReference]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("secret reference settings are unreadable") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("secret reference settings must be an object")
        if payload.get("schema_version") != SECRET_REFERENCE_SETTINGS_SCHEMA_VERSION:
            raise ValueError("unsupported secret reference settings schema_version")
        raw_references = payload.get("references")
        if not isinstance(raw_references, Mapping):
            raise ValueError("secret reference settings references must be an object")
        parsed: dict[str, SecretReference] = {}
        for raw_name, raw_reference in raw_references.items():
            if not isinstance(raw_name, str) or not isinstance(raw_reference, Mapping):
                raise ValueError("secret reference settings entry is invalid")
            try:
                parsed[raw_name] = secret_reference_from_dict(raw_reference)
            except (TypeError, ValueError) as exc:
                raise ValueError("secret reference settings entry is invalid") from exc
        return _validate_secret_reference_settings(parsed)


def _environment_owned_fields() -> set[str]:
    locked: set[str] = set()
    if any(
        os.getenv(name) for name in ("GPT2GIGA_HARNESS_DEFAULT_MODEL", "GIGACHAT_MODEL")
    ):
        locked.add("default_model")
    if any(
        os.getenv(name)
        for name in (
            "GPT2GIGA_HARNESS_DEFAULT_API_MODE",
            "GPT2GIGA_GIGACHAT_API_MODE",
        )
    ):
        locked.add("default_api_mode")
    return locked


def _revision(defaults: HarnessDefaults, sources: Mapping[str, str]) -> str:
    encoded = json.dumps(
        {"defaults": asdict(defaults), "sources": dict(sources)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_secret_reference_settings(
    references: Mapping[str, SecretReference],
) -> dict[str, SecretReference]:
    normalized: dict[str, SecretReference] = {}
    for raw_name, reference in references.items():
        if not isinstance(raw_name, str) or not _SECRET_REFERENCE_ID_RE.fullmatch(
            raw_name
        ):
            raise ValueError("secret reference setting id is invalid")
        if not isinstance(reference, SecretReference):
            raise TypeError(
                "secret reference settings accept SecretReference values only"
            )
        if reference.kind is SecretReferenceKind.TEST:
            raise ValueError("test secret references cannot be persisted")
        normalized[raw_name] = reference
    return normalized


def _secret_reference_revision(
    references: Mapping[str, SecretReference],
) -> str:
    encoded = json.dumps(
        {
            name: secret_reference_to_dict(reference)
            for name, reference in sorted(references.items())
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
