import threading
import time
from email.parser import BytesParser
from email.policy import default

import pytest

from gpt2giga_harness import proxy
from gpt2giga_harness.types import GigaChatApiMode, HarnessContext


def test_upload_file_sends_multipart_to_versioned_files_route(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return b'{"id":"file-pdf-1"}'

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(proxy, "urlopen", fake_urlopen)

    result = proxy.upload_file(
        "http://127.0.0.1:8090",
        GigaChatApiMode.V2,
        filename="Отчёт.pdf",
        content=b"%PDF-1.7\nfixture",
        content_type="application/pdf",
        api_key="proxy-key",
        timeout=12,
    )

    request = captured["request"]
    content_type = request.get_header("Content-type")
    message = BytesParser(policy=default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode()
        + request.data
    )
    parts = list(message.iter_parts())

    assert result == {"id": "file-pdf-1"}
    assert request.full_url == "http://127.0.0.1:8090/v2/files"
    assert request.get_header("Authorization") == "Bearer proxy-key"
    assert parts[0].get_payload(decode=True) == b"assistants"
    assert parts[1].get_filename() == "Отчёт.pdf"
    assert parts[1].get_content_type() == "application/pdf"
    assert parts[1].get_payload(decode=True) == b"%PDF-1.7\nfixture"


def test_stream_sse_json_decodes_events_and_stops_at_done(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def __iter__(self):
            return iter(
                (
                    b": keepalive\n",
                    b'data: {"chunk": 1}\n',
                    b"\n",
                    b'data: {"chunk": 2}\n',
                    b"\n",
                    b"data: [DONE]\n",
                    b"\n",
                )
            )

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(proxy, "urlopen", fake_urlopen)

    events = list(
        proxy.stream_sse_json(
            "POST",
            "http://127.0.0.1:8090/v2/chat/completions",
            payload={"stream": True},
            api_key="proxy-key",
            timeout=12,
        )
    )

    assert events == [{"chunk": 1}, {"chunk": 2}]
    assert captured["timeout"] == 12
    assert captured["request"].get_header("Accept") == "text/event-stream"
    assert captured["request"].get_header("Authorization") == "Bearer proxy-key"
    assert captured["request"].data == b'{"stream": true}'


def test_stream_sse_json_cancellation_interrupts_blocked_read(monkeypatch):
    closed = threading.Event()

    class BlockingResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            self.close()
            return False

        def __iter__(self):
            return self

        def __next__(self):
            closed.wait(5)
            raise StopIteration

        def close(self):
            closed.set()

    monkeypatch.setattr(proxy, "urlopen", lambda request, timeout: BlockingResponse())
    cancel_event = threading.Event()
    timer = threading.Timer(0.1, cancel_event.set)
    started_at = time.monotonic()
    timer.start()
    try:
        events = list(
            proxy.stream_sse_json(
                "POST",
                "http://127.0.0.1:8090/v2/chat/completions",
                payload={"stream": True},
                timeout=5,
                cancel_event=cancel_event,
            )
        )
    finally:
        timer.cancel()

    assert events == []
    assert time.monotonic() - started_at < 0.75
    assert closed.wait(0.2)


def test_sidecar_preflight_requires_gigachat_credentials(monkeypatch):
    monkeypatch.setattr(proxy, "gpt2giga_preset_available", lambda: True)
    monkeypatch.delenv("GIGACHAT_CREDENTIALS", raising=False)
    monkeypatch.delenv("GIGACHAT_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("GIGACHAT_USER", raising=False)

    result = proxy.sidecar_preflight(
        HarnessContext(
            proxy_url="http://127.0.0.1:8090",
            auto_start_proxy=True,
        )
    )

    assert result.ok is False
    assert "missing GigaChat credentials" in result.reason


def test_sidecar_preflight_requires_optional_gpt2giga_preset(monkeypatch):
    monkeypatch.setattr(proxy, "gpt2giga_preset_available", lambda: False)
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "secret")

    result = proxy.sidecar_preflight(
        HarnessContext(
            proxy_url="http://127.0.0.1:8090",
            auto_start_proxy=True,
        )
    )

    assert result.ok is False
    assert result.reason == (
        "optional gpt2giga preset is not installed; install gpt2giga-harness[gpt2giga]"
    )


def test_sidecar_preflight_rejects_remote_proxy_url(monkeypatch):
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "secret")

    result = proxy.sidecar_preflight(
        HarnessContext(
            proxy_url="http://192.0.2.10:8090",
            auto_start_proxy=True,
        )
    )

    assert result.ok is False
    assert "limited to 127.0.0.1" in result.reason


def test_ensure_proxy_available_starts_local_sidecar(monkeypatch):
    captured = {}
    health_results = [
        proxy.ProxyHealth(
            ok=False,
            url="http://127.0.0.1:8090",
            error="connection refused",
        ),
        proxy.ProxyHealth(
            ok=True,
            url="http://127.0.0.1:8090",
            path="/health",
            status_code=200,
        ),
    ]

    class FakeProcess:
        pid = 4321
        returncode = None

        def poll(self):
            return None

        def terminate(self):
            captured["terminated"] = True

        def wait(self, timeout):
            captured["wait_timeout"] = timeout

        def kill(self):
            captured["killed"] = True

    def fake_popen(command, *, env, stdout, stderr, start_new_session):
        captured["command"] = command
        captured["env"] = env
        captured["stdout"] = stdout
        captured["stderr"] = stderr
        captured["start_new_session"] = start_new_session
        return FakeProcess()

    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "secret")
    monkeypatch.setattr(proxy, "_SIDECAR_API_KEYS", {})
    monkeypatch.setattr(proxy, "_OWNED_SIDECARS", {})
    monkeypatch.setattr(proxy, "_health_check_url", lambda url: health_results.pop(0))
    monkeypatch.setattr(proxy.subprocess, "Popen", fake_popen)

    result = proxy.ensure_proxy_available(
        HarnessContext(
            proxy_url="http://127.0.0.1:8090",
            default_model="GigaChat-2-Max",
            auto_start_proxy=True,
        ),
        GigaChatApiMode.V2,
    )

    assert result.ok is True
    assert result.started is True
    assert result.pid == 4321
    assert result.api_key
    assert captured["command"][-1] == "from gpt2giga import run; run()"
    assert captured["env"]["GPT2GIGA_HOST"] == "127.0.0.1"
    assert captured["env"]["GPT2GIGA_PORT"] == "8090"
    assert captured["env"]["GPT2GIGA_ENABLE_API_KEY_AUTH"] == "True"
    assert captured["env"]["GPT2GIGA_API_KEY"] == result.api_key
    assert captured["env"]["GPT2GIGA_GIGACHAT_API_MODE"] == "v2"
    assert captured["env"]["GPT2GIGA_PASS_MODEL"] == "False"
    assert captured["env"]["GPT2GIGA_DISABLE_REASONING"] == "True"
    assert captured["env"]["GIGACHAT_MODEL"] == "GigaChat-2-Max"
    assert proxy.cached_sidecar_api_key("http://127.0.0.1:8090") == result.api_key


