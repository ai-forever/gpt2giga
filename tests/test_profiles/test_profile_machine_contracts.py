"""Redacted supervisor projections for the provider-profile lane."""

from __future__ import annotations

import json
import socket
from typing import Any

import pytest

from gpt2giga.providers.profiles import (
    BRIDGE_CAPABILITIES_SCHEMA_VERSION,
    BRIDGE_CATALOG_MODELS_SCHEMA_VERSION,
    INSPECT_SCHEMA_VERSION,
    READINESS_SCHEMA_VERSION,
    LoadedProviderProfileSet,
    ProviderMachineContracts,
    ProviderProfileConfig,
    ProviderProfileError,
    ProviderRegistry,
    not_ready_manifest,
)


MATRIX_REVISION = f"sha256:{'b' * 64}"
SECRET = "machine-contract-secret-never-render"
PROTOCOLS = (
    "anthropic_messages",
    "gemini_generate_content",
    "openai_chat_completions",
    "openai_responses",
)
PROVIDERS = ("anthropic", "gemini", "gigachat", "openai_compatible")


def _contracts() -> ProviderMachineContracts:
    config = ProviderProfileConfig.model_validate(
        {
            "profiles": [
                {
                    "profile_id": "openai-main",
                    "provider_kind": "openai_compatible",
                    "base_url": "https://openai.example/v1",
                    "credential_env": "OPENAI_API_KEY",
                    "network_policy_ref": "public-openai",
                    "tls_policy_ref": "system-default",
                    "models": [
                        {
                            "public_alias": "openai/default",
                            "upstream_model": "exact-model",
                            "capability_profile": "openai-default-v1",
                            "support_status": "stable",
                        }
                    ],
                }
            ]
        }
    )
    loaded = LoadedProviderProfileSet(
        config=config,
        _credentials={"openai-main": SECRET},
    )
    return ProviderMachineContracts(
        ProviderRegistry(loaded, loss_matrix_revision=MATRIX_REVISION)
    )


def _matrix_manifest() -> dict[str, Any]:
    cells = [
        {
            "public_protocol": protocol,
            "provider_kind": provider,
            "status": "blocked",
            "reasons": [{"reason_id": "evidence_pending"}],
            "evidence_ids": [],
        }
        for protocol in reversed(PROTOCOLS)
        for provider in reversed(PROVIDERS)
    ]
    return {"matrix_revision": MATRIX_REVISION, "cells": cells}


def _catalog_snapshot() -> dict[str, Any]:
    inventory_revision = f"sha256:{'d' * 64}"
    return {
        "schema_version": "gpt2giga.model-catalog.v1",
        "provider_profile_id": "openai-main",
        "credential_scope_digest": f"sha256:{'e' * 64}",
        "inventory_revision": inventory_revision,
        "discovered_at": "2026-08-03T08:00:00Z",
        "expires_at": "2026-08-03T08:01:00Z",
        "stale": False,
        "source": "provider",
        "models": [
            {
                "id": "model-b",
                "provider_kind": "openai_compatible",
                "provider_profile_id": "openai-main",
                "owned_by": "provider",
                "model_type": "chat",
                "available": True,
                "deprecated": False,
                "stale": False,
                "inventory_revision": inventory_revision,
                "provider_metadata": {"secret": SECRET},
            },
            {
                "id": "model-a",
                "provider_kind": "openai_compatible",
                "provider_profile_id": "openai-main",
                "owned_by": None,
                "model_type": None,
                "available": True,
                "deprecated": False,
                "stale": False,
                "inventory_revision": inventory_revision,
            },
        ],
    }


