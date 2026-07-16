from pathlib import Path

import pytest

from gpt2giga_harness.executables import (
    ExecutableResolver,
    UserHarnessConfigError,
    load_user_executables,
    set_user_executable,
    unset_user_executable,
)
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.types import HarnessContext, HarnessRequest


def test_resolver_prefers_user_config_over_path(tmp_path, monkeypatch):
    configured = _executable(tmp_path / "custom" / "codex")
    fallback = _executable(tmp_path / "path" / "codex")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[executables]\n"codex-cli" = "{configured}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PATH", str(fallback.parent))

    resolution = ExecutableResolver.from_user_config(config_path).resolve(
        "codex-cli",
        "codex",
    )

    assert resolution.executable == str(configured)
    assert resolution.configured == str(configured)
    assert resolution.source == "user_config"


def test_resolver_falls_back_to_path_when_override_is_absent(tmp_path, monkeypatch):
    executable = _executable(tmp_path / "bin" / "claude")
    monkeypatch.setenv("PATH", str(executable.parent))

    resolution = ExecutableResolver.from_user_config(tmp_path / "missing.toml").resolve(
        "claude-code", "claude"
    )

    assert resolution.executable == str(executable)
    assert resolution.source == "path"
    assert resolution.configured is None


@pytest.mark.parametrize(
    ("document", "expected"),
    (
        ('[executables]\n"codex-cli" = "relative/codex"\n', "absolute path"),
        ('[executables]\n"codex-cli" = 42\n', "non-empty string"),
    ),
)
def test_resolver_reports_invalid_override(tmp_path, document, expected):
    config_path = tmp_path / "config.toml"
    config_path.write_text(document, encoding="utf-8")

    resolution = ExecutableResolver.from_user_config(config_path).resolve(
        "codex-cli",
        "codex",
    )

    assert resolution.executable is None
    assert resolution.source == "user_config"
    assert expected in (resolution.error or "")
    assert str(config_path) in (resolution.error or "")


def test_resolver_accepts_safe_wrapper_argv_without_shell(tmp_path):
    wrapper = _executable(tmp_path / "bin" / "gemini-wrapper")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[executables]\n"gemini-cli" = ["{wrapper}", "--profile", "safe"]\n',
        encoding="utf-8",
    )

    resolution = ExecutableResolver.from_user_config(config_path).resolve(
        "gemini-cli", "gemini"
    )

    assert resolution.command == (str(wrapper), "--profile", "safe")
    assert resolution.available is True


def test_resolver_reports_invalid_toml_without_crashing_registry(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[executables\n", encoding="utf-8")

    registry = create_default_registry(
        include_entry_points=False,
        config_path=str(config_path),
    )
    availability = registry.get("codex-cli").availability()

    assert availability.status.value == "error"
    assert "Could not read Harness config" in availability.reason


def test_set_and_unset_preserve_unrelated_toml(tmp_path):
    executable = _executable(tmp_path / "bin" / "gemini")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '# Keep this comment.\n[ui]\ntheme = "dark"\n',
        encoding="utf-8",
    )

    set_user_executable(
        "gemini-cli",
        str(executable),
        config_path=config_path,
    )

    text = config_path.read_text(encoding="utf-8")
    assert "# Keep this comment." in text
    assert '[ui]\ntheme = "dark"' in text
    assert load_user_executables(config_path) == {"gemini-cli": str(executable)}
    assert config_path.stat().st_mode & 0o777 == 0o600

    path, removed = unset_user_executable("gemini-cli", config_path=config_path)

    assert path == config_path
    assert removed is True
    assert load_user_executables(config_path) == {}
    assert "# Keep this comment." in config_path.read_text(encoding="utf-8")


def test_set_updates_quoted_table_and_literal_key(tmp_path):
    first = _executable(tmp_path / "bin" / "first-codex")
    second = _executable(tmp_path / "bin" / "second-codex")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'["executables"]\n\'codex-cli\' = "{first}"\n',
        encoding="utf-8",
    )

    set_user_executable("codex-cli", str(second), config_path=config_path)

    assert load_user_executables(config_path) == {"codex-cli": str(second)}
    assert config_path.read_text(encoding="utf-8").count("codex-cli") == 1


def test_set_rejects_relative_path_without_writing(tmp_path):
    config_path = tmp_path / "config.toml"

    with pytest.raises(UserHarnessConfigError, match="absolute"):
        set_user_executable(
            "codex-cli",
            "relative/codex",
            config_path=config_path,
        )

    assert not config_path.exists()


def test_registry_uses_same_resolution_for_command_and_availability(tmp_path):
    executable = _executable(tmp_path / "bin" / "codex")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[executables]\n"codex-cli" = "{executable}"\n',
        encoding="utf-8",
    )
    harness = create_default_registry(
        include_entry_points=False,
        config_path=str(config_path),
    ).get("codex-cli")

    assert harness.availability().status.value == "available"
    assert harness.executable_resolution().source == "user_config"
    command = harness.build_command(
        HarnessRequest(prompt="inspect"),
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )
    assert command[0] == str(executable)


def _executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then echo "fixture 0.144.3"; exit 0; fi\n'
        'echo "--json --sandbox --ephemeral --image --output-format stream-json '
        "--permission-mode --no-session-persistence --include-partial-messages "
        '--approval-mode --skip-trust --prompt-interactive --list-sessions --resume"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path
