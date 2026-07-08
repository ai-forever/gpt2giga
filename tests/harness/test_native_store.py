import json

from gpt2giga.harness.native import NativeSessionRef, NativeSessionStatus
from gpt2giga.harness.native.store import (
    FilesystemNativeSessionIndexStore,
    native_session_ref_to_dict,
)
from gpt2giga.harness.types import REDACTED


def test_native_session_index_store_upserts_and_filters(tmp_path):
    store = FilesystemNativeSessionIndexStore(tmp_path)
    codex = _ref(
        "native_codex_1",
        harness_id="codex-cli",
        status=NativeSessionStatus.MANAGED_NATIVE,
        workspace="/repo",
        updated_at="2026-07-09T10:00:00Z",
    )
    claude = _ref(
        "native_claude_1",
        harness_id="claude-code",
        status=NativeSessionStatus.EXTERNAL_NATIVE,
        workspace="/other",
        updated_at="2026-07-09T11:00:00Z",
    )

    stored_codex = store.upsert_ref(codex, project_id="proj_gpt2giga")
    stored_claude = store.upsert_ref(claude, project_id="proj_other")

    reopened = FilesystemNativeSessionIndexStore(tmp_path)

    assert reopened.get_ref(codex.id) == stored_codex
    assert reopened.list_refs() == (stored_claude, stored_codex)
    assert reopened.list_refs(harness_id="codex-cli") == (stored_codex,)
    assert reopened.list_refs(workspace="/other") == (stored_claude,)
    assert reopened.list_refs(project_id="proj_gpt2giga") == (stored_codex,)
    assert reopened.list_refs(status="external_native") == (stored_claude,)
    assert reopened.list_refs(limit=1) == (stored_claude,)


def test_native_session_index_store_replaces_by_stable_id(tmp_path):
    store = FilesystemNativeSessionIndexStore(tmp_path)
    original = _ref("native_codex_1", title="Old title")
    replacement = _ref(
        "native_codex_1",
        title="New title",
        message_count=5,
        updated_at="2026-07-09T12:00:00Z",
    )

    store.upsert_ref(original)
    stored = store.upsert_ref(replacement)

    assert store.list_refs() == (stored,)
    assert stored.title == "New title"
    assert stored.message_count == 5


def test_native_session_index_store_handles_corrupt_index(tmp_path):
    store = FilesystemNativeSessionIndexStore(tmp_path)
    index_path = tmp_path / "native" / "index.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text("{not json", encoding="utf-8")

    assert store.list_refs() == ()

    stored = store.upsert_ref(_ref("native_codex_1"))
    assert store.list_refs() == (stored,)
    assert json.loads(index_path.read_text(encoding="utf-8"))["sessions"][0]["id"] == (
        "native_codex_1"
    )


def test_native_session_index_store_redacts_secret_metadata(tmp_path, monkeypatch):
    secret = "sk-native-secret-123"
    monkeypatch.setenv("GPT2GIGA_API_KEY", secret)
    store = FilesystemNativeSessionIndexStore(tmp_path)
    ref = _ref(
        "native_codex_1",
        native_session_id=f"codex-{secret}",
        source=f"/tmp/{secret}/sessions",
        metadata={
            "api_key": secret,
            "headers": {"Authorization": f"Bearer {secret}"},
            "safe": "ok",
        },
    )

    stored = store.upsert_ref(ref)
    disk_text = (tmp_path / "native" / "index.json").read_text(encoding="utf-8")

    assert secret not in disk_text
    assert REDACTED in disk_text
    assert stored.metadata["api_key"] == REDACTED
    assert stored.metadata["safe"] == "ok"
    assert secret not in str(native_session_ref_to_dict(stored))


def test_native_session_index_store_drops_transcript_metadata(tmp_path):
    store = FilesystemNativeSessionIndexStore(tmp_path)
    ref = _ref(
        "native_codex_1",
        metadata={
            "messages": [{"role": "user", "content": "full transcript"}],
            "raw_transcript": "assistant response",
            "nested": {"tool_calls": [{"name": "shell"}], "safe": "ok"},
            "safe": "kept",
        },
    )

    stored = store.upsert_ref(ref)

    assert stored.metadata == {"nested": {"safe": "ok"}, "safe": "kept"}
    assert "full transcript" not in (tmp_path / "native" / "index.json").read_text(
        encoding="utf-8"
    )


def test_native_session_index_store_deletes_refs(tmp_path):
    store = FilesystemNativeSessionIndexStore(tmp_path)
    stored = store.upsert_ref(_ref("native_codex_1"))

    assert store.delete_ref(stored.id) is True
    assert store.delete_ref(stored.id) is False
    assert store.get_ref(stored.id) is None


def _ref(
    ref_id: str,
    *,
    harness_id: str = "codex-cli",
    native_session_id: str | None = "codex-session-1",
    title: str = "Fix harness",
    workspace: str | None = "/repo",
    source: str = "~/.codex/sessions",
    status: NativeSessionStatus = NativeSessionStatus.EXTERNAL_NATIVE,
    created_at: str | None = "2026-07-09T09:00:00Z",
    updated_at: str | None = "2026-07-09T09:00:00Z",
    message_count: int | None = 2,
    metadata: dict | None = None,
) -> NativeSessionRef:
    return NativeSessionRef(
        id=ref_id,
        harness_id=harness_id,
        native_session_id=native_session_id,
        title=title,
        workspace=workspace,
        source=source,
        status=status,
        created_at=created_at,
        updated_at=updated_at,
        message_count=message_count,
        can_preview=True,
        can_import=True,
        can_resume=status is NativeSessionStatus.MANAGED_NATIVE,
        resume_reason=None,
        metadata=metadata or {},
    )
