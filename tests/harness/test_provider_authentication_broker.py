from pathlib import Path
import threading
import time

import pytest
from fastapi.testclient import TestClient

from gpt2giga_harness.cli_capabilities import CliCapabilitySnapshot
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.executables import ExecutableResolution
from gpt2giga_harness.provider_authentication_broker import (
    AuthenticationCommandResult,
    NativeLoginBroker,
    ProviderAccountStatus,
    ProviderAuthenticationConflictError,
    ProviderAuthenticationOperationError,
    provider_account_snapshot_to_dict,
    provider_session_binding_to_dict,
)
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.sessions import InMemoryHarnessSessionStore
from gpt2giga_harness.ui.app import create_app


def test_broker_fails_closed_for_missing_cli_and_reviewed_pin_drift(tmp_path):
    runner = _Runner()
    broker = _broker(
        tmp_path,
        runner,
        capabilities={
            "codex-cli": _capability("codex-cli", status="missing", version=None),
            "claude-code": _capability(
                "claude-code",
                status="supported",
                version="2.1.211",
            ),
        },
        resolutions={
            "codex-cli": _resolution("codex-cli", executable=None),
            "claude-code": _resolution("claude-code", executable="/fake/claude"),
        },
    )

    codex = broker.status("codex-cli")
    claude = broker.status("claude-code")

    assert codex.status is ProviderAccountStatus.UNAVAILABLE
    assert codex.reason_code == "provider_cli_missing"
    assert claude.status is ProviderAccountStatus.UNAVAILABLE
    assert claude.reason_code == "provider_cli_version_drift"
    assert runner.calls == []
    with pytest.raises(
        ProviderAuthenticationOperationError,
        match="provider_cli_missing",
    ):
        broker.start("codex-cli")


def test_broker_projects_only_typed_status_from_isolated_homes(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-canary")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-canary")
    runner = _Runner(
        results={
            ("login", "status"): AuthenticationCommandResult(
                0,
                b"Logged in using ChatGPT\nsecret-token-canary",
            ),
            ("auth", "status"): AuthenticationCommandResult(
                0,
                (
                    b'{"loggedIn":false,"status":"expired",'
                    b'"email":"person@example.test",'
                    b'"authMethod":"oauth","expiresAt":"2026-07-27T10:00:00Z",'
                    b'"accessToken":"must-never-project"}'
                ),
            ),
        }
    )
    broker = _broker(tmp_path, runner)

    codex = provider_account_snapshot_to_dict(broker.status("codex-cli"))
    claude = provider_account_snapshot_to_dict(broker.status("claude-code"))
    gemini = provider_account_snapshot_to_dict(broker.status("gemini-cli"))

    assert codex["status"] == "ready"
    assert codex["authentication_method"] == "chatgpt"
    assert claude["status"] == "expired"
    assert claude["identity_label"] == "person@example.test"
    assert claude["expires_at"] == "2026-07-27T10:00:00Z"
    assert gemini["status"] == "unknown"
    assert gemini["reason_code"] == "machine_status_unavailable"
    assert gemini["actions"] == {
        "start": False,
        "status": False,
        "logout": False,
        "cancel": False,
    }
    serialized = str((codex, claude, gemini))
    assert "secret-token-canary" not in serialized
    assert "must-never-project" not in serialized
    assert all("OPENAI_API_KEY" not in call.environment for call in runner.calls)
    assert all("ANTHROPIC_API_KEY" not in call.environment for call in runner.calls)
    assert all(
        Path(call.environment["HOME"]).is_relative_to(
            tmp_path / "provider_authentication" / "homes"
        )
        for call in runner.calls
    )
    assert all(call.cwd == Path(call.environment["HOME"]) for call in runner.calls)


