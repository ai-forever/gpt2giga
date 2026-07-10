"""Shared, execution-neutral tool and secret-reference contracts."""

from gpt2giga.tools.base import ToolDescriptor, ToolProvider, ToolRisk
from gpt2giga.tools.policy import (
    PolicyDecision,
    ToolExecutionPolicy,
    ToolPolicyResolution,
)
from gpt2giga.tools.secrets import (
    CompositeSecretResolver,
    EnvironmentSecretResolver,
    ResolvedSecret,
    SecretReference,
    SecretReferenceKind,
    SecretResolutionError,
    SecretResolutionErrorCode,
    SecretResolver,
    secret_reference_to_dict,
)

__all__ = [
    "CompositeSecretResolver",
    "EnvironmentSecretResolver",
    "PolicyDecision",
    "ResolvedSecret",
    "SecretReference",
    "SecretReferenceKind",
    "SecretResolutionError",
    "SecretResolutionErrorCode",
    "SecretResolver",
    "ToolDescriptor",
    "ToolExecutionPolicy",
    "ToolPolicyResolution",
    "ToolProvider",
    "ToolRisk",
    "secret_reference_to_dict",
]
