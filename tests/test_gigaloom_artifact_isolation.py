"""Artifact and dependency contracts owned by krakenalt/gigaloom."""

from pathlib import Path
import tarfile

import pytest

from package_isolation_support import (
    BuiltArtifacts,
    HARNESS_BASE_SMOKE,
    HARNESS_MEMBER,
    HARNESS_VERSION,
    _artifact_members,
    _build_artifacts,
    _install_artifacts,
    _run_clean_python,
    test_all_late_bound_gateway_imports_are_characterized as _check_late_imports,
    test_harness_gateway_imports_stay_within_the_reviewed_boundary as _check_gateway_boundary,
    test_harness_imports_only_declared_distributions as _check_declared_dependencies,
    test_installed_third_party_plugin_is_discovered as _check_third_party_plugin,
    test_neutral_third_party_wheel_registers_without_core_edits as _check_neutral_plugin,
    test_optional_and_development_dependencies_stay_with_their_owner as _check_optional_dependencies,
)


FUTURE_REPOSITORY_OWNER = "krakenalt/gigaloom"


@pytest.fixture(scope="module")
def built_artifacts(tmp_path_factory) -> BuiltArtifacts:
    return _build_artifacts(tmp_path_factory)


@pytest.mark.parametrize("artifact_kind", ["wheel", "sdist"])
def test_gigaloom_base_artifact_runs_without_gateway(
    built_artifacts: BuiltArtifacts,
    tmp_path,
    artifact_kind: str,
):
    artifact = (
        built_artifacts.harness_wheel
        if artifact_kind == "wheel"
        else built_artifacts.harness_sdist
    )
    installed = tmp_path / "installed"
    _install_artifacts(installed, artifact)
    _run_clean_python(installed, HARNESS_BASE_SMOKE)


def test_editable_gigaloom_member_resolves_to_gigaloom_source():
    import gpt2giga_harness
    import importlib.metadata

    assert (
        Path(gpt2giga_harness.__file__).resolve().is_relative_to(HARNESS_MEMBER / "src")
    )
    assert importlib.metadata.version("gpt2giga-harness") == HARNESS_VERSION


def test_gigaloom_imports_only_declared_distributions():
    _check_declared_dependencies()


def test_gigaloom_optional_dependencies_stay_with_their_owner():
    _check_optional_dependencies()


def test_gigaloom_gateway_imports_stay_within_reviewed_boundaries():
    _check_gateway_boundary()


def test_all_late_bound_gateway_imports_are_characterized():
    _check_late_imports()


def test_neutral_third_party_wheel_registers_without_core_edits(
    built_artifacts: BuiltArtifacts,
    tmp_path,
):
    _check_neutral_plugin(built_artifacts, tmp_path)


def test_installed_third_party_plugin_is_discovered(
    built_artifacts: BuiltArtifacts,
    tmp_path,
):
    _check_third_party_plugin(built_artifacts, tmp_path)


def test_gigaloom_sdist_is_self_contained(built_artifacts: BuiltArtifacts):
    with tarfile.open(built_artifacts.harness_sdist) as archive:
        names = archive.getnames()
    assert any(name.endswith("/pyproject.toml") for name in names)
    assert any(name.endswith("/README.md") for name in names)


@pytest.mark.parametrize("artifact_attribute", ["harness_wheel", "harness_sdist"])
def test_gigaloom_artifacts_do_not_package_gateway(
    built_artifacts: BuiltArtifacts,
    artifact_attribute: str,
):
    artifact = getattr(built_artifacts, artifact_attribute)
    violations = [
        name for name in _artifact_members(artifact) if "gpt2giga" in Path(name).parts
    ]
    assert violations == []
