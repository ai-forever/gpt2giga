from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from gpt2giga.api.admin import logs_router
from gpt2giga.app.factory import create_app
from gpt2giga.auth import verify_api_key
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.sinks.logs.query import TrafficLogQueryUnavailable


EVENT_ID = str(uuid4())


class FakeTrafficLogQueryStore:
    def __init__(self, records=None, unavailable: bool = False):
        self.records = records or []
        self.unavailable = unavailable
        self.list_calls = []
        self.get_calls = []
        self.purge_calls = []
        self.redact_calls = []

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

    async def purge_expired(
        self,
        *,
        cutoff,
        batch_size,
        dry_run=True,
        max_batches=1,
    ):
        if self.unavailable:
            raise TrafficLogQueryUnavailable("store unavailable")
        self.purge_calls.append(
            {
                "cutoff": cutoff,
                "batch_size": batch_size,
                "dry_run": dry_run,
                "max_batches": max_batches,
            }
        )
        return {
            "cutoff": cutoff,
            "dry_run": dry_run,
            "expired": 3 if dry_run else None,
            "deleted": 0 if dry_run else 2,
            "batch_size": batch_size,
            "batches": 0 if dry_run else 1,
            "max_batches": max_batches,
            "complete": None if dry_run else True,
        }

    async def redact_payloads(self, event_id, *, fields, metadata=None):
        if self.unavailable:
            raise TrafficLogQueryUnavailable("store unavailable")
        self.redact_calls.append(
            {"event_id": event_id, "fields": list(fields), "metadata": metadata}
        )
        for record in self.records:
            if record["id"] != event_id:
                continue
            for field in fields:
                record[field] = None
            return {
                "id": event_id,
                "request_headers_redacted": record.get("request_headers") is None,
                "request_body_redacted": record.get("request_body") is None,
                "response_body_redacted": record.get("response_body") is None,
                "metadata": metadata or {},
            }
        return None


def make_logs_app(
    store,
    *,
    admin_key: str | None = "secret",
    replay_enabled: bool = False,
):
    app = FastAPI()
    app.include_router(logs_router)
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            admin_api_enabled=True,
            admin_api_key=admin_key,
            replay_enabled=replay_enabled,
        )
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
            "route_group": "chat",
            "operation": "chat_completions",
            "model": "GigaChat",
            "status_code": "200",
            "status_class": "2xx",
            "has_error": "false",
            "stream": "false",
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
    assert body["data"][0]["operation"] == "chat_completions"
    assert body["data"][0]["route_group"] == "chat"
    assert body["data"][0]["stream"] is False
    assert body["data"][0]["has_error"] is False
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
                "route_group": "chat",
                "operation": "chat_completions",
                "model": "GigaChat",
                "status_code": 200,
                "status_class": "2xx",
                "has_error": False,
                "stream": False,
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


def test_admin_logs_csv_export_omits_payload_bodies():
    store = FakeTrafficLogQueryStore([_record()])
    client = TestClient(make_logs_app(store))

    export = client.get("/_admin/logs/export.csv?limit=1", headers=_headers())

    assert export.status_code == 200
    assert export.headers["content-type"].startswith("text/csv")
    assert "id,created_at,request_id" in export.text
    assert "route_group,operation" in export.text
    assert EVENT_ID in export.text
    assert "authorization" not in export.text
    assert "messages" not in export.text
    assert "choices" not in export.text


