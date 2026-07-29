"""Transitional artifact helpers used by future repository-owned suites."""

import ast
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

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
NEUTRAL_HARNESS_ENTRY_POINT_GROUP = "agent_workbench.harness_adapters.v1"


def _project_metadata(root: Path) -> dict:
    with (root / "pyproject.toml").open("rb") as file:
        return tomllib.load(file)["project"]


_HARNESS_METADATA = _project_metadata(REPO_ROOT)
HARNESS_VERSION = _HARNESS_METADATA["version"]
HARNESS_DESCRIPTION = _HARNESS_METADATA["description"]


def _optional_gateway_version() -> str:
    with (REPO_ROOT / "pyproject.toml").open("rb") as file:
        metadata = tomllib.load(file)
    requirement = metadata["project"]["optional-dependencies"]["gpt2giga"][0]
    prefix = "gpt2giga=="
    if not requirement.startswith(prefix):
        raise ValueError("GigaLoom gateway compatibility dependency must be exact")
    return requirement.removeprefix(prefix)


GATEWAY_VERSION = _optional_gateway_version()
IMPORT_DISTRIBUTIONS = {
    "anyio": "anyio",
    "dateutil": "python-dateutil",
    "fastapi": "fastapi",
    "gigachat": "gigachat",
    "gpt2giga": "gpt2giga",
    "jwt": "pyjwt",
    "pydantic": "pydantic",
    "starlette": "starlette",
    "textual": "textual",
    "tomli": "tomli",
    "uvicorn": "uvicorn",
    "yaml": "pyyaml",
}


@dataclass(frozen=True)
class BuiltArtifacts:
    gateway_wheel: Path | None
    gateway_sdist: Path | None
    harness_wheel: Path
    harness_sdist: Path