def test_broker_builds_stable_opaque_session_bindings(tmp_path):
    runner = _Runner(
        results={
            ("auth", "status"): AuthenticationCommandResult(
                0,
                (
                    b'{"loggedIn":true,"email":"person@example.test",'
                    b'"authMethod":"oauth"}'
                ),
            )
        }
    )
    broker = _broker(tmp_path, runner)

    first = provider_session_binding_to_dict(broker.session_binding("claude-code"))
    second = provider_session_binding_to_dict(broker.session_binding("claude-code"))
    restarted = provider_session_binding_to_dict(
        _broker(tmp_path, runner).session_binding("claude-code")
    )

    assert first["account_identity"] == second["account_identity"]
    assert restarted["account_identity"] == first["account_identity"]
    assert first["home_identity"] == second["home_identity"]
    assert first["source_identity"] == second["source_identity"]
    assert first["identity_evidence"] == "provider_reported"
    assert first["quota"] == {
        "ownership": "provider",
        "status": "provider_owned_unobserved",
    }
    assert first["monetary_cost"] == {
        "ownership": "api_route",
        "status": "api_route_separate",
    }
    serialized = str(first)
    assert "person@example.test" not in serialized
    assert str(tmp_path) not in serialized
    key_path = tmp_path / "provider_authentication" / "binding_identity.key"
    assert key_path.stat().st_mode & 0o777 == 0o600

    runner.results[("auth", "status")] = AuthenticationCommandResult(
        0,
        b'{"loggedIn":true,"email":"other@example.test","authMethod":"oauth"}',
    )
    changed = provider_session_binding_to_dict(broker.session_binding("claude-code"))
    assert changed["account_identity"] != first["account_identity"]
    assert changed["home_identity"] == first["home_identity"]
    assert changed["source_identity"] == first["source_identity"]


def test_broker_rejects_symlinked_binding_identity_key(tmp_path):
    runner = _Runner(
        results={
            ("login", "status"): AuthenticationCommandResult(
                0,
                b"Logged in using ChatGPT",
            )
        }
    )
    broker = _broker(tmp_path, runner)
    broker.root.mkdir(parents=True)
    outside = tmp_path / "outside-key"
    outside.write_bytes(b"x" * 32)
    try:
        (broker.root / "binding_identity.key").symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(
        ProviderAuthenticationOperationError,
        match="provider_binding_identity_key_invalid",
    ):
        broker.session_binding("codex-cli")

    assert outside.read_bytes() == b"x" * 32


def test_broker_rotates_opaque_account_identity_after_logout_and_login(tmp_path):
    runner = _Runner(
        results={
            ("login", "status"): AuthenticationCommandResult(
                0,
                b"Logged in using ChatGPT",
            ),
            ("logout",): AuthenticationCommandResult(0),
            ("login",): AuthenticationCommandResult(0),
        }
    )
    broker = _broker(tmp_path, runner)
    before = provider_session_binding_to_dict(broker.session_binding("codex-cli"))

    broker.logout("codex-cli")
    pending = broker.start("codex-cli")
    final = _wait_for_attempt(broker, "codex-cli", pending.attempt_id)
    after = provider_session_binding_to_dict(broker.session_binding("codex-cli"))

    assert final.status is ProviderAccountStatus.READY
    assert after["account_identity"] != before["account_identity"]
    assert after["home_identity"] == before["home_identity"]
    assert after["source_identity"] == before["source_identity"]


def test_broker_rejects_concurrent_login_and_cancels_exact_attempt(tmp_path):
    runner = _BlockingRunner()
    broker = _broker(tmp_path, runner)

    pending = broker.start("codex-cli")

    assert pending.status is ProviderAccountStatus.PENDING
    assert pending.actions["cancel"] is True
    with pytest.raises(ProviderAuthenticationConflictError, match="already pending"):
        broker.start("codex-cli")
    with pytest.raises(ProviderAuthenticationConflictError, match="still pending"):
        broker.refresh("codex-cli")
    with pytest.raises(ProviderAuthenticationConflictError, match="still pending"):
        broker.logout("codex-cli")

    cancelled = broker.cancel("codex-cli")
    runner.finished.wait(timeout=1)

    assert cancelled.status is ProviderAccountStatus.LOGGED_OUT
    assert cancelled.reason_code == "provider_login_cancelled"
    assert broker.status("codex-cli").reason_code == "provider_login_cancelled"


