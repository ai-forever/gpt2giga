from gpt2giga.harness import proxy
from gpt2giga.harness.config import HarnessConfig
from gpt2giga.harness.doctor import run_doctor


def test_probe_json_route_treats_validation_error_as_reachable(monkeypatch):
    def fake_request_json(*args, **kwargs):
        raise proxy.ProxyRequestError("bad request", status_code=422)

    monkeypatch.setattr(proxy, "request_json", fake_request_json)

    result = proxy.probe_json_route(HarnessConfig(), "/v2/chat/completions")

    assert result.ok is True
    assert result.status_code == 422
    assert "minimal JSON probe" in (result.detail or "")


def test_probe_json_route_treats_not_found_as_unreachable(monkeypatch):
    def fake_request_json(*args, **kwargs):
        raise proxy.ProxyRequestError("not found", status_code=404)

    monkeypatch.setattr(proxy, "request_json", fake_request_json)

    result = proxy.probe_json_route(HarnessConfig(), "/v2/chat/completions")

    assert result.ok is False
    assert result.status_code == 404
    assert result.detail == "route not found"


def test_doctor_reports_live_route_probes(monkeypatch):
    monkeypatch.setattr(
        proxy,
        "health_check",
        lambda config: proxy.ProxyHealth(
            ok=True,
            url=config.proxy_url,
            path="/health",
            status_code=200,
        ),
    )
    monkeypatch.setattr(
        proxy,
        "discover_models",
        lambda config, api_mode: proxy.ModelDiscovery(
            ok=True,
            models=("GigaChat-2-Max",),
            source="/v2/models",
        ),
    )
    monkeypatch.setattr(
        proxy,
        "probe_json_route",
        lambda config, path: proxy.RouteProbe(
            ok=True,
            path=path,
            method="POST",
            status_code=422,
            detail="route rejected the intentionally minimal JSON probe",
        ),
    )

    output = run_doctor(HarnessConfig())

    assert "/v1/chat/completions: reachable (HTTP 422" in output
    assert "/v2/chat/completions: reachable (HTTP 422" in output
