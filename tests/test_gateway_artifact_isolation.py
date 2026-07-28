"""Artifact isolation contracts owned by ai-forever/gpt2giga."""

from pathlib import Path
import tarfile

import pytest

from package_isolation_support import (
    BuiltArtifacts,
    GATEWAY_MEMBER,
    GATEWAY_SMOKE,
    GATEWAY_VERSION,
    _artifact_members,
    _build_artifacts,
    _install_artifacts,
    _run_clean_python,
)


FUTURE_REPOSITORY_OWNER = "ai-forever/gpt2giga"


@pytest.fixture(scope="module")
def built_artifacts(tmp_path_factory) -> BuiltArtifacts:
    return _build_artifacts(tmp_path_factory)


@pytest.mark.parametrize("artifact_kind", ["wheel", "sdist"])
def test_gateway_artifact_is_isolated(
    built_artifacts: BuiltArtifacts,
    tmp_path,
    artifact_kind: str,
):
    artifact = (
        built_artifacts.gateway_wheel
        if artifact_kind == "wheel"
        else built_artifacts.gateway_sdist
    )
    installed = tmp_path / "installed"
    _install_artifacts(installed, artifact)
    _run_clean_python(installed, GATEWAY_SMOKE)


def test_editable_gateway_member_resolves_to_gateway_source():
    import gpt2giga
    import importlib.metadata

    assert Path(gpt2giga.__file__).resolve().is_relative_to(GATEWAY_MEMBER / "src")
    assert importlib.metadata.version("gpt2giga") == GATEWAY_VERSION


def test_gateway_sdist_is_self_contained(built_artifacts: BuiltArtifacts):
    with tarfile.open(built_artifacts.gateway_sdist) as archive:
        names = archive.getnames()
    assert any(name.endswith("/pyproject.toml") for name in names)
    assert any(name.endswith("/README.md") for name in names)


@pytest.mark.parametrize("artifact_attribute", ["gateway_wheel", "gateway_sdist"])
def test_gateway_artifacts_do_not_package_gigaloom(
    built_artifacts: BuiltArtifacts,
    artifact_attribute: str,
):
    artifact = getattr(built_artifacts, artifact_attribute)
    violations = [
        name
        for name in _artifact_members(artifact)
        if "gpt2giga_harness" in Path(name).parts
    ]
    assert violations == []
