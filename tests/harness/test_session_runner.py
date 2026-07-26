import json
import subprocess
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.native import HarnessInvocationMode
from gpt2giga_harness.preflight import PreflightBlockedError
from gpt2giga_harness.project import project_id_for_root, resolve_project
from gpt2giga_harness.project_memory import FilesystemProjectMemoryStore
from gpt2giga_harness.provider_account_sessions import ProviderAccountSessionError
from gpt2giga_harness.provider_authentication_broker import (
    ProviderAccountSnapshot,
    ProviderAccountStatus,
    ProviderSessionBinding,
)
from gpt2giga_harness.registry import HarnessRegistry
from gpt2giga_harness.session_runner import HarnessSessionRunner
from gpt2giga_harness.session_titles import title_diagnostics
from gpt2giga_harness.sessions import InMemoryHarnessSessionStore
from gpt2giga_harness.sessions.conversation import active_conversation_messages
from gpt2giga_harness.sessions.models import HarnessMessage
from gpt2giga_harness.sessions.store import new_id, utc_now
from gpt2giga_harness.types import (
    Availability,
    GigaChatBuiltinTool,
    HarnessCapability,
    HarnessContext,
    HarnessEvent,
    HeadlessContinuationStrategy,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
    emit_event,
)


def test_session_runner_create_and_run_persists_success():
    harness = _CaptureHarness()
    runner = _runner(harness)

    result = runner.create_and_run(
        {
            "harness_id": "capture",
            "prompt": "hello",
            "api_mode": "v2",
            "mode": "plan",
        }
    )
    bundle = result.bundle

    assert result.result.ok is True
    assert bundle.session.title == "hello"
    assert [message.role for message in bundle.messages] == ["user", "assistant"]
    assert bundle.messages[-1].content == "answer: hello"
    assert bundle.runs[0].status == "succeeded"
    assert bundle.raw_requests
    assert bundle.raw_responses
    assert {event.type for event in bundle.events} >= {
        "run_started",
        "raw_request",
        "raw_response",
        "message_completed",
        "run_finished",
    }
    assert result.run.metadata["preflight"]["ok"] is True
    assert result.run.metadata["preflight"]["context_budget"]["prompt_chars"] == 5
    assert bundle.raw_requests[0].payload["preflight"]["ok"] is True


def test_session_runner_edits_latest_user_turn_without_replaying_old_answer():
    harness = _CaptureHarness()
    runner = _runner(harness)
    session = runner.create_session(default_harness_id="capture")
    runner.run_in_session(session.id, {"harness_id": "capture", "prompt": "first"})
    runner.run_in_session(session.id, {"harness_id": "capture", "prompt": "old"})
    retained = runner.store.list_messages(session.id)
    edited = next(message for message in reversed(retained) if message.role == "user")

    result = runner.run_in_session(
        session.id,
        {
            "harness_id": "capture",
            "prompt": "replacement",
            "extra": {"edit_message_id": edited.id},
        },
    )

    active = active_conversation_messages(result.bundle.messages)
    assert [message.content for message in active] == [
        "first",
        "answer: first",
        "replacement",
        "answer: replacement",
    ]
    assert len(result.bundle.messages) == 6
    assert result.run.metadata["edited_from_message_id"] == edited.id
    assert harness.last_request is not None
    assert [message.content for message in harness.last_request.messages] == [
        "first",
        "answer: first",
        "replacement",
    ]


def test_session_runner_blocks_private_key_before_harness_invocation():
    harness = _CaptureHarness()
    runner = _runner(harness)
    prompt = "-----BEGIN PRIVATE KEY-----\nnot-real-secret\n-----END PRIVATE KEY-----"

    with pytest.raises(PreflightBlockedError) as exc_info:
        runner.create_and_run({"harness_id": "capture", "prompt": prompt})

    assert harness.last_request is None
    assert "private_key_material" in str(exc_info.value)


def test_session_runner_blocks_denied_required_permission_before_invocation():
    harness = _CaptureHarness()
    runner = _runner(harness)

    with pytest.raises(PreflightBlockedError, match="git.push"):
        runner.create_and_run(
            {
                "harness_id": "capture",
                "prompt": "publish",
                "permission_profile": "unattended",
                "extra": {"required_permission_actions": ["git.push"]},
            }
        )

    assert harness.last_request is None


