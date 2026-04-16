"""Runtime resource descriptors and provisioning helpers."""

from __future__ import annotations

from typing import Any

from .contracts import RuntimeResourceDescriptor, RuntimeStateBackend

RUNTIME_RESOURCE_DESCRIPTORS: tuple[RuntimeResourceDescriptor, ...] = (
    RuntimeResourceDescriptor(
        name="files",
        kind="mapping",
        description="Uploaded file metadata.",
    ),
    RuntimeResourceDescriptor(
        name="batches",
        kind="mapping",
        description="Batch metadata.",
    ),
    RuntimeResourceDescriptor(
        name="responses",
        kind="mapping",
        description="Responses API metadata.",
    ),
    RuntimeResourceDescriptor(
        name="usage_by_api_key",
        kind="mapping",
        description="Aggregated usage accounting grouped by API key.",
    ),
    RuntimeResourceDescriptor(
        name="usage_by_provider",
        kind="mapping",
        description="Aggregated usage accounting grouped by external provider.",
    ),
    RuntimeResourceDescriptor(
        name="governance_counters",
        kind="mapping",
        description="Fixed-window governance counters for request and token quotas.",
    ),
    RuntimeResourceDescriptor(
        name="recent_requests",
        kind="feed",
        description="Recent request audit events.",
        max_items_setting="recent_requests_max_items",
        default_max_items=200,
    ),
    RuntimeResourceDescriptor(
        name="recent_errors",
        kind="feed",
        description="Recent request error events.",
        max_items_setting="recent_errors_max_items",
        default_max_items=100,
    ),
)


def provision_runtime_resources(
    backend: RuntimeStateBackend,
    *,
    config: Any | None = None,
) -> dict[str, Any]:
    """Provision all declared runtime resources from a backend."""
    resources: dict[str, Any] = {}
    for descriptor in RUNTIME_RESOURCE_DESCRIPTORS:
        if descriptor.kind == "mapping":
            resources[descriptor.name] = backend.mapping(descriptor.name)
            continue
        resources[descriptor.name] = backend.feed(
            descriptor.name,
            max_items=descriptor.resolve_max_items(config),
        )
    return resources
