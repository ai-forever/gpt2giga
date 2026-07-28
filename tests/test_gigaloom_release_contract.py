"""Bootstrap-time publication guards owned by krakenalt/gigaloom."""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_publication_is_absent_until_target_release_workflow_slice():
    assert not (REPOSITORY_ROOT / ".github/workflows/publish-pypi.yml").exists()


def test_release_ready_lock_is_deferred_until_s5_03b():
    assert not (REPOSITORY_ROOT / "uv.lock").exists()
    ignore = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "\nuv.lock\n" in ignore
