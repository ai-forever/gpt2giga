from fastapi.testclient import TestClient

from gpt2giga.api_server import create_app
from gpt2giga.models.config import ProxyConfig, ProxySettings


def test_metrics_endpoint_disabled_by_default():
    app = create_app()
    client = TestClient(app)

    response = client.get("/metrics")

    assert response.status_code == 404


def test_metrics_endpoint_returns_prometheus_text_without_secrets():
    app = create_app(
        ProxyConfig(proxy=ProxySettings(metrics_enabled=True)),
    )
    client = TestClient(app)

    health_response = client.get(
        "/health",
        headers={"Authorization": "Bearer local-secret"},
    )
    response = client.get("/metrics")

    assert health_response.status_code == 200
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "# TYPE gpt2giga_requests_total counter" in response.text
    assert (
        'gpt2giga_requests_total{lifecycle="request_completed",method="GET",'
        'protocol="system",route="/health",status_code="200"} 1'
    ) in response.text
    assert "local-secret" not in response.text
    assert "request_id" not in response.text


def test_metrics_endpoint_uses_custom_path():
    app = create_app(
        ProxyConfig(
            proxy=ProxySettings(
                metrics_enabled=True,
                metrics_path="internal/metrics/",
            )
        ),
    )
    client = TestClient(app)

    assert client.get("/metrics").status_code == 404
    assert client.get("/internal/metrics").status_code == 200


def test_metrics_endpoint_requires_api_key_when_auth_enabled():
    app = create_app(
        ProxyConfig(
            proxy=ProxySettings(
                metrics_enabled=True,
                enable_api_key_auth=True,
                api_key="metrics-secret",
            )
        ),
    )
    client = TestClient(app)

    assert client.get("/metrics").status_code == 401
    assert (
        client.get(
            "/metrics",
            headers={"Authorization": "Bearer metrics-secret"},
        ).status_code
        == 200
    )
