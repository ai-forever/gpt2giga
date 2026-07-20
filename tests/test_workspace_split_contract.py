import ast
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib


REPO_ROOT = Path(__file__).resolve().parents[1]
GATEWAY_MEMBER = REPO_ROOT / "packages/gpt2giga"
HARNESS_MEMBER = REPO_ROOT / "packages/gpt2giga-harness"


def _load_toml(path: Path) -> dict:
    with path.open("rb") as file:
        return tomllib.load(file)


def _gateway_source_root() -> Path:
    workspace_root = GATEWAY_MEMBER / "src/gpt2giga"
    return workspace_root if workspace_root.is_dir() else REPO_ROOT / "gpt2giga"


def _workspace_members(metadata: dict) -> set[str]:
    members: set[str] = set()
    for pattern in metadata["tool"]["uv"]["workspace"]["members"]:
        for path in REPO_ROOT.glob(pattern):
            if (path / "pyproject.toml").is_file():
                members.add(path.relative_to(REPO_ROOT).as_posix())
    return members


def _forbidden_harness_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    forbidden: list[str] = []
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        for module in modules:
            if module == "gpt2giga_harness" or module.startswith("gpt2giga_harness."):
                forbidden.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
            if module == "gpt2giga.harness" or module.startswith("gpt2giga.harness."):
                forbidden.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    return forbidden


def test_gateway_owned_modules_do_not_import_harness():
    source_root = _gateway_source_root()
    violations: list[str] = []
    for path in source_root.rglob("*.py"):
        relative_path = path.relative_to(source_root)
        if relative_path.parts[0] == "harness":
            continue
        violations.extend(_forbidden_harness_imports(path))
    assert violations == []


def test_pre_split_relocation_sources_are_present():
    if GATEWAY_MEMBER.exists() or HARNESS_MEMBER.exists():
        return

    assert (REPO_ROOT / "gpt2giga/harness").is_dir()
    assert (REPO_ROOT / "gpt2giga/tools").is_dir()
    assert (REPO_ROOT / "gpt2giga/protocols/openai/stream_accumulator.py").is_file()
    assert {
        "__init__.py",
        "app.css",
        "app.js",
        "index.html",
    } == {
        path.name
        for path in (REPO_ROOT / "gpt2giga/harness/ui/assets").iterdir()
        if path.is_file()
    }


def test_workspace_member_metadata_and_source_ownership_when_present():
    if not GATEWAY_MEMBER.exists():
        return

    root_metadata = _load_toml(REPO_ROOT / "pyproject.toml")
    members = _workspace_members(root_metadata)
    gateway_metadata = _load_toml(GATEWAY_MEMBER / "pyproject.toml")["project"]

    if not HARNESS_MEMBER.exists():
        assert set(members) == {"packages/gpt2giga"}
        assert gateway_metadata["name"] == "gpt2giga"
        assert gateway_metadata["version"]
        assert (GATEWAY_MEMBER / "src/gpt2giga/harness").is_dir()
        return

    assert set(members) == {"packages/gpt2giga", "packages/gpt2giga-harness"}
    harness_metadata = _load_toml(HARNESS_MEMBER / "pyproject.toml")["project"]
    assert gateway_metadata["name"] == "gpt2giga"
    assert gateway_metadata["version"]
    assert gateway_metadata["scripts"] == {"gpt2giga": "gpt2giga:run"}
    assert "entry-points" not in gateway_metadata
    assert not {
        "certifi",
        "python-dateutil",
        "pyyaml",
    } & {
        dependency.split("<", 1)[0].split("=", 1)[0]
        for dependency in gateway_metadata["dependencies"]
    }
    assert harness_metadata["name"] == "gpt2giga-harness"
    assert harness_metadata["version"]
    assert not any(
        dependency.startswith(("gpt2giga", "gigachat"))
        for dependency in harness_metadata["dependencies"]
    )
    assert harness_metadata["optional-dependencies"]["gpt2giga"] == [
        f"gpt2giga=={gateway_metadata['version']}",
        "gigachat>=0.2.2a1,<0.3.0",
    ]
    assert any(
        dependency.startswith("pyyaml")
        for dependency in harness_metadata["dependencies"]
    )
    assert any(
        dependency.startswith("python-dateutil")
        for dependency in harness_metadata["dependencies"]
    )
    assert harness_metadata["scripts"] == {
        "giga": "gpt2giga_harness.entrypoint:main",
        "giga-skills-catalog-proxy": "gpt2giga_harness.skills_catalog_proxy:main",
        "gpt2giga-harness": "gpt2giga_harness.entrypoint:main",
    }
    entry_point_groups = harness_metadata["entry-points"]
    assert set(entry_point_groups) == {
        "agent_workbench.harness_adapters.v1",
        "agent_workbench.provider_adapters.v1",
        "gpt2giga.harnesses",
    }
    for group in (
        "agent_workbench.harness_adapters.v1",
        "gpt2giga.harnesses",
    ):
        entry_points = entry_point_groups[group]
        assert set(entry_points) == {
            "claude-code",
            "codex-cli",
            "direct-chat",
            "echo",
            "gemini-cli",
        }
        assert all(
            target.startswith("gpt2giga_harness.") for target in entry_points.values()
        )
    provider_entry_points = entry_point_groups["agent_workbench.provider_adapters.v1"]
    assert set(provider_entry_points) == {
        "claude-legacy",
        "codex-legacy",
        "direct-chat-legacy",
        "gemini-legacy",
    }
    assert all(
        target.startswith("gpt2giga_harness.provider_profiles:")
        for target in provider_entry_points.values()
    )

    gateway_source = GATEWAY_MEMBER / "src/gpt2giga"
    harness_source = HARNESS_MEMBER / "src/gpt2giga_harness"
    assert not (gateway_source / "harness").exists()
    assert not (gateway_source / "tools").exists()
    assert not (gateway_source / "protocols/openai/stream_accumulator.py").exists()
    assert (harness_source / "tools").is_dir()
    assert (harness_source / "protocols/openai/stream_accumulator.py").is_file()
    assert (harness_source / "ui/assets/index.html").is_file()