@pytest.mark.parametrize("api_mode", [GigaChatApiMode.V1, GigaChatApiMode.V2])
@pytest.mark.parametrize("api_key", [None, "configured-proxy-key"])
def test_route_preflight_probes_exact_selected_route_without_cached_key(
    monkeypatch,
    api_mode,
    api_key,
):
    captured = {}

    def fake_ensure(context, selected_mode, *, use_cached_sidecar_key):
        captured["ensure"] = (context.proxy_url, selected_mode, use_cached_sidecar_key)
        return proxy.ProxyStartup(
            ok=True,
            proxy_url=context.proxy_url,
            api_key=api_key,
            health_path="/health",
            health_status_code=200,
            detail="external proxy",
        )

    def fake_request(method, url, *, api_key, timeout):
        captured["request"] = (method, url, api_key, timeout)
        return {"data": []}

    monkeypatch.setattr(proxy, "ensure_proxy_available", fake_ensure)
    monkeypatch.setattr(proxy, "request_json", fake_request)

    result = proxy.ensure_proxy_route_available(
        HarnessContext(proxy_url="http://127.0.0.1:8090", api_key=api_key),
        api_mode,
    )
    evidence = proxy.proxy_route_preflight_to_dict(result)

    assert result.ok is True
    assert captured["ensure"] == (
        "http://127.0.0.1:8090",
        api_mode,
        False,
    )
    assert captured["request"] == (
        "GET",
        f"http://127.0.0.1:8090/{api_mode.value}/models",
        api_key,
        5,
    )
    assert evidence["route_path"] == f"/{api_mode.value}/models"
    assert evidence["auth"] == ("configured" if api_key else "not_configured")
    assert evidence["ownership"] == "external"
    assert "api_key" not in evidence


