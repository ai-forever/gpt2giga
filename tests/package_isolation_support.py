"""Gateway artifact helpers shared by repository-owned isolation tests."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
GATEWAY_MEMBER = REPO_ROOT / "packages/gpt2giga"


def _project_version(member: Path) -> str:
    with (member / "pyproject.toml").open("rb") as file:
        try:
            import tomllib
        except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
            import tomli as tomllib

        return tomllib.load(file)["project"]["version"]


GATEWAY_VERSION = _project_version(GATEWAY_MEMBER)


@dataclass(frozen=True)
class BuiltArtifacts:
    """Gateway wheel and source distribution built from this repository."""

    gateway_wheel: Path
    gateway_sdist: Path


def _run(*command: str, cwd: Path = REPO_ROOT) -> None:
    subprocess.run(
        command,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _build_artifacts(tmp_path_factory) -> BuiltArtifacts:
    output = tmp_path_factory.mktemp("gateway-artifacts")
    _run(
        "uv",
        "build",
        "--package",
        "gpt2giga",
        "--wheel",
        "--sdist",
        "--no-sources",
        "--out-dir",
        str(output),
    )
    return BuiltArtifacts(
        gateway_wheel=next(output.glob("gpt2giga-*.whl")),
        gateway_sdist=next(output.glob("gpt2giga-*.tar.gz")),
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


def _artifact_members(path: Path) -> tuple[str, ...]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return tuple(archive.namelist())
    with tarfile.open(path) as archive:
        return tuple(archive.getnames())


def test_workspace_lock_is_current() -> None:
    """Require the checked-in lock to match the gateway-only workspace."""

    _run("uv", "lock", "--check")
