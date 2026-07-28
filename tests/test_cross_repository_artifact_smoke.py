"""Cross-repository artifact smoke owned by krakenalt/gigaloom.

Manual candidate invocation:

GIGALOOM_GATEWAY_CANDIDATE_WHEEL=/absolute/path/gpt2giga.whl
GIGALOOM_GATEWAY_CANDIDATE_SHA256=<sha256>
GIGALOOM_GATEWAY_CANDIDATE_VERSION=<exact-version>
uv run pytest tests/test_cross_repository_artifact_smoke.py -q -n 0
"""

import hashlib
import os
from pathlib import Path

import pytest

from package_isolation_support import (
    BuiltArtifacts,
    GATEWAY_VERSION,
    GPT2GIGA_PRESET_SMOKE,
    _build_artifacts,
    _build_member,
    _install_checksum_bound_artifacts,
    _run_clean_python,
)


FUTURE_REPOSITORY_OWNER = "krakenalt/gigaloom"
_CANDIDATE_INPUTS = {
    "wheel": "GIGALOOM_GATEWAY_CANDIDATE_WHEEL",
    "sha256": "GIGALOOM_GATEWAY_CANDIDATE_SHA256",
    "version": "GIGALOOM_GATEWAY_CANDIDATE_VERSION",
}


@pytest.fixture(scope="module")
def built_artifacts(tmp_path_factory) -> BuiltArtifacts:
    return _build_artifacts(tmp_path_factory)


def _manual_gateway_candidate() -> tuple[Path, str, str]:
    values = {
        name: os.environ.get(variable) for name, variable in _CANDIDATE_INPUTS.items()
    }
    if not any(values.values()):
        pytest.skip(
            "manual gateway candidate not provided; no workspace artifact fallback"
        )
    missing = [
        variable for name, variable in _CANDIDATE_INPUTS.items() if not values[name]
    ]
    if missing:
        pytest.fail(f"incomplete manual gateway candidate inputs: {', '.join(missing)}")
    wheel = Path(values["wheel"]).expanduser().resolve()
    if not wheel.is_file() or wheel.suffix != ".whl":
        pytest.fail("manual gateway candidate must be an existing wheel")
    if values["version"] != GATEWAY_VERSION:
        pytest.fail(
            "manual gateway candidate version does not match the exact optional dependency"
        )
    return wheel, values["sha256"], values["version"]


@pytest.mark.parametrize("artifact_kind", ["wheel", "sdist"])
def test_monorepo_artifacts_model_checksum_bound_cross_repository_install(
    built_artifacts: BuiltArtifacts,
    tmp_path,
    artifact_kind: str,
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
    _install_checksum_bound_artifacts(
        installed,
        {
            gateway_artifact: hashlib.sha256(gateway_artifact.read_bytes()).hexdigest(),
            harness_artifact: hashlib.sha256(harness_artifact.read_bytes()).hexdigest(),
        },
    )
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


def test_manual_gateway_candidate_never_falls_back_to_workspace_source(tmp_path):
    gateway_wheel, gateway_sha256, gateway_version = _manual_gateway_candidate()
    assert gateway_version == GATEWAY_VERSION

    harness_dist = tmp_path / "harness-dist"
    harness_dist.mkdir()
    harness_wheel, _ = _build_member("gpt2giga-harness", harness_dist)
    installed = tmp_path / "installed"
    _install_checksum_bound_artifacts(
        installed,
        {
            gateway_wheel: gateway_sha256,
            harness_wheel: hashlib.sha256(harness_wheel.read_bytes()).hexdigest(),
        },
    )
    _run_clean_python(installed, GPT2GIGA_PRESET_SMOKE)