def test_route_preflight_reports_missing_existing_proxy_auth(monkeypatch):
    monkeypatch.setattr(
        proxy,
        "ensure_proxy_available",
        lambda context, api_mode, *, use_cached_sidecar_key: proxy.ProxyStartup(
            ok=True,
            proxy_url=context.proxy_url,
            health_path="/health",
            health_status_code=200,
        ),
    )

    def reject_auth(method, url, *, api_key, timeout):
        del method, url, api_key, timeout
        raise proxy.ProxyRequestError("proxy returned HTTP 401", status_code=401)

    monkeypatch.setattr(proxy, "request_json", reject_auth)

    result = proxy.ensure_proxy_route_available(
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
        GigaChatApiMode.V1,
    )

    assert result.ok is False
    assert result.status_code == 401
    assert "GPT2GIGA_HARNESS_API_KEY" in str(result.error)


def test_route_preflight_evidence_removes_proxy_url_userinfo():
    result = proxy.ProxyRoutePreflight(
        ok=True,
        proxy_url="https://user:password@example.test:8443/base?token=secret#frag",
        api_mode=GigaChatApiMode.V2,
        route_path="/v2/models",
        startup=proxy.ProxyStartup(ok=True, api_key="proxy-key"),
        status_code=200,
    )

    evidence = proxy.proxy_route_preflight_to_dict(result)

    assert evidence["proxy_url"] == "https://example.test:8443/base"
    assert "password" not in str(evidence)
    assert "secret" not in str(evidence)


def test_stop_owned_sidecar_terminates_only_exact_owned_process(monkeypatch):
    calls = []

    class FakeProcess:
        def poll(self):
            return None

        def terminate(self):
            calls.append("terminate")

        def wait(self, timeout):
            calls.append(("wait", timeout))

        def kill(self):
            calls.append("kill")

    process = FakeProcess()
    monkeypatch.setattr(proxy, "_OWNED_SIDECARS", {"owner-1": process})
    monkeypatch.setattr(
        proxy,
        "_SIDECAR_API_KEYS",
        {"http://127.0.0.1:8090": "owned-key"},
    )
    owned = proxy.ProxyStartup(
        ok=True,
        proxy_url="http://127.0.0.1:8090",
        started=True,
        api_key="owned-key",
        ownership_id="owner-1",
    )
    external = proxy.ProxyStartup(
        ok=True,
        proxy_url="http://127.0.0.1:8090",
        started=False,
    )

    assert proxy.stop_owned_sidecar(external) is False
    assert calls == []
    assert proxy.stop_owned_sidecar(owned) is True
    assert calls == ["terminate", ("wait", 2)]
    assert proxy.cached_sidecar_api_key("http://127.0.0.1:8090") is None
    assert proxy.stop_owned_sidecar(owned) is False
