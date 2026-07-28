"""Versioned machine inventory for GigaLoom product truth."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterable, Mapping
from importlib import metadata, resources
from pathlib import Path
from typing import Any

from gpt2giga_harness import __version__
from gpt2giga_harness.capability_matrix import (
    build_adapter_capability_matrix,
    build_agent_surface_capability_matrix,
    render_agent_surface_capability_matrix_markdown,
)
from gpt2giga_harness.cli_capabilities import CLI_PROBE_CONTRACTS
from gpt2giga_harness.execution import ExecutionTransport
from gpt2giga_harness.integration_sdk import integration_sdk_policy_to_dict
from gpt2giga_harness.native import HarnessInvocationMode
from gpt2giga_harness.product_capabilities import capability_manifest
from gpt2giga_harness.provider_profiles import (
    PROVIDER_ADAPTER_ENTRY_POINTS,
    ProviderCompatibilityRegistry,
    ProviderProtocol,
)
from gpt2giga_harness.registry import (
    HARNESS_ADAPTER_ENTRY_POINTS,
    HarnessRegistry,
)
from gpt2giga_harness.tui.commands import COMMAND_REGISTRY
from gpt2giga_harness.types import spec_to_dict

PRODUCT_INVENTORY_SCHEMA_VERSION = 1
PRODUCT_INVENTORY_KIND = "gigaloom_product_inventory"
PRODUCT_INVENTORY_RESOURCE = "evidence/product_inventory/v1/inventory.json"
PRODUCT_INVENTORY_SOURCE = (
    "schemas+registries+entry_points+provider_profiles+cli+tui+api+contract_tests"
)
_DOCUMENTATION = (
    {
        "id": "agents-guide-en",
        "path": "docs/agents-and-multi-agent.md",
    },
    {
        "id": "agents-guide-ru",
        "path": (
            "docs-site/i18n/ru/docusaurus-plugin-content-docs/current/"
            "agents-and-multi-agent.md"
        ),
    },
    {
        "id": "agent-capability-matrix-en",
        "path": "docs/agent-capability-matrix.md",
    },
    {
        "id": "agent-capability-matrix-ru",
        "path": (
            "docs-site/i18n/ru/docusaurus-plugin-content-docs/current/"
            "agent-capability-matrix.md"
        ),
    },
    {
        "id": "provider-authentication-en",
        "path": "docs/architecture/provider-authentication-capability-matrix.md",
    },
    {
        "id": "provider-authentication-ru",
        "path": (
            "docs-site/i18n/ru/docusaurus-plugin-content-docs/current/"
            "architecture/provider-authentication-capability-matrix.md"
        ),
    },
    {
        "id": "product-capability-admission-en",
        "path": "docs/architecture/product-capability-admission-adr.md",
    },
    {
        "id": "product-capability-admission-ru",
        "path": (
            "docs-site/i18n/ru/docusaurus-plugin-content-docs/current/"
            "architecture/product-capability-admission-adr.md"
        ),
    },
)
_CONTRACT_TESTS = (
    "tests/harness/test_capability_matrix.py",
    "tests/harness/test_cli_capabilities.py",
    "tests/harness/test_doctor.py",
    "tests/harness/test_harness_cli.py",
    "tests/harness/test_product_capabilities.py",
    "tests/harness/test_product_inventory.py",
    "tests/harness/test_provider_profiles.py",
    "tests/harness/test_terminal_dispatch.py",
    "tests/harness/test_tui_app.py",
    "tests/harness/test_ui.py",
)


def build_product_inventory(
    registry: HarnessRegistry,
    *,
    cli_parser: argparse.ArgumentParser,
    api_routes: Iterable[Any],
) -> dict[str, Any]:
    """Build deterministic product truth from the runtime's owning contracts."""
    product_vocabulary = capability_manifest()
    adapter_matrix = build_adapter_capability_matrix(registry)
    agent_matrix = build_agent_surface_capability_matrix(registry)
    compatibility_profiles = ProviderCompatibilityRegistry.with_builtins().list()
    harnesses = []
    for harness in sorted(registry.list(), key=lambda item: item.spec().id):
        spec = spec_to_dict(harness.spec())
        harnesses.append(
            {
                "id": spec["id"],
                "title": spec["title"],
                "kind": spec["kind"],
                "capabilities": list(spec["capabilities"]),
                "default_invocation_mode": spec["default_invocation_mode"],
                "protocol_capability_scope": spec["protocol_capability_scope"],
                "supports": dict(spec["plugin_metadata"]["supports"]),
            }
        )

    document: dict[str, Any] = {
        "schema_version": PRODUCT_INVENTORY_SCHEMA_VERSION,
        "kind": PRODUCT_INVENTORY_KIND,
        "product": {
            "name": "GigaLoom",
            "distribution": "gpt2giga-harness",
            "version": __version__,
            "repository": "https://github.com/krakenalt/gigaloom",
        },
        "generated_from": PRODUCT_INVENTORY_SOURCE,
        "sources": [
            "product_capabilities.capability_manifest",
            "HarnessRegistry.with_builtins",
            "ProviderCompatibilityRegistry.with_builtins",
            "installed gpt2giga-harness entry points",
            "cli.build_parser",
            "tui.commands.COMMAND_REGISTRY",
            "ui.app.create_app routes",
            "contract tests",
        ],
        "entry_points": _distribution_entry_points(),
        "vocabulary": product_vocabulary,
        "harnesses": harnesses,
        "adapter_capability_matrix": adapter_matrix,
        "agent_surface_capability_matrix": agent_matrix,
        "provider_compatibility_profiles": [
            {
                "id": profile.id,
                "revision": profile.revision,
                "harness_id": profile.harness_id,
                "adapter_version": profile.adapter_version,
                "protocol": profile.protocol.value,
                "dialects": list(profile.dialects),
                "transports": [item.value for item in profile.transports],
                "capabilities": list(profile.capabilities),
                "native_auth": profile.native_auth,
                "evidence": [
                    {
                        "id": item.id,
                        "revision": item.revision,
                        "status": item.status,
                        "source": item.source,
                    }
                    for item in profile.evidence
                ],
            }
            for profile in compatibility_profiles
        ],
        "interfaces": {
            "cli_commands": _cli_commands(cli_parser),
            "tui_commands": [
                {
                    "id": command.id,
                    "slash": command.slash,
                    "action": command.action,
                    "requires_session": command.requires_session,
                }
                for command in COMMAND_REGISTRY
            ],
            "api_operations": _api_operations(api_routes),
        },
        "protocols": [item.value for item in ProviderProtocol],
        "transports": [item.value for item in ExecutionTransport],
        "modes": {
            "task_intents": list(product_vocabulary["task_intents"]),
            "authority_levels": list(product_vocabulary["authority_levels"]),
            "invocation_modes": [item.value for item in HarnessInvocationMode],
            "legacy_modes": [
                receipt["value"]
                for receipt in product_vocabulary["legacy_mode_receipts"]
            ],
        },
        "deprecations": {
            "legacy_capability_mappings": list(product_vocabulary["legacy_mappings"]),
            "legacy_mode_receipts": list(product_vocabulary["legacy_mode_receipts"]),
            "entry_point_compatibility": {
                "preferred": HARNESS_ADAPTER_ENTRY_POINTS.primary_group,
                "compatibility_groups": list(
                    HARNESS_ADAPTER_ENTRY_POINTS.compatibility_groups
                ),
            },
            "integration_sdk": integration_sdk_policy_to_dict()["deprecation"],
        },
        "readiness": {
            "installed_executable_proves_account_ready": False,
            "provider_cli_contracts": [
                {
                    "harness_id": contract.harness_id,
                    "minimum_version": contract.minimum_version,
                    "maximum_version_exclusive": (contract.maximum_version_exclusive),
                    "required_tokens": list(contract.required_tokens),
                    "evidence_required": [
                        "executable_resolution",
                        "bounded_version_probe",
                        "bounded_help_probe",
                        "provider_owned_account_status",
                    ],
                }
                for contract in sorted(
                    CLI_PROBE_CONTRACTS.values(),
                    key=lambda item: item.harness_id,
                )
            ],
            "doctor_consumer": {
                "report_kind": "gpt2giga_harness_doctor_report",
                "inventory_kind": PRODUCT_INVENTORY_KIND,
                "inventory_schema_version": PRODUCT_INVENTORY_SCHEMA_VERSION,
            },
        },
        "documentation": [dict(item) for item in _DOCUMENTATION],
        "contract_tests": list(_CONTRACT_TESTS),
    }
    document["content_sha256"] = _content_sha256(document)
    return document


