import pytest

from gpt2giga.core.interfaces import ObservabilitySink
from gpt2giga.models.config import ProxySettings
from gpt2giga.sinks.observability.factory import (
    create_observability_sink,
    emit_observability_event,
    flush_observability_sink,
)
from gpt2giga.sinks.observability.noop import NoopObservabilitySink


@pytest.mark.asyncio
async def test_noop_observability_sink_implements_contract():
    sink = NoopObservabilitySink()

    assert isinstance(sink, ObservabilitySink)
    await sink.emit("request.completed", {"status_code": 200})
    await sink.flush()


def test_observability_factory_returns_noop_when_enabled():
    sink = create_observability_sink(ProxySettings(observability_enabled=True))

    assert isinstance(sink, NoopObservabilitySink)


@pytest.mark.asyncio
async def test_observability_safe_helpers_do_not_raise_on_sink_errors():
    class BrokenSink:
        async def emit(self, name, attributes=None, *, context=None):
            raise RuntimeError("emit failed")

        async def flush(self):
            raise RuntimeError("flush failed")

    sink = BrokenSink()

    await emit_observability_event(sink, "request.failed")
    await flush_observability_sink(sink)
