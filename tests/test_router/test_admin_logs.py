from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gpt2giga.api.admin import logs_router
from gpt2giga.app.factory import create_app
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.sinks.logs.query import TrafficLogQueryUnavailable


EVENT_ID = str(uuid4())


class FakeTrafficLogQueryStore:
    def __init__(self, records=None, unavailable: bool = False):
        self.records = records or []
        self.unavailable = unavailable
        self.list_calls = []
        self.get_calls = []

    async def list(self, *, limit=100, offset=0, filters=None):
        if self.unavailable:
            raise TrafficLogQueryUnavailable("store unavailable")
        self.list_calls.append(
            {"limit": limit, "offset": offset, "filters": dict(filters or {})}
        )
        return self.records[:limit]

    async def get(self, event_id):
        if self.unavailable:
            raise TrafficLogQueryUnavailable("store unavailable")
        self.get_calls.append(event_id)
        for record in self.records:
            if record["id"] == event_id:
                return record
        return None

    async def get_by_request_id(self, request_id):
        return [record for record in self.records if record["request_id"] == request_id]


def make_logs_app(store, *, admin_key: str | None = "secret"):
    app = FastAPI()
    app.include_router(logs_router)
    app.state.config = ProxyConfig(
        proxy=ProxySettings(admin_api_enabled=True, admin_api_key=admin_key)
    )
    app.state.traffic_log_query_store = store
    return app


def _headers(key: str = "secret") -> dict[str, str]:
    return {"x-admin-api-key": key}


def _record(**overrides):
    base = {
        "id": EVENT_ID,
        "created_at": datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc),
        "request_id": "req-1",
        "trace_id": "trace-1",
        "span_id": "span-1",
        "protocol": "openai",
        "route": "/v1/chat/completions",
        "method": "POST",
        "status_code": 200,
        "model_requested": "GigaChat",
        "model_effective": "GigaChat",
        "provider": "gigachat",
        "latency_ms": 12,
        "input_tokens": 1,
        "output_tokens": 2,
        "total_tokens": 3,
        "api_key_hash": "hash-1",
        "metadata": {"stream": False},
        "request_headers": {"authorization": "***"},
        "request_body": {"messages": [{"role": "user", "content": "***"}]},
        "response_body": {"choices": [{"message": {"content": "ok"}}]},
    }
    base.update(overrides)
    return base


def test_admin_logs_unmounted_by_default():
    app = create_app(ProxyConfig(proxy=ProxySettings()))
    client = TestClient(app)

    response = client.get("/_admin/logs", headers=_headers())

    assert response.status_code == 404


def test_admin_logs_prod_default_is_unmounted():
    app = create_app(
        ProxyConfig(
            proxy=ProxySettings(
                mode="PROD",
                enable_api_key_auth=True,
                api_key="client-secret",
            )
        )
    )
    client = TestClient(app)

    response = client.get("/_admin/logs", headers=_headers())

    assert response.status_code == 404


def test_admin_logs_requires_admin_key():
    client = TestClient(make_logs_app(FakeTrafficLogQueryStore([_record()])))

    missing = client.get("/_admin/logs")
    wrong = client.get("/_admin/logs", headers=_headers("wrong"))
    bearer = client.get("/_admin/logs", headers={"authorization": "Bearer secret"})

    assert missing.status_code == 403
    assert wrong.status_code == 403
    assert bearer.status_code == 200


def test_admin_logs_enabled_without_admin_key_returns_403():
    client = TestClient(
        make_logs_app(FakeTrafficLogQueryStore([_record()]), admin_key=None)
    )

    response = client.get("/_admin/logs", headers=_headers())

    assert response.status_code == 403


def test_admin_logs_list_filters_and_paginates():
    store = FakeTrafficLogQueryStore([_record(), _record(id=str(uuid4()))])
    client = TestClient(make_logs_app(store))

    response = client.get(
        "/_admin/logs",
        params={
            "from": "2026-06-07T00:00:00Z",
            "to": "2026-06-08T00:00:00Z",
            "protocol": "openai",
            "route": "/v1/chat/completions",
            "model": "GigaChat",
            "status_code": "200",
            "has_error": "false",
            "request_id": "req-1",
            "trace_id": "trace-1",
            "api_key_hash": "hash-1",
            "limit": "2",
            "cursor": "4",
        },
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["next_cursor"] == "6"
    assert body["data"][0]["id"] == EVENT_ID
    assert body["data"][0]["created_at"] == "2026-06-07T12:00:00+00:00"
    assert body["data"][0]["has_request_body"] is True
    assert "request_body" not in body["data"][0]
    assert store.list_calls == [
        {
            "limit": 2,
            "offset": 4,
            "filters": {
                "from": "2026-06-07T00:00:00Z",
                "to": "2026-06-08T00:00:00Z",
                "protocol": "openai",
                "route": "/v1/chat/completions",
                "model": "GigaChat",
                "status_code": 200,
                "has_error": False,
                "request_id": "req-1",
                "trace_id": "trace-1",
                "api_key_hash": "hash-1",
            },
        }
    ]


def test_admin_logs_get_request_and_response_payloads():
    client = TestClient(make_logs_app(FakeTrafficLogQueryStore([_record()])))

    detail = client.get(f"/_admin/logs/{EVENT_ID}", headers=_headers())
    request = client.get(f"/_admin/logs/{EVENT_ID}/request", headers=_headers())
    response = client.get(f"/_admin/logs/{EVENT_ID}/response", headers=_headers())

    assert detail.status_code == 200
    assert detail.json()["has_response_body"] is True
    assert "response_body" not in detail.json()
    assert request.status_code == 200
    assert request.json()["request_headers"] == {"authorization": "***"}
    assert request.json()["request_body"]["messages"][0]["content"] == "***"
    assert response.status_code == 200
    assert response.json()["response_body"]["choices"][0]["message"]["content"] == "ok"


def test_admin_logs_not_found_and_invalid_id():
    client = TestClient(make_logs_app(FakeTrafficLogQueryStore([])))

    missing = client.get(f"/_admin/logs/{EVENT_ID}", headers=_headers())
    invalid = client.get("/_admin/logs/not-a-uuid", headers=_headers())

    assert missing.status_code == 404
    assert invalid.status_code == 400


def test_admin_logs_tail_and_ndjson_export():
    store = FakeTrafficLogQueryStore([_record()])
    client = TestClient(make_logs_app(store))

    tail = client.get("/_admin/logs/tail?limit=1", headers=_headers())
    export = client.get("/_admin/logs/export.ndjson?limit=1", headers=_headers())

    assert tail.status_code == 200
    assert tail.json()["data"][0]["id"] == EVENT_ID
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("application/x-ndjson")
    assert '"request_body"' in export.text
    assert export.text.endswith("\n")


def test_admin_logs_unavailable_store_returns_503():
    client = TestClient(make_logs_app(FakeTrafficLogQueryStore(unavailable=True)))

    response = client.get("/_admin/logs", headers=_headers())

    assert response.status_code == 503
    assert response.json()["detail"] == "store unavailable"
