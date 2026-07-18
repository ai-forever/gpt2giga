import pytest

from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.harnesses.direct_chat import DirectChatHarness
from gpt2giga_harness import registry as registry_module
from gpt2giga_harness.registry import (
    HARNESS_ADAPTER_ENTRY_POINTS,
    MAX_DISCOVERY_ERRORS,
    MAX_DISCOVERY_ERROR_CHARS,
    HarnessRegistry,
    NEUTRAL_ENTRY_POINT_GROUP,
    UnknownHarnessError,
    create_default_registry,
)
from gpt2giga_harness.registries import RegistryCollisionError
from gpt2giga_harness.types import (
    Availability,
    HarnessCapability,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
    redact_secrets,
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
        value = f"{__name__}:_PluginHarness"

        def load(self):
            return _PluginHarness

    class FakeEntryPoints:
        def select(self, *, group):
            if group == NEUTRAL_ENTRY_POINT_GROUP:
                return (FakeEntryPoint(),)
            assert group == registry_module.ENTRY_POINT_GROUP
            return ()

    monkeypatch.setattr(registry_module, "entry_points", lambda: FakeEntryPoints())

    registry = HarnessRegistry()
    registry.load_entry_points()

    assert registry.ids() == ("plugin-harness",)
    assert registry.validation_report("plugin-harness").ok is True
    assert registry.discovery_errors == []


def test_registry_loads_legacy_entry_point_alias(monkeypatch):
    class FakeEntryPoint:
        name = "plugin-harness"
        value = f"{__name__}:_PluginHarness"

        def load(self):
            return _PluginHarness

    class FakeEntryPoints:
        def select(self, *, group):
            if group == registry_module.ENTRY_POINT_GROUP:
                return (FakeEntryPoint(),)
            return ()

    monkeypatch.setattr(registry_module, "entry_points", lambda: FakeEntryPoints())

    registry = HarnessRegistry()
    registry.load_entry_points()

    assert HARNESS_ADAPTER_ENTRY_POINTS.groups == (
        NEUTRAL_ENTRY_POINT_GROUP,
        registry_module.ENTRY_POINT_GROUP,
    )
    assert registry.ids() == ("plugin-harness",)
    assert registry.discovery_errors == []


def test_registry_deduplicates_equivalent_neutral_and_legacy_aliases(monkeypatch):
    class FakeEntryPoint:
        name = "plugin-harness"
        value = f"{__name__}:_PluginHarness"

        def load(self):
            return _PluginHarness

    class FakeEntryPoints:
        def select(self, *, group):
            assert group in HARNESS_ADAPTER_ENTRY_POINTS.groups
            return (FakeEntryPoint(),)

    monkeypatch.setattr(registry_module, "entry_points", lambda: FakeEntryPoints())

    registry = HarnessRegistry()
    registry.load_entry_points()

    assert registry.ids() == ("plugin-harness",)
    assert registry.discovery_errors == []


def test_registry_keeps_first_registration_on_id_collision(monkeypatch):
    class NeutralEntryPoint:
        name = "neutral-plugin"
        value = f"{__name__}:_PluginHarness"

        def load(self):
            return _PluginHarness

    class LegacyEntryPoint:
        name = "legacy-plugin"
        value = f"{__name__}:_CollidingPluginHarness"

        def load(self):
            return _CollidingPluginHarness

    class FakeEntryPoints:
        def select(self, *, group):
            if group == NEUTRAL_ENTRY_POINT_GROUP:
                return (NeutralEntryPoint(),)
            return (LegacyEntryPoint(),)

    monkeypatch.setattr(registry_module, "entry_points", lambda: FakeEntryPoints())

    registry = HarnessRegistry()
    registry.load_entry_points()

    assert type(registry.get("plugin-harness")) is _PluginHarness
    assert len(registry.discovery_errors) == 1
    assert "collision" in registry.discovery_errors[0]
    assert NEUTRAL_ENTRY_POINT_GROUP in registry.discovery_errors[0]


def test_registry_rejects_runtime_duplicate_id_without_overwrite():
    registry = HarnessRegistry()
    original = _PluginHarness()
    registry.register(original)

    with pytest.raises(RegistryCollisionError):
        registry.register(_CollidingPluginHarness())

    assert registry.get("plugin-harness") is original


def test_registry_bounds_and_redacts_load_failures(monkeypatch):
    class BrokenEntryPoint:
        value = "broken_plugin:factory"

        def __init__(self, index):
            self.name = f"broken-{index}"

        def load(self):
            raise ValueError("token=super-secret-credential " + "x" * 800)

    class FakeEntryPoints:
        def select(self, *, group):
            if group == NEUTRAL_ENTRY_POINT_GROUP:
                return tuple(
                    BrokenEntryPoint(index) for index in range(MAX_DISCOVERY_ERRORS + 5)
                )
            return ()

    monkeypatch.setattr(registry_module, "entry_points", lambda: FakeEntryPoints())

    registry = HarnessRegistry()
    registry.load_entry_points()

    assert len(registry.discovery_errors) == MAX_DISCOVERY_ERRORS
    assert all(
        len(message) <= MAX_DISCOVERY_ERROR_CHARS
        for message in registry.discovery_errors
    )
    assert all(
        "super-secret-credential" not in message
        for message in registry.discovery_errors
    )
    assert all("details omitted" in message for message in registry.discovery_errors)


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


def test_direct_chat_spec_serializes_canonical_builtin_tool_names():
    payload = spec_to_dict(DirectChatHarness.spec())

    assert payload["supported_builtin_tools"] == [
        "web_search",
        "url_content_extraction",
        "code_interpreter",
        "image_generate",
        "model_3d_generate",
    ]


def test_redact_secrets_preserves_only_numeric_usage_token_fields():
    payload = redact_secrets(
        {
            "input_tokens": 8,
            "output_tokens": 3,
            "total_tokens": 11,
            "input_tokens_details": {"cached_tokens": 2, "token": "secret"},
            "access_token": "secret-access-token",
            "completion_tokens": "not-a-counter",
        }
    )

    assert payload == {
        "input_tokens": 8,
        "output_tokens": 3,
        "total_tokens": 11,
        "input_tokens_details": {
            "cached_tokens": 2,
            "token": "<redacted>",
        },
        "access_token": "<redacted>",
        "completion_tokens": "<redacted>",
    }


def test_redact_secrets_scrubs_secret_assignments_in_free_form_tool_output():
    output = redact_secrets(
        "FOO_SECRET=plain-secret\n"
        'DATABASE_URL="postgresql://user:password@db.local/app"\n'
        "safe=https://example.com/path"
    )

    assert "plain-secret" not in output
    assert "user:password" not in output
    assert "FOO_SECRET=<redacted>" in output
    assert 'DATABASE_URL="<redacted>"' in output
    assert "safe=https://example.com/path" in output


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


class _CollidingPluginHarness(_PluginHarness):
    pass
