"""Content-free machine projections for the provider-profile registry."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from gpt2giga.providers.profiles.errors import ProviderProfileError
from gpt2giga.providers.profiles.registry import ProviderRegistry


INSPECT_SCHEMA_VERSION = "gpt2giga.inspect.v1"
READINESS_SCHEMA_VERSION = "gpt2giga.readiness.v1"
BRIDGE_CAPABILITIES_SCHEMA_VERSION = "gpt2giga.bridge-capabilities.v1"
_CAPABILITY_STATUSES = {"blocked", "stable", "technical_preview"}
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

    def models_manifest(self) -> dict[str, Any]:
        """Return the deterministic `/bridge/models` document."""
        return self._registry.models_manifest()

    def readiness_manifest(
        self,
        *,
        adapters_ready: bool,
        shutting_down: bool = False,
    ) -> dict[str, Any]:
        """Distinguish loaded configuration from route/client readiness."""
        reasons: list[dict[str, str]] = []
        if shutting_down:
            reasons.append({"reason_id": "gateway_shutting_down"})
        elif not adapters_ready:
            reasons.append({"reason_id": "provider_clients_not_ready"})
        return {
            "schema_version": READINESS_SCHEMA_VERSION,
            "ready": not reasons,
            "config_revision": self._registry.config_revision,
            "matrix_revision": self._registry.loss_matrix_revision,
            "reasons": reasons,
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
            "config_revision": self._registry.config_revision,
            "matrix_revision": self._registry.loss_matrix_revision,
            "cells": ordered,
        }
        self._capability_source = deepcopy(matrix_manifest)
        self._capability_template = manifest
        return deepcopy(manifest)


def not_ready_manifest(reason_id: str = "registry_not_loaded") -> dict[str, Any]:
    """Return the pre-registry readiness document used during startup failure."""
    if not reason_id or any(character.isspace() for character in reason_id):
        raise ValueError("reason_id must be a bounded machine identifier")
    return {
        "schema_version": READINESS_SCHEMA_VERSION,
        "ready": False,
        "reasons": [{"reason_id": reason_id}],
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
