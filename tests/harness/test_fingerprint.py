from gpt2giga_harness.harnesses.echo import EchoHarness
from gpt2giga_harness.registry import HarnessRegistry, create_default_registry
from gpt2giga_harness.runtime import fingerprint


def test_worker_fingerprint_reports_both_distribution_versions(monkeypatch):
    versions = {
        "gpt2giga": "0.2.2a1",
        "gigaloom": "0.5.1a1",
    }
    monkeypatch.setattr(fingerprint.metadata, "version", versions.__getitem__)

    registry = HarnessRegistry()
    registry.register(EchoHarness())

    result = fingerprint.build_worker_fingerprint(registry)

    assert result["gpt2giga"] == "0.2.2a1"
    assert result["gpt2giga_harness"] == "0.5.1a1"


def test_worker_fingerprint_uses_resolved_user_executable(tmp_path):
    executable = tmp_path / "bin" / "codex"
    executable.parent.mkdir()
    executable.write_text(
        '#!/bin/sh\nif [ "$1" = "--version" ]; then echo "codex 0.144.3"; '
        'else echo "--json --sandbox --ephemeral --image --config"; fi\n',
        encoding="utf-8",
    )
    executable.chmod(0o755)
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[executables]\n"codex-cli" = "{executable}"\n',
        encoding="utf-8",
    )
    registry = create_default_registry(
        include_entry_points=False,
        config_path=str(config_path),
    )

    result = fingerprint.build_worker_fingerprint(registry)
    codex = result["harnesses"]["codex-cli"]

    assert codex["binary_path"] == str(executable)
    assert codex["binary_source"] == "user_config"
    assert codex["binary_version"] == "codex 0.144.3"
    assert codex["compatibility"]["status"] == "supported"
    assert codex["features"]["agent_reasoning_effort"] is True
    assert codex["features"]["agent_allowed_tools"] is False
