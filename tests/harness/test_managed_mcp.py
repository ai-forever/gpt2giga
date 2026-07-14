import json

from fastapi.testclient import TestClient
import pytest

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.managed_mcp import (
    HEADLESS_SNAPSHOT_MARKER,
    MANAGED_MARKER,
    HeadlessManagedMCPSnapshotStore,
    ManagedConfigConflictError,
    ManagedConfigOwnershipError,
    ManagedMCPConfigService,
    compose_managed_config,
    compose_startup_config,
    materialize_headless_mcp_snapshot,
    write_startup_config,
)
from gpt2giga_harness.mcp import descriptor_from_profile
from gpt2giga_harness.project import ProjectToolProfile
from gpt2giga_harness.tools import EnvironmentSecretResolver
from gpt2giga_harness.ui.app import create_app


def _stdio_descriptor(*, trusted=True, harnesses=()):
    return descriptor_from_profile(
        "issues",
        ProjectToolProfile(
            enabled=True,
            title="Issues",
            harnesses=harnesses,
            config={
                "transport": "stdio",
                "command": "issue-mcp",
                "args": ["--readonly"],
                "trusted": trusted,
                "env": {
                    "MODE": "read",
                    "TOKEN": {
                        "secret_ref": {
                            "kind": "environment",
                            "name": "ISSUE_TOKEN",
                        }
                    },
                },
            },
        ),
    )


def test_composer_preserves_startup_settings_and_never_copies_secret_refs():
    descriptor = _stdio_descriptor()

    codex, warnings = compose_managed_config(
        "codex-cli", 'model = "GigaChat"\n', (descriptor,)
    )
    restarted = compose_startup_config("codex-cli", codex, 'model = "GigaChat-2-Max"\n')
    claude, _ = compose_managed_config("claude-code", "{}", (descriptor,))
    claude = compose_startup_config(
        "claude-code",
        json.dumps(
            {
                **json.loads(claude),
                "projects": {
                    "/repo": {
                        "allowedTools": ["Read"],
                        "hasTrustDialogAccepted": False,
                    },
                    "/other": {"hasTrustDialogAccepted": True},
                },
            }
        ),
        {
            "hasCompletedOnboarding": True,
            "projects": {"/repo": {"hasTrustDialogAccepted": True}},
        },
    )
    gemini = compose_startup_config(
        "gemini-cli",
        json.dumps({"mcpServers": {"issues": {"command": "issue-mcp"}}}),
        {"security": {"auth": {"selectedType": "gemini-api-key"}}},
    )

    assert MANAGED_MARKER in restarted
    assert 'model = "GigaChat-2-Max"' in restarted
    assert "ISSUE_TOKEN" not in codex
    assert "TOKEN" not in codex
    assert warnings == (
        "issues: secret reference TOKEN was not copied; use an explicit secret flow",
    )
    assert json.loads(claude)["mcpServers"]["issues"]["env"] == {"MODE": "read"}
    assert json.loads(claude)["hasCompletedOnboarding"] is True
    assert json.loads(claude)["projects"] == {
        "/other": {"hasTrustDialogAccepted": True},
        "/repo": {
            "allowedTools": ["Read"],
            "hasTrustDialogAccepted": True,
        },
    }
    assert json.loads(gemini)["mcpServers"]["issues"]["command"] == "issue-mcp"


@pytest.mark.parametrize("harness_id", ["codex-cli", "claude-code", "gemini-cli"])
def test_managed_service_previews_applies_and_rolls_back(tmp_path, harness_id):
    service = ManagedMCPConfigService(tmp_path / "data")
    descriptor = _stdio_descriptor(harnesses=(harness_id,))
    plan = service.preview(harness_id, "proj_abc123", (descriptor,))

    assert plan.changed is True
    assert "issue-mcp" in plan.diff
    result = service.apply(
        harness_id,
        "proj_abc123",
        (descriptor,),
        expected_hash=plan.current_hash,
    )
    path = service.managed_home(harness_id, "proj_abc123")
    assert result.server_ids == ("issues",)
    assert (path / ".gpt2giga-mcp-owner.json").exists()
    assert service.preview(harness_id, "proj_abc123", (descriptor,)).changed is False

    rolled_back = service.rollback(harness_id, "proj_abc123")

    assert rolled_back.rolled_back is True
    assert not (path / ".gpt2giga-mcp-owner.json").exists()


def test_managed_service_rejects_active_home_stale_preview_and_external_edit(tmp_path):
    data_dir = tmp_path / "data"
    active = False
    service = ManagedMCPConfigService(data_dir, home_active=lambda _home: active)
    descriptor = _stdio_descriptor()
    plan = service.preview("codex-cli", "proj_abc123", (descriptor,))
    home = service.managed_home("codex-cli", "proj_abc123")
    home.mkdir(parents=True)
    (home / "config.toml").write_text("changed", encoding="utf-8")

    with pytest.raises(ManagedConfigConflictError, match="changed after preview"):
        service.apply(
            "codex-cli",
            "proj_abc123",
            (descriptor,),
            expected_hash=plan.current_hash,
        )

    fresh = service.preview("codex-cli", "proj_abc123", (descriptor,))
    active = True
    with pytest.raises(ManagedConfigConflictError, match="native process"):
        service.apply(
            "codex-cli",
            "proj_abc123",
            (descriptor,),
            expected_hash=fresh.current_hash,
        )
    active = False
    service.apply(
        "codex-cli",
        "proj_abc123",
        (descriptor,),
        expected_hash=fresh.current_hash,
    )
    (home / "config.toml").write_text("external edit", encoding="utf-8")
    with pytest.raises(ManagedConfigOwnershipError, match="outside gpt2giga"):
        service.rollback("codex-cli", "proj_abc123")


