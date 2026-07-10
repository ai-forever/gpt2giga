import pytest

from gpt2giga.harness import proxy
from gpt2giga.harness.config import HarnessConfig
from gpt2giga.harness.harnesses.direct_chat import DirectChatHarness
from gpt2giga.harness.types import (
    GigaChatApiMode,
    HarnessChatMessage,
    HarnessContext,
    HarnessRequest,
)


@pytest.mark.parametrize(
    ("api_mode", "expected_path"),
    (
        (GigaChatApiMode.V1, "/v1/chat/completions"),
        (GigaChatApiMode.V2, "/v2/chat/completions"),
    ),
)
def test_direct_chat_builds_v1_v2_urls(monkeypatch, api_mode, expected_path):
    captured = {}

    def fake_request_json(method, url, *, payload, api_key, timeout):
        captured.update(
            {
                "method": method,
                "url": url,
                "payload": payload,
                "api_key": api_key,
                "timeout": timeout,
            }
        )
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(proxy, "request_json", fake_request_json)
    result = DirectChatHarness().run(
        HarnessRequest(prompt="hello", model="GigaChat-2-Max", api_mode=api_mode),
        HarnessContext(
            proxy_url="http://127.0.0.1:8090",
            api_key="proxy-key",
            timeout_seconds=12,
        ),
    )

    assert result.ok is True
    assert result.text == "ok"
    assert captured["method"] == "POST"
    assert captured["url"] == f"http://127.0.0.1:8090{expected_path}"
    assert captured["payload"]["model"] == "GigaChat-2-Max"
    assert captured["payload"]["messages"] == [{"role": "user", "content": "hello"}]
    assert captured["api_key"] == "proxy-key"
    assert captured["timeout"] == 12


def test_direct_chat_parses_choices_message_content(monkeypatch):
    monkeypatch.setattr(
        proxy,
        "request_json",
        lambda *args, **kwargs: {"choices": [{"message": {"content": "answer"}}]},
    )

    result = DirectChatHarness().run(
        HarnessRequest(prompt="hello"),
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    assert result.text == "answer"


def test_direct_chat_sends_provided_history(monkeypatch):
    captured = {}

    def fake_request_json(method, url, *, payload, api_key, timeout):
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(proxy, "request_json", fake_request_json)

    DirectChatHarness().run(
        HarnessRequest(
            prompt="second",
            messages=(
                HarnessChatMessage(role="user", content="first"),
                HarnessChatMessage(role="assistant", content="answer"),
                HarnessChatMessage(role="user", content="second"),
            ),
        ),
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    assert captured["payload"]["messages"] == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "second"},
    ]


def test_direct_chat_streams_coalesced_message_tool_and_usage_events(monkeypatch):
    captured = {}
    emitted = []

    def fake_stream_sse_json(
        method,
        url,
        *,
        payload,
        api_key,
        timeout,
        cancel_event,
        idle_callback,
    ):
        captured.update(
            {
                "method": method,
                "url": url,
                "payload": payload,
                "api_key": api_key,
                "timeout": timeout,
                "cancel_event": cancel_event,
                "idle_callback": idle_callback,
            }
        )
        yield {
            "id": "chatcmpl-1",
            "model": "GigaChat",
            "choices": [{"index": 0, "delta": {"content": "Hel"}}],
        }
        yield {
            "id": "chatcmpl-1",
            "model": "GigaChat",
            "choices": [{"index": 0, "delta": {"content": "lo"}}],
        }
        yield {
            "id": "chatcmpl-1",
            "model": "GigaChat",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "weather",
                                    "arguments": '{"city":',
                                },
                            }
                        ]
                    },
                }
            ],
        }
        yield {
            "id": "chatcmpl-1",
            "model": "GigaChat",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": '"Moscow"}'},
                            }
                        ]
                    },
                }
            ],
        }
        yield {
            "id": "chatcmpl-1",
            "model": "GigaChat",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
            "usage": {
                "prompt_tokens": 8,
                "completion_tokens": 3,
                "total_tokens": 11,
                "prompt_tokens_details": {"cached_tokens": 2},
            },
        }

    monkeypatch.setattr(proxy, "stream_sse_json", fake_stream_sse_json)

    result = DirectChatHarness().run(
        HarnessRequest(
            prompt="hello",
            model="GigaChat",
            stream=True,
            event_sink=emitted.append,
        ),
        HarnessContext(
            proxy_url="http://127.0.0.1:8090",
            api_key="proxy-key",
            timeout_seconds=12,
        ),
    )

    assert result.ok is True
    assert result.text == "Hello"
    assert result.events == ()
    assert captured["method"] == "POST"
    assert captured["payload"]["stream"] is True
    assert captured["api_key"] == "proxy-key"
    assert [event.type for event in emitted] == [
        "message_delta",
        "tool_call_started",
        "tool_call_delta",
        "usage",
        "tool_call_finished",
    ]
    assert (
        "".join(
            event.payload["delta"] for event in emitted if event.type == "message_delta"
        )
        == "Hello"
    )
    assert emitted[1].payload["name"] == "weather"
    assert emitted[2].payload["arguments_delta"] == '"Moscow"}'
    assert emitted[3].payload == {
        "input_tokens": 8,
        "output_tokens": 3,
        "total_tokens": 11,
        "source": "direct-chat",
        "cached_input_tokens": 2,
    }
    assert emitted[4].payload["arguments"] == '{"city":"Moscow"}'


