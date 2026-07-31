"""Artifact isolation contracts owned by ai-forever/gpt2giga."""

from pathlib import Path
import tarfile

import pytest

from artifact_contract_support import (
    BuiltArtifacts,
    GATEWAY_SOURCE_ROOT,
    GATEWAY_SMOKE,
    GATEWAY_VERSION,
    _artifact_members,
    _build_artifacts,
    _install_artifacts,
    _run_clean_python,
)


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


def test_editable_gateway_resolves_to_source_root():
    import gpt2giga
    import importlib.metadata

    assert Path(gpt2giga.__file__).resolve().is_relative_to(GATEWAY_SOURCE_ROOT)
    assert importlib.metadata.version("gpt2giga") == GATEWAY_VERSION


def test_gateway_sdist_is_self_contained(built_artifacts: BuiltArtifacts):
    with tarfile.open(built_artifacts.gateway_sdist) as archive:
        names = archive.getnames()

    required_members = (
        "/pyproject.toml",
        "/README.md",
        "/CHANGELOG.md",
        "/CHANGELOG_en.md",
        "/src/gpt2giga/__init__.py",
    )
    assert {
        member
        for member in required_members
        if not any(name.endswith(member) for name in names)
    } == set()
    legacy_layout = "packages" + "/gpt2giga/"
    assert not any(legacy_layout in name for name in names)


@pytest.mark.parametrize("artifact_attribute", ["gateway_wheel", "gateway_sdist"])
def test_gateway_artifacts_include_postgres_migration(
    built_artifacts: BuiltArtifacts,
    artifact_attribute: str,
):
    artifact = getattr(built_artifacts, artifact_attribute)
    migration = "gpt2giga/storage/postgres/migrations/0001_traffic_logs.sql"

    assert any(name.endswith(migration) for name in _artifact_members(artifact))


def test_production_image_installs_the_root_built_wheel():
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY pyproject.toml README.md ./" in dockerfile
    assert "COPY src/ src/" in dockerfile
    assert "RUN uv build --wheel" in dockerfile
    assert "COPY --from=builder /app/dist/*.whl /tmp/" in dockerfile
    assert 'pip install --no-cache-dir "${wheel_path}${INSTALL_EXTRAS}"' in dockerfile


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
