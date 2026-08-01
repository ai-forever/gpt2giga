from types import SimpleNamespace

import pytest

import gpt2giga.routers.gemini.generate_content as gemini_module
import gpt2giga.routers.openai.chat_completions as chat_module
from gpt2giga.sinks.base import is_sink_active
from gpt2giga.sinks.logs.noop import NoopTrafficLogSink
from gpt2giga.sinks.metrics.noop import NoopMetricsSink
from gpt2giga.sinks.observability.noop import NoopObservabilitySink


@pytest.mark.parametrize(
    "sink",
    [
        None,
        NoopTrafficLogSink(),
        NoopMetricsSink(),
        NoopObservabilitySink(),
    ],
)
def test_noop_sinks_are_inactive(sink):
    assert not is_sink_active(sink)


def test_regular_sink_is_active():
    assert is_sink_active(object())


@pytest.mark.parametrize(
    ("module", "emit_helper"),
    [
        (chat_module, chat_module._emit_chat_completion_observability),
        (gemini_module, gemini_module._emit_gemini_observability),
    ],
)
async def test_noop_observability_skips_attribute_building(
    monkeypatch, module, emit_helper
):
    build_calls = []

    def record_build(*args, **kwargs):
        build_calls.append((args, kwargs))
        return {}

    monkeypatch.setattr(module, "build_llm_chat_completion_attributes", record_build)
    state = SimpleNamespace(observability_sink=NoopObservabilitySink())

    await emit_helper(state, object(), object(), context=None)

    assert build_calls == []