@pytest.mark.parametrize(
    ("result", "expected_status", "expected_reason"),
    [
        (
            AuthenticationCommandResult(1, timed_out=True),
            ProviderAccountStatus.UNKNOWN,
            "provider_login_timed_out",
        ),
        (
            AuthenticationCommandResult(1),
            ProviderAccountStatus.LOGGED_OUT,
            "provider_login_failed",
        ),
    ],
)
def test_abandoned_or_failed_login_has_deterministic_recovery(
    tmp_path,
    result,
    expected_status,
    expected_reason,
):
    broker = _broker(
        tmp_path,
        _Runner(results={("login",): result}),
    )

    pending = broker.start("codex-cli")
    final = _wait_for_attempt(broker, "codex-cli", pending.attempt_id)

    assert final.status is expected_status
    assert final.reason_code == expected_reason
    assert final.recovery


def test_logout_is_bounded_content_free_and_provider_owned(tmp_path):
    runner = _Runner(
        results={
            ("auth", "logout"): AuthenticationCommandResult(
                0,
                b"oauth-token-that-must-not-be-returned",
            )
        }
    )
    broker = _broker(tmp_path, runner)

    snapshot = provider_account_snapshot_to_dict(broker.logout("claude-code"))

    assert snapshot["status"] == "logged_out"
    assert snapshot["source"] == "claude auth logout"
    assert "oauth-token-that-must-not-be-returned" not in str(snapshot)
    assert runner.calls[-1].capture_output is False
    with pytest.raises(
        ProviderAuthenticationOperationError,
        match="logout_unavailable",
    ):
        broker.logout("gemini-cli")


def test_provider_account_api_is_typed_bounded_and_content_free(tmp_path):
    runner = _Runner(
        results={
            ("login", "status"): AuthenticationCommandResult(
                0,
                b"Logged in using ChatGPT\napi-secret-canary",
            ),
            ("auth", "status"): AuthenticationCommandResult(
                1,
                b'{"loggedIn":false}',
            ),
            ("auth", "logout"): AuthenticationCommandResult(0),
        }
    )
    broker = _broker(tmp_path / "data", runner)
    client = TestClient(
        create_app(
            HarnessConfig(data_dir=str(tmp_path / "data")),
            registry=create_default_registry(include_entry_points=False),
            store=InMemoryHarnessSessionStore(),
            native_login_broker=broker,
        )
    )

    response = client.get("/api/provider-accounts")

    assert response.status_code == 200
    body = response.json()
    assert body["credential_values_readable"] is False
    assert body["real_native_homes_accessed"] is False
    assert [item["provider_id"] for item in body["accounts"]] == [
        "codex-cli",
        "claude-code",
        "gemini-cli",
    ]
    assert [item["status"] for item in body["accounts"]] == [
        "ready",
        "logged_out",
        "unknown",
    ]
    assert "api-secret-canary" not in str(body)

    refreshed = client.post("/api/provider-accounts/claude-code/refresh")
    logged_out = client.post("/api/provider-accounts/claude-code/logout")
    unavailable = client.post("/api/provider-accounts/gemini-cli/login")
    unknown = client.post("/api/provider-accounts/not-a-provider/refresh")

    assert refreshed.status_code == 200
    assert refreshed.json()["account"]["status"] == "logged_out"
    assert logged_out.status_code == 200
    assert logged_out.json()["account"]["reason_code"] == "provider_logout_complete"
    assert unavailable.status_code == 409
    assert unavailable.json()["detail"]["code"] == "login_start_unavailable"
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "provider_authentication_unknown"


