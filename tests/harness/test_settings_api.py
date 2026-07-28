import json
import stat

from fastapi.testclient import TestClient
import pytest

from gpt2giga_harness import proxy
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.provider_profiles import ProviderProtocol
from gpt2giga_harness.provider_registry import ProviderProbeResponse
from gpt2giga_harness.provider_settings import ProviderSettingsService
from gpt2giga_harness.secrets import SecretReference, SecretReferenceKind
from gpt2giga_harness.sessions import InMemoryHarnessSessionStore
from gpt2giga_harness.settings import (
    SecretReferenceSettingsStore,
    SettingsConflictError,
)
from gpt2giga_harness.ui.app import create_app
from gpt2giga_harness.ui.routers import settings as settings_router


def test_settings_read_model_is_bounded_and_never_exposes_secrets(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "provider-secret")
    client = _client(
        tmp_path,
        api_key="provider-secret",
        proxy_url="http://operator:proxy-secret@127.0.0.1:8090/?token=hidden",
    )

    response = client.get("/api/settings", params={"workspace": str(tmp_path)})

    assert response.status_code == 200
    body = response.json()
    assert body["runtime"]["proxy_url"] == "http://127.0.0.1:8090/"
    assert body["provider"] == {
        "configured": False,
        "count": 0,
        "source": "unconfigured",
        "health": "not_checked",
        "secret_readable": False,
        "change_effect": "new_session_required",
        "registry_path_readable": False,
    }
    assert body["workspace"]["name"] == tmp_path.name
    assert body["routes"]["default_api_mode_source"] == "built_in"
    assert body["routes"]["default_model_source"] == "built_in"
    assert body["harness_defaults"]["default_model"] == "GigaChat-3.5-432B-A28B"
    assert body["harness_defaults"]["default_title_model"] == "GigaChat-3-Lightning"
    assert body["harness_defaults"]["execution_transport"] == "native_structured"
    assert "root" not in body["workspace"]
    assert body["diagnostics"]["content_free"] is True
    serialized = str(body)
    assert "provider-secret" not in serialized
    assert "proxy-secret" not in serialized
    assert "token=hidden" not in serialized


def test_guided_doctor_api_is_content_free_and_offline(
    tmp_path,
    monkeypatch,
):
    def unexpected_online_probe(*_args, **_kwargs):
        raise AssertionError("Web doctor must not perform online probes")

    monkeypatch.setattr(proxy, "health_check", unexpected_online_probe)
    monkeypatch.setattr(proxy, "discover_models", unexpected_online_probe)
    monkeypatch.setattr(proxy, "probe_json_route", unexpected_online_probe)
    monkeypatch.setattr(
        proxy,
        "sidecar_preflight",
        lambda _context: proxy.SidecarPreflight(ok=True, reason="ready"),
    )
    client = _client(tmp_path)
    assert client.get("/cockpit-v2/settings").status_code == 200

    response = client.get("/api/doctor", params={"workspace": str(tmp_path)})

    assert response.status_code == 200
    body = response.json()
    by_id = {check["id"]: check for check in body["checks"]}
    assert body["schema_version"] == 2
    assert body["guided"]["online_checks"] is False
    assert body["privacy"]["content_free"] is True
    assert body["privacy"]["raw_traffic_collected"] is False
    assert body["privacy"]["private_file_content_collected"] is False
    assert by_id["ui-identity"]["status"] == "ready"
    assert by_id["proxy-health"]["evidence"]["network_contacted"] is False
    assert {
        "durable-worker",
        "git-readiness",
        "github-cli",
        "scoped-network",
        "mcp-sources",
        "skills-sources",
        "plugin-sources",
    }.issubset(by_id)
    serialized = json.dumps(body)
    assert str(tmp_path) not in serialized
    assert "giga-skills-catalog-proxy" in serialized
    assert "request-scoped OIDC token" in serialized


