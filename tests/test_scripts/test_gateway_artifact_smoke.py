"""Tests for the installed gateway artifact smoke policy."""

import importlib.util
from pathlib import Path

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "gateway_artifact_smoke.py"
)
SPEC = importlib.util.spec_from_file_location("gateway_artifact_smoke", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize(
    "version",
    ["0.2.3a1", "0.2.3b1", "0.2.3rc1", "0.2.3.dev1", "0.2.3-alpha1"],
)
def test_prerelease_sdk_versions_are_detected(version: str):
    assert MODULE._is_prerelease(version)


@pytest.mark.parametrize("version", ["0.2.3", "0.2.3.post1", "0.2.3+vendor"])
def test_stable_sdk_versions_are_accepted(version: str):
    assert not MODULE._is_prerelease(version)


def test_gigachat_metadata_requirement_is_order_independent():
    assert MODULE._gigachat_specifiers(
        ["fastapi>=0.140", "gigachat<0.3.0,>=0.2.4a1"]
    ) == {">=0.2.4a1", "<0.3.0"}


@pytest.mark.parametrize(
    "requirements",
    [[], ["fastapi>=0.140"], ["gigachat>=0.2.4a1", "gigachat<0.3.0"]],
)
def test_gigachat_metadata_requirement_must_be_unique(requirements: list[str]):
    with pytest.raises(MODULE.ArtifactSmokeError):
        MODULE._gigachat_specifiers(requirements)