def _run(*command: str, cwd: Path = REPO_ROOT) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"command {command!r} failed with {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def _build_member(package: str, output: Path) -> tuple[Path, Path]:
    _run(
        "uv",
        "build",
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


def _build_artifacts(tmp_path_factory) -> BuiltArtifacts:
    root = tmp_path_factory.mktemp("workspace-artifacts")
    direct = root / "direct"
    direct.mkdir()
    gateway_wheel = gateway_sdist = None
    if GATEWAY_MEMBER.is_dir():
        gateway_wheel, gateway_sdist = _build_member("gpt2giga", direct)
    harness_wheel, harness_sdist = _build_member("gigaloom", direct)
    return BuiltArtifacts(
        gateway_wheel=gateway_wheel,
        gateway_sdist=gateway_sdist,
        harness_wheel=harness_wheel,
        harness_sdist=harness_sdist,
    )


@pytest.fixture(scope="module")
def built_artifacts(tmp_path_factory) -> BuiltArtifacts:
    return _build_artifacts(tmp_path_factory)


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


def _install_checksum_bound_artifacts(
    target: Path,
    artifacts: dict[Path, str],
) -> None:
    for artifact, expected_sha256 in artifacts.items():
        if len(expected_sha256) != 64:
            raise ValueError(f"invalid SHA-256 for candidate artifact: {artifact.name}")
        actual_sha256 = hashlib.sha256(artifact.read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError(f"candidate artifact digest changed: {artifact.name}")
    _install_artifacts(target, *artifacts)


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
    env["EXPECTED_HARNESS_DESCRIPTION"] = HARNESS_DESCRIPTION
    env["EXPECTED_HARNESS_VERSION"] = HARNESS_VERSION
    result = subprocess.run(
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
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"isolated artifact smoke failed with {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
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


HARNESS_BASE_SMOKE = """
import importlib.metadata
import json
import os
from pathlib import Path
import stat
import sys

from fastapi.testclient import TestClient

class BlockPresetImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in {"gpt2giga", "gigachat"}:
            raise ModuleNotFoundError(fullname)
        return None


sys.meta_path.insert(0, BlockPresetImports())

import gpt2giga_harness
from gpt2giga_harness.cli import build_parser
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.doctor import write_doctor_support_report
from gpt2giga_harness.environments import EnvironmentProviderRegistry
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.skills_catalog_proxy import create_skills_catalog_proxy_app
from gpt2giga_harness.skills_catalog_proxy_client import SkillsCatalogProxyFetcher
from gpt2giga_harness.state_backup import (
    create_state_backup,
    restore_state_backup,
    verify_state_backup,
)
from gpt2giga_harness.ui.app import create_app
from gpt2giga_harness.ui.cockpit_v2 import (
    load_cockpit_v2_manifest,
    load_cockpit_v2_shell,
)
from gpt2giga_harness.types import HarnessContext, HarnessRequest

assert Path(gpt2giga_harness.__file__).resolve().is_relative_to(installed_root)
assert "gpt2giga" not in sys.modules
assert "gigachat" not in sys.modules
harness_distribution = importlib.metadata.distribution("gigaloom")
assert harness_distribution.version == os.environ["EXPECTED_HARNESS_VERSION"]
assert (
    harness_distribution.metadata["Summary"]
    == os.environ["EXPECTED_HARNESS_DESCRIPTION"]
)
requirements = harness_distribution.requires or ()
assert not any(
    requirement.startswith(("gpt2giga", "gigachat"))
    and "extra ==" not in requirement
    for requirement in requirements
)
assert any(
    requirement.startswith(f"gpt2giga=={os.environ['EXPECTED_GATEWAY_VERSION']}")
    and "extra ==" in requirement
    for requirement in requirements
)
assert any(
    requirement.startswith("textual")
    and ">=8.2.8" in requirement
    and "extra ==" not in requirement
    for requirement in requirements
)
assert "tui" not in harness_distribution.metadata.get_all("Provides-Extra", [])
scripts = {
    entry.name: entry.value
    for entry in harness_distribution.entry_points
    if entry.group == "console_scripts"
}
assert scripts == {
    "giga": "gpt2giga_harness.entrypoint:main",
    "giga-skills-catalog-proxy": "gpt2giga_harness.skills_catalog_proxy:main",
    "gpt2giga-harness": "gpt2giga_harness.entrypoint:main",
}
environment_entry_points = {
    entry.name: entry.value
    for entry in harness_distribution.entry_points
    if entry.group == "agent_workbench.environment_providers.v1"
}
assert environment_entry_points == {
    "git": "gpt2giga_harness.environments:git_environment_provider_plugin"
}
environment_registry = EnvironmentProviderRegistry.with_builtins()
environment_registry.load_entry_points()
assert [item.id for item in environment_registry.list()] == ["git"]
assert environment_registry.discovery_errors == []
proxy_client = TestClient(create_skills_catalog_proxy_app())
assert proxy_client.get("/healthz").json()["read_only"] is True
assert SkillsCatalogProxyFetcher("https://proxy.example").proxy_origin == (
    "https://proxy.example"
)
harness_entry_points = {
    entry.group: entry.value
    for entry in harness_distribution.entry_points
    if entry.name == "echo"
    and entry.group
    in {
        "agent_workbench.harness_adapters.v1",
        "gpt2giga.harnesses",
    }
}
assert harness_entry_points == {
    "agent_workbench.harness_adapters.v1": (
        "gpt2giga_harness.harnesses.echo:EchoHarness"
    ),
    "gpt2giga.harnesses": "gpt2giga_harness.harnesses.echo:EchoHarness",
}
registry = create_default_registry(include_entry_points=False)
echo = registry.get("echo").run(
    HarnessRequest(prompt="provider-neutral smoke"),
    HarnessContext(proxy_url="http://127.0.0.1:9"),
)
assert echo.ok is True
assert echo.text == "provider-neutral smoke"
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
manifest = load_cockpit_v2_manifest()
assert manifest.entry == "index.html"
assert "<title>GigaLoom</title>" in load_cockpit_v2_shell()

data_dir = installed_root.parent / "runtime-smoke-state"
client = TestClient(
    create_app(HarnessConfig(data_dir=str(data_dir))),
    base_url="http://127.0.0.1",
    client=("127.0.0.1", 50000),
)
assert client.get("/healthz").status_code == 200
shell = client.get("/")
assert shell.status_code == 200
assert "GigaLoom" in shell.text
assert client.get("/legacy", follow_redirects=False).status_code == 404
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


GPT2GIGA_PRESET_SMOKE = """
import importlib.metadata
import os
from pathlib import Path

import gpt2giga
import gpt2giga_harness
from gpt2giga_harness.gpt2giga_preset import require_gpt2giga_preset

assert Path(gpt2giga.__file__).resolve().is_relative_to(installed_root)
assert Path(gpt2giga_harness.__file__).resolve().is_relative_to(installed_root)
assert importlib.metadata.version("gpt2giga") == os.environ["EXPECTED_GATEWAY_VERSION"]
runtime = require_gpt2giga_preset()
assert runtime.client_type.__module__.split(".", 1)[0] == "gigachat"
assert runtime.load_config.__module__ == "gpt2giga.cli"
"""


NEUTRAL_PLUGIN_SMOKE = """
import importlib.metadata

from gpt2giga_harness.registry import create_default_registry

distribution = importlib.metadata.distribution("neutral-harness-plugin")
entry_points = {
    entry.name: entry.value
    for entry in distribution.entry_points
    if entry.group == "agent_workbench.harness_adapters.v1"
}
assert entry_points == {
    "neutral-wheel": "neutral_harness_plugin:NeutralWheelHarness"
}

registry = create_default_registry()
assert registry.get("neutral-wheel").spec().title == "Neutral Wheel"
assert registry.discovery_errors == []
"""


def _build_neutral_plugin(root: Path) -> Path:
    project = root / "neutral-plugin"
    package = project / "src" / "neutral_harness_plugin"
    package.mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        f"""[project]
name = "neutral-harness-plugin"
version = "1.0.0"
requires-python = ">=3.10"

[project.entry-points."{NEUTRAL_HARNESS_ENTRY_POINT_GROUP}"]
neutral-wheel = "neutral_harness_plugin:NeutralWheelHarness"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/neutral_harness_plugin"]
""",
        encoding="utf-8",
    )
    (package / "__init__.py").write_text(
        """from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.types import (
    Availability,
    HarnessCapability,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
)


class NeutralWheelHarness(BaseHarness):
    @classmethod
    def spec(cls):
        return HarnessSpec(
            id="neutral-wheel",
            title="Neutral Wheel",
            kind="custom",
            description="Out-of-tree neutral registry smoke",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
        )

    def availability(self):
        return Availability.available("isolated wheel")

    def run(self, request: HarnessRequest, context):
        return HarnessResult(ok=True, text=request.prompt)
""",
        encoding="utf-8",
    )
    output = root / "neutral-plugin-dist"
    _run("uv", "build", "--wheel", "--out-dir", str(output), cwd=project)
    return next(output.glob("neutral_harness_plugin-*.whl"))


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
def test_harness_base_artifact_runs_without_provider_preset(
    built_artifacts: BuiltArtifacts, tmp_path, artifact_kind: str
):
    harness_artifact = (
        built_artifacts.harness_wheel
        if artifact_kind == "wheel"
        else built_artifacts.harness_sdist
    )
    installed = tmp_path / "installed"
    _install_artifacts(installed, harness_artifact)
    _run_clean_python(installed, HARNESS_BASE_SMOKE)


@pytest.mark.parametrize("artifact_kind", ["wheel", "sdist"])
def test_gpt2giga_preset_artifacts_restore_gateway_runtime(
    built_artifacts: BuiltArtifacts, tmp_path, artifact_kind: str
):
    gateway_artifact = (
        built_artifacts.gateway_wheel
        if artifact_kind == "wheel"
        else built_artifacts.gateway_sdist
    )
    harness_artifact = (
        built_artifacts.harness_wheel
        if artifact_kind == "wheel"
        else built_artifacts.harness_sdist
    )
    installed = tmp_path / "installed"
    candidate_artifacts = {
        gateway_artifact: hashlib.sha256(gateway_artifact.read_bytes()).hexdigest(),
        harness_artifact: hashlib.sha256(harness_artifact.read_bytes()).hexdigest(),
    }
    _install_checksum_bound_artifacts(installed, candidate_artifacts)
    _run_clean_python(installed, GPT2GIGA_PRESET_SMOKE)


def test_candidate_artifact_digest_mismatch_fails_before_install(
    built_artifacts: BuiltArtifacts,
    tmp_path,
):
    installed = tmp_path / "installed"
    with pytest.raises(ValueError, match="candidate artifact digest changed"):
        _install_checksum_bound_artifacts(
            installed,
            {built_artifacts.gateway_wheel: "0" * 64},
        )
    assert not installed.exists()


def test_neutral_third_party_wheel_registers_without_core_edits(
    built_artifacts: BuiltArtifacts,
    tmp_path,
):
    plugin_wheel = _build_neutral_plugin(tmp_path)
    installed = tmp_path / "installed"
    _install_artifacts(installed, built_artifacts.harness_wheel, plugin_wheel)
    _run_clean_python(installed, NEUTRAL_PLUGIN_SMOKE)


def test_editable_workspace_members_resolve_to_member_sources():
    import gpt2giga
    import gpt2giga_harness

    assert Path(gpt2giga.__file__).resolve().is_relative_to(GATEWAY_MEMBER / "src")
    assert (
        Path(gpt2giga_harness.__file__).resolve().is_relative_to(HARNESS_MEMBER / "src")
    )
    assert importlib.metadata.version("gpt2giga") == GATEWAY_VERSION
    assert importlib.metadata.version("gigaloom") == HARNESS_VERSION


def _declared_distribution_names(metadata: dict) -> set[str]:
    names = set()
    for requirement in metadata["project"]["dependencies"]:
        name = requirement.split(";", 1)[0].strip()
        for separator in ("<", ">", "=", "!", "~", "["):
            name = name.split(separator, 1)[0]
        names.add(name.strip().lower())
    return names


def _all_declared_distribution_names(metadata: dict) -> set[str]:
    names = _declared_distribution_names(metadata)
    for requirements in metadata["project"].get("optional-dependencies", {}).values():
        for requirement in requirements:
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
    with (REPO_ROOT / "pyproject.toml").open("rb") as file:
        declared = _all_declared_distribution_names(tomllib.load(file))
    imported = _external_import_roots(HARNESS_SOURCE, "gpt2giga_harness")
    unknown_roots = imported - IMPORT_DISTRIBUTIONS.keys()
    assert unknown_roots == set()
    assert {IMPORT_DISTRIBUTIONS[root] for root in imported} <= declared


def test_optional_and_development_dependencies_stay_with_their_owner():
    with (REPO_ROOT / "pyproject.toml").open("rb") as file:
        root_metadata = tomllib.load(file)
    harness_metadata = root_metadata

    assert root_metadata["project"]["name"] == "gigaloom"
    assert root_metadata["project"]["description"]
    assert set(root_metadata["dependency-groups"]) == {"dev", "integrations"}
    assert "sources" not in harness_metadata.get("tool", {}).get("uv", {})
    assert harness_metadata["project"]["optional-dependencies"] == {
        "claude-sdk": ["claude-agent-sdk>=0.2.122,<0.3"],
        "gpt2giga": [
            f"gpt2giga=={GATEWAY_VERSION}",
            "gigachat>=0.2.2a1,<0.3.0",
        ],
    }
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
    assert gateway_imports == set()
    proxy_source = (HARNESS_SOURCE / "proxy.py").read_text(encoding="utf-8")
    assert "from gpt2giga import run; run()" in proxy_source


def test_all_late_bound_gateway_imports_are_characterized():
    late_bound_imports: set[tuple[str, str]] = set()
    for path in HARNESS_SOURCE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative_path = path.relative_to(HARNESS_SOURCE).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            function_name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else None
            )
            if function_name == "import_module":
                module = node.args[0]
                if (
                    isinstance(module, ast.Constant)
                    and isinstance(module.value, str)
                    and module.value.startswith("gpt2giga.")
                ):
                    late_bound_imports.add((relative_path, module.value))
            for argument in ast.walk(node.args[0]):
                if (
                    isinstance(argument, ast.Constant)
                    and isinstance(argument.value, str)
                    and "from gpt2giga import" in argument.value
                ):
                    late_bound_imports.add((relative_path, argument.value))

    assert late_bound_imports == {
        ("gpt2giga_preset.py", "gpt2giga.cli"),
        ("openai_upstream.py", "gpt2giga.providers.openai_compatible"),
        ("proxy.py", "from gpt2giga import run; run()"),
    }


def _write_minimal_plugin(source_root: Path) -> None:
    package = source_root / "src/example_harness_plugin"
    package.mkdir(parents=True)
    (source_root / "pyproject.toml").write_text(
        f"""[project]
name = "example-harness-plugin"
version = "1.0.0"
requires-python = ">=3.10"
dependencies = ["gigaloom=={HARNESS_VERSION}"]

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


def _artifact_members(path: Path) -> tuple[str, ...]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return tuple(archive.namelist())
    with tarfile.open(path) as archive:
        return tuple(archive.getnames())


@pytest.mark.parametrize(
    ("artifact_attribute", "forbidden_package"),
    [
        ("gateway_wheel", "gpt2giga_harness"),
        ("gateway_sdist", "gpt2giga_harness"),
        ("harness_wheel", "gpt2giga"),
        ("harness_sdist", "gpt2giga"),
    ],
)
def test_artifacts_do_not_package_the_other_distribution(
    built_artifacts: BuiltArtifacts,
    artifact_attribute: str,
    forbidden_package: str,
):
    artifact = getattr(built_artifacts, artifact_attribute)
    violations = [
        name
        for name in _artifact_members(artifact)
        if forbidden_package in Path(name).parts
    ]
    assert violations == []
