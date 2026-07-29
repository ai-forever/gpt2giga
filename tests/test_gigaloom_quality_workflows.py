"""Standalone GigaLoom quality-workflow contracts."""

from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPOSITORY_ROOT / ".github/workflows"


def _workflow(name: str) -> dict:
    with (WORKFLOWS / name).open(encoding="utf-8") as file:
        return yaml.load(file, Loader=yaml.BaseLoader)


def _workflow_text(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_required_quality_jobs_are_independent_and_standalone():
    workflow = _workflow("ci.yaml")
    jobs = workflow["jobs"]

    assert workflow["permissions"] == {"contents": "read"}
    assert set(jobs) == {
        "frontend",
        "package",
        "performance",
        "python",
        "registry-readiness",
        "terminal",
    }
    assert jobs["python"]["strategy"]["matrix"]["python-version"] == [
        "3.10",
        "3.13",
        "3.14",
    ]
    assert jobs["terminal"]["strategy"]["matrix"] == {
        "os": ["ubuntu-latest", "macos-latest", "windows-latest"],
        "python-version": ["3.10", "3.13", "3.14"],
    }

    text = _workflow_text("ci.yaml")
    for forbidden in (
        "git push",
        "packages/gpt2giga/",
        "blocked_pending_S5_03B",
    ):
        assert forbidden not in text
    assert "Public registry / exact gateway lock" in text
    assert "./scripts/ci-base.sh sync-all-extras" in text
    assert "./scripts/ci-public-gateway.sh" in text
    assert "cache-dependency-glob: uv.lock" in text
    assert "benchmark performance --profile ci-smoke" in text
    assert "test-results/browser-qa" in text


def test_browser_gate_covers_required_viewports_console_and_overflow():
    config = (
        REPOSITORY_ROOT / "packages/gpt2giga-harness/frontend/playwright.config.ts"
    ).read_text(encoding="utf-8")
    smoke = (
        REPOSITORY_ROOT / "packages/gpt2giga-harness/frontend/e2e/cockpit.spec.ts"
    ).read_text(encoding="utf-8")

    assert "width: 1440, height: 1000" in config
    assert 'name: "mobile-390x844"' in config
    assert "width: 390, height: 844" in config
    assert "workers: 1" in config
    assert "url: `${baseURL}/local-access`" in config
    assert 'message.type() === "error"' in smoke
    assert 'page.on("pageerror"' in smoke
    assert "scrollWidth" in smoke
    assert "clientWidth" in smoke
    assert 'name: "Recover this browser"' in smoke
    assert 'getByRole("link", { name: "Settings" })' in smoke


def test_candidate_injection_paths_are_removed():
    assert not (WORKFLOWS / "candidate-gateway-smoke.yaml").exists()
    assert not (REPOSITORY_ROOT / "scripts/ci-candidate-gateway.sh").exists()
    assert (REPOSITORY_ROOT / "scripts/ci-public-gateway.sh").is_file()


def test_detail_profiles_are_scheduled_and_non_blocking():
    workflow = _workflow("nightly-smoke.yaml")
    assert set(workflow["on"]) == {"schedule", "workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}

    text = _workflow_text("nightly-smoke.yaml")
    for profile in ("local-detail", "tui-detail", "runtime-detail"):
        assert f"--profile {profile}" in text
    assert text.count("continue-on-error: true") == 3
