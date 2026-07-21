"""Early root-namespace routing for provider-native CLI passthrough."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import os

from gpt2giga_harness.native_cli_contracts import (
    NATIVE_NAMESPACE_SPECS,
    NativeNamespaceSpec,
)
from gpt2giga_harness.native_cli_process import run_native_l0


NativeRunner = Callable[..., int]


def match_native_namespace(
    argv: Sequence[str],
) -> tuple[NativeNamespaceSpec, tuple[str, ...]] | None:
    """Return one reviewed root namespace and its untouched provider suffix."""
    if not argv:
        return None
    spec = NATIVE_NAMESPACE_SPECS.get(argv[0])
    if spec is None:
        return None
    return spec, tuple(argv[1:])


def run_native_namespace(
    argv: Sequence[str],
    *,
    environment: Mapping[str, str] | None = None,
    facade_executable: str | os.PathLike[str] | None = None,
    runner: NativeRunner = run_native_l0,
) -> int | None:
    """Run an admitted L0 namespace or return control to the Harness CLI."""
    invocation = match_native_namespace(argv)
    if invocation is None:
        return None
    spec, suffix = invocation
    return runner(
        spec,
        suffix,
        environment=environment,
        facade_executable=facade_executable,
    )
