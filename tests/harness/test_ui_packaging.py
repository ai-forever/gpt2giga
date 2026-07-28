import os
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
            "gpt2giga",
            "--wheel",
            "--out-dir",
            str(dist_dir),
        ],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
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
    wheel_path = next(dist_dir.glob("gpt2giga-*.whl"))
    harness_wheel_path = next(dist_dir.glob("gpt2giga_harness-*.whl"))
    installed_root = tmp_path / "installed"
    with zipfile.ZipFile(wheel_path) as wheel:
        wheel.extractall(installed_root)
    with zipfile.ZipFile(harness_wheel_path) as wheel:
        wheel.extractall(installed_root)

    smoke = """
import importlib.util
from pathlib import Path

import gpt2giga
import gpt2giga_harness
from gpt2giga_harness.ui.cockpit_v2 import load_cockpit_v2_manifest, load_cockpit_v2_shell

installed_root = Path(__import__("sys").argv[1]).resolve()
assert Path(gpt2giga.__file__).resolve().is_relative_to(installed_root)
assert Path(gpt2giga_harness.__file__).resolve().is_relative_to(installed_root)
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


def test_harness_sdist_omits_frontend_build_toolchain(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    dist_dir = tmp_path / "dist"
    subprocess.run(
        [
            "uv",
            "build",
            "--package",
            "gpt2giga-harness",
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

    with tarfile.open(archive, "r:gz") as source:
        members = source.getnames()

    assert not any("/frontend/" in name for name in members)
    assert not any("/ui/assets/" in name for name in members)
    assert any("/ui/cockpit_v2/assets/manifest.json" in name for name in members)
