"""Content-free machine projections for the provider-profile registry."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from gpt2giga.providers.profiles.errors import ProviderProfileError
from gpt2giga.providers.profiles.registry import ProviderRegistry


INSPECT_SCHEMA_VERSION = "gpt2giga.inspect.v1"
READINESS_SCHEMA_VERSION = "gpt2giga.readiness.v1"
ROUTE_SUPPORT_MATRIX_SCHEMA_VERSION = "gpt2giga.route-support-matrix.v1"
# Backward-compatible import name; the document itself is explicitly route-scoped.
BRIDGE_CAPABILITIES_SCHEMA_VERSION = ROUTE_SUPPORT_MATRIX_SCHEMA_VERSION
BRIDGE_CATALOG_MODELS_SCHEMA_VERSION = "gpt2giga.bridge-models.v2"
EFFECTIVE_CAPABILITIES_SCHEMA_VERSION = "gpt2giga.effective-capabilities.v1"
_CAPABILITY_STATUSES = {"blocked", "stable", "technical_preview"}
_CAPABILITY_STATES = {"supported", "unsupported", "unknown"}
_CATALOG_STATES = {"fresh", "stale", "unavailable"}
_CAPABILITY_PROTOCOLS = {
    "anthropic_messages",
    "gemini_generate_content",
    "openai_chat_completions",
    "openai_responses",
}
_CAPABILITY_PROVIDERS = {"anthropic", "gemini", "gigachat", "openai_compatible"}
_FORBIDDEN_MACHINE_KEYS = {
    "api_key",
    "authorization",
    "content",
    "credential",
    "credential_value",
    "prompt",
    "request_body",
    "response_body",
    "secret",
    "tool_arguments",
}


class ProviderMachineContracts:
    """Build supervisor documents without network or provider access."""

    def __init__(self, registry: ProviderRegistry) -> None:
        self._registry = registry
        self._capability_source: Mapping[str, Any] | None = None
        self._capability_template: dict[str, Any] | None = None

    def inspect_manifest(self) -> dict[str, Any]:
        """Return the validated startup config with credential values redacted."""
        profiles: list[dict[str, Any]] = []
        for profile in sorted(
            self._registry.config.profiles,
            key=lambda item: item.profile_id,
        ):
            profiles.append(
                {
                    "profile_id": profile.profile_id,
                    "profile_revision": profile.revision,
                    "provider_kind": profile.provider_kind.value,
                    "base_url": profile.base_url,
                    "credential_env": profile.credential_env,
                    "network_policy_ref": profile.network_policy_ref,
                    "tls_policy_ref": profile.tls_policy_ref,
                    "allow_loopback": profile.allow_loopback,
                    "models": [
                        {
                            "public_alias": model.public_alias,
                            "upstream_model": model.upstream_model,
                            "capability_profile": model.capability_profile,
                            "support_status": model.support_status.value,
                            "enabled": model.enabled,
                            "deprecated": model.deprecated,
                        }
                        for model in sorted(
                            profile.models,
                            key=lambda item: item.public_alias,
                        )
                    ],
                }
            )
        return {
            "schema_version": INSPECT_SCHEMA_VERSION,
            "valid": True,
            "config_revision": self._registry.config_revision,
            "matrix_revision": self._registry.loss_matrix_revision,
            "profiles": profiles,
        }

    def models_manifest(self, catalog_snapshot: Any) -> dict[str, Any]:
        """Project `/bridge/models` from the shared model catalog snapshot."""
        snapshot = _as_mapping(catalog_snapshot)
        inventory_revision = _machine_string(snapshot, "inventory_revision")
        provider_profile_id = _machine_string(snapshot, "provider_profile_id")
        raw_models = snapshot.get("models")
        if not isinstance(raw_models, Sequence) or isinstance(
            raw_models,
            (str, bytes),
        ):
            raise _invalid_catalog_snapshot()

        models: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for raw_model in raw_models:
            model = _as_mapping(raw_model)
            model_id = _machine_string(model, "id")
            if model_id in seen_ids:
                raise _invalid_catalog_snapshot()
            seen_ids.add(model_id)
            model_revision = _machine_string(model, "inventory_revision")
            if model_revision != inventory_revision:
                raise _invalid_catalog_snapshot()
            model_profile_id = _machine_string(model, "provider_profile_id")
            if model_profile_id != provider_profile_id:
                raise _invalid_catalog_snapshot()
            models.append(
                {
                    "id": model_id,
                    "provider_kind": _machine_string(model, "provider_kind"),
                    "provider_profile_id": model_profile_id,
                    "owned_by": _optional_machine_string(model, "owned_by"),
                    "model_type": _optional_machine_string(model, "model_type"),
                    "available": _machine_bool(model, "available", default=True),
                    "deprecated": _machine_bool(
                        model,
                        "deprecated",
                        default=False,
                    ),
                    "stale": _machine_bool(
                        model,
                        "stale",
                        default=_machine_bool(snapshot, "stale", default=False),
                    ),
                    "inventory_revision": model_revision,
                }
            )

        return {
            "schema_version": BRIDGE_CATALOG_MODELS_SCHEMA_VERSION,
            "source": "shared_model_catalog",
            "deprecated_endpoint": True,
            "replacement": "/models",
            "config_revision": self._registry.config_revision,
            "matrix_revision": self._registry.loss_matrix_revision,
            "catalog_schema_version": _machine_string(snapshot, "schema_version"),
            "provider_profile_id": provider_profile_id,
            "inventory_revision": inventory_revision,
            "discovered_at": _machine_string(snapshot, "discovered_at"),
            "expires_at": _machine_string(snapshot, "expires_at"),
            "stale": _machine_bool(snapshot, "stale", default=False),
            "models": sorted(models, key=lambda item: item["id"]),
        }

    def readiness_manifest(
        self,
        *,
        adapters_ready: bool,
        catalog_readiness: Any | None = None,
        shutting_down: bool = False,
    ) -> dict[str, Any]:
        """Distinguish process, route, adapter, and catalog readiness."""
        reasons: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        routes_configured = bool(self._registry.public_aliases())
        catalog = _catalog_readiness_manifest(catalog_readiness)
        if shutting_down:
            reasons.append({"reason_id": "gateway_shutting_down"})
        if not routes_configured:
            reasons.append({"reason_id": "provider_routes_not_configured"})
        if not adapters_ready:
            reasons.append({"reason_id": "provider_clients_not_ready"})
        if not catalog["usable"]:
            reasons.append({"reason_id": "model_inventory_unavailable"})
        elif catalog["state"] == "stale":
            warnings.append({"reason_id": "model_inventory_stale_but_usable"})
        return {
            "schema_version": READINESS_SCHEMA_VERSION,
            "ready": not reasons,
            "process_alive": True,
            "provider_routes_configured": routes_configured,
            "provider_adapters_ready": adapters_ready,
            "model_catalog": catalog,
            "config_revision": self._registry.config_revision,
            "matrix_revision": self._registry.loss_matrix_revision,
            "reasons": reasons,
            "warnings": warnings,
        }

    def capabilities_manifest(
        self,
        matrix_manifest: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Bind an A6-owned complete matrix to this exact profile revision."""
        if (
            self._capability_template is not None
            and matrix_manifest == self._capability_source
        ):
            return deepcopy(self._capability_template)
        matrix_revision = matrix_manifest.get("matrix_revision")
        if matrix_revision != self._registry.loss_matrix_revision:
            raise _invalid_capability_manifest()
        raw_cells = matrix_manifest.get("cells")
        if not isinstance(raw_cells, Sequence) or isinstance(raw_cells, (str, bytes)):
            raise _invalid_capability_manifest()
        cells = [deepcopy(cell) for cell in raw_cells]
        if len(cells) != 16 or any(not isinstance(cell, Mapping) for cell in cells):
            raise _invalid_capability_manifest()
        if any(cell.get("status") not in _CAPABILITY_STATUSES for cell in cells):
            raise _invalid_capability_manifest()
        identities = [_capability_identity(cell) for cell in cells]
        expected_identities = {
            (protocol, provider)
            for protocol in _CAPABILITY_PROTOCOLS
            for provider in _CAPABILITY_PROVIDERS
        }
        if set(identities) != expected_identities:
            raise _invalid_capability_manifest()
        if _contains_forbidden_machine_key(cells):
            raise _invalid_capability_manifest()
        ordered = [
            cell
            for _, cell in sorted(
                zip(identities, cells, strict=True),
                key=lambda item: item[0],
            )
        ]
        manifest = {
            "schema_version": BRIDGE_CAPABILITIES_SCHEMA_VERSION,
            "contract_kind": "route_support_matrix",
            "scope": "protocol_provider_route",
            "not_model_inventory": True,
            "not_effective_model_capabilities": True,
            "model_inventory_endpoint": "/models",
            "effective_capabilities_endpoint": (
                "/bridge/capabilities?model=<model-id>"
                "&protocol=<public-protocol>&api_mode=<api-mode>"
            ),
            "config_revision": self._registry.config_revision,
            "matrix_revision": self._registry.loss_matrix_revision,
            "cells": ordered,
        }
        self._capability_source = deepcopy(matrix_manifest)
        self._capability_template = manifest
        return deepcopy(manifest)

    def effective_capabilities_manifest(
        self,
        *,
        model: Any,
        resolution: Any,
        public_protocol: str,
        api_mode: str | None,
    ) -> dict[str, Any]:
        """Project one selected model's effective tri-state capabilities."""
        descriptor = _capability_mapping(model)
        resolved = _capability_mapping(resolution)
        model_id = _capability_string(descriptor, "id")
        provider_kind = _capability_string(descriptor, "provider_kind")
        provider_profile_id = _capability_string(
            descriptor,
            "provider_profile_id",
        )
        inventory_revision = _capability_string(
            descriptor,
            "inventory_revision",
        )
        capability_revision = _capability_string(resolved, "revision")
        if (
            resolved.get("model_id") != model_id
            or resolved.get("provider_kind") != provider_kind
            or resolved.get("public_protocol") != public_protocol
            or resolved.get("api_mode") != api_mode
        ):
            raise _invalid_effective_capabilities()

        raw_capabilities = resolved.get("capabilities")
        if not isinstance(raw_capabilities, Mapping) or not raw_capabilities:
            raise _invalid_effective_capabilities()
        capabilities: dict[str, dict[str, Any]] = {}
        for raw_name, raw_decision in raw_capabilities.items():
            if not isinstance(raw_name, str) or not raw_name or len(raw_name) > 128:
                raise _invalid_effective_capabilities()
            decision = _capability_mapping(raw_decision)
            state = _capability_string(decision, "state")
            if state not in _CAPABILITY_STATES:
                raise _invalid_effective_capabilities()
            raw_evidence_ids = decision.get("evidence_ids")
            if not isinstance(raw_evidence_ids, Sequence) or isinstance(
                raw_evidence_ids,
                (str, bytes),
            ):
                raise _invalid_effective_capabilities()
            evidence_ids = [
                _bounded_capability_string(value) for value in raw_evidence_ids
            ]
            capabilities[raw_name] = {
                "state": state,
                "reason_id": _capability_string(decision, "reason_id"),
                "source": _capability_string(decision, "source"),
                "evidence_ids": sorted(evidence_ids),
                "revision": _capability_string(decision, "revision"),
            }

        manifest = {
            "schema_version": EFFECTIVE_CAPABILITIES_SCHEMA_VERSION,
            "model": model_id,
            "provider_kind": provider_kind,
            "provider_profile_id": provider_profile_id,
            "public_protocol": public_protocol,
            "api_mode": api_mode,
            "inventory_revision": inventory_revision,
            "capability_revision": capability_revision,
            "capabilities": {key: capabilities[key] for key in sorted(capabilities)},
        }
        if _contains_forbidden_machine_key(manifest):
            raise _invalid_effective_capabilities()
        return manifest


