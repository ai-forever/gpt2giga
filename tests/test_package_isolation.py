import ast
from dataclasses import dataclass
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

from gpt2giga_harness.base_install import BASE_DIRECT_DISTRIBUTIONS

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib


REPO_ROOT = Path(__file__).resolve().parents[1]
GATEWAY_MEMBER = REPO_ROOT / "packages/gpt2giga"
HARNESS_MEMBER = REPO_ROOT / "packages/gpt2giga-harness"
HARNESS_SOURCE = HARNESS_MEMBER / "src/gpt2giga_harness"


def _project_version(member: Path) -> str:
    with (member / "pyproject.toml").open("rb") as file:
        return tomllib.load(file)["project"]["version"]


GATEWAY_VERSION = _project_version(GATEWAY_MEMBER)
HARNESS_VERSION = _project_version(HARNESS_MEMBER)
IMPORT_DISTRIBUTIONS = {
    "anyio": "anyio",
    "dateutil": "python-dateutil",
    "fastapi": "fastapi",
    "gigachat": "gigachat",
    "gpt2giga": "gpt2giga",
    "pydantic": "pydantic",
    "starlette": "starlette",
    "tomli": "tomli",
    "uvicorn": "uvicorn",
    "yaml": "pyyaml",
}


@dataclass(frozen=True)
class BuiltArtifacts:
    gateway_wheel: Path
    gateway_sdist: Path
    harness_wheel: Path
    harness_sdist: Path


