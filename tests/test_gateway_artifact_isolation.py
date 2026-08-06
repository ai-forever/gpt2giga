"""Artifact isolation contracts owned by ai-forever/gpt2giga."""

from pathlib import Path
import tarfile

import pytest

from artifact_contract_support import (
    BuiltArtifacts,
    GATEWAY_DESCRIPTION,
    GATEWAY_NAME,
    GATEWAY_README,
    GATEWAY_SOURCE_ROOT,
    GATEWAY_SMOKE,
    GATEWAY_VERSION,
    _artifact_member_bytes,
    _artifact_members,
    _artifact_metadata,
    _build_artifacts,
    _install_artifacts,
    _run_clean_python,
)


@pytest.fixture(scope="module")
def built_artifacts(tmp_path_factory) -> BuiltArtifacts:
    return _build_artifacts(tmp_path_factory)


@pytest.mark.parametrize("artifact_kind", ["wheel", "sdist"])
def test_gateway_artifact_clean_install_smoke(
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


@pytest.mark.parametrize(
    ("artifact_attribute", "namespace_suffix"),
    [
        ("gateway_wheel", "gpt2giga/__init__.py"),
        ("gateway_sdist", "src/gpt2giga/__init__.py"),
    ],
)
def test_gateway_artifact_contents_and_metadata(
    built_artifacts: BuiltArtifacts,
    artifact_attribute: str,
    namespace_suffix: str,
):
    artifact = getattr(built_artifacts, artifact_attribute)
    members = _artifact_members(artifact)
    metadata = _artifact_metadata(artifact)
    package_data = (
        "gpt2giga/storage/postgres/migrations/0001_traffic_logs.sql",
        "gpt2giga/templates/log_viewer.html",
    )

    assert any(name.endswith(namespace_suffix) for name in members)
    assert not any(
        "gpt2giga_harness" in Path(name).parts or "/gpt2giga/harness/" in f"/{name}/"
        for name in members
    )
    assert all(any(name.endswith(data) for name in members) for data in package_data)
    assert metadata["Name"] == GATEWAY_NAME
    assert metadata["Version"] == GATEWAY_VERSION
    assert metadata["Summary"] == GATEWAY_DESCRIPTION
    assert metadata["Description-Content-Type"] == "text/markdown"
    metadata_suffix = (
        ".dist-info/METADATA" if artifact.suffix == ".whl" else "/PKG-INFO"
    )
    assert _artifact_member_bytes(artifact, metadata_suffix).endswith(GATEWAY_README)


def test_production_image_installs_the_root_built_wheel():
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY pyproject.toml README.md ./" in dockerfile
    assert "COPY src/ src/" in dockerfile
    assert "RUN uv build --wheel" in dockerfile
    assert "COPY --from=builder /app/dist/*.whl /tmp/" in dockerfile
    assert "COPY gigachat-0.2.4a1-py3-none-any.whl /tmp/" in dockerfile
    assert "-name 'gpt2giga-*.whl'" in dockerfile
    assert "-name 'gigachat-*.whl'" in dockerfile
    assert (
        'pip install --no-cache-dir "$sdk_wheel_path" "${wheel_path}${INSTALL_EXTRAS}"'
    ) in dockerfile
