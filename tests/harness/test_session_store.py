import json

from gpt2giga_harness.sessions import FilesystemHarnessSessionStore
from gpt2giga_harness.native import HarnessInvocationMode, NativeSessionStatus
from gpt2giga_harness.sessions.models import (
    HarnessMessage,
    HarnessNativeLink,
    HarnessStoredEvent,
    bundle_to_dict,
)
from gpt2giga_harness.sessions.store import new_id, title_from_prompt, utc_now
from gpt2giga_harness.types import GigaChatApiMode, HarnessCapability, REDACTED


def test_filesystem_store_persists_session_messages_runs_and_events(tmp_path):
    store = FilesystemHarnessSessionStore(tmp_path)

    session = store.create_session(
        title="Fix tests",
        workspace="/repo",
        default_harness_id="echo",
        default_model="GigaChat-2-Max",
        default_api_mode=GigaChatApiMode.V2,
    )
    message = store.append_message(
        HarnessMessage(
            id=new_id("msg"),
            session_id=session.id,
            run_id=None,
            role="user",
            content="hello",
            created_at=utc_now(),
        )
    )
    run = store.create_run(
        session_id=session.id,
        harness_id="echo",
        status="running",
        prompt="hello",
        model="GigaChat-2-Max",
        api_mode=GigaChatApiMode.V2,
        capability=HarnessCapability.CHAT_COMPLETIONS,
        mode="plan",
        workspace="/repo",
    )
    event = store.append_event(
        HarnessStoredEvent(
            id=new_id("evt"),
            session_id=session.id,
            run_id=run.id,
            type="run_started",
            message="started",
            payload={"ok": True},
            created_at=utc_now(),
        )
    )

    reopened = FilesystemHarnessSessionStore(tmp_path)
    bundle = reopened.get_session_bundle(session.id)

    assert bundle.session.title == "Fix tests"
    assert bundle.messages == (message,)
    assert bundle.runs[0].id == run.id
    assert bundle.events == (event,)
    assert bundle.native_links == ()


def test_title_from_prompt_creates_compact_plain_session_name():
    assert title_from_prompt("# Streaming QA - **bold item** and a long suffix") == (
        "Streaming QA - **bold item** and a..."
    )
    assert title_from_prompt("  Какой курс доллара?  ") == "Какой курс доллара?"


def test_filesystem_store_persists_invocation_mode_on_runs(tmp_path):
    store = FilesystemHarnessSessionStore(tmp_path)
    session = store.create_session(title="native")

    run = store.create_run(
        session_id=session.id,
        harness_id="codex-cli",
        prompt="inspect",
        model=None,
        api_mode=GigaChatApiMode.V2,
        capability=HarnessCapability.AGENT_CLI,
        mode="plan",
        invocation_mode="native",
        workspace="/repo",
    )
    default_run = store.create_run(
        session_id=session.id,
        harness_id="echo",
        prompt="hello",
        model=None,
        api_mode=GigaChatApiMode.V2,
        capability=HarnessCapability.CHAT_COMPLETIONS,
        mode="plan",
        workspace=None,
    )

    reopened = FilesystemHarnessSessionStore(tmp_path)
    runs = reopened.list_runs(session.id)

    assert run.invocation_mode is HarnessInvocationMode.NATIVE
    assert default_run.invocation_mode is HarnessInvocationMode.HEADLESS
    assert runs[0].invocation_mode is HarnessInvocationMode.NATIVE
    assert runs[1].invocation_mode is HarnessInvocationMode.HEADLESS
    assert (
        bundle_to_dict(reopened.get_session_bundle(session.id))["runs"][0][
            "invocation_mode"
        ]
        == "native"
    )


def test_filesystem_store_persists_native_links_in_bundle(tmp_path, monkeypatch):
    secret = "sk-native-secret-123"
    monkeypatch.setenv("GPT2GIGA_API_KEY", secret)
    store = FilesystemHarnessSessionStore(tmp_path)
    session = store.create_session(title="linked")
    link = HarnessNativeLink(
        id=new_id("nlink"),
        session_id="wrong-session",
        harness_id="codex-cli",
        status=NativeSessionStatus.LINKED,
        created_at=utc_now(),
        updated_at=utc_now(),
        native_session_id=f"codex-{secret}",
        native_ref_id="native_codex_1",
        source=f"/tmp/{secret}/sessions",
        workspace="/repo",
        metadata={"api_key": secret, "safe": "ok"},
    )

    stored = store.append_native_link(session.id, link)
    reopened = FilesystemHarnessSessionStore(tmp_path)
    bundle = reopened.get_session_bundle(session.id)

    assert stored.session_id == session.id
    assert secret not in str(bundle_to_dict(bundle))
    assert bundle.native_links == (stored,)
    assert reopened.list_native_links(session.id) == (stored,)
    assert reopened.get_native_link(session.id, "codex-cli") == stored
    assert bundle_to_dict(bundle)["native_links"][0]["status"] == "linked"
    assert (next(tmp_path.rglob("native_links.jsonl"))).is_file()