def _run(*command: str, cwd: Path = REPO_ROOT) -> None:
    subprocess.run(
        command,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _build_member(package: str, output: Path) -> tuple[Path, Path]:
    _run(
        "uv",
        "build",
        "--package",
        package,
        "--wheel",
        "--sdist",
        "--no-sources",
        "--out-dir",
        str(output),
    )
    wheel_prefix = package.replace("-", "_")
    wheel = next(output.glob(f"{wheel_prefix}-*.whl"))
    sdist = next(output.glob(f"{wheel_prefix}-*.tar.gz"))
    return wheel, sdist


@pytest.fixture(scope="module")
def built_artifacts(tmp_path_factory) -> BuiltArtifacts:
    root = tmp_path_factory.mktemp("workspace-artifacts")
    direct = root / "direct"
    direct.mkdir()
    gateway_wheel, gateway_sdist = _build_member("gpt2giga", direct)
    harness_wheel, harness_sdist = _build_member("gpt2giga-harness", direct)
    return BuiltArtifacts(
        gateway_wheel=gateway_wheel,
        gateway_sdist=gateway_sdist,
        harness_wheel=harness_wheel,
        harness_sdist=harness_sdist,
    )


def _install_artifacts(target: Path, *artifacts: Path) -> None:
    _run(
        "uv",
        "pip",
        "install",
        "--target",
        str(target),
        "--no-deps",
        *(str(artifact) for artifact in artifacts),
        cwd=target.parent,
    )


def _run_clean_python(target: Path, source: str) -> None:
    dependency_paths = [
        path
        for path in sys.path
        if path and Path(path).name in {"site-packages", "dist-packages"}
    ]
    bootstrap = (
        """
import json
from pathlib import Path
import sys

installed_root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(installed_root))
sys.path.extend(json.loads(sys.argv[2]))
"""
        + source
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["EXPECTED_GATEWAY_VERSION"] = GATEWAY_VERSION
    env["EXPECTED_HARNESS_VERSION"] = HARNESS_VERSION
    subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            bootstrap,
            str(target),
            json.dumps(dependency_paths),
        ],
        cwd=target.parent,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


GATEWAY_SMOKE = """
import importlib.metadata
import importlib.util
import os
from pathlib import Path

from fastapi.testclient import TestClient

import gpt2giga
from gpt2giga.app.factory import create_app
from gpt2giga.models.config import ProxyConfig

assert Path(gpt2giga.__file__).resolve().is_relative_to(installed_root)
assert importlib.util.find_spec("gpt2giga_harness") is None
distribution = importlib.metadata.distribution("gpt2giga")
assert distribution.version == os.environ["EXPECTED_GATEWAY_VERSION"]
scripts = {
    entry.name: entry.value
    for entry in distribution.entry_points
    if entry.group == "console_scripts"
}
assert scripts == {"gpt2giga": "gpt2giga:run"}

client = TestClient(create_app(ProxyConfig()))
assert client.get("/health").status_code == 200
openapi = client.get("/openapi.json")
assert openapi.status_code == 200
paths = openapi.json()["paths"]
assert "/v1/chat/completions" in paths
assert "/v1/messages" in paths
assert "/v1beta/models/{model}:generateContent" in paths
"""


HARNESS_SMOKE = """
import importlib.metadata
import json
import os
from pathlib import Path
import stat

from fastapi.testclient import TestClient

import gpt2giga
import gpt2giga_harness
from gpt2giga_harness.cli import build_parser
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.doctor import write_doctor_support_report
from gpt2giga_harness.state_backup import (
    create_state_backup,
    restore_state_backup,
    verify_state_backup,
)
from gpt2giga_harness.ui.app import create_app
from gpt2giga_harness.ui.static import INDEX_HTML, load_text_asset

assert Path(gpt2giga.__file__).resolve().is_relative_to(installed_root)
assert Path(gpt2giga_harness.__file__).resolve().is_relative_to(installed_root)
assert importlib.metadata.version("gpt2giga") == os.environ["EXPECTED_GATEWAY_VERSION"]
harness_distribution = importlib.metadata.distribution("gpt2giga-harness")
assert harness_distribution.version == os.environ["EXPECTED_HARNESS_VERSION"]
assert (
    f"gpt2giga>={os.environ['EXPECTED_GATEWAY_VERSION']}"
    in (harness_distribution.requires or ())
)
scripts = {
    entry.name: entry.value
    for entry in harness_distribution.entry_points
    if entry.group == "console_scripts"
}
assert scripts == {
    "giga": "gpt2giga_harness.cli:main",
    "gpt2giga-harness": "gpt2giga_harness.cli:main",
}
doctor_output = installed_root.parent / "doctor-support.json"
doctor_args = build_parser().parse_args(
    ["doctor", ".", "--json", "--output", str(doctor_output), "--fail-on", "degraded"]
)
assert doctor_args.output == str(doctor_output)
assert doctor_args.fail_on == "degraded"
write_doctor_support_report(
    {
        "schema_version": 1,
        "kind": "gpt2giga_harness_doctor_report",
        "summary": {"ready": 1, "degraded": 0, "blocked": 0},
        "checks": [],
    },
    doctor_output,
)
assert json.loads(doctor_output.read_text(encoding="utf-8"))["schema_version"] == 1
assert stat.S_IMODE(doctor_output.stat().st_mode) == 0o600
assert "function boot()" in load_text_asset("app.js")
assert ".app {" in load_text_asset("app.css")

data_dir = installed_root.parent / "runtime-smoke-state"
client = TestClient(
    create_app(HarnessConfig(data_dir=str(data_dir))),
    base_url="http://127.0.0.1",
    client=("127.0.0.1", 50000),
)
assert client.get("/healthz").status_code == 200
shell = client.get("/")
assert shell.status_code == 200
assert "gpt2giga Harness" in shell.text
assert client.get("/assets/app.css").status_code == 200
harnesses = client.get("/api/harnesses")
assert harnesses.status_code == 200
ids = {item["spec"]["id"] for item in harnesses.json()["harnesses"]}
assert {"direct-chat", "echo"} <= ids

backup = installed_root.parent / "runtime-smoke-backup.zip"
created = create_state_backup(data_dir, backup)
assert created == verify_state_backup(backup)
restored = installed_root.parent / "runtime-smoke-restored"
restore_result = restore_state_backup(backup, restored)
assert restore_result.backup == created
assert restore_result.replaced_existing is False
assert (restored / "runtime.sqlite3").is_file()
"""


@pytest.mark.parametrize("artifact_kind", ["wheel", "sdist"])
def test_gateway_artifact_is_isolated(
    built_artifacts: BuiltArtifacts, tmp_path, artifact_kind: str
):
    wheel = (
        built_artifacts.gateway_wheel
        if artifact_kind == "wheel"
        else built_artifacts.gateway_sdist
    )
    installed = tmp_path / "installed"
    _install_artifacts(installed, wheel)
    _run_clean_python(installed, GATEWAY_SMOKE)


@pytest.mark.parametrize("artifact_kind", ["wheel", "sdist"])
def test_harness_artifact_resolves_gateway_without_repository_leakage(
    built_artifacts: BuiltArtifacts, tmp_path, artifact_kind: str
):
    if artifact_kind == "wheel":
        gateway_wheel = built_artifacts.gateway_wheel
        harness_wheel = built_artifacts.harness_wheel
    else:
        gateway_wheel = built_artifacts.gateway_sdist
        harness_wheel = built_artifacts.harness_sdist
    installed = tmp_path / "installed"
    _install_artifacts(installed, gateway_wheel, harness_wheel)
    _run_clean_python(installed, HARNESS_SMOKE)


def test_editable_workspace_members_resolve_to_member_sources():
    import gpt2giga
    import gpt2giga_harness

    assert Path(gpt2giga.__file__).resolve().is_relative_to(GATEWAY_MEMBER / "src")
    assert (
        Path(gpt2giga_harness.__file__).resolve().is_relative_to(HARNESS_MEMBER / "src")
    )
    assert importlib.metadata.version("gpt2giga") == GATEWAY_VERSION
    assert importlib.metadata.version("gpt2giga-harness") == HARNESS_VERSION


def _declared_distribution_names(metadata: dict) -> set[str]:
    names = set()
    for requirement in metadata["project"]["dependencies"]:
        name = requirement.split(";", 1)[0].strip()
        for separator in ("<", ">", "=", "!", "~", "["):
            name = name.split(separator, 1)[0]
        names.add(name.strip().lower())
    return names


def _external_import_roots(source_root: Path, own_package: str) -> set[str]:
    roots: set[str] = set()
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules.append(node.module)
            for module in modules:
                root = module.split(".", 1)[0]
                if (
                    root != own_package
                    and root not in sys.stdlib_module_names
                    and root != "tomllib"
                ):
                    roots.add(root)
    return roots


def test_harness_imports_only_declared_distributions():
    with (HARNESS_MEMBER / "pyproject.toml").open("rb") as file:
        declared = _declared_distribution_names(tomllib.load(file))
    imported = _external_import_roots(HARNESS_SOURCE, "gpt2giga_harness")
    unknown_roots = imported - IMPORT_DISTRIBUTIONS.keys()
    assert unknown_roots == set()
    assert {IMPORT_DISTRIBUTIONS[root] for root in imported} <= declared


def test_optional_and_development_dependencies_stay_with_their_owner():
    with (REPO_ROOT / "pyproject.toml").open("rb") as file:
        root_metadata = tomllib.load(file)
    with (GATEWAY_MEMBER / "pyproject.toml").open("rb") as file:
        gateway_metadata = tomllib.load(file)
    with (HARNESS_MEMBER / "pyproject.toml").open("rb") as file:
        harness_metadata = tomllib.load(file)

    assert "project" not in root_metadata
    assert set(root_metadata["dependency-groups"]) == {"dev", "integrations"}
    assert set(gateway_metadata["project"]["optional-dependencies"]) == {
        "opensearch",
        "phoenix",
        "postgres",
    }
    assert "optional-dependencies" not in harness_metadata["project"]
    assert _declared_distribution_names(harness_metadata) == set(
        BASE_DIRECT_DISTRIBUTIONS
    )


def test_harness_gateway_imports_stay_within_the_reviewed_boundary():
    gateway_imports: set[str] = set()
    for path in HARNESS_SOURCE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "gpt2giga" or node.module.startswith("gpt2giga."):
                    gateway_imports.add(node.module)
            elif isinstance(node, ast.Import):
                gateway_imports.update(
                    alias.name
                    for alias in node.names
                    if alias.name == "gpt2giga" or alias.name.startswith("gpt2giga.")
                )
    assert gateway_imports == {
        "gpt2giga.cli",
        "gpt2giga.protocols.normalized",
        "gpt2giga.protocols.normalized.models",
    }
    proxy_source = (HARNESS_SOURCE / "proxy.py").read_text(encoding="utf-8")
    assert "from gpt2giga import run; run()" in proxy_source


def _write_minimal_plugin(source_root: Path) -> None:
    package = source_root / "src/example_harness_plugin"
    package.mkdir(parents=True)
    (source_root / "pyproject.toml").write_text(
        f"""[project]
name = "example-harness-plugin"
version = "1.0.0"
requires-python = ">=3.10"
dependencies = ["gpt2giga-harness=={HARNESS_VERSION}"]

[project.entry-points."gpt2giga.harnesses"]
third-party-smoke = "example_harness_plugin:ThirdPartyHarness"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/example_harness_plugin"]
""",
        encoding="utf-8",
    )
    (package / "__init__.py").write_text(
        """from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.types import (
    Availability,
    HarnessCapability,
    HarnessResult,
    HarnessSpec,
)


class ThirdPartyHarness(BaseHarness):
    @classmethod
    def spec(cls):
        return HarnessSpec(
            id="third-party-smoke",
            title="Third-party smoke",
            kind="custom",
            description="Artifact isolation smoke plugin",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
        )

    def availability(self):
        return Availability.available("installed artifact")

    def run(self, request, context):
        return HarnessResult(ok=True, text=request.prompt)
""",
        encoding="utf-8",
    )


def test_installed_third_party_plugin_is_discovered(
    built_artifacts: BuiltArtifacts, tmp_path
):
    plugin_source = tmp_path / "plugin-source"
    _write_minimal_plugin(plugin_source)
    plugin_dist = tmp_path / "plugin-dist"
    _run(
        "uv",
        "build",
        str(plugin_source),
        "--wheel",
        "--no-sources",
        "--out-dir",
        str(plugin_dist),
    )
    installed = tmp_path / "installed"
    _install_artifacts(
        installed,
        built_artifacts.gateway_wheel,
        built_artifacts.harness_wheel,
        next(plugin_dist.glob("example_harness_plugin-*.whl")),
    )
    _run_clean_python(
        installed,
        """
from gpt2giga_harness.registry import create_default_registry

registry = create_default_registry()
assert "third-party-smoke" in registry.ids()
assert registry.discovery_errors == []
""",
    )


def test_workspace_lock_is_current():
    _run("uv", "lock", "--check")


def test_sdists_are_self_contained(built_artifacts: BuiltArtifacts):
    for sdist in (built_artifacts.gateway_sdist, built_artifacts.harness_sdist):
        with tarfile.open(sdist) as archive:
            names = archive.getnames()
        assert any(name.endswith("/pyproject.toml") for name in names)
        assert any(name.endswith("/README.md") for name in names)
