import json

from gpt2giga.core.config._control_plane.bootstrap import (
    claim_admin_instance as internal_claim_admin_instance,
)
from gpt2giga.core.config._control_plane.paths import (
    get_control_plane_file as internal_get_control_plane_file,
)
from gpt2giga.core.config._control_plane.payloads import (
    persist_control_plane_config as internal_persist_control_plane_config,
)
from gpt2giga.core.config.control_plane import (
    apply_control_plane_overrides,
    build_proxy_config_from_control_plane_payload,
    claim_admin_instance,
    get_control_plane_bootstrap_token_file,
    get_control_plane_bootstrap_state_file,
    get_control_plane_file,
    has_persisted_control_plane,
    is_admin_instance_claimed,
    list_control_plane_revisions,
    load_bootstrap_token,
    load_bootstrap_state,
    load_control_plane_overrides,
    load_control_plane_revision_payload,
    persist_control_plane_config,
)
from gpt2giga.core.config.settings import ProxyConfig, ProxySettings


def test_control_plane_public_imports_reexport_internal_helpers():
    assert claim_admin_instance is internal_claim_admin_instance
    assert get_control_plane_file is internal_get_control_plane_file
    assert persist_control_plane_config is internal_persist_control_plane_config


def test_control_plane_roundtrip_encrypts_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    config = ProxyConfig(
        proxy=ProxySettings(
            mode="DEV",
            api_key="global-secret",
            scoped_api_keys=[
                {
                    "name": "sdk-openai",
                    "key": "scoped-secret",
                    "providers": ["openai"],
                }
            ],
        ),
        gigachat={
            "credentials": "gigachat-credentials",
            "model": "GigaChat",
            "scope": "GIGACHAT_API_PERS",
        },
    )

    persist_control_plane_config(config)

    assert has_persisted_control_plane() is True
    raw = get_control_plane_file().read_text(encoding="utf-8")
    assert "global-secret" not in raw
    assert "scoped-secret" not in raw
    assert "gigachat-credentials" not in raw

    proxy_overrides, gigachat_overrides = load_control_plane_overrides()
    assert proxy_overrides["api_key"] == "global-secret"
    assert proxy_overrides["scoped_api_keys"][0]["name"] == "sdk-openai"
    assert proxy_overrides["scoped_api_keys"][0]["key"] == "scoped-secret"
    assert gigachat_overrides["credentials"] == "gigachat-credentials"


def test_apply_control_plane_overrides_replaces_runtime_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    persisted = ProxyConfig(
        proxy=ProxySettings(
            mode="DEV",
            gigachat_api_mode="v2",
            gigachat_responses_api_mode="v1",
            api_key="persisted-secret",
            enable_reasoning=True,
        ),
        gigachat={"credentials": "persisted-creds", "model": "GigaChat-Max"},
    )
    persist_control_plane_config(persisted)

    runtime = ProxyConfig(proxy=ProxySettings(mode="DEV"))
    merged = apply_control_plane_overrides(runtime)

    assert merged.proxy_settings.gigachat_api_mode == "v2"
    assert merged.proxy_settings.gigachat_responses_api_mode == "v1"
    assert merged.proxy_settings.responses_backend_mode == "v1"
    assert merged.proxy_settings.api_key == "persisted-secret"
    assert merged.proxy_settings.enable_reasoning is True
    assert merged.gigachat_settings.credentials.get_secret_value() == "persisted-creds"
    assert merged.gigachat_settings.model == "GigaChat-Max"


def test_bootstrap_token_is_created_and_cleared_on_completed_setup(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))

    token = load_bootstrap_token(create=True)

    assert token
    assert get_control_plane_bootstrap_token_file().exists()

    persist_control_plane_config(
        ProxyConfig(
            proxy=ProxySettings(
                mode="PROD",
                enable_api_key_auth=True,
                api_key="global-secret",
            ),
            gigachat={
                "credentials": "gigachat-credentials",
                "scope": "GIGACHAT_API_PERS",
            },
        )
    )

    assert get_control_plane_bootstrap_token_file().exists() is False


def test_claim_admin_instance_persists_first_operator_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))

    claimed = claim_admin_instance(
        operator_label="Local operator",
        claimed_via="admin_setup",
        claimed_from="127.0.0.1",
    )

    assert claimed["claimed_at"] is not None
    assert claimed["operator_label"] == "Local operator"
    assert get_control_plane_bootstrap_state_file().exists() is True
    assert is_admin_instance_claimed() is True

    loaded = load_bootstrap_state()
    assert loaded["operator_label"] == "Local operator"
    assert loaded["claimed_via"] == "admin_setup"
    assert loaded["claimed_from"] == "127.0.0.1"

    duplicate = claim_admin_instance(operator_label="Someone else")
    assert duplicate == loaded


def test_control_plane_revisions_keep_recent_snapshots(tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))

    persist_control_plane_config(
        ProxyConfig(proxy=ProxySettings(mode="DEV", enable_reasoning=False)),
        changed_fields={"enable_reasoning"},
    )
    persist_control_plane_config(
        ProxyConfig(proxy=ProxySettings(mode="DEV", enable_reasoning=True)),
        changed_fields={"enable_reasoning"},
    )

    revisions = list_control_plane_revisions(limit=10)

    assert len(revisions) == 2
    assert revisions[0]["change"]["changed_fields"] == ["enable_reasoning"]
    restored = build_proxy_config_from_control_plane_payload(revisions[0])
    previous = build_proxy_config_from_control_plane_payload(revisions[1])
    assert restored.proxy_settings.enable_reasoning is True
    assert previous.proxy_settings.enable_reasoning is False


