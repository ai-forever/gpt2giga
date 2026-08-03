"""Startup loading and preflight contracts for provider profiles."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gpt2giga.providers.profiles import (
    CONFIG_ENV_NAME,
    MAX_PROFILE_CONFIG_BYTES,
    ProviderPolicyCatalog,
    ProviderProfileError,
    load_provider_profiles,
    select_provider_config_path,
)


POLICIES = ProviderPolicyCatalog(
    network_policy_refs=frozenset(
        {"public-anthropic", "public-gigachat", "loopback-development"}
    ),
    tls_policy_refs=frozenset({"system-default"}),
)
SECRET = "fixture-credential-value-never-render"


def _payload(**profile_overrides: object) -> dict[str, object]:
    profile: dict[str, object] = {
        "profile_id": "anthropic-main",
        "provider_kind": "anthropic",
        "base_url": "https://api.anthropic.com",
        "credential_env": "ANTHROPIC_API_KEY",
        "network_policy_ref": "public-anthropic",
        "tls_policy_ref": "system-default",
        "models": [
            {
                "public_alias": "anthropic/opus",
                "upstream_model": "claude-opus-exact",
                "capability_profile": "anthropic-opus-v1",
                "support_status": "technical_preview",
            }
        ],
    }
    profile.update(profile_overrides)
    return {
        "schema_version": "gpt2giga.provider-profiles.v1",
        "profiles": [profile],
    }


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_config_path_precedence_is_exact_and_conflicts_fail() -> None:
    cli = "/tmp/provider-config.json"
    expected = Path(cli).resolve()
    assert select_provider_config_path(None, environ={}) is None
    assert select_provider_config_path(None, environ={CONFIG_ENV_NAME: cli}) == expected
    assert select_provider_config_path(cli, environ={CONFIG_ENV_NAME: cli}) == expected

    with pytest.raises(ProviderProfileError) as raised:
        select_provider_config_path(
            cli,
            environ={CONFIG_ENV_NAME: "/tmp/different.json"},
        )
    assert raised.value.code == "invalid_profile_schema"


def test_json_profile_loads_once_and_keeps_credentials_redacted(tmp_path: Path) -> None:
    path = _write_json(tmp_path / "profiles.json", _payload())
    loaded = load_provider_profiles(
        path,
        environ={"ANTHROPIC_API_KEY": SECRET},
        policies=POLICIES,
    )

    assert loaded.immutable is True
    assert loaded.schema_version == "gpt2giga.provider-profiles.v1"
    assert loaded.credential_for("anthropic-main") == SECRET
    assert loaded.redacted()["config_revision"] == loaded.config.revision
    assert SECRET not in repr(loaded)
    assert "ANTHROPIC_API_KEY" not in repr(loaded)
    assert SECRET not in json.dumps(loaded.redacted())


def test_dynamic_gigachat_profile_resolves_credential_without_static_aliases(
    tmp_path: Path,
) -> None:
    payload = _payload(
        profile_id="gigachat-main",
        provider_kind="gigachat",
        credential_env="GIGACHAT_CREDENTIALS",
        network_policy_ref="public-gigachat",
        model_inventory="dynamic",
        models=[],
    )
    payload["schema_version"] = "gpt2giga.provider-profiles.v2"
    path = _write_json(tmp_path / "profiles.json", payload)

    loaded = load_provider_profiles(
        path,
        environ={"GIGACHAT_CREDENTIALS": SECRET},
        policies=POLICIES,
    )

    profile = loaded.config.profiles[0]
    assert profile.model_inventory.value == "dynamic"
    assert profile.models == ()
    assert loaded.credential_for("gigachat-main") == SECRET


def test_yaml_uses_safe_loading_and_rejects_duplicate_keys(tmp_path: Path) -> None:
    yaml_path = tmp_path / "profiles.yaml"
    yaml_path.write_text(
        """\
schema_version: gpt2giga.provider-profiles.v1
profiles:
  - profile_id: anthropic-main
    provider_kind: anthropic
    base_url: https://api.anthropic.com
    credential_env: ANTHROPIC_API_KEY
    network_policy_ref: public-anthropic
    tls_policy_ref: system-default
    models:
      - public_alias: anthropic/opus
        upstream_model: claude-opus-exact
        capability_profile: anthropic-opus-v1
        support_status: technical_preview
