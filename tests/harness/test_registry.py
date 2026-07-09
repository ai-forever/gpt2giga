import pytest

from gpt2giga.harness.harnesses.base import BaseHarness
from gpt2giga.harness import registry as registry_module
from gpt2giga.harness.registry import (
    HarnessRegistry,
    UnknownHarnessError,
    create_default_registry,
)
from gpt2giga.harness.types import (
    Availability,
    HarnessCapability,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
    spec_to_dict,
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


def test_registry_loads_entry_point_plugin(monkeypatch):
    class FakeEntryPoint:
        name = "plugin-harness"

        def load(self):
            return _PluginHarness

    class FakeEntryPoints:
        def select(self, *, group):
            assert group == registry_module.ENTRY_POINT_GROUP
            return (FakeEntryPoint(),)

    monkeypatch.setattr(registry_module, "entry_points", lambda: FakeEntryPoints())

    registry = HarnessRegistry()
    registry.load_entry_points()

    assert registry.ids() == ("plugin-harness",)
    assert registry.validation_report("plugin-harness").ok is True
    assert registry.discovery_errors == []


def test_registry_records_validation_for_unknown_capability():
    registry = HarnessRegistry()
    harness = _UnknownCapabilityHarness()

    registry.register(harness)

    report = registry.validation_report("plugin-harness")
    assert report is not None
    assert report.ok is False
    assert [issue.code for issue in report.issues] == [
        "no_known_capabilities",
        "unknown_capability",
    ]


def test_spec_to_dict_ignores_unknown_capabilities_and_redacts_metadata():
    spec = HarnessSpec(
        id="plugin-harness",
        title="Plugin",
        kind="custom",
        description="Plugin harness",
        capabilities=(HarnessCapability.CHAT_COMPLETIONS, "future_capability"),
        config_schema={
            "type": "object",
            "properties": {
                "endpoint": {"type": "string", "default": "sk-secret-value"}
            },
        },
        metadata={"token": "secret-token-value", "safe": "ok"},
    )

    payload = spec_to_dict(spec)

    assert payload["capabilities"] == ["chat_completions"]
    assert payload["plugin_metadata"]["capabilities"] == ["chat_completions"]
    assert payload["metadata"]["token"] == "<redacted>"
    assert (
        payload["plugin_metadata"]["config_schema"]["properties"]["endpoint"]["default"]
        == "<redacted>"
    )


class _PluginHarness(BaseHarness):
    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="plugin-harness",
            title="Plugin Harness",
            kind="custom",
            description="Plugin harness for tests",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
            icon="plug",
            config_schema={
                "type": "object",
                "properties": {"endpoint": {"type": "string", "title": "Endpoint"}},
            },
            metadata={"package": "plugin-package"},
        )

    def availability(self) -> Availability:
        return Availability.available("plugin harness")

    def run(
        self,
        request: HarnessRequest,
        context,
    ) -> HarnessResult:
        return HarnessResult(ok=True, text=request.prompt)


class _UnknownCapabilityHarness(_PluginHarness):
    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="plugin-harness",
            title="Plugin Harness",
            kind="custom",
            description="Plugin harness for tests",
            capabilities=("future_capability",),
        )
