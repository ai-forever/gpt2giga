import json
import stat

from gpt2giga_harness import doctor, proxy
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.doctor import (
    _native_facade_evidence,
    build_doctor_report,
    format_doctor_report,
    run_doctor,
    write_doctor_support_report,
)
from gpt2giga_harness.registry import HarnessRegistry
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore


def test_native_facade_doctor_evidence_keeps_l0_ready_when_l2_drifts():
    evidence = _native_facade_evidence(
        "codex",
        probe_status="degraded",
        compatible=False,
        version="0.145.0",
        version_status="above_window",
        executable="/tmp/codex",
        executable_source="path",
    )

    assert evidence["levels"] == {
        "L0": "ready",
        "L1": "ready",
        "L2": "degraded",
    }
    assert evidence["transport"] == "app-server"
    assert evidence["degradation"] == "structured_above_window"
    assert evidence["executable"] == "codex"
    assert evidence["executable_present"] is True
    assert "L0 remains available" in evidence["remediation"]


def test_native_facade_doctor_evidence_reports_truthful_claude_l1():
    evidence = _native_facade_evidence(
        "claude",
        probe_status="supported",
        compatible=True,
        version="2.1.0",
        version_status="in_window",
        executable="/tmp/claude",
        executable_source="configured",
    )

    assert evidence["levels"]["L0"] == "ready"
    assert evidence["levels"]["L1"] == "ready"
    assert evidence["levels"]["L2"] == "degraded"
    assert evidence["transport"] is None
    assert evidence["degradation"] == "provider_owned_l1"


def test_doctor_text_formats_native_facade_levels_and_remediation():
    output = format_doctor_report(
        {
            "summary": {"ready": 0, "degraded": 1, "blocked": 0},
            "checks": [
                {
                    "status": "degraded",
                    "summary": "Harness / codex-cli: degraded",
                    "evidence": {
                        "native_facade": _native_facade_evidence(
                            "codex",
                            probe_status="degraded",
                            compatible=False,
                            version="0.145.0",
                            version_status="above_window",
                            executable="/tmp/codex",
                            executable_source="path",
                        )
                    },
                }
            ],
        }
    )

    assert "L0=ready; L1=ready; L2=degraded" in output
    assert "transport=app-server" in output
    assert "Degradation: structured_above_window" in output
    assert "L0 remains available" in output


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


def test_probe_json_route_sends_ping_message(monkeypatch):
    captured = {}

    def fake_request_json(method, url, *, payload, api_key, timeout):
        captured["method"] = method
        captured["url"] = url
        captured["payload"] = payload
        captured["api_key"] = api_key
        captured["timeout"] = timeout
        return {}

    monkeypatch.setattr(proxy, "request_json", fake_request_json)

    result = proxy.probe_json_route(
        HarnessConfig(default_model="GigaChat-2-Max", api_key="proxy-key"),
        "/v2/chat/completions",
    )

    assert result.ok is True
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/v2/chat/completions")
    assert captured["payload"] == {
        "messages": [{"role": "user", "content": "ping"}],
        "stream": False,
        "model": "GigaChat-2-Max",
    }
    assert captured["api_key"] == "proxy-key"
    assert captured["timeout"] == 5


def test_probe_json_route_uses_model_fallback(monkeypatch):
    captured = {}

    def fake_request_json(method, url, *, payload, api_key, timeout):
        captured["payload"] = payload
        return {}

    monkeypatch.setattr(proxy, "request_json", fake_request_json)

    result = proxy.probe_json_route(HarnessConfig(), "/v2/chat/completions")

    assert result.ok is True
    assert captured["payload"]["model"] == "GigaChat-3.5-432B-A28B"
    assert captured["payload"]["messages"] == [{"role": "user", "content": "ping"}]


