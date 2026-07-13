import pytest

from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.harnesses.direct_chat import DirectChatHarness
from gpt2giga_harness import registry as registry_module
from gpt2giga_harness.registry import (
    HarnessRegistry,
    UnknownHarnessError,
    create_default_registry,
)
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
