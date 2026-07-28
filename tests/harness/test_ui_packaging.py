import os
import hashlib
from pathlib import Path
import subprocess
import sys
import tarfile
import zipfile


def test_packaged_ui_assets_survive_wheel_install(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    dist_dir = tmp_path / "dist"
    subprocess.run(
        [
            "uv",
            "build",
            "--package",
            "gpt2giga-harness",
            "--wheel",
            "--out-dir",
            str(dist_dir),
        ],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    harness_wheel_path = next(dist_dir.glob("gpt2giga_harness-*.whl"))
    installed_root = tmp_path / "installed"
    with zipfile.ZipFile(harness_wheel_path) as wheel:
        harness_members = set(wheel.namelist())
        assert any(
            name.endswith("/assets/_build/provenance.json") for name in harness_members
        )
        assert any(
            name.endswith("/assets/_build/sbom.cdx.json") for name in harness_members
        )
        assert any(
            name.endswith("/assets/_build/licenses.json") for name in harness_members
        )
        wheel.extractall(installed_root)

    smoke = """
import importlib.util
from pathlib import Path

import gpt2giga_harness
from gpt2giga_harness.ui.cockpit_v2 import load_cockpit_v2_manifest, load_cockpit_v2_shell

installed_root = Path(__import__("sys").argv[1]).resolve()
assert Path(gpt2giga_harness.__file__).resolve().is_relative_to(installed_root)
assert importlib.util.find_spec("gpt2giga") is None
assert importlib.util.find_spec("gpt2giga_harness.ui.static") is None
manifest = load_cockpit_v2_manifest()
assert manifest.entry == "index.html"
assert any(name.startswith("assets/workbench-") for name in manifest.assets)
assert any(name.startswith("assets/raw-evidence-") for name in manifest.assets)
assert "<title>GigaLoom</title>" in load_cockpit_v2_shell()
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(installed_root)
    subprocess.run(
        [sys.executable, "-c", smoke, str(installed_root)],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def test_harness_sdist_seals_assets_and_rebuilds_identical_node_free_wheel(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    dist_dir = tmp_path / "dist"
    subprocess.run(
        [
            "uv",
            "build",
            "--package",
            "gpt2giga-harness",
            "--wheel",
            "--sdist",
            "--no-sources",
            "--out-dir",
            str(dist_dir),
        ],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    archive = next(dist_dir.glob("gpt2giga_harness-*.tar.gz"))
    direct_wheel = next(dist_dir.glob("gpt2giga_harness-*.whl"))

    with tarfile.open(archive, "r:gz") as source:
        members = source.getnames()
        source.extractall(tmp_path / "source")

    assert not any("/frontend/" in name for name in members)
    assert not any("/ui/assets/" in name for name in members)
    assert any("/ui/cockpit_v2/assets/manifest.json" in name for name in members)
    assert any(
        "/ui/cockpit_v2/assets/_build/provenance.json" in name for name in members
    )
    assert any(name.endswith("/asset_contract.py") for name in members)
    assert any(name.endswith("/hatch_build.py") for name in members)

    extracted = next((tmp_path / "source").iterdir())
    rebuilt = tmp_path / "rebuilt"
    subprocess.run(
        [
            "uv",
            "build",
            "--wheel",
            "--no-sources",
            "--out-dir",
            str(rebuilt),
        ],
        cwd=extracted,
        check=True,
        capture_output=True,
        text=True,
    )
    rebuilt_wheel = next(rebuilt.glob("gpt2giga_harness-*.whl"))
    assert (
        hashlib.sha256(direct_wheel.read_bytes()).hexdigest()
        == hashlib.sha256(rebuilt_wheel.read_bytes()).hexdigest()
    )
