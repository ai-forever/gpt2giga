"""Repository layout contracts owned by ai-forever/gpt2giga."""

from pathlib import Path
import subprocess

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

from repository_boundary_support import (
    assert_gateway_runtime_has_no_extracted_namespace_imports,
)


def test_gateway_owned_modules_do_not_import_gigaloom():
    assert_gateway_runtime_has_no_extracted_namespace_imports()


def test_source_repository_is_a_root_level_gateway_project():
    root = Path(__file__).resolve().parents[1]

    with (root / "pyproject.toml").open("rb") as file:
        metadata = tomllib.load(file)

    tracked_metadata = subprocess.run(
        ["git", "ls-files", "*pyproject.toml"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    project = metadata["project"]
    build_targets = metadata["tool"]["hatch"]["build"]["targets"]

    assert tracked_metadata == ["pyproject.toml"]
    assert project["name"] == "gpt2giga"
    assert project["description"]
    assert project["readme"] == "README.md"
    assert project["scripts"] == {"gpt2giga": "gpt2giga:run"}
    assert "workspace" not in metadata.get("tool", {}).get("uv", {})
    assert build_targets["wheel"]["packages"] == ["src/gpt2giga"]
    assert build_targets["sdist"]["only-include"] == [
        "src",
        "CHANGELOG.md",
        "CHANGELOG_en.md",
    ]
    assert (root / "src/gpt2giga/__init__.py").is_file()
    assert not (root / "packages").exists()
    assert not (root / "packages/gpt2giga-harness").exists()
    assert not (root / "tests/harness").exists()
    assert not (root / "examples/harness").exists()
    assert not (root / "benchmarks/harness_p0").exists()
    assert not (root / "benchmarks/harness_p2_5").exists()


def test_nested_gateway_layout_survives_only_as_changelog_history():
    root = Path(__file__).resolve().parents[1]
    legacy_layout = "packages" + "/gpt2giga/"
    result = subprocess.run(
        ["git", "grep", "-l", legacy_layout, "--"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert set(result.stdout.splitlines()) == {"CHANGELOG.md", "CHANGELOG_en.md"}