def test_ci_builds_and_smokes_both_workspace_artifacts_when_present():
    if not HARNESS_MEMBER.exists():
        return

    workflow = (REPO_ROOT / ".github/workflows/ci.yaml").read_text(encoding="utf-8")
    gateway_version = _load_toml(GATEWAY_MEMBER / "pyproject.toml")["project"][
        "version"
    ]
    harness_version = _load_toml(HARNESS_MEMBER / "pyproject.toml")["project"][
        "version"
    ]
    assert "build-artifacts:" in workflow
    assert "artifact-smoke:" in workflow
    assert "package: [gateway, harness]" in workflow
    assert "- '!packages/**/*.md'" in workflow
    assert 'python-version: ["3.10", "3.13", "3.14"]' in workflow
    assert 'python-version: ["3.10", "3.14"]' in workflow
    assert "uv build --package gpt2giga --wheel --sdist --no-sources" in workflow
    assert (
        "uv build --package gpt2giga-harness --wheel --sdist --no-sources" in workflow
    )
    assert "id: versions" in workflow
    assert "name: gpt2giga-${{ steps.versions.outputs.gateway }}" in workflow
    assert "name: gpt2giga-harness-${{ steps.versions.outputs.harness }}" in workflow
    assert "GATEWAY_VERSION: ${{ steps.versions.outputs.gateway }}" in workflow
    assert "HARNESS_VERSION: ${{ steps.versions.outputs.harness }}" in workflow
    assert "- name: Commit coverage badge on main" in workflow
    assert "if: github.event_name == 'push'" in workflow
    assert gateway_version not in workflow
    assert harness_version not in workflow
    assert ".venv-artifact/bin/gpt2giga --help" in workflow
    assert ".venv-artifact/bin/giga --help" in workflow
    assert ".venv-artifact/bin/gpt2giga-harness --help" in workflow
    assert "python -I -m gpt2giga_harness.base_install --json" in workflow
    assert (
        workflow.index("Install Harness base artifact")
        < workflow.index("Audit Harness base installation")
        < workflow.index("Install gateway artifact for combined smoke")
    )


def test_code_workflows_skip_documentation_only_changes():
    codeql = (REPO_ROOT / ".github/workflows/codeql.yaml").read_text(encoding="utf-8")
    dependency_review = (
        REPO_ROOT / ".github/workflows/dependency-review.yaml"
    ).read_text(encoding="utf-8")
    docker_workflows = tuple(
        (REPO_ROOT / path).read_text(encoding="utf-8")
        for path in (
            ".github/workflows/docker-smoke.yaml",
            ".github/workflows/docker_image.yaml",
            ".github/workflows/publish-ghcr.yml",
        )
    )

    assert "- 'packages/**/*.py'" in codeql
    assert "- 'packages/*/pyproject.toml'" in codeql
    assert "- 'packages/**'" not in codeql
    assert "- 'packages/*/pyproject.toml'" in dependency_review
    assert "- 'docs-site/package-lock.json'" in dependency_review
    assert all(
        "- '!packages/gpt2giga/**/*.md'" in workflow for workflow in docker_workflows
    )


def test_pr_labeler_tracks_harness_owned_paths():
    labeler = (REPO_ROOT / ".github/labeler.yml").read_text(encoding="utf-8")

    assert "harness:" in labeler
    assert "- 'packages/gpt2giga-harness/**'" in labeler
    assert "- 'tests/harness/**'" in labeler
    assert "- 'docs/harness.md'" in labeler


