from gpt2giga.harness import proxy
from gpt2giga.harness.types import GigaChatApiMode, HarnessContext


def test_sidecar_preflight_requires_gigachat_credentials(monkeypatch):
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
