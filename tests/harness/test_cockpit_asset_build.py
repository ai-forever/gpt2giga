from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_ROOT = REPO_ROOT / "packages/gpt2giga-harness"
ASSET_ROOT = HARNESS_ROOT / "src/gpt2giga_harness/ui/cockpit_v2/assets"


def _contract_module():
    specification = importlib.util.spec_from_file_location(
        "gpt2giga_harness_asset_contract",
        HARNESS_ROOT / "asset_contract.py",
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _sealed_project(tmp_path: Path) -> Path:
    project = tmp_path / "sealed"
    destination = project / "src/gpt2giga_harness/ui/cockpit_v2/assets"
    shutil.copytree(ASSET_ROOT, destination)
    return project


def test_injected_cockpit_asset_tree_is_source_and_supply_chain_bound():
    contract = _contract_module()

    evidence = contract.verify_asset_tree(HARNESS_ROOT)

    assert evidence["asset_count"] >= 40
    assert len(evidence["output_sha256"]) == 64
    assert len(evidence["frontend_input_sha256"]) == 64
    assert len(evidence["sbom_sha256"]) == 64
    assert len(evidence["licenses_sha256"]) == 64
    assert len(evidence["source_revision"]) in {40, 64}


@pytest.mark.parametrize("mutation", ["missing", "modified", "unexpected"])
def test_injected_cockpit_asset_tree_fails_closed(
    tmp_path: Path,
    mutation: str,
):
    contract = _contract_module()
    project = _sealed_project(tmp_path)
    assets = project / contract.ASSET_RELATIVE_ROOT
    manifest = json.loads((assets / "manifest.json").read_text(encoding="utf-8"))
    target = assets / next(iter(manifest["assets"]))
    if mutation == "missing":
        target.unlink()
    elif mutation == "modified":
        target.write_bytes(target.read_bytes() + b"stale")
    else:
        (assets / "unexpected.js").write_text("shadow", encoding="utf-8")

    with pytest.raises(contract.AssetContractError, match="Recover with: npm"):
        contract.verify_asset_tree(project)


def test_injected_cockpit_asset_tree_rejects_symlinks(tmp_path: Path):
    contract = _contract_module()
    project = _sealed_project(tmp_path)
    assets = project / contract.ASSET_RELATIVE_ROOT
    link = assets / "shadow.js"
    try:
        link.symlink_to(assets / "index.html")
    except OSError:
        pytest.skip("symlinks are unavailable")

    with pytest.raises(contract.AssetContractError, match="symlink"):
        contract.verify_asset_tree(project)


def test_hatch_consumer_rejects_a_wheel_without_injected_assets(tmp_path: Path):
    project = tmp_path / "missing-assets"
    package = project / "src/example"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy2(HARNESS_ROOT / "asset_contract.py", project / "asset_contract.py")
    shutil.copy2(HARNESS_ROOT / "hatch_build.py", project / "hatch_build.py")
    (project / "pyproject.toml").write_text(
        """
[project]
name = "missing-cockpit-assets"
version = "0.0.0"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/example"]

[tool.hatch.build.hooks.custom]
path = "hatch_build.py"
""".lstrip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["uv", "build", "--wheel", "--no-sources"],
        cwd=project,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Cockpit injected asset directory is unavailable" in (
        result.stdout + result.stderr
    )
    assert "npm --prefix packages/gpt2giga-harness/frontend run build" in (
        result.stdout + result.stderr
    )