def not_ready_manifest(reason_id: str = "registry_not_loaded") -> dict[str, Any]:
    """Return the pre-registry readiness document used during startup failure."""
    if not reason_id or any(character.isspace() for character in reason_id):
        raise ValueError("reason_id must be a bounded machine identifier")
    return {
        "schema_version": READINESS_SCHEMA_VERSION,
        "ready": False,
        "process_alive": True,
        "provider_routes_configured": False,
        "provider_adapters_ready": False,
        "model_catalog": _catalog_readiness_manifest(None),
        "reasons": [{"reason_id": reason_id}],
        "warnings": [],
    }


def _capability_identity(cell: Mapping[str, Any]) -> tuple[str, str]:
    protocol = cell.get("public_protocol", cell.get("client_protocol"))
    provider = cell.get("provider_kind", cell.get("upstream_provider"))
    if not isinstance(protocol, str) or not isinstance(provider, str):
        raise _invalid_capability_manifest()
    return protocol, provider


def _contains_forbidden_machine_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).lower() in _FORBIDDEN_MACHINE_KEYS:
                return True
            if _contains_forbidden_machine_key(nested):
                return True
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(_contains_forbidden_machine_key(item) for item in value)
    return False


def _invalid_capability_manifest() -> ProviderProfileError:
    return ProviderProfileError(
        "invalid_profile_schema",
        "Bridge capability manifest is incomplete or unsafe.",
    )


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dumped
    raise _invalid_catalog_snapshot()


