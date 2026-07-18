"""Explicit forward-only migration of legacy gpt2giga provider defaults."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.provider_profiles import (
    ModelPurpose,
    ModelPurposeDefault,
    ProviderOwnership,
    ProviderProfile,
    RouteProfile,
    migrate_legacy_provider_route,
    provider_profile_to_dict,
    route_profile_to_dict,
)
from gpt2giga_harness.provider_registry import (
    PROVIDER_REGISTRY_SCHEMA_VERSION,
    ProviderRegistryEntry,
    ProviderRegistryStore,
)
from gpt2giga_harness.sessions.locking import exclusive_file_lock
from gpt2giga_harness.settings import HarnessSettingsStore
from gpt2giga_harness.state_backup import create_state_backup, verify_state_backup


PROVIDER_MIGRATION_SCHEMA_VERSION = 1
PROVIDER_MIGRATION_ID = "legacy_gpt2giga_defaults_v1"
PROVIDER_MIGRATION_ALIASES = {
    "cli": ("--proxy-url", "--api-mode", "--model"),
    "state": (
        "settings/defaults.json:default_api_mode",
        "settings/defaults.json:default_model",
        "settings/defaults.json:default_title_model",
    ),
    "api": (
        "/api/settings:routes.default_api_mode",
        "/api/settings:routes.default_model",
        "/api/models?api_mode={v1|v2}",
    ),
}
PROVIDER_MIGRATION_ROLLBACK_POLICY = "restore_verified_pre_upgrade_archive"
_LEGACY_HARNESSES = ("direct-chat", "codex-cli", "claude-code", "gemini-cli")


@dataclass(frozen=True)
class ProviderMigrationPlan:
    """Content-free preflight for one explicit provider-state conversion."""

    schema_version: int
    migration_id: str
    status: str
    source_revision: str
    provider_ids: tuple[str, ...]
    route_count: int
    backup_required: bool
    rollback_policy: str
    compatibility_aliases: Mapping[str, tuple[str, ...]]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the bounded plan without filesystem paths or secrets."""
        return {
            "schema_version": self.schema_version,
            "migration_id": self.migration_id,
            "status": self.status,
            "source_revision": self.source_revision,
            "provider_ids": list(self.provider_ids),
            "route_count": self.route_count,
            "backup_required": self.backup_required,
            "rollback_policy": self.rollback_policy,
            "compatibility_aliases": {
                key: list(values)
                for key, values in sorted(self.compatibility_aliases.items())
            },
        }