def test_direct_chat_flushes_pending_text_during_upstream_pause(monkeypatch):
    emitted = []
    observed = {}

    def fake_stream_sse_json(
        method,
        url,
        *,
        payload,
        api_key,
        timeout,
        cancel_event,
        idle_callback,
    ):
        yield {
            "id": "chatcmpl-1",
            "model": "GigaChat",
            "choices": [{"index": 0, "delta": {"content": "A"}}],
        }
        idle_callback.__self__._started_at -= 1
        idle_callback()
        observed["event_count_during_pause"] = len(emitted)

    monkeypatch.setattr(proxy, "stream_sse_json", fake_stream_sse_json)

    result = DirectChatHarness().run(
        HarnessRequest(prompt="hello", stream=True, event_sink=emitted.append),
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    assert result.ok is True
    assert result.text == "A"
    assert observed["event_count_during_pause"] == 1
    assert emitted[0].type == "message_delta"
    assert emitted[0].payload["delta"] == "A"


def test_direct_chat_autostart_uses_generated_sidecar_api_key(monkeypatch):
    captured = {}

    def fake_ensure_proxy_available(context, api_mode):
        captured["startup_context"] = context
        captured["startup_api_mode"] = api_mode
        return proxy.ProxyStartup(
            ok=True,
            started=True,
            api_key="generated-proxy-key",
            pid=123,
            detail="started",
        )

    def fake_request_json(method, url, *, payload, api_key, timeout):
        captured["api_key"] = api_key
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(proxy, "ensure_proxy_available", fake_ensure_proxy_available)
    monkeypatch.setattr(proxy, "request_json", fake_request_json)

    result = DirectChatHarness().run(
        HarnessRequest(prompt="hello", api_mode=GigaChatApiMode.V2),
        HarnessContext(
            proxy_url="http://127.0.0.1:8090",
            auto_start_proxy=True,
        ),
    )

    assert result.ok is True
    assert captured["api_key"] == "generated-proxy-key"
    assert captured["startup_api_mode"] == GigaChatApiMode.V2
    assert result.events[0].type == "proxy_sidecar"
    assert result.events[0].payload["pid"] == 123
    assert "Authorization: Bearer <redacted>" in result.raw["curl_command"]
    assert "generated-proxy-key" not in str(result.raw)


def test_model_listing_falls_back_when_proxy_unavailable(monkeypatch):
    def fail_request(*args, **kwargs):
        raise proxy.ProxyRequestError("down")

    monkeypatch.setattr(proxy, "request_json", fail_request)
    config = HarnessConfig(default_model="ConfiguredModel")

    discovery = proxy.discover_models(config, GigaChatApiMode.V2)

    assert discovery.ok is False
    assert discovery.source == "fallback"
    assert discovery.models[0] == "ConfiguredModel"


def test_model_listing_can_be_strict_to_selected_api_mode(monkeypatch):
    called_urls = []

    def fake_request_json(method, url, *, payload=None, api_key=None, timeout=60.0):
        called_urls.append(url)
        raise proxy.ProxyRequestError("down")

    monkeypatch.setattr(proxy, "request_json", fake_request_json)
    config = HarnessConfig(default_model="ConfiguredModel")

    discovery = proxy.discover_models(
        config,
        GigaChatApiMode.V2,
        include_compat_paths=False,
        include_fallback=False,
    )

    assert discovery.ok is False
    assert discovery.models == ()
    assert discovery.source == "/v2/models"
    assert called_urls == ["http://127.0.0.1:8090/v2/models"]
