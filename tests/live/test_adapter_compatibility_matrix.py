"""Opt-in installed-CLI compatibility matrix without executing user tasks."""

from __future__ import annotations

import os

import pytest

from gpt2giga_harness.evals import adapter_compatibility_matrix
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.types import GigaChatApiMode


pytestmark = [pytest.mark.integration, pytest.mark.live_native_cli]


def test_installed_cli_compatibility_matrix_uses_explicit_route():
    if os.getenv("GPT2GIGA_RUN_CLI_COMPAT_MATRIX") != "1":
        pytest.skip("set GPT2GIGA_RUN_CLI_COMPAT_MATRIX=1 to run installed CLI probes")
    route = os.getenv("GPT2GIGA_COMPAT_API_MODE")
    if route not in {"v1", "v2"}:
        pytest.skip("set GPT2GIGA_COMPAT_API_MODE explicitly to v1 or v2")

    registry = create_default_registry(include_entry_points=False)
    external = [
        harness
        for harness in registry.list()
        if callable(getattr(harness, "capability_probe", None))
    ]
    snapshots = [harness.capability_probe() for harness in external]
    unsupported = [
        f"{snapshot.harness_id}: {snapshot.warning}"
        for snapshot in snapshots
        if not snapshot.compatible
    ]
    assert not unsupported, "\n".join(unsupported)

    cells = adapter_compatibility_matrix(
        registry,
        api_modes=(GigaChatApiMode(route),),
    )
    assert {item["harness_id"] for item in cells} == {
        "codex-cli",
        "claude-code",
        "gemini-cli",
    }
    assert all(item["api_mode"] == route for item in cells)
