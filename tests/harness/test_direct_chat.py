import pytest

from gpt2giga.harness import proxy
from gpt2giga.harness.config import HarnessConfig
from gpt2giga.harness.harnesses.direct_chat import DirectChatHarness
from gpt2giga.harness.types import GigaChatApiMode, HarnessContext, HarnessRequest


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


def test_model_listing_falls_back_when_proxy_unavailable(monkeypatch):
    def fail_request(*args, **kwargs):
        raise proxy.ProxyRequestError("down")

    monkeypatch.setattr(proxy, "request_json", fail_request)
    config = HarnessConfig(default_model="ConfiguredModel")

    discovery = proxy.discover_models(config, GigaChatApiMode.V2)

    assert discovery.ok is False
    assert discovery.source == "fallback"
    assert discovery.models[0] == "ConfiguredModel"