def test_session_runner_persists_structured_thread_and_rejects_identity_change(
    tmp_path,
):
    harness = _StructuredThreadHarness()
    runner = _runner(harness, data_dir=tmp_path / "data")
    session = runner.create_session(
        workspace=str(tmp_path),
        default_harness_id="codex-cli",
        default_model="GigaChat-2-Max",
    )

    first = runner.run_in_session(
        session.id,
        {
            "harness_id": "codex-cli",
            "prompt": "first",
            "model": "GigaChat-2-Max",
            "stream": True,
        },
    )
    second = runner.run_in_session(
        session.id,
        {
            "harness_id": "codex-cli",
            "prompt": "second",
            "model": "GigaChat-2-Max",
            "stream": True,
        },
    )

    assert first.run.metadata["continuation"]["action"] == "start"
    assert second.run.metadata["continuation"]["action"] == "continue"
    assert [
        request.extra["continuation"]["action"] for request in harness.requests
    ] == [
        "start",
        "continue",
    ]
    assert harness.requests[1].extra["continuation"]["history_replayed"] is False
    assert harness.requests[1].extra["continuation"]["cli_version"] == "unknown"
    assert second.session.metadata["app_server_thread"]["thread_id"] == "thread-1"

    with pytest.raises(ValueError, match="fork explicitly"):
        runner.run_in_session(
            session.id,
            {
                "harness_id": "codex-cli",
                "prompt": "incompatible",
                "model": "DifferentModel",
                "stream": True,
            },
        )
    assert len(harness.requests) == 2
    assert len(runner.store.list_runs(session.id)) == 2
    assert len(runner.store.list_messages(session.id)) == 4


def test_session_runner_binds_account_and_rejects_drift_before_execution(tmp_path):
    harness = _StructuredThreadHarness()
    account_provider = _AccountProvider(_provider_binding(account="account_one"))
    runner = _runner(
        harness,
        data_dir=tmp_path / "data",
        provider_account_provider=account_provider,
    )
    session = runner.create_session(
        workspace=str(tmp_path),
        default_harness_id="codex-cli",
        default_model="GigaChat-2-Max",
    )

    first = runner.run_in_session(
        session.id,
        {
            "harness_id": "codex-cli",
            "prompt": "first",
            "model": "GigaChat-2-Max",
        },
    )

    binding = first.session.metadata["provider_account_binding"]
    assert binding["account_identity"] == "account_one"
    assert binding["home_identity"] == "home_one"
    assert binding["quota"]["ownership"] == "provider"
    assert binding["monetary_cost"]["ownership"] == "api_route"
    assert first.run.metadata["provider_account_binding"] == binding

    account_provider.binding = _provider_binding(account="account_two")
    with pytest.raises(ProviderAccountSessionError) as preflight_caught:
        runner.preflight(
            {
                "harness_id": "codex-cli",
                "prompt": "must not run",
                "model": "GigaChat-2-Max",
            },
            session_id=session.id,
        )
    assert preflight_caught.value.code == "provider_account_identity_drift"

    with pytest.raises(ProviderAccountSessionError) as caught:
        runner.run_in_session(
            session.id,
            {
                "harness_id": "codex-cli",
                "prompt": "must not run",
                "model": "GigaChat-2-Max",
            },
        )

    assert caught.value.code == "provider_account_identity_drift"
    assert caught.value.to_detail()["execution_authorized"] is False
    assert caught.value.to_detail()["allowed_actions"] == [
        "new_session",
        "evidence_only_handoff",
    ]
    assert len(harness.requests) == 1
    assert len(runner.store.list_runs(session.id)) == 1
    assert len(runner.store.list_messages(session.id)) == 2


def test_native_resume_requires_current_ready_account_identity(tmp_path):
    harness = _StructuredThreadHarness()
    account_provider = _AccountProvider(None, status=ProviderAccountStatus.LOGGED_OUT)
    runner = _runner(
        harness,
        data_dir=tmp_path / "data",
        provider_account_provider=account_provider,
    )
    session = runner.create_session(
        workspace=str(tmp_path),
        default_harness_id="codex-cli",
        default_model="GigaChat-2-Max",
    )

    with pytest.raises(ProviderAccountSessionError) as caught:
        runner.run_in_session(
            session.id,
            {
                "harness_id": "codex-cli",
                "prompt": "resume",
                "native_session_id": "provider-thread",
                "extra": {"native_session_operation": "resume"},
            },
        )

    assert caught.value.code == "provider_account_identity_unavailable"
    assert caught.value.status == "logged_out"
    assert harness.requests == []
    assert runner.store.list_runs(session.id) == ()
    assert runner.store.list_messages(session.id) == ()


@pytest.mark.parametrize("operation", ("resume", "fork"))
def test_codex_native_deep_link_seeds_exact_app_server_identity(tmp_path, operation):
    harness = _StructuredThreadHarness()
    runner = _runner(harness, data_dir=tmp_path / "data")
    session = runner.create_session(
        workspace=str(tmp_path),
        default_harness_id="codex-cli",
        default_model="GigaChat-2-Max",
    )

    runner.run_in_session(
        session.id,
        {
            "harness_id": "codex-cli",
            "prompt": "continue",
            "model": "GigaChat-2-Max",
            "native_session_id": "native-thread-fixture",
            "extra": {"native_session_operation": operation},
        },
    )

    continuation = harness.requests[0].extra["continuation"]
    assert continuation["action"] == operation
    if operation == "resume":
        assert continuation["link"]["thread_id"] == "native-thread-fixture"
        assert continuation["fork_thread_id"] is None
    else:
        assert continuation["link"] is None
        assert continuation["fork_thread_id"] == "native-thread-fixture"