def test_doctor_reports_live_route_probes(monkeypatch):
    captured_models = []
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
            models=("DiscoveredModel",),
            source="/v2/models",
        ),
    )

    def fake_probe_json_route(config, path, *, model=None, **kwargs):
        captured_models.append(model)
        return proxy.RouteProbe(
            ok=True,
            path=path,
            method="POST",
            status_code=422,
            detail="route rejected the intentionally minimal JSON probe",
        )

    monkeypatch.setattr(proxy, "probe_json_route", fake_probe_json_route)

    output = run_doctor(HarnessConfig())

    assert "/v1/chat/completions: reachable (HTTP 422" in output
    assert "/v2/chat/completions: reachable (HTTP 422" in output
    assert captured_models == ["DiscoveredModel", "DiscoveredModel"]


def test_doctor_report_is_redacted_actionable_and_workspace_scoped(
    monkeypatch,
    tmp_path,
):
    secret = "doctor-secret-value"
    package_versions = {
        "gpt2giga": "0.2.3a2",
        "gpt2giga-harness": "0.0.1a4",
    }
    monkeypatch.setattr(doctor, "_package_version", package_versions.__getitem__)
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", secret)
    monkeypatch.setattr(
        proxy,
        "health_check",
        lambda config: proxy.ProxyHealth(
            ok=False,
            url=config.proxy_url,
            error=f"upstream password={secret}",
        ),
    )
    monkeypatch.setattr(
        proxy,
        "sidecar_preflight",
        lambda _context: proxy.SidecarPreflight(
            ok=False,
            reason=f"authorization: {secret}",
        ),
    )
    monkeypatch.setattr(
        proxy,
        "discover_models",
        lambda config, api_mode: proxy.ModelDiscovery(
            ok=False,
            models=(),
            source="fallback hints",
            error="proxy unavailable",
        ),
    )
    registry = HarnessRegistry()
    registry.discovery_errors.append(f"plugin token={secret}")

    report = build_doctor_report(
        HarnessConfig(
            proxy_url=f"http://operator:{secret}@127.0.0.1:8090",
            data_dir=str(tmp_path / "state"),
        ),
        registry,
        workspace=tmp_path,
    )

    serialized = json.dumps(report)
    by_id = {check["id"]: check for check in report["checks"]}
    assert report["schema_version"] == 2
    assert report["kind"] == "gpt2giga_harness_doctor_report"
    assert report["privacy"] == {
        "content_free": True,
        "prompts_collected": False,
        "sensitive_values_collected": False,
        "oauth_material_collected": False,
        "raw_traffic_collected": False,
        "private_file_content_collected": False,
        "raw_paths_collected": False,
    }
    assert report["export"]["check_count"] == len(report["checks"])
    assert len(report["export"]["content_sha256"]) == 64
    assert report["environment"]["packages"] == {
        "gpt2giga": "0.2.3a2",
        "gpt2giga-harness": "0.0.1a4",
    }
    assert report["ok"] is False
    assert secret not in serialized
    assert str(tmp_path) not in serialized
    assert by_id["workspace"]["status"] == "ready"
    assert by_id["git-readiness"]["status"] == "degraded"
    assert by_id["git-readiness"]["remediation"][0]["command"] == "git init"
    assert by_id["durable-worker"]["remediation"][0]["command"] == "giga worker start"
    assert by_id["managed-homes"]["evidence"]["storage_writable"] is True
    assert by_id["managed-mcp-snapshots"]["evidence"]["stored"] == 0
    assert by_id["ui-identity"]["evidence"]["mode"] == "local"
    assert by_id["scoped-network"]["evidence"]["default"] == "deny"
    assert by_id["mcp-sources"]["evidence"]["probed"] is False
    assert by_id["skills-sources"]["evidence"]["oidc_material_readable"] is False
    assert by_id["plugin-sources"]["evidence"]["plugin_content_retained"] is False
    assert by_id["provider-profiles"]["evidence"]["values_resolved"] is False
    assert by_id["extensions"]["evidence"]["installation_authorized"] is False
    assert by_id["github-cli"]["evidence"]["network_contacted"] is False
    assert by_id["optional-dependencies"]["status"] == "ready"
    assert by_id["support-export"]["evidence"]["mode"] == "0600"


