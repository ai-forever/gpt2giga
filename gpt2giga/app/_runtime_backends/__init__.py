"""Internal runtime backend implementation package."""

from .contracts import (
    ConfigurableRuntimeStateBackend,
    EventFeed,
    QueryableEventFeed,
    RuntimeBackendDescriptor,
    RuntimeBackendFactory,
    RuntimeResourceDescriptor,
    RuntimeResourceKind,
    RuntimeStateBackend,
)
from .memory import InMemoryEventFeed, InMemoryRuntimeStateBackend
from .provisioning import RUNTIME_RESOURCE_DESCRIPTORS, provision_runtime_resources
from .registry import (
    create_runtime_backend,
    get_runtime_backend_descriptor,
    list_runtime_backend_descriptors,
    register_runtime_backend,
)
from .sqlite import SqliteEventFeed, SqliteMapping, SqliteRuntimeStateBackend

__all__ = [
    "ConfigurableRuntimeStateBackend",
    "EventFeed",
    "QueryableEventFeed",
    "RuntimeBackendDescriptor",
    "RuntimeBackendFactory",
    "RuntimeResourceDescriptor",
    "RuntimeResourceKind",
    "RuntimeStateBackend",
    "InMemoryEventFeed",
    "InMemoryRuntimeStateBackend",
    "RUNTIME_RESOURCE_DESCRIPTORS",
    "provision_runtime_resources",
    "create_runtime_backend",
    "get_runtime_backend_descriptor",
    "list_runtime_backend_descriptors",
    "register_runtime_backend",
    "SqliteEventFeed",
    "SqliteMapping",
    "SqliteRuntimeStateBackend",
]
