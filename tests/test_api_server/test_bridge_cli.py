"""Installed CLI contracts for the 0.3 bridge supervisor integration."""

from __future__ import annotations

import json

import pytest

from gpt2giga import api_server
from gpt2giga.models.config import ProxyConfig


def test_inspect_config_prints_one_redacted_manifest_without_starting_server(
    monkeypatch,
    capsys,
) -> None:
    config = ProxyConfig(inspect_config=True)
    monkeypatch.setattr(api_server, "load_app_config", lambda: config)
    monkeypatch.setattr(
        api_server.uvicorn,
        "run",
        lambda *_args, **_kwargs: pytest.fail("inspect must not bind a socket"),
    )

    api_server.run()

    captured = capsys.readouterr()
    manifest = json.loads(captured.out)
    assert captured.err == ""
    assert manifest["schema_version"] == "gpt2giga.inspect.v1"
    assert manifest["valid"] is True
    assert manifest["profiles"][0]["credential_env"] == "GIGACHAT_CREDENTIALS"
    assert "credential_value" not in captured.out.lower()


def test_inspect_config_failure_is_bounded_json_and_exit_two(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    profile_path = tmp_path / "providers.json"
    profile_path.write_text("{}", encoding="utf-8")
    config = ProxyConfig(config=str(profile_path), inspect_config=True)
    monkeypatch.setattr(api_server, "load_app_config", lambda: config)

    with pytest.raises(SystemExit) as raised:
        api_server.run()

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert raised.value.code == 2
    assert captured.err == ""
    assert payload == {
        "schema_version": "gpt2giga.error.v1",
        "error": {
            "code": "invalid_profile_schema",
            "message": "Provider profile config does not match the required schema.",
            "details": [],
        },
    }


def test_proxy_config_accepts_documented_inspect_flag() -> None:
    config = ProxyConfig(_cli_parse_args=["--inspect-config"])

    assert config.inspect_config is True
