from gpt2giga.core.config.control_plane import (
    apply_control_plane_overrides,
    get_control_plane_bootstrap_token_file,
    get_control_plane_file,
    has_persisted_control_plane,
    load_bootstrap_token,
    load_control_plane_overrides,
    persist_control_plane_config,
)
from gpt2giga.core.config.settings import ProxyConfig, ProxySettings


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
            api_key="persisted-secret",
            enable_reasoning=True,
        ),
        gigachat={"credentials": "persisted-creds", "model": "GigaChat-Max"},
    )
    persist_control_plane_config(persisted)

    runtime = ProxyConfig(proxy=ProxySettings(mode="DEV"))
    merged = apply_control_plane_overrides(runtime)

    assert merged.proxy_settings.gigachat_api_mode == "v2"
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