def _machine_string(value: Mapping[str, Any], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw or len(raw) > 512:
        raise _invalid_catalog_snapshot()
    return raw


def _optional_machine_string(value: Mapping[str, Any], key: str) -> str | None:
    raw = value.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw or len(raw) > 512:
        raise _invalid_catalog_snapshot()
    return raw


def _machine_bool(
    value: Mapping[str, Any],
    key: str,
    *,
    default: bool,
) -> bool:
    raw = value.get(key, default)
    if not isinstance(raw, bool):
        raise _invalid_catalog_snapshot()
    return raw


def _invalid_catalog_snapshot() -> ProviderProfileError:
    return ProviderProfileError(
        "invalid_profile_schema",
        "Model catalog snapshot is incomplete or unsafe.",
    )


def _capability_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dumped
    raise _invalid_effective_capabilities()


def _capability_string(value: Mapping[str, Any], key: str) -> str:
    raw = value.get(key)
    return _bounded_capability_string(raw)


def _bounded_capability_string(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise _invalid_effective_capabilities()
    return value


def _invalid_effective_capabilities() -> ProviderProfileError:
    return ProviderProfileError(
        "invalid_profile_schema",
        "Effective capability result is incomplete or unsafe.",
    )


def _catalog_readiness_manifest(value: Any | None) -> dict[str, Any]:
    if value is None:
        return {
            "state": "unavailable",
            "usable": False,
            "discovery_available": False,
            "provider_profile_id": None,
            "inventory_revision": None,
        }
    readiness = _catalog_readiness_mapping(value)
    state = _catalog_readiness_string(readiness.get("state"))
    if state not in _CATALOG_STATES:
        raise _invalid_catalog_readiness()
    usable = state in {"fresh", "stale"}
    provider_profile_id = readiness.get("provider_profile_id")
    inventory_revision = readiness.get("inventory_revision")
    if usable:
        provider_profile_id = _catalog_readiness_string(provider_profile_id)
        inventory_revision = _catalog_readiness_string(inventory_revision)
    elif provider_profile_id is not None or inventory_revision is not None:
        raise _invalid_catalog_readiness()
    return {
        "state": state,
        "usable": usable,
        "discovery_available": state == "fresh",
        "provider_profile_id": provider_profile_id,
        "inventory_revision": inventory_revision,
    }


def _invalid_catalog_readiness() -> ProviderProfileError:
    return ProviderProfileError(
        "invalid_profile_schema",
        "Model catalog readiness is incomplete or unsafe.",
    )


def _catalog_readiness_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dumped
    raise _invalid_catalog_readiness()


def _catalog_readiness_string(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise _invalid_catalog_readiness()
    return value