def test_privacy_safe_web_doctor_skips_online_model_and_route_checks(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        proxy,
        "health_check",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("health probe must not run")
        ),
    )
    monkeypatch.setattr(
        proxy,
        "discover_models",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("model discovery must not run")
        ),
    )
    monkeypatch.setattr(
        proxy,
        "probe_json_route",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("route probe must not run")
        ),
    )
    monkeypatch.setattr(
        proxy,
        "sidecar_preflight",
        lambda _context: proxy.SidecarPreflight(ok=True, reason="ready"),
    )

    report = build_doctor_report(
        HarnessConfig(data_dir=str(tmp_path / "state")),
        HarnessRegistry(),
        workspace=tmp_path,
        online_checks=False,
        ui_identity={
            "local": True,
            "authenticated": True,
            "claimable": False,
        },
    )

    by_id = {check["id"]: check for check in report["checks"]}
    assert report["guided"]["online_checks"] is False
    assert by_id["ui-identity"]["status"] == "ready"
    assert by_id["proxy-health"]["evidence"]["network_contacted"] is False
    assert by_id["route-v1"]["evidence"]["checked"] is False
    assert by_id["route-v2"]["evidence"]["checked"] is False
    assert by_id["model-discovery"]["evidence"]["checked"] is False


def test_doctor_reads_worker_status_without_rewriting_runtime_state(
    monkeypatch,
    tmp_path,
):
    store = RuntimeCoordinationStore(tmp_path)
    store.register_worker(
        worker_id="worker-test",
        process_id=123,
        hostname="test-host",
        capability_fingerprint={},
    )
    runtime_path = tmp_path / "runtime.sqlite3"
    before = runtime_path.stat().st_mtime_ns
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
        "sidecar_preflight",
        lambda _context: proxy.SidecarPreflight(
            ok=False, reason="local credentials are not configured"
        ),
    )
    monkeypatch.setattr(
        proxy,
        "discover_models",
        lambda config, api_mode: proxy.ModelDiscovery(
            ok=True,
            models=("GigaChat",),
            source="/v2/models",
        ),
    )
    monkeypatch.setattr(
        proxy,
        "probe_json_route",
        lambda config, path, **kwargs: proxy.RouteProbe(
            ok=path.startswith("/v2"),
            path=path,
            method="POST",
            status_code=422 if path.startswith("/v2") else 404,
        ),
    )

    report = build_doctor_report(
        HarnessConfig(data_dir=str(tmp_path)),
        HarnessRegistry(),
        workspace=tmp_path,
    )

    by_id = {check["id"]: check for check in report["checks"]}
    worker = by_id["durable-worker"]
    assert report["ok"] is True
    assert by_id["proxy-autostart"]["status"] == "ready"
    assert by_id["route-v1"]["status"] == "degraded"
    assert by_id["route-v2"]["status"] == "ready"
    assert worker["status"] == "ready"
    assert worker["evidence"] == {
        "initialized": True,
        "readable": True,
        "online": 1,
        "offline": 0,
        "total": 1,
    }
    assert runtime_path.stat().st_mtime_ns == before


def test_doctor_support_report_is_canonical_private_and_replaceable(tmp_path):
    output = tmp_path / "support" / "doctor.json"
    report = {
        "schema_version": 1,
        "kind": "gpt2giga_harness_doctor_report",
        "ok": False,
        "summary": {"ready": 1, "degraded": 2, "blocked": 3},
        "checks": [],
    }

    write_doctor_support_report(report, output)
    first = output.read_bytes()
    write_doctor_support_report(report, output)

    assert output.read_bytes() == first
    assert (
        first
        == (
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode()
    )
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