def test_managed_config_api_requires_trust_and_expected_hash(tmp_path):
    config_path = tmp_path / ".giga" / "harness.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[tools.issues]
enabled = true
kind = "mcp"
transport = "stdio"
command = "issue-mcp"
trusted = true
""",
        encoding="utf-8",
    )
    data_dir = tmp_path / "data"
    client = TestClient(create_app(HarnessConfig(data_dir=str(data_dir))))
    payload = {"workspace": str(tmp_path), "harness_id": "codex-cli"}

    preview = client.post("/api/tool-config/preview", json=payload)
    applied = client.post(
        "/api/tool-config/apply",
        json={**payload, "expected_hash": preview.json()["plan"]["current_hash"]},
    )
    rolled_back = client.post("/api/tool-config/rollback", json=payload)

    assert preview.status_code == 200
    assert preview.json()["enforcement"] == "delegated_to_cli_sandbox"
    assert applied.status_code == 200
    assert applied.json()["provenance"]["server_ids"] == ["issues"]
    assert rolled_back.status_code == 200
    assert rolled_back.json()["provenance"]["rolled_back"] is True


@pytest.mark.parametrize("harness_id", ["codex-cli", "claude-code", "gemini-cli"])
def test_headless_snapshot_is_immutable_and_resolves_secrets_only_in_temp_home(
    tmp_path,
    harness_id,
):
    data_dir = tmp_path / "data"
    store = HeadlessManagedMCPSnapshotStore(data_dir)
    snapshot = store.create(
        project_id="proj_abc123",
        harness_id=harness_id,
        descriptors=(_stdio_descriptor(harnesses=(harness_id,)),),
        server_ids=("issues",),
    )
    snapshot_path = store.root / f"{snapshot.snapshot_id}.json"
    stored = snapshot_path.read_text(encoding="utf-8")

    assert snapshot.public_ref()["marker"] == HEADLESS_SNAPSHOT_MARKER
    assert "runtime-secret" not in stored
    assert "ISSUE_TOKEN" in stored
    assert "descriptors" not in snapshot.public_ref()

    home = tmp_path / "temporary-home"
    if harness_id == "codex-cli":
        startup = 'model = "GigaChat"\n'
    elif harness_id == "claude-code":
        startup = {"hasCompletedOnboarding": True}
    else:
        startup = {"security": {"auth": {"selectedType": "gemini-api-key"}}}
    write_startup_config(harness_id, home, startup)
    binding = materialize_headless_mcp_snapshot(
        harness_id,
        home,
        snapshot.public_ref(),
        data_dir=data_dir,
        resolver=EnvironmentSecretResolver({"ISSUE_TOKEN": "runtime-secret"}),
    )
    config_path = {
        "codex-cli": home / "config.toml",
        "claude-code": home / ".claude.json",
        "gemini-cli": home / ".gemini" / "settings.json",
    }[harness_id]
    active = config_path.read_text(encoding="utf-8")

    assert binding is not None
    assert binding["snapshot_id"] == snapshot.snapshot_id
    assert binding["active_home"] == "temporary"
    assert "runtime-secret" in active
    assert "issue-mcp" in active
    assert "runtime-secret" not in json.dumps(binding)
    if harness_id == "codex-cli":
        assert 'model = "GigaChat"' in active
    elif harness_id == "claude-code":
        assert json.loads(active)["hasCompletedOnboarding"] is True
    else:
        assert json.loads(active)["security"]["auth"]["selectedType"] == (
            "gemini-api-key"
        )


def test_headless_snapshot_rejects_untrusted_incompatible_and_tampered_records(
    tmp_path,
):
    store = HeadlessManagedMCPSnapshotStore(tmp_path / "data")
    with pytest.raises(ValueError, match="not trusted"):
        store.create(
            project_id="proj_abc123",
            harness_id="codex-cli",
            descriptors=(_stdio_descriptor(trusted=False),),
            server_ids=("issues",),
        )
    with pytest.raises(ValueError, match="incompatible"):
        store.create(
            project_id="proj_abc123",
            harness_id="codex-cli",
            descriptors=(_stdio_descriptor(harnesses=("claude-code",)),),
            server_ids=("issues",),
        )

    snapshot = store.create(
        project_id="proj_abc123",
        harness_id="codex-cli",
        descriptors=(_stdio_descriptor(harnesses=("codex-cli",)),),
        server_ids=("issues",),
    )
    path = store.root / f"{snapshot.snapshot_id}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["descriptors"][0]["command"] = "changed-after-preview"
    path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ValueError, match="integrity check failed"):
        store.load(snapshot.public_ref())