def test_session_api_exposes_account_drift_before_provider_execution(tmp_path):
    runner = _Runner(
        results={
            ("login", "status"): AuthenticationCommandResult(
                0,
                b"Logged in using ChatGPT",
            )
        }
    )
    broker = _broker(tmp_path / "data", runner)
    store = InMemoryHarnessSessionStore()
    client = TestClient(
        create_app(
            HarnessConfig(data_dir=str(tmp_path / "data")),
            registry=create_default_registry(include_entry_points=False),
            store=store,
            native_login_broker=broker,
        )
    )
    payload = {
        "harness_id": "codex-cli",
        "prompt": "dry run",
        "mode": "plan",
        "execution_transport": "one_shot",
        "dry_run": True,
    }

    first = client.post("/api/sessions/run", json=payload)
    assert first.status_code == 200
    session_id = first.json()["session"]["id"]
    assert first.json()["run"]["metadata"]["provider_account_binding"][
        "account_identity"
    ].startswith("account_")

    runner.results[("login", "status")] = AuthenticationCommandResult(1)
    blocked = client.post(f"/api/sessions/{session_id}/run", json=payload)

    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "provider_account_identity_unavailable"
    assert blocked.json()["detail"]["status"] == "logged_out"
    assert blocked.json()["detail"]["execution_authorized"] is False
    assert len(store.list_runs(session_id)) == 1
    assert len(store.list_messages(session_id)) == 2


class _Call:
    def __init__(self, argv, environment, cwd, capture_output):
        self.argv = tuple(argv)
        self.environment = dict(environment)
        self.cwd = cwd
        self.capture_output = capture_output


class _Runner:
    def __init__(self, *, results=None):
        self.results = dict(results or {})
        self.calls = []

    def run(
        self,
        argv,
        *,
        environment,
        cwd,
        timeout_seconds,
        cancel_event,
        capture_output,
    ):
        del timeout_seconds, cancel_event
        self.calls.append(_Call(argv, environment, cwd, capture_output))
        for suffix, result in self.results.items():
            if tuple(argv[-len(suffix) :]) == suffix:
                return result
        return AuthenticationCommandResult(1)


class _BlockingRunner(_Runner):
    def __init__(self):
        super().__init__()
        self.finished = threading.Event()

    def run(
        self,
        argv,
        *,
        environment,
        cwd,
        timeout_seconds,
        cancel_event,
        capture_output,
    ):
        self.calls.append(_Call(argv, environment, cwd, capture_output))
        cancel_event.wait(timeout_seconds)
        self.finished.set()
        return AuthenticationCommandResult(1, cancelled=cancel_event.is_set())


def _broker(
    tmp_path,
    runner,
    *,
    capabilities=None,
    resolutions=None,
):
    capabilities = {
        "codex-cli": _capability("codex-cli", version="0.144.3"),
        "claude-code": _capability("claude-code", version="2.1.212"),
        "gemini-cli": _capability("gemini-cli", version="0.46.0"),
        **(capabilities or {}),
    }
    resolutions = {
        "codex-cli": _resolution("codex-cli", executable="/fake/codex"),
        "claude-code": _resolution("claude-code", executable="/fake/claude"),
        "gemini-cli": _resolution("gemini-cli", executable="/fake/gemini"),
        **(resolutions or {}),
    }
    return NativeLoginBroker(
        tmp_path,
        runner=runner,
        resolution_provider=resolutions.__getitem__,
        capability_provider=capabilities.__getitem__,
        login_timeout_seconds=0.2,
        status_timeout_seconds=0.2,
    )


def _capability(
    harness_id,
    *,
    status="supported",
    version,
):
    return CliCapabilitySnapshot(
        harness_id=harness_id,
        status=status,
        version=version,
        parsed_version=version,
        command=(harness_id,),
        capabilities={},
        event_schema="test",
        history_schema="test",
        version_window_status="in_window" if version else "not_probed",
    )


def _resolution(harness_id, *, executable):
    return ExecutableResolution(
        harness_id=harness_id,
        command_name=harness_id,
        executable=executable,
        source="test",
        argv=(executable,) if executable else (),
    )


def _wait_for_attempt(broker, provider_id, attempt_id):
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        snapshot = broker.status(provider_id)
        if (
            snapshot.attempt_id == attempt_id
            and snapshot.status is not ProviderAccountStatus.PENDING
        ):
            return snapshot
        time.sleep(0.01)
    raise AssertionError("provider login attempt did not finish")
