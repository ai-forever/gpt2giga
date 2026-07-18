from __future__ import annotations

from datetime import datetime, timezone
import json
import stat

from fastapi.testclient import TestClient
import pytest

from gpt2giga_harness import cli
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.provider_migration import ProviderMigrationService
from gpt2giga_harness.provider_settings import ProviderSettingsService
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.sessions import InMemoryHarnessSessionStore
from gpt2giga_harness.state_backup import restore_state_backup, verify_state_backup
from gpt2giga_harness.ui.app import create_app


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)


def test_provider_migration_is_deterministic_backup_gated_and_idempotent(tmp_path):
    data_dir = tmp_path / "state"
    _write_defaults(data_dir)
    config = HarnessConfig(
        data_dir=str(data_dir),
        proxy_url="https://proxy.example/root",
    )
    service = ProviderMigrationService(data_dir, config, now=lambda: NOW)

    first_plan = service.plan()
    second_plan = service.plan()

    assert first_plan == second_plan
    assert first_plan.status == "ready"
    assert first_plan.backup_required is True
    assert first_plan.provider_ids == (
        "legacy-gpt2giga-anthropic-compatible",
        "legacy-gpt2giga-gemini-compatible",
        "legacy-gpt2giga-openai-compatible",
    )
    assert first_plan.route_count == 8
    assert not service.registry.path.exists()

    archive = tmp_path / "pre-upgrade.zip"
    result = service.migrate(archive)

    assert result.applied is True
    assert result.plan.status == "current"
    assert result.plan.backup_required is False
    assert result.backup_sha256 == verify_state_backup(archive).sha256
    assert stat.S_IMODE(service.registry.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(service.journal_path.stat().st_mode) == 0o600
    serialized = service.registry.path.read_text(encoding="utf-8")
    assert "GPT2GIGA_HARNESS_API_KEY" in serialized
    assert "secret-value-canary" not in serialized

    second_archive = tmp_path / "must-not-be-created.zip"
    repeated = service.migrate(second_archive)
    assert repeated.applied is False
    assert repeated.backup_sha256 == result.backup_sha256
    assert not second_archive.exists()


def test_provider_migration_rejects_future_state_before_backup_or_mutation(tmp_path):
    data_dir = tmp_path / "state"
    _write_defaults(data_dir, schema_version=2)
    service = ProviderMigrationService(
        data_dir,
        HarnessConfig(data_dir=str(data_dir)),
        now=lambda: NOW,
    )
    archive = tmp_path / "must-not-exist.zip"

    with pytest.raises(ValueError, match="schema_version"):
        service.migrate(archive)

    assert not archive.exists()
    assert not service.registry.path.exists()
    assert not service.journal_path.exists()


def test_provider_migration_rejects_source_change_after_verified_backup(
    tmp_path,
    monkeypatch,
):
    from gpt2giga_harness import provider_migration

    data_dir = tmp_path / "state"
    _write_defaults(data_dir)
    service = ProviderMigrationService(
        data_dir,
        HarnessConfig(data_dir=str(data_dir)),
        now=lambda: NOW,
    )
    real_backup = provider_migration.create_state_backup

    def backup_then_change(source, archive):
        result = real_backup(source, archive)
        _write_defaults(data_dir, default_model="ChangedAfterBackup")
        return result

    monkeypatch.setattr(provider_migration, "create_state_backup", backup_then_change)
    archive = tmp_path / "stale-pre-upgrade.zip"

    with pytest.raises(ValueError, match="source changed after backup"):
        service.migrate(archive)

    assert archive.is_file()
    assert not service.registry.path.exists()
    assert not service.journal_path.exists()


def test_provider_migration_rollback_restores_pre_upgrade_archive(tmp_path):
    data_dir = tmp_path / "state"
    _write_defaults(data_dir)
    service = ProviderMigrationService(
        data_dir,
        HarnessConfig(data_dir=str(data_dir)),
        now=lambda: NOW,
    )
    archive = tmp_path / "pre-upgrade.zip"
    service.migrate(archive)

    restored = restore_state_backup(archive, data_dir, replace=True)

    assert restored.replaced_existing is True
    assert (data_dir / "settings" / "defaults.json").is_file()
    assert not (data_dir / "providers" / "migrated_legacy.json").exists()
    assert not (data_dir / "migrations" / "provider_registry.json").exists()


def test_migrated_defaults_read_back_through_cli_state_and_api_aliases(
    tmp_path,
    monkeypatch,
    capsys,
):
    data_dir = tmp_path / "state"
    _write_defaults(data_dir)
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("GPT2GIGA_HARNESS_PROXY_URL", "https://proxy.example/root")

    assert cli.main(["provider", "migrate", "--dry-run", "--json"]) == 0
    canonical = json.loads(capsys.readouterr().out)
    assert cli.main(["state", "migrate-providers", "--dry-run", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == canonical

    archive = tmp_path / "pre-upgrade.zip"
    assert (
        cli.main(
            [
                "provider",
                "migrate-legacy",
                "--backup",
                str(archive),
                "--json",
            ]
        )
        == 0
    )
    migrated = json.loads(capsys.readouterr().out)
    assert migrated["applied"] is True
    assert migrated["rollback_policy"] == "restore_verified_pre_upgrade_archive"

    service = ProviderSettingsService(str(data_dir))
    listed = service.list()
    assert {provider["source"] for provider in listed["providers"]} == {
        "migrated_legacy"
    }
    assert listed["compatibility_aliases"] == canonical["compatibility_aliases"]
    provider_id = "legacy-gpt2giga-openai-compatible"
    assert service.get(provider_id)["editable"] is False
    assert cli.main(["provider", "show", provider_id, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == provider_id

    app = create_app(
        HarnessConfig(data_dir=str(data_dir)),
        registry=create_default_registry(include_entry_points=False),
        store=InMemoryHarnessSessionStore(),
    )
    response = TestClient(app).get("/api/providers")
    assert response.status_code == 200
    assert response.json()["compatibility_aliases"]["api"] == [
        "/api/settings:routes.default_api_mode",
        "/api/settings:routes.default_model",
        "/api/models?api_mode={v1|v2}",
    ]


def _write_defaults(data_dir, *, schema_version=1, default_model="LegacyCoding"):
    settings = data_dir / "settings"
    settings.mkdir(parents=True, exist_ok=True)
    (settings / "defaults.json").write_text(
        json.dumps(
            {
                "schema_version": schema_version,
                "defaults": {
                    "default_api_mode": "v1",
                    "default_harness_id": "codex-cli",
                    "default_model": default_model,
                    "default_title_model": "LegacyTitle",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
