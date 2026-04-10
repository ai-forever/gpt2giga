from gpt2giga.app.telemetry import PrometheusMetricsSink


def test_prometheus_metrics_sink_renders_request_error_and_stream_metrics():
    sink = PrometheusMetricsSink()
    sink.record_request_event(
        {
            "provider": "openai",
            "endpoint": "/chat/completions",
            "method": "POST",
            "status_code": 429,
            "duration_ms": 125.0,
            "stream_duration_ms": 500.0,
            "error_type": "RateLimitError",
        }
    )

    rendered = sink.render_prometheus_text()

    assert (
        'gpt2giga_http_requests_total{provider="openai",endpoint="/chat/completions",'
        'method="POST",status_code="429"} 1'
    ) in rendered
    assert (
        'gpt2giga_http_request_errors_total{provider="openai",'
        'endpoint="/chat/completions",method="POST",error_type="RateLimitError"} 1'
    ) in rendered
    assert "gpt2giga_http_request_duration_seconds_bucket" in rendered
    assert (
        'gpt2giga_http_stream_duration_seconds_sum{provider="openai",'
        'endpoint="/chat/completions",method="POST"} 0.5'
    ) in rendered