def test_load_control_plane_revision_payload_returns_saved_snapshot(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    persist_control_plane_config(
        ProxyConfig(
            proxy=ProxySettings(mode="DEV", api_key="global-secret"),
            gigachat={"credentials": "persisted-creds"},
        ),
        changed_fields={"api_key", "credentials"},
    )

    revision = list_control_plane_revisions(limit=1)[0]
    loaded = load_control_plane_revision_payload(revision["revision_id"])
    restored = build_proxy_config_from_control_plane_payload(loaded)

    assert loaded["revision_id"] == revision["revision_id"]
    assert restored.proxy_settings.api_key == "global-secret"
    assert (
        restored.gigachat_settings.credentials.get_secret_value() == "persisted-creds"
    )


def test_build_proxy_config_from_control_plane_payload_ignores_legacy_unknown_fields():
    payload = {
        "proxy": {
            "mode": "DEV",
            "enable_reasoning": True,
            "enable_images": True,
        },
        "gigachat": {
            "model": "GigaChat-Max",
            "unknown_gigachat_field": "ignored",
        },
        "secrets": {
            "proxy": {},
            "gigachat": {},
        },
    }

    restored = build_proxy_config_from_control_plane_payload(payload)

    assert restored.proxy_settings.mode == "DEV"
    assert restored.proxy_settings.enable_reasoning is True
    assert restored.gigachat_settings.model == "GigaChat-Max"


def test_apply_control_plane_overrides_ignores_unmanaged_payload_fields(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))

    payload = {
        "version": 1,
        "proxy": {
            "mode": "DEV",
            "observability_sinks": ["prometheus"],
            "runtime_store_backend": "memory",
            "runtime_store_namespace": "gpt2giga",
            "enable_telemetry": True,
            "enabled_providers": ["openai", "anthropic", "gemini"],
            "gigachat_api_mode": "v1",
            "pass_model": False,
            "pass_token": False,
        },
        "gigachat": {
            "base_url": "https://gigachat.devices.sberbank.ru/api/v1",
            "auth_url": "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
            "scope": "GIGACHAT_API_PERS",
            "model": None,
            "verify_ssl_certs": True,
            "timeout": 30.0,
        },
        "secrets": {
            "proxy": {},
            "gigachat": {},
        },
        "change": {
            "changed_fields": [
                "enable_telemetry",
                "enabled_providers",
                "gigachat_api_mode",
                "mode",
                "observability_sinks",
                "pass_model",
                "pass_token",
                "runtime_store_backend",
                "runtime_store_namespace",
            ]
        },
        "revision_id": "legacy-revision",
        "updated_at": "2026-04-15T08:08:28.443991Z",
    }

    get_control_plane_file().write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    runtime = ProxyConfig(
        proxy=ProxySettings(
            mode="DEV",
            observability_sinks=["phoenix"],
            enable_telemetry=False,
        ),
        gigachat={
            "credentials": "runtime-creds",
            "model": "GigaChat-2-Max",
            "verify_ssl_certs": False,
        },
    )
    merged = apply_control_plane_overrides(runtime)

    assert merged.gigachat_settings.credentials.get_secret_value() == "runtime-creds"
    assert merged.gigachat_settings.model == "GigaChat-2-Max"
    assert merged.gigachat_settings.verify_ssl_certs is False
    assert merged.proxy_settings.observability_sinks == ["phoenix"]
    assert merged.proxy_settings.enable_telemetry is False


def test_persist_control_plane_config_keeps_managed_gigachat_fields_across_saves(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))

    persist_control_plane_config(
        ProxyConfig(
            proxy=ProxySettings(mode="DEV"),
            gigachat={"credentials": "persisted-creds", "model": "GigaChat-Max"},
        ),
        changed_fields={"credentials", "model"},
    )
    persist_control_plane_config(
        ProxyConfig(
            proxy=ProxySettings(mode="DEV", enable_reasoning=True),
            gigachat={"credentials": "persisted-creds", "model": "GigaChat-Max"},
        ),
        changed_fields={"enable_reasoning"},
    )

    runtime = ProxyConfig(proxy=ProxySettings(mode="DEV"))
    merged = apply_control_plane_overrides(runtime)

    assert merged.proxy_settings.enable_reasoning is True
    assert merged.gigachat_settings.credentials.get_secret_value() == "persisted-creds"
    assert merged.gigachat_settings.model == "GigaChat-Max"


def test_apply_control_plane_overrides_skips_persisted_state_when_disabled(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))

    persist_control_plane_config(
        ProxyConfig(
            proxy=ProxySettings(mode="DEV", api_key="persisted-secret"),
            gigachat={"credentials": "persisted-creds", "model": "GigaChat-Max"},
        )
    )

    runtime = ProxyConfig(
        proxy=ProxySettings(mode="DEV", disable_persist=True, api_key="env-secret"),
        gigachat={"credentials": "env-creds", "model": "GigaChat-2-Max"},
    )
    merged = apply_control_plane_overrides(runtime)

    assert merged.proxy_settings.api_key == "env-secret"
    assert merged.gigachat_settings.credentials.get_secret_value() == "env-creds"
    assert merged.gigachat_settings.model == "GigaChat-2-Max"