def test_release_workflow_routes_and_publishes_both_workspace_members():
    if not HARNESS_MEMBER.exists():
        return

    workflow = (REPO_ROOT / ".github/workflows/publish-pypi.yml").read_text(
        encoding="utf-8"
    )
    gateway_version = _load_toml(GATEWAY_MEMBER / "pyproject.toml")["project"][
        "version"
    ]
    harness_version = _load_toml(HARNESS_MEMBER / "pyproject.toml")["project"][
        "version"
    ]
    assert "workflow_dispatch:" in workflow
    assert "release_metadata:" in workflow
    assert 'elif ref_name == f"v{gateway_version}":' in workflow
    assert 'elif ref_name == f"gpt2giga-harness-v{harness_version}":' in workflow
    assert "gateway_release:" in workflow
    assert "harness_release:" in workflow
    assert "environment: pypi-harness" in workflow
    assert "uv build --package gpt2giga --wheel --sdist --no-sources" in workflow
    assert (
        "uv build --package gpt2giga-harness --wheel --sdist --no-sources" in workflow
    )
    assert workflow.count("uses: actions/attest-build-provenance@v3") == 2
    assert "subject-path: dist/gpt2giga/*" in workflow
    assert "subject-path: dist/gpt2giga-harness/*" in workflow
    assert workflow.count("\\( -name '*.whl' -o -name '*.tar.gz' \\)") == 2
    assert '-name "gpt2giga-${GATEWAY_VERSION}*.whl"' in workflow
    assert '-name "gpt2giga-${GATEWAY_VERSION}.tar.gz"' in workflow
    assert '-name "gpt2giga_harness-${HARNESS_VERSION}*.whl"' in workflow
    assert '-name "gpt2giga_harness-${HARNESS_VERSION}.tar.gz"' in workflow
    assert (
        "uv pip install --prerelease allow --python "
        '.venv-release-check/bin/python "gpt2giga==${GATEWAY_VERSION}"' in workflow
    )
    assert gateway_version not in workflow
    assert harness_version not in workflow

    publish_commands = [
        line.strip()
        for line in workflow.splitlines()
        if line.strip().startswith("uv publish ")
    ]
    assert publish_commands == [
        'uv publish --token "${PYPI_TOKEN}" dist/gpt2giga/*',
        "uv publish --trusted-publishing always dist/gpt2giga-harness/*",
    ]
    assert workflow.count("secrets.PYPI_API_KEY") == 1


def test_split_install_and_namespace_migration_are_documented():
    if not HARNESS_MEMBER.exists():
        return

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    quickstart = (REPO_ROOT / "docs/quickstart.md").read_text(encoding="utf-8")
    harness_guide = (REPO_ROOT / "docs/harness.md").read_text(encoding="utf-8")
    root_instructions = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    harness_instructions = (HARNESS_MEMBER / "AGENTS.md").read_text(encoding="utf-8")

    for guide in (readme, quickstart):
        assert "uv tool install --prerelease allow gpt2giga" in guide
        assert "uv tool install --prerelease allow gpt2giga-harness" in guide
        assert "gpt2giga_harness" in guide

    assert "Migration from the Combined Prerelease" in harness_guide
    assert "from gpt2giga.harness.harnesses.base import BaseHarness" in harness_guide
    assert "from gpt2giga_harness.harnesses.base import BaseHarness" in harness_guide
    assert "python -m pip uninstall -y gpt2giga gpt2giga-harness" in harness_guide
    assert "`gpt2giga.harnesses`" in harness_guide
    assert "`~/.gpt2giga/harness`" in harness_guide
    assert "`.giga/`" in harness_guide

    for instructions in (root_instructions, harness_instructions):
        assert "uv sync --all-packages --all-extras --dev" in instructions
    assert "uv build --package gpt2giga" in root_instructions
    assert "uv build --package gpt2giga-harness" in root_instructions
    assert "gateway code must never import `gpt2giga_harness`" in root_instructions


def test_production_docker_build_remains_gateway_only():
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    docker_workflows = "\n".join(
        (REPO_ROOT / path).read_text(encoding="utf-8")
        for path in (
            ".github/workflows/docker-smoke.yaml",
            ".github/workflows/docker_image.yaml",
            ".github/workflows/publish-ghcr.yml",
        )
    )

    assert "uv build --package gpt2giga --wheel" in dockerfile
    assert "COPY packages/gpt2giga/README.md packages/gpt2giga/README.md" in dockerfile
    assert "packages/gpt2giga-harness" not in dockerfile
    assert "gpt2giga_harness" not in dockerfile
    assert "packages/gpt2giga-harness" not in docker_workflows
    assert "- 'uv.lock'" not in docker_workflows
