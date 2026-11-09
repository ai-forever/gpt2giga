"""Release and CI contracts owned by ai-forever/gpt2giga."""

from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version
import yaml

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

from artifact_contract_support import assert_lock_is_current
from repository_boundary_support import (
    assert_code_workflows_target_root_project,
    assert_production_dockerfile_installs_root_gateway,
)


_WORKFLOW_ROOT = Path(__file__).resolve().parents[1] / ".github/workflows"


def test_gateway_code_workflows_target_root_project():
    assert_code_workflows_target_root_project()


def test_production_dockerfile_installs_root_gateway():
    assert_production_dockerfile_installs_root_gateway()


def test_source_lock_is_current():
    assert_lock_is_current()


def test_gateway_dependency_lock_excludes_vulnerable_image_and_lock_packages():
    root = _WORKFLOW_ROOT.parents[1]
    with (root / "pyproject.toml").open("rb") as file:
        project = tomllib.load(file)["project"]
    with (root / "uv.lock").open("rb") as file:
        packages = tomllib.load(file)["package"]

    # The gateway forwards image bytes and needs no native image decoder.
    assert "pillow" not in {
        Requirement(dependency).name.lower() for dependency in project["dependencies"]
    }
    assert all(package["name"] != "pillow" for package in packages)
    # Check every resolution, including Python 3.10 branches, not just this host.
    filelocks = [package for package in packages if package["name"] == "filelock"]
    assert filelocks
    assert all(Version(package["version"]) >= Version("4.2.1") for package in filelocks)


def test_gateway_resolves_sdk_from_pypi():
    root = _WORKFLOW_ROOT.parents[1]
    with (root / "pyproject.toml").open("rb") as file:
        pyproject = tomllib.load(file)
    with (root / "uv.lock").open("rb") as file:
        lock = tomllib.load(file)

    assert "gigachat" not in pyproject["tool"].get("uv", {}).get("sources", {})
    sdk = next(package for package in lock["package"] if package["name"] == "gigachat")
    assert sdk["version"] == "0.3.0a1"
    assert sdk["source"] == {"registry": "https://pypi.org/simple"}
    assert all(
        wheel["url"].startswith("https://files.pythonhosted.org/")
        for wheel in sdk["wheels"]
    )


def test_gateway_ci_has_stable_bounded_required_check_names():
    workflow = (_WORKFLOW_ROOT / "ci.yaml").read_text(encoding="utf-8")

    assert "Gateway tests / Python ${{ matrix.python-version }}" in workflow
    assert "Gateway package / wheel and sdist" in workflow
    assert "Gateway artifact / Python ${{ matrix.python-version }}" in workflow
    assert "uv build --wheel --sdist --no-sources" in workflow


def test_gateway_ci_selects_the_python_version_it_advertises():
    workflow = yaml.safe_load((_WORKFLOW_ROOT / "ci.yaml").read_text(encoding="utf-8"))
    jobs = workflow["jobs"]

    for job_name in ("test", "artifact-smoke"):
        job = jobs[job_name]
        assert job["env"]["UV_PYTHON"] == "${{ matrix.python-version }}"
        assert not job.get("continue-on-error", False)
    assert jobs["build"]["env"]["UV_PYTHON"] == "3.13"


