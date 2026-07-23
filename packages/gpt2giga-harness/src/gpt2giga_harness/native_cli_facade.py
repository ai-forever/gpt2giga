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
StructuredRunner = Callable[[TuiLaunchIntent], int]
StructuredProbe = Callable[
    [NativeNamespaceSpec, tuple[str, ...]], tuple[str | None, bool]
]


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
    structured_runner: StructuredRunner | None = None,
    structured_probe: StructuredProbe | None = None,
    context: TerminalContext | None = None,
) -> int | None:
    """Run an admitted native namespace or return to Harness root routing."""
    invocation = match_native_namespace(argv)
    if invocation is None:
        return None
    spec, suffix = invocation
    terminal = context or TerminalContext.capture()
    human_terminal = terminal.fully_interactive and not terminal.ci
    version: str | None = None
    structured_ready = False
    preliminary = classify_native_route(
        spec.namespace,
        suffix,
        stdin_is_tty=human_terminal,
        stdout_is_tty=human_terminal,
        structured_transport_ready=False,
    )
    if (
        spec.namespace == "codex"
        and preliminary.level is CapabilityLevel.MANAGED_HANDOFF
    ):
        try:
            version, structured_ready = (structured_probe or _probe_codex_structured)(
                spec, suffix
            )
        except Exception:
            # Probe drift or failure degrades only the optional L2 route.
            version, structured_ready = None, False
    decision = classify_native_route(
        spec.namespace,
        suffix,
        version=version,
        stdin_is_tty=human_terminal,
        stdout_is_tty=human_terminal,
        structured_transport_ready=structured_ready,
    )
    if decision.level in {
        CapabilityLevel.MANAGED_HANDOFF,
        CapabilityLevel.STRUCTURED_WORKBENCH,
    }:
        # Import the semantic decoder only for an affirmative human route.
        from gpt2giga_harness.terminal_intent import parse_native_tui_launch_intent

        intent: TuiLaunchIntent | None = parse_native_tui_launch_intent(
            spec.namespace, suffix, decision, workspace=os.getcwd()
        )
        if intent is not None:
            if decision.level is CapabilityLevel.STRUCTURED_WORKBENCH:
                return (structured_runner or _run_structured_workbench)(intent)
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


def _probe_codex_structured(
    _spec: NativeNamespaceSpec, suffix: tuple[str, ...]
) -> tuple[str | None, bool]:
    """Return bounded Codex app-server admission without reading its native home."""
    if suffix == ("resume", "--last"):
        # The reviewed app-server contract has no admitted thread-list selector.
        return None, False
    from gpt2giga_harness.harnesses.codex_cli import CodexCliHarness
    from gpt2giga_harness.harnesses.codex_workbench import admit_codex_workbench

    admission = admit_codex_workbench(CodexCliHarness().capability_probe())
    return admission.version, admission.admitted


def _run_structured_workbench(intent: TuiLaunchIntent) -> int:
    """Launch the canonical TUI for an admitted provider integration."""
    from gpt2giga_harness.tui.entrypoint import main as tui_main

    return tui_main([], launch_intent=intent)
