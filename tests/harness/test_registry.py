import pytest

from gpt2giga.harness.registry import (
    HarnessRegistry,
    UnknownHarnessError,
    create_default_registry,
)


def test_registry_loads_builtin_harnesses():
    registry = create_default_registry(include_entry_points=False)

    assert registry.ids() == (
        "claude-code",
        "codex-cli",
        "direct-chat",
        "echo",
        "gemini-cli",
    )


def test_registry_unknown_harness_error():
    registry = HarnessRegistry.with_builtins()

    with pytest.raises(UnknownHarnessError):
        registry.get("missing")