def test_session_runner_edit_forks_codex_before_the_replaced_turn(tmp_path):
    harness = _StructuredThreadHarness()
    runner = _runner(harness, data_dir=tmp_path / "data")
    session = runner.create_session(
        workspace=str(tmp_path),
        default_harness_id="codex-cli",
        default_model="GigaChat-2-Max",
    )
    runner.run_in_session(
        session.id,
        {
            "harness_id": "codex-cli",
            "prompt": "first",
            "model": "GigaChat-2-Max",
            "stream": True,
        },
    )
    runner.run_in_session(
        session.id,
        {
            "harness_id": "codex-cli",
            "prompt": "old second",
            "model": "GigaChat-2-Max",
            "stream": True,
        },
    )
    edited = next(
        message
        for message in reversed(runner.store.list_messages(session.id))
        if message.role == "user"
    )

    runner.run_in_session(
        session.id,
        {
            "harness_id": "codex-cli",
            "prompt": "new second",
            "model": "GigaChat-2-Max",
            "stream": True,
            "extra": {"edit_message_id": edited.id},
        },
    )

    continuation = harness.requests[-1].extra["continuation"]
    assert continuation["action"] == "fork"
    assert continuation["fork_thread_id"] == "thread-1"
    assert continuation["fork_turn_id"] == "turn-1"


def test_session_runner_passes_and_records_selected_builtin_tools():
    harness = _CaptureHarness()
    runner = _runner(harness)

    result = runner.create_and_run(
        {
            "harness_id": "capture",
            "prompt": "search",
            "api_mode": "v2",
            "builtin_tools": ["web_search"],
        }
    )

    assert harness.last_request is not None
    assert harness.last_request.builtin_tools == (GigaChatBuiltinTool.WEB_SEARCH,)
    assert result.bundle.raw_requests[0].payload["builtin_tools"] == ["web_search"]
    assert result.run.metadata["builtin_tools"] == ["web_search"]


def test_session_runner_rejects_builtin_tools_for_v1():
    runner = _runner(_CaptureHarness())

    with pytest.raises(ValueError, match="/v2/chat/completions"):
        runner.create_and_run(
            {
                "harness_id": "capture",
                "prompt": "search",
                "api_mode": "v1",
                "builtin_tools": ["web_search"],
            }
        )


def test_session_runner_rejects_unknown_builtin_tool_before_harness_call():
    harness = _CaptureHarness()
    runner = _runner(harness)

    with pytest.raises(ValueError, match="Unsupported built-in tool: unknown"):
        runner.create_and_run(
            {
                "harness_id": "capture",
                "prompt": "search",
                "api_mode": "v2",
                "builtin_tools": ["unknown"],
            }
        )

    assert harness.last_request is None


def test_managed_mcp_snapshot_is_bound_to_provenance_and_reused_for_replay(tmp_path):
    workspace = tmp_path / "project"
    config_path = workspace / ".giga" / "harness.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[tools.issues]