""",
        encoding="utf-8",
    )
    loaded = load_provider_profiles(
        yaml_path,
        environ={"ANTHROPIC_API_KEY": SECRET},
        policies=POLICIES,
    )
    assert loaded.config.profiles[0].profile_id == "anthropic-main"

    yaml_path.write_text("schema_version: one\nschema_version: two\n", encoding="utf-8")
    with pytest.raises(ProviderProfileError) as raised:
        load_provider_profiles(yaml_path, environ={}, policies=POLICIES)
    assert raised.value.code == "invalid_profile_schema"

    yaml_path.write_text(
        "payload: !!python/object/apply:os.system ['forbidden']\n",
        encoding="utf-8",
    )
    with pytest.raises(ProviderProfileError) as raised:
        load_provider_profiles(yaml_path, environ={}, policies=POLICIES)
    assert raised.value.code == "invalid_profile_schema"


@pytest.mark.parametrize(
    ("profile_overrides", "expected_code"),
    [
        ({"base_url": "http://provider.invalid"}, "invalid_destination"),
        ({"base_url": "https://127.0.0.1"}, "invalid_destination"),
        ({"base_url": "https://169.254.169.254"}, "invalid_destination"),
        ({"network_policy_ref": "unknown"}, "invalid_policy_reference"),
    ],
)
def test_invalid_destination_and_policy_fail_before_runtime_construction(
    tmp_path: Path,
    profile_overrides: dict[str, object],
    expected_code: str,
) -> None:
    path = _write_json(tmp_path / "profiles.json", _payload(**profile_overrides))
    with pytest.raises(ProviderProfileError) as raised:
        load_provider_profiles(
            path,
            environ={"ANTHROPIC_API_KEY": SECRET},
            policies=POLICIES,
        )
    assert raised.value.code == expected_code
    assert SECRET not in str(raised.value)


def test_explicit_loopback_development_profile_is_the_only_http_exception(
    tmp_path: Path,
) -> None:
    path = _write_json(
        tmp_path / "profiles.json",
        _payload(
            base_url="http://127.0.0.1:8080/v1",
            allow_loopback=True,
            network_policy_ref="loopback-development",
        ),
    )
    loaded = load_provider_profiles(
        path,
        environ={"ANTHROPIC_API_KEY": SECRET},
        policies=POLICIES,
    )
    assert loaded.config.profiles[0].allow_loopback is True


def test_duplicate_alias_missing_credential_and_secret_field_have_stable_errors(
    tmp_path: Path,
) -> None:
    payload = _payload()
    duplicate = json.loads(json.dumps(payload["profiles"][0]))
    duplicate["profile_id"] = "anthropic-second"
    payload["profiles"].append(duplicate)
    path = _write_json(tmp_path / "profiles.json", payload)
    with pytest.raises(ProviderProfileError) as raised:
        load_provider_profiles(
            path,
            environ={"ANTHROPIC_API_KEY": SECRET},
            policies=POLICIES,
        )
    assert raised.value.code == "duplicate_model_alias"

    payload = _payload()
    duplicate = json.loads(json.dumps(payload["profiles"][0]))
    duplicate["models"][0]["public_alias"] = "anthropic/sonnet"
    payload["profiles"].append(duplicate)
    path = _write_json(tmp_path / "profiles.json", payload)
    with pytest.raises(ProviderProfileError) as raised:
        load_provider_profiles(
            path,
            environ={"ANTHROPIC_API_KEY": SECRET},
            policies=POLICIES,
        )
    assert raised.value.code == "duplicate_profile_id"

    path = _write_json(tmp_path / "profiles.json", _payload())
    with pytest.raises(ProviderProfileError) as raised:
        load_provider_profiles(path, environ={}, policies=POLICIES)
    assert raised.value.code == "credential_unavailable"

    path = _write_json(tmp_path / "profiles.json", _payload(api_key=SECRET))
    with pytest.raises(ProviderProfileError) as raised:
        load_provider_profiles(
            path,
            environ={"ANTHROPIC_API_KEY": SECRET},
            policies=POLICIES,
        )
    assert raised.value.code == "invalid_profile_schema"
    assert SECRET not in str(raised.value)
    assert SECRET not in repr(raised.value)


def test_loader_rejects_oversize_and_duplicate_json_without_echoing_input(
    tmp_path: Path,
) -> None:
    path = tmp_path / "profiles.json"
    path.write_bytes(b" " * (MAX_PROFILE_CONFIG_BYTES + 1))
    with pytest.raises(ProviderProfileError) as raised:
        load_provider_profiles(path, environ={}, policies=POLICIES)
    assert raised.value.code == "invalid_profile_schema"

    path.write_text('{"schema_version":"one","schema_version":"two"}', encoding="utf-8")
    with pytest.raises(ProviderProfileError) as raised:
        load_provider_profiles(path, environ={}, policies=POLICIES)
    assert raised.value.code == "invalid_profile_schema"
