"""Early root-namespace routing for provider-native CLI passthrough."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import os

from gpt2giga_harness.native_cli_contracts import (
    CapabilityLevel,
    NATIVE_NAMESPACE_SPECS,
    NativeNamespaceSpec,
    classify_native_route,
)
from gpt2giga_harness.native_cli_process import run_native_l0, run_native_l1_handoff
from gpt2giga_harness.terminal_dispatch import TerminalContext, TuiLaunchIntent


NativeRunner = Callable[..., int]
ManagedRunner = Callable[..., int]


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
    managed_runner: ManagedRunner = run_native_l1_handoff,
    context: TerminalContext | None = None,
) -> int | None:
    """Run an admitted native namespace or return to Harness root routing."""
    invocation = match_native_namespace(argv)
    if invocation is None:
        return None
    spec, suffix = invocation
    terminal = context or TerminalContext.capture()
    human_terminal = terminal.fully_interactive and not terminal.ci
    decision = classify_native_route(
        spec.namespace,
        suffix,
        stdin_is_tty=human_terminal,
        stdout_is_tty=human_terminal,
        structured_transport_ready=False,
    )
    if decision.level is CapabilityLevel.MANAGED_HANDOFF:
        # Import the semantic decoder only for an affirmative human route.
        from gpt2giga_harness.terminal_intent import parse_native_tui_launch_intent

        intent: TuiLaunchIntent | None = parse_native_tui_launch_intent(
            spec.namespace, suffix, decision
        )
        if intent is not None:
            return managed_runner(
                spec,
                suffix,
                environment=environment,
                facade_executable=facade_executable,
            )
    return runner(
        spec,
        suffix,
        environment=environment,
        facade_executable=facade_executable,
    )