def test_guided_doctor_api_does_not_forward_browser_workspace_paths(
    tmp_path,
    monkeypatch,
):
    captured = {}

    def fake_build_doctor_report(
        config,
        registry,
        *,
        workspace,
        online_checks,
        ui_identity,
    ):
        captured.update(
            {
                "workspace": workspace,
                "online_checks": online_checks,
                "ui_identity": ui_identity,
            }
        )
        return {"schema_version": 2, "checks": []}

    monkeypatch.setattr(
        settings_router,
        "build_doctor_report",
        fake_build_doctor_report,
    )
    client = _client(tmp_path)

    response = client.get(
        "/api/doctor",
        params={"workspace": str(tmp_path / "untrusted-workspace")},
    )

    assert response.status_code == 200
    assert captured["workspace"] is None
    assert captured["online_checks"] is False
    assert captured["ui_identity"]["local"] is True


def test_provider_settings_api_crud_is_reference_only_and_optimistic(tmp_path):
    canary = "n3-06-provider-secret-canary"
    client = _client(tmp_path)
    created = client.post(
        "/api/providers",
        json={
            "id": "team-openai",
            "display_name": "Team OpenAI",
            "protocol": "openai_compatible",
            "dialect": "openai-responses-v1",
            "base_url": "https://models.example.test",
            "route_prefix": "/v1",
            "authentication": {
                "ownership": "secret_reference",
                "reference_kind": "environment",
                "reference_name": "TEAM_OPENAI_KEY",
            },
            "default_models": {
                "coding": "coding-model",
                "title": "title-model",
            },
            "enabled": True,
            "offline": False,
        },
    )

    assert created.status_code == 200
    provider = created.json()["provider"]
    assert provider["source"] == "user"
    assert provider["authentication"] == {
        "ownership": "secret_reference",
        "reference_kind": "environment",
        "reference_name": "TEAM_OPENAI_KEY",
        "service": None,
        "account": None,
        "value_readable": False,
        "explanation": (
            "The backend resolves the environment reference only at the owning "
            "probe or execution boundary; its value is never stored or returned."
        ),
    }
    assert {route["purpose"] for route in provider["routes"]} == {
        "coding",
        "title",
    }
    assert provider["effects"]["structured_sessions"] == (
        "fork_or_new_session_required"
    )
    serialized = str(created.json())
    assert canary not in serialized
    assert "filesystem" not in serialized.lower()

    updated = client.patch(
        "/api/providers/team-openai",
        json={
            "expected_revision": provider["registry_revision"],
            "display_name": "Team Models",
            "default_models": {"coding": "coding-model-v2"},
        },
    )
    assert updated.status_code == 200
    read_back = client.get("/api/providers/team-openai").json()
    assert read_back == updated.json()["provider"]
    assert read_back["display_name"] == "Team Models"
    assert read_back["default_models"] == {
        "coding": "coding-model-v2",
        "title": "title-model",
    }

    stale = client.patch(
        "/api/providers/team-openai",
        json={
            "expected_revision": provider["registry_revision"],
            "display_name": "Stale write",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "provider_conflict"
    stored = tmp_path / "data" / "providers" / "user.json"
    assert "TEAM_OPENAI_KEY" in stored.read_text(encoding="utf-8")
    assert canary not in stored.read_text(encoding="utf-8")


def test_provider_settings_api_returns_field_errors_before_persistence(tmp_path):
    client = _client(tmp_path)

    response = client.post(
        "/api/providers",
        json={
            "id": "invalid-provider",
            "display_name": "Invalid",
            "protocol": "openai_compatible",
            "dialect": "gemini-generate-content-v1beta",
            "base_url": "https://user:secret@example.test",
            "authentication": {
                "ownership": "secret_reference",
                "reference_kind": "environment",
            },
            "default_models": {"unknown": "model"},
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_provider"
    assert set(detail["field_errors"]) >= {
        "dialect",
        "authentication.reference_name",
        "default_models.unknown",
    }
    assert not (tmp_path / "data" / "providers" / "user.json").exists()


def test_provider_settings_api_probe_is_explicit_bounded_and_content_free(tmp_path):
    service = ProviderSettingsService(
        str(tmp_path / "data"),
        probe_backends={ProviderProtocol.OPENAI_COMPATIBLE: _ProbeBackend()},
    )
    client = _client(tmp_path, provider_settings_service=service)
    created = client.post(
        "/api/providers",
        json={
            "id": "offline-fixture",
            "display_name": "Offline fixture",
            "protocol": "openai_compatible",
            "dialect": "openai-chat-completions-v1",
            "base_url": "https://fixture.invalid",
            "authentication": {"ownership": "none"},
            "default_models": {"coding": "configured-model"},
        },
    )
    assert created.status_code == 200
    assert service.health_store.load("offline-fixture") is None

    tested = client.post("/api/providers/offline-fixture/test")
    assert tested.status_code == 200
    assert tested.json()["health"]["status"] == "ready"
    assert tested.json()["health"]["discovery_status"] == "not_requested"

    discovered = client.post("/api/providers/offline-fixture/discover")
    assert discovered.status_code == 200
    assert discovered.json()["health"]["models"] == [
        {"model": "configured-model", "source": "configured_fallback"},
        {"model": "discovered-model", "source": "discovered"},
    ]
    assert "fixture-response-canary" not in str(discovered.json())


def test_settings_defaults_persist_read_back_and_seed_new_sessions(tmp_path):
    client = _client(tmp_path)
    revision = client.get("/api/settings", params={"workspace": str(tmp_path)}).json()[
        "revision"
    ]

    saved = client.patch(
        "/api/settings/defaults",
        json={
            "expected_revision": revision,
            "defaults": {
                "default_harness_id": "direct-chat",
                "default_model": "GigaChat",
                "default_title_model": "GigaChat-3-Lightning",
                "default_api_mode": "v2",
                "mode": "act",
                "execution_transport": "one_shot",
                "invocation_mode": "headless",
                "workspace_policy": "current",
                "permission_profile": "review_every_action",
                "stream": False,
            },
        },
    )

    assert saved.status_code == 200
    body = saved.json()
    assert body["saved"] is True
    assert body["defaults"]["default_harness_id"] == "direct-chat"
    assert body["defaults"]["default_title_model"] == "GigaChat-3-Lightning"
    assert body["defaults"]["execution_transport"] == "one_shot"
    assert body["defaults"]["task_intent"] == "ask"
    assert body["defaults"]["authority"] == "read_only"
    assert body["sources"]["default_harness_id"] == "harness_settings"
    assert body["change_effect"] == "new_runs"
    stored = tmp_path / "data" / "settings" / "defaults.json"
    assert stored.is_file()
    assert "api_key" not in stored.read_text(encoding="utf-8")

    read_back = client.get("/api/settings", params={"workspace": str(tmp_path)}).json()
    assert read_back["harness_defaults"]["permission_profile"] == (
        "review_every_action"
    )
    assert read_back["routes"]["default_model"] == "GigaChat"
    assert read_back["harness_defaults"]["default_title_model"] == (
        "GigaChat-3-Lightning"
    )
    assert read_back["harness_defaults"]["compatibility"]["mode"]["warning"] == (
        "legacy_mode_unmapped_read_only"
    )

    created = client.post("/api/sessions", json={})
    assert created.status_code == 200
    session = created.json()["session"]
    assert session["default_harness_id"] == "direct-chat"
    assert session["default_model"] == "GigaChat"
    assert session["default_api_mode"] == "v2"
    assert session["default_mode"] == "plan"
    assert session["metadata"]["workbench_selection"] == {
        "schema_version": 1,
        "kind": "direct_chat",
        "intent": "ask",
        "authority": "read_only",
        "input_source": "product",
        "compatibility_warning": None,
    }


def test_settings_reject_invalid_harness_invocation_before_persistence(tmp_path):
    client = _client(tmp_path)

    response = client.patch(
        "/api/settings/defaults",
        json={
            "defaults": {
                "default_harness_id": "direct-chat",
                "invocation_mode": "native",
            }
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["field_errors"] == {
        "invocation_mode": "selected harness does not support native sessions"
    }
    assert not (tmp_path / "data" / "settings" / "defaults.json").exists()


def test_settings_reject_native_terminal_for_non_native_harness(tmp_path):
    client = _client(tmp_path)

    response = client.patch(
        "/api/settings/defaults",
        json={
            "defaults": {
                "default_harness_id": "direct-chat",
                "execution_transport": "native_terminal",
                "invocation_mode": "native",
            }
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["field_errors"] == {
        "execution_transport": (
            "selected harness does not support native terminal sessions"
        ),
        "invocation_mode": "selected harness does not support native sessions",
    }


def test_settings_reject_invalid_title_model_before_persistence(tmp_path):
    client = _client(tmp_path)

    response = client.patch(
        "/api/settings/defaults",
        json={"defaults": {"default_title_model": "invalid\nmodel"}},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["field_errors"] == {
        "default_title_model": "expected a non-empty model name up to 200 characters"
    }
    assert not (tmp_path / "data" / "settings" / "defaults.json").exists()


def test_settings_do_not_persist_environment_owned_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_HARNESS_DEFAULT_MODEL", "EnvironmentModel")
    client = _client(tmp_path, default_model="EnvironmentModel")

    response = client.patch(
        "/api/settings/defaults",
        json={"defaults": {"default_model": "StoredModel"}},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "environment_owned"
    assert "default_model" in detail["field_errors"]
    assert "EnvironmentModel" not in str(detail)
    assert not (tmp_path / "data" / "settings" / "defaults.json").exists()


def test_settings_reject_stale_revision_without_overwriting(tmp_path):
    client = _client(tmp_path)
    original = client.get("/api/settings", params={"workspace": str(tmp_path)}).json()[
        "revision"
    ]
    first = client.patch(
        "/api/settings/defaults",
        json={
            "expected_revision": original,
            "defaults": {"workspace_policy": "current"},
        },
    )
    assert first.status_code == 200

    stale = client.patch(
        "/api/settings/defaults",
        json={
            "expected_revision": original,
            "defaults": {"workspace_policy": "worktree"},
        },
    )

    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "revision_conflict"
    read_back = client.get("/api/settings", params={"workspace": str(tmp_path)}).json()
    assert read_back["harness_defaults"]["workspace_policy"] == "current"


def test_secret_reference_settings_round_trip_references_only(tmp_path):
    canary = "n1-02-settings-secret-canary"
    store = SecretReferenceSettingsStore(tmp_path / "data")
    initial = store.load()
    reference = SecretReference(
        SecretReferenceKind.ENVIRONMENT,
        "PROVIDER_TOKEN",
        cache_ttl_seconds=30,
    )

    saved = store.save(
        {"provider.default": reference},
        expected_revision=initial.revision,
    )

    assert saved.references == {"provider.default": reference}
    assert saved.revision != initial.revision
    serialized = store.path.read_text(encoding="utf-8")
    payload = json.loads(serialized)
    assert payload["schema_version"] == 1
    assert payload["references"]["provider.default"]["name"] == "PROVIDER_TOKEN"
    assert "value" not in serialized
    assert canary not in serialized
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600

    with pytest.raises(SettingsConflictError, match="revision changed"):
        store.save({}, expected_revision=initial.revision)
    with pytest.raises(ValueError, match="test secret references"):
        store.save(
            {
                "test.only": SecretReference(
                    SecretReferenceKind.TEST,
                    "TEST_TOKEN",
                )
            }
        )


class _ProbeBackend:
    def check(self, request):
        assert request.timeout_seconds <= 30
        return ProviderProbeResponse(
            models=("discovered-model",) if request.discover_models else (),
        )


def _client(data_dir, *, provider_settings_service=None, **overrides) -> TestClient:
    config = HarnessConfig(data_dir=str(data_dir / "data"), **overrides)
    app = create_app(
        config,
        registry=create_default_registry(include_entry_points=False),
        store=InMemoryHarnessSessionStore(),
        provider_settings_service=provider_settings_service,
    )
    return TestClient(app)