@dataclass(frozen=True)
class ProviderMigrationResult:
    """Content-free result of an explicit backup-gated migration."""

    plan: ProviderMigrationPlan
    applied: bool
    backup_sha256: str
    migration_journal_sha256: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize retained migration and rollback evidence."""
        return {
            **self.plan.to_dict(),
            "applied": self.applied,
            "backup_sha256": self.backup_sha256,
            "migration_journal_sha256": self.migration_journal_sha256,
        }


class ProviderMigrationService:
    """Plan and atomically publish legacy provider defaults after backup."""

    def __init__(
        self,
        data_dir: str | Path,
        config: HarnessConfig,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.config = config
        self.settings = HarnessSettingsStore(self.data_dir, config)
        self.registry = ProviderRegistryStore(
            self.data_dir,
            ProviderOwnership.MIGRATED_LEGACY,
            now=now,
        )
        self.journal_path = self.data_dir / "migrations" / "provider_registry.json"
        self.lock_path = self.data_dir / "migrations" / "provider_registry"
        self._now = now or (lambda: datetime.now(timezone.utc))

    def plan(self) -> ProviderMigrationPlan:
        """Return a deterministic preflight without converting user state."""
        snapshot = self.settings.load()
        expected = self._expected_entries(snapshot.defaults)
        expected_hash = _registry_semantic_hash(expected)
        journal = self._read_journal()
        existing = self.registry.list() if self.registry.path.exists() else ()

        if journal is not None:
            if not existing:
                raise ValueError(
                    "provider migration journal exists without migrated registry"
                )
            actual_hash = _registry_semantic_hash(existing)
            if actual_hash != journal["registry_semantic_sha256"]:
                raise ValueError("migrated provider registry changed after migration")
            return self._plan(
                status="current",
                source_revision=str(journal["source_revision"]),
                entries=existing,
                backup_required=False,
            )

        if existing:
            if _registry_semantic_hash(existing) == expected_hash:
                raise ValueError(
                    "migrated provider registry exists without a migration journal; "
                    "restore the verified pre-upgrade archive"
                )
            raise ValueError("unmanaged migrated provider registry blocks migration")
        return self._plan(
            status="ready",
            source_revision=snapshot.revision,
            entries=expected,
            backup_required=True,
        )

    def migrate(self, backup_archive: str | Path) -> ProviderMigrationResult:
        """Create and verify a backup, then publish registry and journal."""
        if not self.data_dir.is_dir():
            raise ValueError("Harness state directory must exist before migration")
        initial = self.plan()
        if initial.status != "ready":
            journal = self._read_journal()
            if journal is None:
                raise ValueError("provider migration is not ready")
            return ProviderMigrationResult(
                plan=initial,
                applied=False,
                backup_sha256=str(journal["backup_sha256"]),
                migration_journal_sha256=_hash_file(self.journal_path),
            )

        backup = create_state_backup(self.data_dir, backup_archive)
        verified = verify_state_backup(backup_archive)
        if backup.sha256 != verified.sha256:
            raise ValueError("pre-upgrade provider migration backup changed")

        with exclusive_file_lock(self.lock_path):
            with exclusive_file_lock(self.settings.lock_path):
                snapshot = self.settings.load_without_lock()
                if snapshot.revision != initial.source_revision:
                    raise ValueError(
                        "provider migration source changed after backup; discard the "
                        "archive and retry"
                    )
                if self.journal_path.exists() or self.registry.path.exists():
                    raise ValueError(
                        "provider migration target changed after backup; discard the "
                        "archive and retry"
                    )
                entries = self._expected_entries(snapshot.defaults)
                registry_hash = _registry_semantic_hash(entries)
                journal = {
                    "schema_version": PROVIDER_MIGRATION_SCHEMA_VERSION,
                    "migration_id": PROVIDER_MIGRATION_ID,
                    "source_revision": snapshot.revision,
                    "target_registry_schema_version": (
                        PROVIDER_REGISTRY_SCHEMA_VERSION
                    ),
                    "registry_semantic_sha256": registry_hash,
                    "backup_sha256": verified.sha256,
                    "applied_at": _format_timestamp(self._now()),
                    "compatibility_aliases": {
                        key: list(values)
                        for key, values in sorted(PROVIDER_MIGRATION_ALIASES.items())
                    },
                    "rollback_policy": PROVIDER_MIGRATION_ROLLBACK_POLICY,
                }
                self.registry.initialize(entries)
                try:
                    _atomic_private_json(self.journal_path, journal)
                except BaseException:
                    self.registry.path.unlink(missing_ok=True)
                    raise

        completed = self.plan()
        return ProviderMigrationResult(
            plan=completed,
            applied=True,
            backup_sha256=verified.sha256,
            migration_journal_sha256=_hash_file(self.journal_path),
        )

    def _plan(
        self,
        *,
        status: str,
        source_revision: str,
        entries: tuple[ProviderRegistryEntry, ...],
        backup_required: bool,
    ) -> ProviderMigrationPlan:
        return ProviderMigrationPlan(
            schema_version=PROVIDER_MIGRATION_SCHEMA_VERSION,
            migration_id=PROVIDER_MIGRATION_ID,
            status=status,
            source_revision=source_revision,
            provider_ids=tuple(sorted(entry.profile.id for entry in entries)),
            route_count=sum(len(entry.routes) for entry in entries),
            backup_required=backup_required,
            rollback_policy=PROVIDER_MIGRATION_ROLLBACK_POLICY,
            compatibility_aliases=PROVIDER_MIGRATION_ALIASES,
        )

    def _expected_entries(self, defaults: Any) -> tuple[ProviderRegistryEntry, ...]:
        models = {
            ModelPurpose.CODING: defaults.default_model,
            ModelPurpose.TITLE: defaults.default_title_model,
        }
        grouped: dict[str, tuple[ProviderProfile, list[RouteProfile], list[Any]]] = {}
        for harness_id in _LEGACY_HARNESSES:
            for purpose, model in models.items():
                if model is None:
                    continue
                profile, route = migrate_legacy_provider_route(
                    proxy_url=self.config.proxy_url,
                    api_mode=defaults.default_api_mode,
                    harness_id=harness_id,
                    model=model,
                    purpose=purpose,
                )
                if profile.id not in grouped:
                    grouped[profile.id] = (profile, [], [])
                grouped[profile.id][1].append(route)
                grouped[profile.id][2].extend(profile.capability_evidence)

        timestamp = _format_timestamp(self._now())
        entries = []
        for provider_id in sorted(grouped):
            base, raw_routes, raw_evidence = grouped[provider_id]
            defaults_by_purpose = {route.purpose: route.model for route in raw_routes}
            evidence_by_id: dict[str, list[Any]] = {}
            for item in raw_evidence:
                evidence_by_id.setdefault(item.id, []).append(item)
            evidence = tuple(
                replace(
                    values[0],
                    revision=sha256(
                        _canonical_json(
                            sorted(
                                {
                                    (item.revision, item.status, item.source)
                                    for item in values
                                }
                            )
                        )
                    ).hexdigest(),
                )
                for _evidence_id, values in sorted(evidence_by_id.items())
            )
            semantic = {
                "migration_id": PROVIDER_MIGRATION_ID,
                "provider_id": provider_id,
                "protocol": base.protocol.value,
                "dialect": base.dialect,
                "base_url": base.base_url,
                "route_prefix": base.route_prefix,
                "models": {
                    purpose.value: model
                    for purpose, model in sorted(
                        defaults_by_purpose.items(), key=lambda item: item[0].value
                    )
                },
                "routes": [
                    {
                        "id": route.id,
                        "purpose": route.purpose.value,
                        "model": route.model,
                    }
                    for route in sorted(raw_routes, key=lambda item: item.id)
                ],
            }
            revision = sha256(_canonical_json(semantic)).hexdigest()
            profile = replace(
                base,
                revision=revision,
                capability_evidence=evidence,
                default_models=tuple(
                    ModelPurposeDefault(purpose, model)
                    for purpose, model in sorted(
                        defaults_by_purpose.items(), key=lambda item: item[0].value
                    )
                ),
            )
            routes = tuple(
                replace(
                    route,
                    provider=profile.ref,
                    revision=sha256(
                        _canonical_json(
                            {
                                "provider_revision": revision,
                                "route_id": route.id,
                                "purpose": route.purpose.value,
                                "model": route.model,
                            }
                        )
                    ).hexdigest(),
                )
                for route in sorted(raw_routes, key=lambda item: item.id)
            )
            entries.append(
                ProviderRegistryEntry(
                    profile=profile,
                    routes=routes,
                    enabled=True,
                    revision=1,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
        return tuple(entries)

    def _read_journal(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self.journal_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("provider migration journal is unreadable") from exc
        required = {
            "schema_version",
            "migration_id",
            "source_revision",
            "target_registry_schema_version",
            "registry_semantic_sha256",
            "backup_sha256",
            "applied_at",
            "compatibility_aliases",
            "rollback_policy",
        }
        if not isinstance(payload, dict) or set(payload) != required:
            raise ValueError("provider migration journal fields are invalid")
        if payload.get("schema_version") != PROVIDER_MIGRATION_SCHEMA_VERSION:
            raise ValueError("unsupported provider migration schema_version")
        if payload.get("migration_id") != PROVIDER_MIGRATION_ID:
            raise ValueError("unsupported provider migration id")
        if payload.get("target_registry_schema_version") != (
            PROVIDER_REGISTRY_SCHEMA_VERSION
        ):
            raise ValueError("unsupported migrated provider registry schema_version")
        if payload.get("rollback_policy") != PROVIDER_MIGRATION_ROLLBACK_POLICY:
            raise ValueError("unsupported provider migration rollback policy")
        return payload


def provider_migration_aliases() -> dict[str, list[str]]:
    """Return additive legacy CLI/state/API compatibility aliases."""
    return {
        key: list(values) for key, values in sorted(PROVIDER_MIGRATION_ALIASES.items())
    }


def _registry_semantic_hash(entries: tuple[ProviderRegistryEntry, ...]) -> str:
    payload = [
        {
            "profile": provider_profile_to_dict(entry.profile),
            "routes": [route_profile_to_dict(route) for route in entry.routes],
            "enabled": entry.enabled,
            "revision": entry.revision,
        }
        for entry in sorted(entries, key=lambda item: item.profile.id)
    ]
    return sha256(_canonical_json(payload)).hexdigest()


def _atomic_private_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        temporary.replace(path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _format_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("provider migration timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "PROVIDER_MIGRATION_ALIASES",
    "PROVIDER_MIGRATION_ID",
    "PROVIDER_MIGRATION_ROLLBACK_POLICY",
    "PROVIDER_MIGRATION_SCHEMA_VERSION",
    "ProviderMigrationPlan",
    "ProviderMigrationResult",
    "ProviderMigrationService",
    "provider_migration_aliases",
]