def load_product_inventory() -> dict[str, Any]:
    """Load the packaged inventory used by installed doctor and docs tooling."""
    resource = resources.files("gpt2giga_harness").joinpath(PRODUCT_INVENTORY_RESOURCE)
    return json.loads(resource.read_text(encoding="utf-8"))


def product_inventory_summary() -> dict[str, Any]:
    """Return a bounded inventory identity suitable for doctor reports."""
    inventory = load_product_inventory()
    readiness = inventory.get("readiness") or {}
    contracts = readiness.get("provider_cli_contracts") or ()
    return {
        "kind": inventory.get("kind"),
        "schema_version": inventory.get("schema_version"),
        "product_version": (inventory.get("product") or {}).get("version"),
        "content_sha256": inventory.get("content_sha256"),
        "provider_cli_contracts": [
            str(item.get("harness_id"))
            for item in contracts
            if isinstance(item, Mapping) and item.get("harness_id")
        ],
        "documentation": [
            str(item.get("id"))
            for item in inventory.get("documentation") or ()
            if isinstance(item, Mapping) and item.get("id")
        ],
    }


def canonical_inventory_json(inventory: Mapping[str, Any]) -> str:
    """Serialize one inventory deterministically for files and CI comparison."""
    return (
        json.dumps(
            inventory,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def validate_product_inventory(
    current: Mapping[str, Any],
    *,
    repository_root: str | Path,
) -> tuple[str, ...]:
    """Validate packaged inventory, docs projections, links, and test evidence."""
    root = Path(repository_root).resolve()
    errors: list[str] = []
    try:
        packaged = load_product_inventory()
    except (OSError, json.JSONDecodeError) as exc:
        return (f"packaged inventory could not be loaded: {type(exc).__name__}",)

    if dict(packaged) != dict(current):
        errors.append("packaged product inventory is stale")
    claimed_digest = current.get("content_sha256")
    unsigned = dict(current)
    unsigned.pop("content_sha256", None)
    if claimed_digest != _content_sha256(unsigned):
        errors.append("product inventory content_sha256 is invalid")

    for item in current.get("documentation") or ():
        path = root / str(item.get("path", ""))
        if not path.is_file():
            errors.append(
                f"documented product truth is missing: {path.relative_to(root)}"
            )
    for relative_path in current.get("contract_tests") or ():
        path = root / str(relative_path)
        if not path.is_file():
            errors.append(
                f"contract test evidence is missing: {path.relative_to(root)}"
            )

    agent_matrix = current.get("agent_surface_capability_matrix")
    if isinstance(agent_matrix, Mapping):
        expected_markdown = render_agent_surface_capability_matrix_markdown(
            agent_matrix
        )
        matrix_path = root / "docs" / "agent-capability-matrix.md"
        if (
            matrix_path.is_file()
            and matrix_path.read_text(encoding="utf-8") != expected_markdown
        ):
            errors.append("English agent capability matrix is stale")
        _validate_russian_matrix(
            agent_matrix,
            root / "docs-site/i18n/ru/docusaurus-plugin-content-docs/current/"
            "agent-capability-matrix.md",
            errors,
        )
    return tuple(errors)


def _distribution_entry_points() -> list[dict[str, str]]:
    groups = {
        *HARNESS_ADAPTER_ENTRY_POINTS.groups,
        PROVIDER_ADAPTER_ENTRY_POINTS.primary_group,
    }
    try:
        distribution = metadata.distribution("gpt2giga-harness")
    except metadata.PackageNotFoundError:
        return []
    return [
        {
            "group": entry_point.group,
            "name": entry_point.name,
            "value": entry_point.value,
        }
        for entry_point in sorted(
            (item for item in distribution.entry_points if item.group in groups),
            key=lambda item: (item.group, item.name, item.value),
        )
    ]


def _cli_commands(parser: argparse.ArgumentParser) -> list[str]:
    commands: set[str] = set()

    def visit(current: argparse.ArgumentParser, prefix: tuple[str, ...]) -> None:
        for action in current._actions:
            if not isinstance(action, argparse._SubParsersAction):
                continue
            for name, child in action.choices.items():
                command = (*prefix, name)
                commands.add(" ".join(command))
                visit(child, command)

    visit(parser, ())
    return sorted(commands)


def _api_operations(routes: Iterable[Any]) -> list[dict[str, str]]:
    operations: list[dict[str, str]] = []

    def visit(route: Any, prefix: str = "") -> None:
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            context = getattr(route, "include_context", None)
            nested_prefix = f"{prefix}{getattr(context, 'prefix', '')}"
            for child in getattr(original_router, "routes", ()):
                visit(child, nested_prefix)
            return
        path = f"{prefix}{getattr(route, 'path', '')}"
        if not path.startswith("/api"):
            return
        name = str(getattr(route, "name", ""))
        for method in sorted(getattr(route, "methods", ()) or ()):
            if method in {"HEAD", "OPTIONS"}:
                continue
            operations.append({"method": method, "path": path, "name": name})

    for route in routes:
        visit(route)
    return sorted(
        operations,
        key=lambda item: (item["path"], item["method"], item["name"]),
    )


def _validate_russian_matrix(
    matrix: Mapping[str, Any],
    path: Path,
    errors: list[str],
) -> None:
    if not path.is_file():
        return
    rendered = path.read_text(encoding="utf-8")
    surfaces = list(matrix.get("surfaces") or ())
    for capability in matrix.get("capabilities") or ():
        support = capability.get("support") or {}
        statuses = [
            str((support.get(surface["id"]) or {}).get("status", "undeclared"))
            for surface in surfaces
        ]
        expected = f"| `{capability['id']}` | " + " | ".join(statuses) + " |"
        if expected not in rendered:
            errors.append(
                f"Russian agent capability matrix is stale at {capability['id']}"
            )


def _content_sha256(document: Mapping[str, Any]) -> str:
    payload = json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
