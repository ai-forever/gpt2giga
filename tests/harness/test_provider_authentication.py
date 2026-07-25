import json
from pathlib import Path

import pytest

from gpt2giga_harness.cli_capabilities import invalidate_cli_probe_cache
from gpt2giga_harness.cli_capabilities import probe_cli_capabilities
from gpt2giga_harness.executables import ExecutableResolution
from gpt2giga_harness.provider_authentication import (
    ProviderAuthenticationEvidenceError,
    build_provider_authentication_capability_matrix,
    load_provider_authentication_evidence,
    parse_provider_authentication_evidence,
    render_provider_authentication_capability_matrix_markdown,
)

REPOSITORY_ROOT = Path(__file__).parents[2]


@pytest.fixture(autouse=True)
def clear_probe_cache():
    invalidate_cli_probe_cache()
    yield
    invalidate_cli_probe_cache()


def test_packaged_provider_authentication_evidence_is_strict_and_source_bound():
    evidence = load_provider_authentication_evidence()

    assert evidence.reviewed_at == "2026-07-26"
    assert len(evidence.evidence_hash) == 64
    assert [item["harness_id"] for item in evidence.providers] == [
        "codex-cli",
        "claude-code",
        "gemini-cli",
    ]
    assert [item["pinned_cli_version"] for item in evidence.providers] == [
        "0.144.3",
        "2.1.212",
        "0.46.0",
    ]
    assert all(item["terms_reviewed_at"] == "2026-07-26" for item in evidence.providers)
    assert all(
        source["url"].startswith("https://")
        for item in evidence.providers
        for source in item["sources"]
    )

    with pytest.raises(ProviderAuthenticationEvidenceError, match="unsupported"):
        parse_provider_authentication_evidence(
            {"schema_version": 2, "reviewed_at": "2026-07-26", "providers": []}
        )


def test_hermetic_command_fakes_admit_only_exact_reviewed_cli_pins(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[-1] == "--version":
            versions = {
                "codex": "codex-cli 0.144.3",
                "claude": "2.1.212 (Claude Code)",
                "gemini": "0.46.0",
            }
            return _Completed(stdout=versions[Path(command[0]).name])
        if "app-server" in command:
            return _Completed(stdout="--listen stdio:// generate-json-schema")
        if "remote-control" in command:
            return _Completed(
                stderr="Error: You must be logged in to use Remote Control.",
                returncode=1,
            )
        output = {
            "codex": "exec --json --sandbox --ephemeral",
            "claude": (
                "--output-format stream-json --permission-mode "
                "--no-session-persistence --remote-control"
            ),
            "gemini": ("--output-format stream-json --approval-mode --skip-trust"),
        }
        return _Completed(stdout=output[Path(command[0]).name])

    monkeypatch.setattr(
        "gpt2giga_harness.cli_capabilities.subprocess.run",
        fake_run,
    )
    snapshots = {
        harness_id: probe_cli_capabilities(
            ExecutableResolution(
                harness_id=harness_id,
                command_name=command_name,
                executable=f"/fixture/{command_name}",
                source="user_config",
                argv=(f"/fixture/{command_name}",),
            ),
            harness_id,
        )
        for harness_id, command_name in (
            ("codex-cli", "codex"),
            ("claude-code", "claude"),
            ("gemini-cli", "gemini"),
        )
    }

    matrix = build_provider_authentication_capability_matrix(snapshots)

    assert all(
        item["runtime_evidence"]["status"] == "reviewed_pin_present"
        for item in matrix["providers"]
    )
    assert all(
        item["broker_status"] == "not_implemented" for item in matrix["providers"]
    )
    assert all(item["live_login_authorized"] is False for item in matrix["providers"])
    assert all("login" not in command[1:] for command in calls)
    assert all("logout" not in command[1:] for command in calls)
    serialized = json.dumps(matrix).casefold()
    assert "sk-test" not in serialized
    assert "refresh_token" not in serialized


def test_version_drift_and_missing_runtime_evidence_fail_closed(monkeypatch):
    monkeypatch.setattr(
        "gpt2giga_harness.cli_capabilities.subprocess.run",
        lambda command, **kwargs: _Completed(
            stdout=(
                "codex-cli 0.144.4"
                if command[-1] == "--version"
                else "--json --sandbox --ephemeral"
                if "app-server" not in command
                else "--listen stdio:// generate-json-schema"
            )
        ),
    )
    snapshot = probe_cli_capabilities(
        ExecutableResolution(
            harness_id="codex-cli",
            command_name="codex",
            executable="/fixture/codex",
            source="user_config",
            argv=("/fixture/codex",),
        ),
        "codex-cli",
    )

    matrix = build_provider_authentication_capability_matrix({"codex-cli": snapshot})
    by_id = {item["harness_id"]: item for item in matrix["providers"]}

    assert by_id["codex-cli"]["runtime_evidence"] == {
        "status": "blocked",
        "reason": "installed CLI version is outside the exact reviewed pin",
    }
    assert by_id["claude-code"]["runtime_evidence"]["status"] == "not_probed"
    assert by_id["gemini-cli"]["runtime_evidence"]["status"] == "not_probed"


def test_provider_authentication_markdown_matches_published_architecture_doc():
    matrix = build_provider_authentication_capability_matrix()
    rendered = render_provider_authentication_capability_matrix_markdown(matrix)

    assert "G3-01 broker" in rendered
    assert "Gemini CLI OAuth may not be harvested" in rendered
    assert (
        REPOSITORY_ROOT
        / "docs"
        / "architecture"
        / "provider-authentication-capability-matrix.md"
    ).read_text(encoding="utf-8") == rendered


class _Completed:
    def __init__(self, *, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
