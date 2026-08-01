import pytest

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