def test_admin_logs_rejects_invalid_status_class():
    client = TestClient(make_logs_app(FakeTrafficLogQueryStore([_record()])))

    response = client.get(
        "/_admin/logs",
        params={"status_class": "ok"},
        headers=_headers(),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid status_class"


def test_admin_logs_retention_purge_defaults_to_dry_run():
    store = FakeTrafficLogQueryStore([_record()])
    client = TestClient(make_logs_app(store))

    response = client.post("/_admin/logs/retention/purge", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["retention_days"] == 30
    assert body["dry_run"] is True
    assert body["expired"] == 3
    assert body["deleted"] == 0
    assert body["cutoff"].endswith("+00:00")
    assert store.purge_calls[0]["dry_run"] is True
    assert store.purge_calls[0]["batch_size"] == 1000
    assert store.purge_calls[0]["max_batches"] == 1


def test_admin_logs_retention_purge_execute_uses_explicit_limits():
    store = FakeTrafficLogQueryStore([_record()])
    client = TestClient(make_logs_app(store))

    response = client.post(
        "/_admin/logs/retention/purge",
        params={
            "retention_days": "7",
            "batch_size": "25",
            "max_batches": "3",
            "dry_run": "false",
        },
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["retention_days"] == 7
    assert body["dry_run"] is False
    assert body["deleted"] == 2
    assert body["complete"] is True
    assert store.purge_calls[0]["dry_run"] is False
    assert store.purge_calls[0]["batch_size"] == 25
    assert store.purge_calls[0]["max_batches"] == 3


def test_admin_logs_replay_is_disabled_by_default():
    client = TestClient(make_logs_app(FakeTrafficLogQueryStore([_record()])))

    response = client.post(f"/_admin/logs/{EVENT_ID}/replay", headers=_headers())

    assert response.status_code == 404


def test_admin_logs_replay_dispatches_sanitized_request_with_metadata():
    replayed = []
    record = _record(
        request_body={
            "model": "GigaChat",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"tenant": "tenant-1"},
            "api_key": "raw-secret",
        }
    )
    app = make_logs_app(
        FakeTrafficLogQueryStore([record]),
        replay_enabled=True,
    )

    @app.post("/v1/chat/completions")
    async def replay_target(request: Request):
        body = await request.json()
        replayed.append({"body": body, "headers": dict(request.headers)})
        return {"ok": True, "metadata": body["metadata"]}

    client = TestClient(app)

    response = client.post(f"/_admin/logs/{EVENT_ID}/replay", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["replayed"] is True
    assert body["request"]["path"] == "/v1/chat/completions"
    assert body["response"]["status_code"] == 200
    assert body["response"]["body"]["ok"] is True
    assert replayed[0]["headers"]["x-gpt2giga-replay"] == "true"
    assert "authorization" not in replayed[0]["headers"]
    assert replayed[0]["body"]["api_key"] == "***"
    metadata = replayed[0]["body"]["metadata"]
    assert metadata["tenant"] == "tenant-1"
    assert metadata["gpt2giga_replay"]["source_log_id"] == EVENT_ID
    assert metadata["gpt2giga_replay"]["source_request_id"] == "req-1"


def test_admin_logs_replay_injects_api_key_when_prod_requires_auth():
    replayed = []
    app = FastAPI()
    app.include_router(logs_router)
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            mode="PROD",
            api_key="client-secret",
            admin_api_enabled=True,
            admin_api_key="secret",
            replay_enabled=True,
        )
    )
    app.state.traffic_log_query_store = FakeTrafficLogQueryStore([_record()])

    @app.post("/v1/chat/completions", dependencies=[Depends(verify_api_key)])
    async def replay_target(request: Request):
        replayed.append(dict(request.headers))
        return {"ok": True}

    client = TestClient(app)

    response = client.post(f"/_admin/logs/{EVENT_ID}/replay", headers=_headers())

    assert response.status_code == 200
    assert response.json()["response"]["status_code"] == 200
    assert replayed[0]["authorization"] == "Bearer client-secret"


def test_admin_logs_replay_rejects_admin_routes():
    client = TestClient(
        make_logs_app(
            FakeTrafficLogQueryStore([_record(route="/_admin/logs")]),
            replay_enabled=True,
        )
    )

    response = client.post(f"/_admin/logs/{EVENT_ID}/replay", headers=_headers())

    assert response.status_code == 400
    assert (
        response.json()["detail"] == "Admin, debug, and log routes cannot be replayed"
    )


def test_admin_logs_replay_requires_captured_request_body():
    client = TestClient(
        make_logs_app(
            FakeTrafficLogQueryStore([_record(request_body=None)]),
            replay_enabled=True,
        )
    )

    response = client.post(f"/_admin/logs/{EVENT_ID}/replay", headers=_headers())

    assert response.status_code == 409
    assert response.json()["detail"] == "Traffic log request body was not captured"


def test_admin_logs_replay_target_exception_returns_502():
    app = make_logs_app(
        FakeTrafficLogQueryStore([_record()]),
        replay_enabled=True,
    )

    @app.post("/v1/chat/completions")
    async def replay_target():
        raise RuntimeError("target failed")

    client = TestClient(app)

    response = client.post(f"/_admin/logs/{EVENT_ID}/replay", headers=_headers())

    assert response.status_code == 502
    assert response.json()["detail"] == "Replay request failed"


def test_admin_logs_manual_redact_defaults_to_all_payload_fields():
    store = FakeTrafficLogQueryStore([_record()])
    client = TestClient(make_logs_app(store))

    response = client.post(f"/_admin/logs/{EVENT_ID}/redact", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["redacted_fields"] == [
        "request_body",
        "request_headers",
        "response_body",
    ]
    assert body["result"]["request_headers_redacted"] is True
    assert body["result"]["request_body_redacted"] is True
    assert body["result"]["response_body_redacted"] is True
    assert store.redact_calls[0]["event_id"] == EVENT_ID
    assert store.redact_calls[0]["metadata"]["manual_redaction"]["fields"] == [
        "request_body",
        "request_headers",
        "response_body",
    ]


def test_admin_logs_manual_redact_accepts_explicit_fields():
    store = FakeTrafficLogQueryStore([_record()])
    client = TestClient(make_logs_app(store))

    response = client.post(
        f"/_admin/logs/{EVENT_ID}/redact",
        json={"fields": ["request_body"]},
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["redacted_fields"] == ["request_body"]
    assert body["result"]["request_headers_redacted"] is False
    assert body["result"]["request_body_redacted"] is True
    assert body["result"]["response_body_redacted"] is False


def test_admin_logs_manual_redact_rejects_invalid_fields():
    client = TestClient(make_logs_app(FakeTrafficLogQueryStore([_record()])))

    response = client.post(
        f"/_admin/logs/{EVENT_ID}/redact",
        json={"fields": ["api_key"]},
        headers=_headers(),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported redaction fields: api_key"


def test_admin_logs_manual_redact_not_found_and_unavailable():
    missing_client = TestClient(make_logs_app(FakeTrafficLogQueryStore([])))
    unavailable_client = TestClient(
        make_logs_app(FakeTrafficLogQueryStore(unavailable=True))
    )

    missing = missing_client.post(f"/_admin/logs/{EVENT_ID}/redact", headers=_headers())
    unavailable = unavailable_client.post(
        f"/_admin/logs/{EVENT_ID}/redact",
        headers=_headers(),
    )

    assert missing.status_code == 404
    assert unavailable.status_code == 503


def test_admin_logs_unavailable_store_returns_503():
    client = TestClient(make_logs_app(FakeTrafficLogQueryStore(unavailable=True)))

    response = client.get("/_admin/logs", headers=_headers())

    assert response.status_code == 503
    assert response.json()["detail"] == "store unavailable"


def test_admin_logs_retention_unavailable_store_returns_503():
    client = TestClient(make_logs_app(FakeTrafficLogQueryStore(unavailable=True)))

    response = client.post("/_admin/logs/retention/purge", headers=_headers())

    assert response.status_code == 503
    assert response.json()["detail"] == "store unavailable"
