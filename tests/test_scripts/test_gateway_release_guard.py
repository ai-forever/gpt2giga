"""Tests for the source repository's gateway release guard."""

import importlib.util
from pathlib import Path

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "gateway_release_guard.py"
)
SPEC = importlib.util.spec_from_file_location("gateway_release_guard", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _metadata(tmp_path: Path, *, name: str = "gpt2giga") -> Path:
    path = tmp_path / "pyproject.toml"
    path.write_text(
        f'[project]\nname = "{name}"\nversion = "1.2.3a1"\n',
        encoding="utf-8",
    )
    return path


def test_exact_gateway_version_tag_can_publish(tmp_path: Path):
    result = MODULE.resolve_release(
        metadata_path=_metadata(tmp_path),
        event_name="release",
        ref_name="v1.2.3a1",
        release_tag="v1.2.3a1",
    )

    assert result == {
        "mode": "publish",
        "tag": "v1.2.3a1",
        "version": "1.2.3a1",
    }


@pytest.mark.parametrize(
    ("ref_name", "release_tag"),
    [
        ("v1.2.3", "v1.2.3"),
        ("gpt2giga-harness-v1.2.3a1", "gpt2giga-harness-v1.2.3a1"),
        ("v1.2.3a1", "v1.2.3"),
    ],
)
def test_other_or_mismatched_tags_fail_closed(
    tmp_path: Path,
    ref_name: str,
    release_tag: str,
):
    with pytest.raises(MODULE.ReleaseGuardError):
        MODULE.resolve_release(
            metadata_path=_metadata(tmp_path),
            event_name="release",
            ref_name=ref_name,
            release_tag=release_tag,
        )


def test_manual_dispatch_builds_without_publishing(tmp_path: Path):
    result = MODULE.resolve_release(
        metadata_path=_metadata(tmp_path),
        event_name="workflow_dispatch",
        ref_name="main",
        release_tag="",
    )

    assert result["mode"] == "manual"


def test_non_gateway_distribution_fails_closed(tmp_path: Path):
    with pytest.raises(MODULE.ReleaseGuardError):
        MODULE.resolve_release(
            metadata_path=_metadata(tmp_path, name="gpt2giga-harness"),
            event_name="workflow_dispatch",
            ref_name="main",
            release_tag="",
        )


def test_cli_failure_path_exits_before_using_release_result(tmp_path: Path):
    with pytest.raises(SystemExit) as error:
        MODULE.main(
            [
                "--metadata",
                str(_metadata(tmp_path)),
                "--event-name",
                "release",
                "--ref-name",
                "v1.2.3",
                "--release-tag",
                "v1.2.3",
            ]
        )

    assert error.value.code == 2