def test_filesystem_store_lists_newest_first_and_archive_filter(tmp_path):
    store = FilesystemHarnessSessionStore(tmp_path)

    older = store.create_session(title="older")
    newer = store.create_session(title="newer")
    store.archive_session(newer.id)

    assert [session.id for session in store.list_sessions()] == [older.id]
    assert [session.id for session in store.list_sessions(include_archived=True)] == [
        newer.id,
        older.id,
    ]


def test_filesystem_store_filters_by_project_id_without_hiding_legacy(tmp_path):
    store = FilesystemHarnessSessionStore(tmp_path)
    first = store.create_session(
        title="first",
        metadata={"project_id": "proj_first"},
    )
    second = store.create_session(
        title="second",
        metadata={"project_id": "proj_second"},
    )
    legacy = store.create_session(title="legacy")

    filtered = store.list_sessions(project_id="proj_first", include_archived=True)
    unfiltered = store.list_sessions(include_archived=True)

    assert [session.id for session in filtered] == [first.id]
    assert {session.id for session in unfiltered} == {first.id, second.id, legacy.id}


def test_filesystem_store_rebuilds_missing_index(tmp_path):
    store = FilesystemHarnessSessionStore(tmp_path)
    session = store.create_session(title="recover me")
    (tmp_path / "sessions" / "index.json").unlink()

    reopened = FilesystemHarnessSessionStore(tmp_path)

    assert reopened.get_session(session.id).title == "recover me"


def test_filesystem_store_ignores_corrupted_manifest_in_list(tmp_path):
    store = FilesystemHarnessSessionStore(tmp_path)
    good = store.create_session(title="good")
    bad_dir = tmp_path / "sessions" / "2026" / "07" / "bad"
    bad_dir.mkdir(parents=True)
    (bad_dir / "manifest.json").write_text("{bad json", encoding="utf-8")
    (tmp_path / "sessions" / "index.json").unlink()

    assert [session.id for session in store.list_sessions()] == [good.id]


def test_filesystem_store_redacts_secrets_on_disk(tmp_path, monkeypatch):
    secret = "sk-test-super-secret-123"
    monkeypatch.setenv("GPT2GIGA_API_KEY", secret)
    store = FilesystemHarnessSessionStore(tmp_path)
    session = store.create_session(title=f"secret {secret}")
    run = store.create_run(
        session_id=session.id,
        harness_id="echo",
        prompt=f"prompt {secret}",
        model=None,
        api_mode=GigaChatApiMode.V2,
        capability=HarnessCapability.CHAT_COMPLETIONS,
        mode="plan",
        workspace=None,
    )
    store.append_raw_request(
        session_id=session.id,
        run_id=run.id,
        payload={"headers": {"Authorization": f"Bearer {secret}"}},
    )
    store.append_raw_response(
        session_id=session.id,
        run_id=run.id,
        payload={"access_token": secret, "text": f"value {secret}"},
    )

    disk_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in tmp_path.rglob("*")
        if path.is_file()
    )

    assert secret not in disk_text
    assert REDACTED in disk_text
    assert json.loads(
        next(tmp_path.rglob("raw_responses.jsonl")).read_text(encoding="utf-8")
    )


def test_filesystem_store_redacts_and_bounds_tool_output_events(tmp_path):
    store = FilesystemHarnessSessionStore(tmp_path)
    session = store.create_session(title="tool output")
    run = store.create_run(
        session_id=session.id,
        harness_id="codex-cli",
        prompt="inspect",
        model=None,
        api_mode=GigaChatApiMode.V2,
        capability=HarnessCapability.AGENT_CLI,
        mode="plan",
        workspace=None,
    )

    event = store.append_event(
        HarnessStoredEvent(
            id=new_id("evt"),
            session_id=session.id,
            run_id=run.id,
            type="tool_call_finished",
            message="Tool call finished.",
            payload={
                "tool_call_id": "tool-1",
                "result": "FOO_SECRET=plain-secret\n" + ("x" * 20_000),
            },
            created_at=utc_now(),
        )
    )

    assert "plain-secret" not in str(event.payload)
    assert "<redacted>" in str(event.payload)
    assert len(event.payload["result"]) <= 16_000
    assert event.payload["result"].endswith("… <truncated>")
    assert "plain-secret" not in next(tmp_path.rglob("events.jsonl")).read_text(
        encoding="utf-8"
    )