def test_inspect_models_and_readiness_are_deterministic_and_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("machine contracts must not resolve or contact providers")

    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    contracts = _contracts()
    inspect = contracts.inspect_manifest()
    models = contracts.models_manifest(_catalog_snapshot())
    waiting = contracts.readiness_manifest(adapters_ready=False)
    ready = contracts.readiness_manifest(adapters_ready=True)

    assert inspect["schema_version"] == INSPECT_SCHEMA_VERSION
    assert models["schema_version"] == BRIDGE_CATALOG_MODELS_SCHEMA_VERSION
    assert models["source"] == "shared_model_catalog"
    assert models["deprecated_endpoint"] is True
    assert [model["id"] for model in models["models"]] == ["model-a", "model-b"]
    assert inspect["valid"] is True
    assert inspect["config_revision"] == models["config_revision"]
    assert inspect["matrix_revision"] == MATRIX_REVISION
    assert waiting == {
        "schema_version": READINESS_SCHEMA_VERSION,
        "ready": False,
        "config_revision": inspect["config_revision"],
        "matrix_revision": MATRIX_REVISION,
        "reasons": [{"reason_id": "provider_clients_not_ready"}],
    }
    assert ready["ready"] is True
    assert ready["reasons"] == []

    serialized = json.dumps(
        {"inspect": inspect, "models": models, "readiness": ready},
        sort_keys=True,
    )
    assert SECRET not in serialized
    assert "OPENAI_API_KEY" in serialized
    assert "authorization" not in serialized.lower()
    assert contracts.inspect_manifest() == inspect


@pytest.mark.parametrize(
    "mutation",
    ["missing_models", "duplicate_model", "revision_mismatch", "profile_mismatch"],
)
def test_models_manifest_rejects_invalid_catalog_snapshots(mutation: str) -> None:
    snapshot = _catalog_snapshot()
    if mutation == "missing_models":
        snapshot.pop("models")
    elif mutation == "duplicate_model":
        snapshot["models"].append(dict(snapshot["models"][0]))
    elif mutation == "revision_mismatch":
        snapshot["models"][0]["inventory_revision"] = f"sha256:{'f' * 64}"
    else:
        snapshot["models"][0]["provider_profile_id"] = "another-profile"

    with pytest.raises(ProviderProfileError) as raised:
        _contracts().models_manifest(snapshot)
    assert raised.value.code == "invalid_profile_schema"


def test_shutdown_and_pre_registry_readiness_are_distinct() -> None:
    contracts = _contracts()
    assert contracts.readiness_manifest(
        adapters_ready=True,
        shutting_down=True,
    )["reasons"] == [{"reason_id": "gateway_shutting_down"}]
    assert not_ready_manifest() == {
        "schema_version": READINESS_SCHEMA_VERSION,
        "ready": False,
        "reasons": [{"reason_id": "registry_not_loaded"}],
    }


def test_capability_projection_binds_revisions_sorts_cells_and_is_content_free() -> (
    None
):
    contracts = _contracts()
    source = _matrix_manifest()
    manifest = contracts.capabilities_manifest(source)

    assert manifest["schema_version"] == BRIDGE_CAPABILITIES_SCHEMA_VERSION
    assert manifest["matrix_revision"] == MATRIX_REVISION
    assert len(manifest["cells"]) == 16
    identities = [
        (cell["public_protocol"], cell["provider_kind"]) for cell in manifest["cells"]
    ]
    assert identities == sorted(identities)
    serialized = json.dumps(manifest).lower()
    assert SECRET.lower() not in serialized
    assert "credential" not in serialized
    assert "prompt" not in serialized

    manifest["cells"][0]["status"] = "tampered"
    repeated = contracts.capabilities_manifest(source)
    assert repeated["cells"][0]["status"] == "blocked"

    source["cells"][0]["credential"] = SECRET
    with pytest.raises(ProviderProfileError):
        contracts.capabilities_manifest(source)


@pytest.mark.parametrize(
    "mutation",
    [
        "revision",
        "missing_cell",
        "duplicate_cell",
        "unknown_status",
        "credential_field",
    ],
)
def test_incomplete_mismatched_or_unsafe_capability_manifest_is_rejected(
    mutation: str,
) -> None:
    manifest = _matrix_manifest()
    if mutation == "revision":
        manifest["matrix_revision"] = f"sha256:{'c' * 64}"
    elif mutation == "missing_cell":
        manifest["cells"].pop()
    elif mutation == "duplicate_cell":
        manifest["cells"][-1] = dict(manifest["cells"][0])
    elif mutation == "unknown_status":
        manifest["cells"][0]["status"] = "unknown"
    else:
        manifest["cells"][0]["credential"] = SECRET

    with pytest.raises(ProviderProfileError) as raised:
        _contracts().capabilities_manifest(manifest)
    assert raised.value.code == "invalid_profile_schema"
    assert SECRET not in str(raised.value)