enabled = true
kind = "mcp"
transport = "stdio"
command = "issue-mcp-v1"
trusted = true
harnesses = ["codex-cli"]
""",
        encoding="utf-8",
    )
    harness = _ManagedCaptureHarness()
    runner = _runner(harness, data_dir=tmp_path / "data")

    first = runner.create_and_run(
        {
            "harness_id": "codex-cli",
            "prompt": "inspect issues",
            "workspace": str(workspace),
            "extra": {"tool_ids": ["issues"]},
        }
    )
    first_ref = harness.requests[-1].extra["managed_mcp_snapshot"]
    replay_request = first.run.metadata["provenance"]["replay_request"]

    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("issue-mcp-v1", "issue-mcp-v2"),
        encoding="utf-8",
    )
    second = runner.run_in_session(first.session.id, replay_request)
    second_ref = harness.requests[-1].extra["managed_mcp_snapshot"]

    assert first_ref["snapshot_id"] == second_ref["snapshot_id"]
    assert first_ref["snapshot_hash"] == second_ref["snapshot_hash"]
    assert first.run.metadata["managed_mcp_snapshot"] == first_ref
    assert second.run.metadata["managed_mcp_snapshot"] == second_ref
    assert (
        second.run.metadata["provenance"]["execution"]["managed_mcp_snapshot"][
            "snapshot_id"
        ]
        == first_ref["snapshot_id"]
    )
    snapshot_path = (
        tmp_path
        / "data"
        / "tools"
        / "headless_mcp_snapshots"
        / f"{first_ref['snapshot_id']}.json"
    )
    snapshot_content = snapshot_path.read_text(encoding="utf-8")
    assert "issue-mcp-v1" in snapshot_content
    assert "issue-mcp-v2" not in snapshot_content


def test_session_runner_failed_harness_stores_error_message():
    runner = _runner(_FailingHarness())

    result = runner.create_and_run({"harness_id": "fail", "prompt": "hello"})

    assert result.run.status == "failed"
    assert result.bundle.messages[-1].role == "error"
    assert result.bundle.messages[-1].content == "boom"


def test_session_runner_deduplicates_live_usage_and_merges_partial_metadata():
    runner = _runner(_StreamingHarness())

    result = runner.create_and_run(
        {"harness_id": "streaming", "prompt": "hello", "stream": True}
    )

    usage_events = [event for event in result.bundle.events if event.type == "usage"]
    assert [event.payload for event in usage_events] == [
        {"input_tokens": 8, "source": "test"},
        {"output_tokens": 3, "source": "test"},
    ]
    expected_usage = {
        "input_tokens": 8,
        "output_tokens": 3,
        "total_tokens": 11,
        "source": "test",
    }
    assert result.run.metadata["usage"] == expected_usage
    assert result.bundle.messages[-1].metadata["usage"] == expected_usage
    assert result.bundle.messages[-1].metadata["reasoning"] == "Short summary"


def test_session_runner_updates_session_defaults_before_terminal_event():
    store = _TerminalOrderingStore()
    runner = _runner(_CaptureHarness(), store=store)
    session = runner.create_session(default_harness_id="echo")

    runner.run_in_session(
        session.id,
        {"harness_id": "capture", "prompt": "hello", "stream": True},
    )

    assert store.harness_at_run_finished == "capture"


def test_session_runner_passes_previous_messages_to_chat_harness():
    harness = _CaptureHarness()
    runner = _runner(harness)
    first = runner.create_and_run({"harness_id": "capture", "prompt": "first"})

    runner.run_in_session(first.session.id, {"prompt": "second"})

    assert harness.last_request is not None
    assert [
        (message.role, message.content) for message in harness.last_request.messages
    ] == [
        ("user", "first"),
        ("assistant", "answer: first"),
        ("user", "second"),
    ]


def test_queued_turn_waits_for_preceding_assistant_in_request_history():
    store = InMemoryHarnessSessionStore()
    harness = _CaptureHarness()
    runner = _runner(harness, store=store)
    session = runner.create_session(default_harness_id="capture")
    first_run = store.create_run(
        session_id=session.id,
        harness_id="capture",
        prompt="first",
        model=None,
        api_mode=session.default_api_mode,
        capability=HarnessCapability.CHAT_COMPLETIONS,
        mode="plan",
        workspace=session.workspace,
        status="running",
    )
    store.append_message(
        HarnessMessage(
            id=new_id("msg"),
            session_id=session.id,
            run_id=first_run.id,
            role="user",
            content="first",
            created_at=utc_now(),
        )
    )
    queued = runner.enqueue_in_session(
        session.id,
        {"harness_id": "capture", "prompt": "second"},
        run_id=new_id("run"),
    )
    store.append_message(
        HarnessMessage(
            id=new_id("msg"),
            session_id=session.id,
            run_id=first_run.id,
            role="assistant",
            content="answer: first",
            created_at=utc_now(),
        )
    )

    runner.run_in_session(
        session.id,
        {"harness_id": "capture", "prompt": "second"},
        existing_run_id=queued.run.id,
        user_message_id=queued.user_message.id,
    )

    assert harness.last_request is not None
    assert [
        (message.role, message.content) for message in harness.last_request.messages
    ] == [
        ("user", "first"),
        ("assistant", "answer: first"),
        ("user", "second"),
    ]


def test_durable_worker_reuses_submission_readiness_for_retry_without_second_probe(
    monkeypatch,
):
    harness = _CaptureHarness()
    runner = _runner(harness)
    session = runner.create_session(default_harness_id="capture")
    calls = 0

    def readiness(_options, *, durable):
        nonlocal calls
        calls += 1
        return {
            "ok": True,
            "blocked": False,
            "summary": {"ready": 1, "degraded": 0, "blocked": 0},
            "plan": {"delivery": "durable" if durable else "synchronous"},
            "findings": [],
        }

    monkeypatch.setattr(runner, "_execution_readiness", readiness)
    payload = {"harness_id": "capture", "prompt": "only one readiness probe"}
    queued = runner.enqueue_in_session(session.id, payload, run_id=new_id("run"))

    runner.run_in_session(
        session.id,
        payload,
        existing_run_id=queued.run.id,
        user_message_id=queued.user_message.id,
        durable=True,
    )
    retry_run_id = new_id("run")
    runner.run_in_session(
        session.id,
        payload,
        existing_run_id=retry_run_id,
        user_message_id=queued.user_message.id,
        excluded_history_run_ids=(queued.run.id,),
        durable=True,
    )

    assert calls == 1
    assert runner.store.get_run(retry_run_id).status.value == "succeeded"


def test_durable_runtime_identity_reaches_provider_driver_request():
    harness = _CaptureHarness()
    runner = _runner(harness)
    session = runner.create_session(default_harness_id="capture")

    runner.run_in_session(
        session.id,
        {"harness_id": "capture", "prompt": "durable identity"},
        runtime_metadata={
            "job_id": "job-1",
            "attempt_id": "attempt-1",
            "worker_id": "worker-1",
        },
        durable=True,
    )

    assert harness.last_request is not None
    assert harness.last_request.extra["runtime"] == {
        "job_id": "job-1",
        "attempt_id": "attempt-1",
        "worker_id": "worker-1",
    }


def test_first_ui_run_generates_title_with_lightning_model(monkeypatch):
    runner = _runner(_CaptureHarness())
    session = runner.create_session(default_harness_id="capture")
    captured = {}
    request_started = threading.Event()
    release_request = threading.Event()

    def request_json(method, url, *, payload, api_key, timeout):
        captured.update(
            method=method, url=url, payload=payload, api_key=api_key, timeout=timeout
        )
        request_started.set()
        assert release_request.wait(timeout=2)
        return {
            "choices": [{"message": {"content": "Починить стрим чата"}}],
            "usage": {
                "prompt_tokens": 14,
                "completion_tokens": 5,
                "total_tokens": 19,
            },
        }

    monkeypatch.setattr(
        "gpt2giga_harness.session_runner.proxy.request_json", request_json
    )

    started_at = time.monotonic()
    result = runner.run_in_session(
        session.id,
        {
            "harness_id": "capture",
            "prompt": "Почему чат не показывает поток ответа?",
            "extra": {
                "generate_session_title": True,
                "session_title_model": "GigaChat-3-Lightning",
            },
        },
    )

    assert request_started.wait(timeout=1)
    assert time.monotonic() - started_at < 1
    assert result.session.title == "Untitled session"
    release_request.set()
    deadline = time.monotonic() + 2
    while runner.store.get_session(session.id).title == "Untitled session":
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert runner.store.get_session(session.id).title == "Починить стрим чата"
    assert title_diagnostics(runner.store.get_session(session.id)) == {
        "schema_version": 1,
        "provenance": "fallback",
        "status": "succeeded",
        "source": "bounded_fallback",
        "bound_run_id": result.run.id,
        "model": "GigaChat-3-Lightning",
        "timeout_seconds": 15.0,
        "duration_ms": pytest.approx(0, abs=2000),
        "usage": {"input_tokens": 14, "output_tokens": 5, "total_tokens": 19},
        "cost": {"knowledge": "unknown"},
    }
    deadline = time.monotonic() + 2
    while not any(
        event.type == "session.updated"
        for event in runner.store.list_events(session.id)
    ):
        assert time.monotonic() < deadline
        time.sleep(0.01)
    title_event = next(
        event
        for event in runner.store.list_events(session.id)
        if event.type == "session.updated"
    )
    assert title_event.run_id == result.run.id
    assert title_event.payload["changed_fields"] == ["title"]
    assert "Почему чат не показывает поток ответа?" not in json.dumps(
        {"message": title_event.message, "payload": title_event.payload},
        ensure_ascii=False,
    )
    assert captured["payload"]["model"] == "GigaChat-3-Lightning"
    assert captured["url"].endswith("/v2/chat/completions")


def test_session_title_proxy_failure_publishes_deterministic_fallback(monkeypatch):
    runner = _runner(_CaptureHarness())
    session = runner.create_session(default_harness_id="capture")
    prompt = "Fallback title when proxy is offline"

    def request_json(*args, **kwargs):
        raise OSError("proxy offline")

    monkeypatch.setattr(
        "gpt2giga_harness.session_runner.proxy.request_json", request_json
    )

    result = runner.run_in_session(
        session.id,
        {
            "harness_id": "capture",
            "prompt": prompt,
            "extra": {"generate_session_title": True},
        },
    )

    deadline = time.monotonic() + 2
    while runner.store.get_session(session.id).title == "Untitled session":
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert runner.store.get_session(session.id).title == prompt
    diagnostics = title_diagnostics(runner.store.get_session(session.id))
    assert diagnostics["provenance"] == "fallback"
    assert diagnostics["status"] == "failed"
    assert diagnostics["failure_kind"] == "OSError"
    assert diagnostics["cost"] == {"knowledge": "unknown"}
    while not any(
        event.type == "session.updated" and event.run_id == result.run.id
        for event in runner.store.list_events(session.id)
    ):
        assert time.monotonic() < deadline
        time.sleep(0.01)


def test_delayed_session_title_never_overwrites_user_rename(monkeypatch):
    runner = _runner(_CaptureHarness())
    session = runner.create_session(default_harness_id="capture")
    request_started = threading.Event()
    release_request = threading.Event()

    def request_json(*args, **kwargs):
        request_started.set()
        assert release_request.wait(timeout=2)
        return {"choices": [{"message": {"content": "Generated title"}}]}

    monkeypatch.setattr(
        "gpt2giga_harness.session_runner.proxy.request_json", request_json
    )
    runner.run_in_session(
        session.id,
        {
            "harness_id": "capture",
            "prompt": "Generate this later",
            "extra": {"generate_session_title": True},
        },
    )

    assert request_started.wait(timeout=1)
    runner.store.update_session(session.id, title="User rename")
    release_request.set()
    _wait_for_session_title_thread(session.id)

    assert runner.store.get_session(session.id).title == "User rename"
    assert (
        title_diagnostics(runner.store.get_session(session.id))["provenance"]
        == "manual"
    )
    assert not any(
        event.type == "session.updated"
        for event in runner.store.list_events(session.id)
    )


def test_delayed_session_title_does_not_recreate_deleted_session(monkeypatch):
    runner = _runner(_CaptureHarness())
    session = runner.create_session(default_harness_id="capture")
    request_started = threading.Event()
    release_request = threading.Event()

    def request_json(*args, **kwargs):
        request_started.set()
        assert release_request.wait(timeout=2)
        return {"choices": [{"message": {"content": "Generated title"}}]}

    monkeypatch.setattr(
        "gpt2giga_harness.session_runner.proxy.request_json", request_json
    )
    runner.run_in_session(
        session.id,
        {
            "harness_id": "capture",
            "prompt": "Delete this session",
            "extra": {"generate_session_title": True},
        },
    )

    assert request_started.wait(timeout=1)
    runner.store.delete_session(session.id)
    release_request.set()
    _wait_for_session_title_thread(session.id)

    with pytest.raises(KeyError):
        runner.store.get_session(session.id)


def _wait_for_session_title_thread(session_id: str) -> None:
    name = f"harness-session-title-{session_id}"
    deadline = time.monotonic() + 2
    while True:
        thread = next(
            (item for item in threading.enumerate() if item.name == name),
            None,
        )
        if thread is None:
            return
        thread.join(timeout=0.05)
        assert time.monotonic() < deadline


def test_provider_native_title_wins_over_local_fallback():
    runner = _runner(_NativeTitleHarness())
    session = runner.create_session(default_harness_id="capture")

    result = runner.run_in_session(
        session.id,
        {"harness_id": "capture", "prompt": "Local fallback prompt"},
    )

    assert result.session.title == "Native provider title"
    diagnostics = title_diagnostics(result.session)
    assert diagnostics["provenance"] == "provider_native"
    assert diagnostics["source"] == "capture"
    assert diagnostics["source_id"] == "provider-session-1"
    assert [
        event.payload["title"]["provenance"]
        for event in result.bundle.events
        if event.type == "session.updated"
    ] == ["fallback", "provider_native"]


def test_session_runner_create_session_records_project_metadata(tmp_path):
    runner = _runner(_CaptureHarness(), data_dir=tmp_path / "data")

    session = runner.create_session(workspace=str(tmp_path))

    assert session.workspace == str(tmp_path)
    assert session.metadata["project_id"] == project_id_for_root(tmp_path)
    assert session.metadata["project_root"] == str(tmp_path)
    assert session.metadata["project_name"] == tmp_path.name


def test_session_runner_updates_legacy_session_project_metadata(tmp_path):
    store = InMemoryHarnessSessionStore()
    legacy = store.create_session(title="legacy", default_harness_id="capture")
    runner = _runner(_CaptureHarness(), store=store, data_dir=tmp_path / "data")

    result = runner.run_in_session(
        legacy.id,
        {
            "prompt": "hello",
            "workspace": str(tmp_path),
        },
    )

    assert result.session.metadata["project_id"] == project_id_for_root(tmp_path)
    assert result.session.metadata["project_root"] == str(tmp_path)


def test_session_runner_persists_invocation_mode_metadata():
    harness = _CaptureHarness()
    runner = _runner(harness)

    result = runner.create_and_run(
        {
            "harness_id": "capture",
            "prompt": "hello",
            "invocation_mode": "native",
        }
    )

    assert harness.last_request is not None
    assert harness.last_request.invocation_mode is HarnessInvocationMode.NATIVE
    assert result.run.invocation_mode is HarnessInvocationMode.NATIVE
    assert result.run.metadata["invocation_mode"] == "native"
    assert result.bundle.runs[0].invocation_mode is HarnessInvocationMode.NATIVE
    assert result.bundle.raw_requests[0].payload["invocation_mode"] == "native"


def test_session_runner_injects_enabled_project_memory(tmp_path):
    harness = _CaptureHarness()
    data_dir = tmp_path / "data"
    project = resolve_project(tmp_path, data_dir=data_dir)
    memory_store = FilesystemProjectMemoryStore()
    enabled = memory_store.add(
        project,
        text="Use Alembic migrations",
        tags=("decision",),
    )
    disabled = memory_store.add(
        project,
        text="Do not include this",
        enabled=False,
    )
    runner = _runner(harness, data_dir=data_dir, memory_store=memory_store)

    result = runner.create_and_run(
        {
            "harness_id": "capture",
            "prompt": "plan database change",
            "workspace": str(tmp_path),
        }
    )

    assert harness.last_request is not None
    assert "Project memory to honor for this run" in harness.last_request.prompt
    assert "Use Alembic migrations" in harness.last_request.prompt
    assert "Do not include this" not in harness.last_request.prompt
    memory = result.run.metadata["project_memory"]
    assert memory["count"] == 1
    assert memory["entries"][0]["id"] == enabled.id
    assert disabled.id not in str(result.bundle.raw_requests[0].payload)
    assert result.bundle.raw_requests[0].payload["original_prompt"] == (
        "plan database change"
    )
    provenance = result.run.metadata["provenance"]
    assert provenance["request"]["prompt"] == "plan database change"
    assert provenance["request"]["prompt_was_augmented"] is True
    assert provenance["request"]["project_memory"]["count"] == 1
    assert provenance["replay_request"]["prompt"] == "plan database change"
    assert provenance["replay_request"]["extra"]["isolated_history"] is True
    assert provenance["project"]["id"] == project.id


def test_session_runner_defaults_agent_edit_to_isolated_worktree(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    harness = _WorkspaceEditHarness()
    runner = _runner(harness, data_dir=tmp_path / "data")

    result = runner.create_and_run(
        {
            "harness_id": "edit-workspace",
            "prompt": "change it",
            "mode": "edit",
            "workspace": str(repo),
        }
    )

    assert harness.last_request is not None
    assert harness.last_request.workspace != str(repo)
    assert result.run.workspace == str(repo)
    workspace_execution = result.run.metadata["workspace_execution"]
    assert workspace_execution["requested_policy"] == "auto"
    assert workspace_execution["policy"] == "worktree"
    assert workspace_execution["source_git_root"] == str(repo)
    assert workspace_execution["effective_workspace"] == harness.last_request.workspace
    assert "app.txt" in workspace_execution["changed_files"]
    assert "diff --git a/app.txt b/app.txt" in workspace_execution["patch"]
    assert (repo / "app.txt").read_text(encoding="utf-8") == "base\n"


def test_session_runner_edit_fails_closed_for_non_git_workspace(tmp_path):
    workspace = tmp_path / "plain"
    workspace.mkdir()
    (workspace / "app.txt").write_text("base\n", encoding="utf-8")
    harness = _WorkspaceEditHarness()
    runner = _runner(harness, data_dir=tmp_path / "data")

    with pytest.raises(PreflightBlockedError, match="git-readiness"):
        runner.create_and_run(
            {
                "harness_id": "edit-workspace",
                "prompt": "change it",
                "mode": "edit",
                "workspace": str(workspace),
            }
        )

    assert harness.last_request is None
    assert (workspace / "app.txt").read_text(encoding="utf-8") == "base\n"


def _runner(
    harness: BaseHarness,
    *,
    store: InMemoryHarnessSessionStore | None = None,
    data_dir=None,
    memory_store: FilesystemProjectMemoryStore | None = None,
    provider_account_provider=None,
) -> HarnessSessionRunner:
    registry = HarnessRegistry()
    registry.register(harness)
    return HarnessSessionRunner(
        registry=registry,
        config=HarnessConfig(
            default_model="ConfiguredModel",
            data_dir=str(data_dir) if data_dir is not None else "~/.gpt2giga/harness",
        ),
        store=store or InMemoryHarnessSessionStore(),
        memory_store=memory_store,
        provider_account_provider=provider_account_provider,
    )


class _AccountProvider:
    def __init__(
        self,
        binding: ProviderSessionBinding | None,
        *,
        status: ProviderAccountStatus = ProviderAccountStatus.READY,
    ) -> None:
        self.binding = binding
        self.account_status = status

    def session_binding(self, provider_id: str) -> ProviderSessionBinding | None:
        assert provider_id == "codex-cli"
        return self.binding

    def status(self, provider_id: str) -> ProviderAccountSnapshot:
        assert provider_id == "codex-cli"
        return ProviderAccountSnapshot(
            provider_id=provider_id,
            display_name="Codex CLI",
            status=self.account_status,
            source="test",
            checked_at="2026-07-26T00:00:00Z",
            pinned_cli_version="0.144.3",
            detected_cli_version="0.144.3",
            version_status="reviewed_pin",
            identity_label=None,
            authentication_method="chatgpt",
            expires_at=None,
            reason_code="test",
            recovery=("test",),
            actions={},
        )


def _provider_binding(*, account: str) -> ProviderSessionBinding:
    return ProviderSessionBinding(
        provider_id="codex-cli",
        account_identity=account,
        home_identity="home_one",
        source_identity="source_one",
        identity_evidence="isolated_home_scoped",
        authentication_method="chatgpt",
        observed_at="2026-07-26T00:00:00Z",
    )


class _CaptureHarness(BaseHarness):
    def __init__(self) -> None:
        self.last_request: HarnessRequest | None = None

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="capture",
            title="Capture",
            kind="test",
            description="Capture request",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
            supported_builtin_tools=(GigaChatBuiltinTool.WEB_SEARCH,),
        )

    def availability(self) -> Availability:
        return Availability.available("test")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        self.last_request = request
        return HarnessResult(
            ok=True,
            text=f"answer: {request.prompt}",
            raw={"request_id": "ok"},
            command=("capture", request.prompt),
        )


class _NativeTitleHarness(_CaptureHarness):
    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        del context
        self.last_request = request
        return HarnessResult(
            ok=True,
            text=f"answer: {request.prompt}",
            raw={
                "provider_session_title": "Native provider title",
                "provider_session_id": "provider-session-1",
            },
            command=("capture", request.prompt),
        )


class _ManagedCaptureHarness(BaseHarness):
    def __init__(self) -> None:
        self.requests: list[HarnessRequest] = []

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="codex-cli",
            title="Managed capture",
            kind="agent-cli",
            description="Capture managed MCP snapshots",
            capabilities=(HarnessCapability.AGENT_CLI,),
        )

    def availability(self) -> Availability:
        return Availability.available("test")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        self.requests.append(request)
        return HarnessResult(
            ok=True,
            text="captured",
            raw={"managed_mcp_snapshot": request.extra["managed_mcp_snapshot"]},
            command=("capture-managed",),
        )


class _StructuredThreadHarness(BaseHarness):
    def __init__(self) -> None:
        self.requests: list[HarnessRequest] = []

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="codex-cli",
            title="Structured Codex",
            kind="agent-cli",
            description="Capture structured continuation plans",
            capabilities=(HarnessCapability.AGENT_CLI,),
            supports_streaming=True,
            headless_continuation=HeadlessContinuationStrategy.STRUCTURED_THREAD,
        )

    def capability_probe(self):
        return SimpleNamespace(capabilities={"app-server": True})

    def availability(self) -> Availability:
        return Availability.available("test")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        del context
        self.requests.append(request)
        continuation = request.extra["continuation"]
        link = continuation.get("link") or {}
        return HarnessResult(
            ok=True,
            text=f"answer: {request.prompt}",
            raw={
                "app_server_thread": {
                    "schema_version": 1,
                    "protocol": continuation["protocol"],
                    "runtime_id": "runtime-1",
                    "thread_id": link.get("thread_id") or "thread-1",
                    "latest_turn_id": f"turn-{len(self.requests)}",
                    "snapshot": continuation["snapshot"],
                    "snapshot_hash": continuation["snapshot"]["snapshot_hash"],
                    "runtime_status": "loaded",
                }
            },
            command=("codex", "app-server", "--stdio"),
        )


class _FailingHarness(BaseHarness):
    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="fail",
            title="Fail",
            kind="test",
            description="Fail request",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
        )

    def availability(self) -> Availability:
        return Availability.available("test")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        return HarnessResult(ok=False, text="", error="boom")


class _StreamingHarness(BaseHarness):
    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="streaming",
            title="Streaming",
            kind="test",
            description="Emit live events",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
            supports_streaming=True,
        )

    def availability(self) -> Availability:
        return Availability.available("test")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        events = (
            HarnessEvent(
                type="reasoning_delta",
                message="Assistant reasoning delta.",
                payload={"delta": "verbose thought", "kind": "text"},
            ),
            HarnessEvent(
                type="reasoning_delta",
                message="Assistant reasoning delta.",
                payload={"delta": "Short summary", "kind": "summary"},
            ),
            HarnessEvent(
                type="message_delta",
                message="Assistant message delta.",
                payload={"delta": "answer"},
            ),
            HarnessEvent(
                type="usage",
                message="Token usage updated.",
                payload={
                    "input_tokens": 8,
                    "source": "test",
                },
            ),
            HarnessEvent(
                type="usage",
                message="Token usage updated.",
                payload={
                    "output_tokens": 3,
                    "source": "test",
                },
            ),
        )
        for event in events:
            emit_event(request, event)
        return HarnessResult(ok=True, text="answer", events=events)


class _TerminalOrderingStore(InMemoryHarnessSessionStore):
    def __init__(self) -> None:
        super().__init__()
        self.harness_at_run_finished: str | None = None

    def append_event(self, event):
        if event.type == "run_finished":
            self.harness_at_run_finished = self.get_session(
                event.session_id
            ).default_harness_id
        return super().append_event(event)


class _WorkspaceEditHarness(BaseHarness):
    def __init__(self) -> None:
        self.last_request: HarnessRequest | None = None

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="edit-workspace",
            title="Edit Workspace",
            kind="agent-cli",
            description="Edit a workspace file",
            capabilities=(HarnessCapability.AGENT_CLI,),
            supports_workspace=True,
        )

    def availability(self) -> Availability:
        return Availability.available("test")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        self.last_request = request
        workspace = Path(request.workspace or "")
        (workspace / "app.txt").write_text("changed\n", encoding="utf-8")
        return HarnessResult(ok=True, text="edited")


def _git_repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test User")
    (path / "app.txt").write_text("base\n", encoding="utf-8")
    _git(path, "add", "app.txt")
    _git(path, "commit", "-m", "initial")
    return path


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ("git", "-C", str(cwd), *args),
        check=True,
        capture_output=True,
        text=True,
    )
