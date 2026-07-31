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


def _metadata(
    tmp_path: Path,
    *,
    name: str = "gpt2giga",
    version: str = "1.2.3a1",
    dependencies: tuple[str, ...] = (),
) -> Path:
    path = tmp_path / "pyproject.toml"
    requirements = "\n".join(f'    "{item}",' for item in dependencies)
    path.write_text(
        f'[project]\nname = "{name}"\nversion = "{version}"\n'
        f"dependencies = [\n{requirements}\n]\n",
        encoding="utf-8",
    )
    return path


def test_exact_gateway_version_tag_can_publish(tmp_path: Path):
    result = MODULE.resolve_release(
        metadata_path=_metadata(tmp_path),
        event_name="release",
        ref_name="v1.2.3a1",
        release_tag="v1.2.3a1",
        release_prerelease=True,
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
            release_prerelease=True,
        )


def test_stable_version_requires_non_prerelease_github_release(tmp_path: Path):
    result = MODULE.resolve_release(
        metadata_path=_metadata(tmp_path, version="1.2.3"),
        event_name="release",
        ref_name="v1.2.3",
        release_tag="v1.2.3",
        release_prerelease=False,
    )

    assert result["mode"] == "publish"


@pytest.mark.parametrize(
    ("version", "release_prerelease"),
    [
        ("1.2.3", True),
        ("1.2.3a1", False),
        ("1.2.3.dev1", False),
        ("1.2.3", None),
    ],
)
def test_release_metadata_must_match_project_version(
    tmp_path: Path,
    version: str,
    release_prerelease: bool | None,
):
    with pytest.raises(MODULE.ReleaseGuardError):
        MODULE.resolve_release(
            metadata_path=_metadata(tmp_path, version=version),
            event_name="release",
            ref_name=f"v{version}",
            release_tag=f"v{version}",
            release_prerelease=release_prerelease,
        )


@pytest.mark.parametrize(
    "requirement",
    [
        "gigachat>=0.2.3a1,<0.3.0",
        "example==1.0rc1",
        "example>=1.0-alpha1",
    ],
)
def test_stable_version_rejects_prerelease_dependency_floor(
    tmp_path: Path,
    requirement: str,
):
    with pytest.raises(MODULE.ReleaseGuardError):
        MODULE.resolve_release(
            metadata_path=_metadata(
                tmp_path,
                version="1.2.3",
                dependencies=(requirement,),
            ),
            event_name="workflow_dispatch",
            ref_name="main",
            release_tag="",
            release_prerelease=None,
        )


def test_manual_dispatch_builds_without_publishing(tmp_path: Path):
    result = MODULE.resolve_release(
        metadata_path=_metadata(tmp_path),
        event_name="workflow_dispatch",
        ref_name="main",
        release_tag="",
        release_prerelease=None,
    )

    assert result["mode"] == "manual"


def test_non_gateway_distribution_fails_closed(tmp_path: Path):
    with pytest.raises(MODULE.ReleaseGuardError):
        MODULE.resolve_release(
            metadata_path=_metadata(tmp_path, name="gpt2giga-harness"),
            event_name="workflow_dispatch",
            ref_name="main",
            release_tag="",
            release_prerelease=None,
        )


def test_cli_failure_path_returns_before_using_release_result():
    result = MODULE.main(
        [
            "--event-name",
            "release",
            "--ref-name",
            "v1.2.3",
            "--release-tag",
            "v1.2.3",
            "--release-prerelease",
            "true",
        ]
    )

    assert result == 2
