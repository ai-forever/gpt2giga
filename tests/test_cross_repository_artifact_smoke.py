"""Public gateway compatibility owned by krakenalt/gigaloom."""

import importlib.metadata
import importlib.util
from pathlib import Path
import tomllib

import pytest
from package_isolation_support import GATEWAY_VERSION


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _locked_packages() -> dict[str, dict]:
    with (REPOSITORY_ROOT / "uv.lock").open("rb") as file:
        lock = tomllib.load(file)
    return {package["name"]: package for package in lock["package"]}


def test_target_lock_resolves_exact_gateway_from_public_registry():
    packages = _locked_packages()
    assert packages["gpt2giga"]["version"] == GATEWAY_VERSION
    assert packages["gpt2giga"]["source"] == {"registry": "https://pypi.org/simple"}
    assert packages["gigaloom"]["source"] == {"editable": "packages/gpt2giga-harness"}
    assert all(
        package["source"] == {"registry": "https://pypi.org/simple"}
        for name, package in packages.items()
        if name != "gigaloom"
    )


def test_locked_public_gateway_restores_optional_runtime():
    if importlib.util.find_spec("gpt2giga") is None:
        pytest.skip("public gateway extra is exercised by the all-extras gate")

    from gpt2giga_harness.gpt2giga_preset import require_gpt2giga_preset

    assert importlib.metadata.version("gpt2giga") == GATEWAY_VERSION
    runtime = require_gpt2giga_preset()
    assert runtime.client_type.__module__.split(".", 1)[0] == "gigachat"
    assert runtime.load_config.__module__ == "gpt2giga.cli"
