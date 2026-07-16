"""Persistent, non-secret Harness defaults owned by the control plane."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from gpt2giga_harness.config import (
    DEFAULT_CHAT_MODEL,
    DEFAULT_TITLE_MODEL,
    HarnessConfig,
)
from gpt2giga_harness.sessions.locking import exclusive_file_lock


SETTINGS_SCHEMA_VERSION = 1
SETTINGS_FIELDS = frozenset(
    {
        "default_api_mode",
        "default_harness_id",
        "default_model",
        "default_title_model",
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
