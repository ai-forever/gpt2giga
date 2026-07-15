import os
from pathlib import Path
import subprocess
import sys
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
from pathlib import Path

import gpt2giga
import gpt2giga_harness
from gpt2giga_harness.ui.static import INDEX_HTML, load_text_asset

installed_root = Path(__import__("sys").argv[1]).resolve()
assert Path(gpt2giga.__file__).resolve().is_relative_to(installed_root)
assert Path(gpt2giga_harness.__file__).resolve().is_relative_to(installed_root)
assert '<link rel="stylesheet" href="/assets/app.css?v=38.38">' in INDEX_HTML
assert '<script src="/assets/app.js?v=38.43"></script>' in INDEX_HTML
assert "function boot()" in load_text_asset("app.js")
assert ".app {" in load_text_asset("app.css")
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