def test_gateway_ci_checks_release_branches_without_updating_their_badges():
    workflow = yaml.load(
        (_WORKFLOW_ROOT / "ci.yaml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    for event in ("push", "pull_request"):
        assert workflow["on"][event]["branches"] == ["main", "release/**"]
    badge_commit = next(
        step
        for step in workflow["jobs"]["coverage-badge"]["steps"]
        if step["name"] == "Commit coverage badge on main"
    )
    assert badge_commit["if"] == (
        "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    )


def test_gateway_python315_is_installable_and_tested_as_required():
    root = _WORKFLOW_ROOT.parents[1]
    with (root / "pyproject.toml").open("rb") as file:
        project = tomllib.load(file)["project"]
    supported = SpecifierSet(project["requires-python"])
    assert "3.10" in supported
    assert "3.15" in supported
    assert "3.16" not in supported

    workflow = yaml.safe_load((_WORKFLOW_ROOT / "ci.yaml").read_text(encoding="utf-8"))
    assert "python315-alpha" not in workflow["jobs"]
    assert "minimum-sdk" not in workflow["jobs"]
    for name in ("test", "artifact-smoke"):
        job = workflow["jobs"][name]
        assert job["strategy"]["matrix"]["python-version"] == [
            "3.10",
            "3.13",
            "3.14",
            "3.15",
        ]
        assert not job.get("continue-on-error", False)
    commands = "\n".join(
        step.get("run", "") for step in workflow["jobs"]["artifact-smoke"]["steps"]
    )
    assert '--expected-gigachat-version "0.3.0a1"' in commands


def test_gateway_ci_installs_artifact_dependencies_without_global_prerelease_flags():
    workflow = (_WORKFLOW_ROOT / "ci.yaml").read_text(encoding="utf-8")

    assert "uv build --wheel --no-sources --out-dir dist/smoke" in workflow
    assert (
        "uv pip install --python .venv-artifact/bin/python dist/smoke/gpt2giga-*.whl"
    ) in workflow
    assert "gigachat-0.2.4-py3-none-any.whl" not in workflow
    assert "test ! -e gpt2giga" in workflow
    assert ".venv-artifact/bin/python -I scripts/gateway_artifact_smoke.py" in workflow
    assert ".venv-artifact/bin/gpt2giga --help" in workflow
    assert " --pre " not in workflow


def test_gateway_release_workflow_has_one_package_and_one_publish_contract():
    workflow = (_WORKFLOW_ROOT / "publish-pypi.yml").read_text(encoding="utf-8")

    assert "scripts/gateway_release_guard.py" in workflow
    assert "RELEASE_PRERELEASE: ${{ github.event.release.prerelease }}" in workflow
    assert '--release-prerelease "${RELEASE_PRERELEASE}"' in workflow
    assert "--metadata" not in workflow
    assert workflow.count("uv publish ") == 1
    assert workflow.count("secrets.PYPI_API_KEY") == 1
    assert "if: needs.metadata.outputs.mode == 'publish'" in workflow
    assert "name: pypi-gateway" in workflow


def test_gateway_security_and_docs_filters_target_root_metadata():
    codeql = (_WORKFLOW_ROOT / "codeql.yaml").read_text(encoding="utf-8")
    dependency_review = (_WORKFLOW_ROOT / "dependency-review.yaml").read_text(
        encoding="utf-8"
    )
    docs = (_WORKFLOW_ROOT / "docs-pages.yaml").read_text(encoding="utf-8")

    for workflow in (codeql, dependency_review, docs):
        assert "'packages/*/pyproject.toml'" not in workflow
        assert "'pyproject.toml'" in workflow


def test_all_workflow_filters_use_standalone_gateway_paths():
    workflows = {
        path.name: path.read_text(encoding="utf-8")
        for path in _WORKFLOW_ROOT.iterdir()
        if path.suffix in {".yml", ".yaml"}
    }

    assert all("packages/gpt2giga" not in workflow for workflow in workflows.values())
    for path in (
        "'src/gpt2giga/**'",
        "'pyproject.toml'",
        "'uv.lock'",
        "'tests/**'",
        "'scripts/**'",
    ):
        assert path in workflows["ci.yaml"]
    for path in ("'src/gpt2giga/**'", "'Dockerfile'", "'deploy/**'"):
        assert path in workflows["docker-smoke.yaml"]
    for workflow_name in ("docker-smoke.yaml", "docker_image.yaml", "publish-ghcr.yml"):
        assert "'pyproject.toml'" in workflows[workflow_name]
        assert "'gigachat-0.2.4-py3-none-any.whl'" not in workflows[workflow_name]
    for path in ("'docs/**'", "'docs-site/**'", "'scripts/check_docs.py'"):
        assert path in workflows["docs-pages.yaml"]


def test_container_preview_is_separate_from_stable_tags(tmp_path):
    import os
    import subprocess

    workflow = yaml.safe_load(
        (_WORKFLOW_ROOT / "docker_image.yaml").read_text(encoding="utf-8")
    )
    job = workflow["jobs"]["build-and-push"]
    preview = job["strategy"]["matrix"]["include"][0]
    assert preview == {
        "python-version": "3.15",
        "python-image": "3.15",
        "preview": True,
    }
    script = next(s["run"] for s in job["steps"] if s.get("id") == "docker_tags")
    for python, is_preview in (("3.13", False), ("3.14", False), ("3.15", True)):
        output = tmp_path / python
        command = (
            script.replace("${{ matrix.python-version }}", python)
            .replace("${{ matrix.preview }}", "true" if is_preview else "")
            .replace("${{ steps.get_version.outputs.VERSION }}", "0.3.1")
            .replace("${{ steps.get_version.outputs.PRERELEASE }}", "false")
        )
        subprocess.run(
            ["bash", "-eu", "-c", command],
            check=True,
            env={
                **os.environ,
                "GITHUB_OUTPUT": str(output),
                "IMAGE_NAME": "gigateam/gpt2giga",
                "GITHUB_SHA": "abc123",
            },
        )
        tags = output.read_text().splitlines()[1:-1]
        assert ("gigateam/gpt2giga:latest" in tags) == (python == "3.13")
        assert ("gigateam/gpt2giga:0.3.1" in tags) == (python == "3.13")
        assert ("gigateam/gpt2giga:preview" in tags) == is_preview
        assert ("gigateam/gpt2giga:0.3.1-preview" in tags) == is_preview
        if is_preview:
            assert "gigateam/gpt2giga:0.3.1-python3.15-preview" in tags

    ghcr = yaml.safe_load((_WORKFLOW_ROOT / "publish-ghcr.yml").read_text())
    ghcr_job = ghcr["jobs"]["build-and-push"]
    assert ghcr_job["strategy"]["matrix"]["include"][0] == {
        "python": "3.15",
        "python-image": "3.15",
        "preview": True,
    }
    metadata = next(s for s in ghcr_job["steps"] if s.get("id") == "meta")
    assert metadata["with"]["flavor"] == "latest=false\n"
    tags = metadata["with"]["tags"]
    assert (
        "value=latest,enable=${{ matrix.python == '3.13' && steps.get_version.outputs.PRERELEASE != 'true' }}"
        in tags
    )
    assert "value=preview,enable=${{ matrix.preview == true }}" in tags
    assert "VERSION }}-preview,enable=${{ matrix.preview == true }}" in tags


def test_container_preview_is_built_and_booted_in_ci():
    workflow = yaml.safe_load((_WORKFLOW_ROOT / "docker-smoke.yaml").read_text())
    job = workflow["jobs"]["docker-smoke"]
    assert job["strategy"]["matrix"]["python"] == ["3.13", "3.15"]
    assert not job.get("continue-on-error", False)
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    assert "PYTHON_VERSION=${{ matrix.python }}" in commands
    assert "http://127.0.0.1:18090/health" in commands


def test_candidate_docker_tags_never_overwrite_stable_aliases(tmp_path):
    import os
    import subprocess

    workflow = yaml.safe_load((_WORKFLOW_ROOT / "docker_image.yaml").read_text())
    script = next(
        s["run"]
        for s in workflow["jobs"]["build-and-push"]["steps"]
        if s.get("id") == "docker_tags"
    )
    for python in ("3.10", "3.13", "3.15"):
        output = tmp_path / python
        command = (
            script.replace("${{ matrix.python-version }}", python)
            .replace("${{ matrix.preview }}", "true" if python == "3.15" else "")
            .replace("${{ steps.get_version.outputs.VERSION }}", "0.3.3a1")
            .replace("${{ steps.get_version.outputs.PRERELEASE }}", "true")
        )
        subprocess.run(
            ["bash", "-eu", "-c", command],
            check=True,
            env={
                **os.environ,
                "GITHUB_OUTPUT": str(output),
                "IMAGE_NAME": "test/image",
                "GITHUB_SHA": "abc",
            },
        )
        tags = output.read_text().splitlines()[1:-1]
        assert "test/image:latest" not in tags
        assert f"test/image:python{python}" not in tags
        assert f"test/image:python{python}-preview" in tags
        assert ("test/image:preview" in tags) == (python == "3.15")


def test_ghcr_tags_render_stable_and_candidate_aliases():
    import re

    job = yaml.safe_load((_WORKFLOW_ROOT / "publish-ghcr.yml").read_text())["jobs"][
        "build-and-push"
    ]
    template = next(step for step in job["steps"] if step.get("id") == "meta")["with"][
        "tags"
    ]
    for version, prerelease in (("0.3.3", False), ("0.3.3a1", True)):
        for python in ("3.10", "3.13", "3.15"):
            preview = python == "3.15"
            values = {
                "matrix.python": python,
                "steps.get_version.outputs.VERSION": version,
                "(matrix.preview || steps.get_version.outputs.PRERELEASE == 'true') && '-preview' || ''": "-preview"
                if preview or prerelease
                else "",
                "matrix.python == '3.13'": str(python == "3.13").lower(),
                "matrix.preview == true": str(preview).lower(),
                "matrix.python == '3.13' && steps.get_version.outputs.PRERELEASE != 'true'": str(
                    python == "3.13" and not prerelease
                ).lower(),
            }
            rendered = re.sub(
                r"\$\{\{ (.*?) \}\}", lambda match: values[match.group(1)], template
            )
            rows = [
                dict(field.split("=", 1) for field in line.split(","))
                for line in rendered.splitlines()
            ]
            tags = {row["value"] for row in rows if row.get("enable", "true") == "true"}
            assert ("latest" in tags) == (python == "3.13" and not prerelease)
            assert (f"py{python}" in tags) == (not preview and not prerelease)
            assert (f"py{python}-preview" in tags) == (preview or prerelease)
            assert ("preview" in tags) == preview
            assert (version in tags) == (python == "3.13")
