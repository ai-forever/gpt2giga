from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.native.base import NativeCommandPlan
from gpt2giga_harness.native.models import (
    NativeSessionRef,
    NativeSessionStatus,
    NativeTranscriptMessage,
)
from gpt2giga_harness.native.registry import NativeHistoryConnectorRegistry
from gpt2giga_harness.native.store import FilesystemNativeSessionIndexStore
from gpt2giga_harness.project import project_id_for_root
from gpt2giga_harness.registry import HarnessRegistry, create_default_registry
from gpt2giga_harness.sessions import InMemoryHarnessSessionStore
from gpt2giga_harness.types import (
    Availability,
    HarnessCapability,
    HarnessContext,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
    REDACTED,
)
from gpt2giga_harness.ui.app import create_app


def test_native_sessions_api_empty_cache_and_unknown_sync(tmp_path):
    client = _client(tmp_path, NativeHistoryConnectorRegistry())

    listed = client.get("/api/native/sessions")
    synced = client.post(
        "/api/native/sessions/sync",
        json={"harness_id": "missing", "include_external": True},
    )

    assert listed.status_code == 200
    assert listed.json() == {"sessions": []}
    assert synced.status_code == 200
    assert synced.json()["sessions"] == []
    assert synced.json()["errors"][0]["code"] == "unknown_connector"


def test_native_sessions_sync_populates_cached_index(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    ref = _ref(workspace=str(workspace))
    connector = FakeConnector("codex-cli", refs=(ref,))
    registry = NativeHistoryConnectorRegistry()
    registry.register(connector)
    client = _client(tmp_path, registry)

    synced = client.post(
        "/api/native/sessions/sync",
        json={
            "harness_id": "codex-cli",
            "workspace": str(workspace),
            "include_external": True,
        },
    )
    default_list = client.get(
        "/api/native/sessions",
        params={"harness_id": "codex-cli", "workspace": str(workspace)},
    )
    external_list = client.get(
        "/api/native/sessions",
        params={
            "harness_id": "codex-cli",
            "workspace": str(workspace),
            "include_external": True,
        },
    )

    assert synced.status_code == 200
    assert synced.json()["errors"] == []
    assert [item["id"] for item in synced.json()["sessions"]] == [ref.id]
    assert default_list.status_code == 200
    assert default_list.json()["sessions"] == []
    assert external_list.status_code == 200
    assert [item["id"] for item in external_list.json()["sessions"]] == [ref.id]
    assert connector.discovery_calls == (
        {"workspace": str(workspace), "include_external": True},
    )


def test_native_sessions_api_filters_by_project_and_can_show_all(tmp_path):
    workspace_a = tmp_path / "repo-a"
    workspace_b = tmp_path / "repo-b"
    workspace_a.mkdir()
    workspace_b.mkdir()
    index_store = FilesystemNativeSessionIndexStore(tmp_path / "data")
    ref_a = _ref(
        workspace=str(workspace_a),
        status=NativeSessionStatus.MANAGED_NATIVE,
    )
    ref_b = replace(
        _ref(
            workspace=str(workspace_b),
            status=NativeSessionStatus.MANAGED_NATIVE,
        ),
        id="native_codex_fake_2",
        native_session_id="codex-session-2",
    )
    project_a = project_id_for_root(workspace_a)
    project_b = project_id_for_root(workspace_b)
    index_store.upsert_ref(ref_a, project_id=project_a)
    index_store.upsert_ref(ref_b, project_id=project_b)
    client = _client(
        tmp_path,
        NativeHistoryConnectorRegistry(),
        native_index_store=index_store,
    )

    scoped = client.get("/api/native/sessions", params={"project_id": project_a})
    all_workspaces = client.get("/api/native/sessions")

    assert [item["id"] for item in scoped.json()["sessions"]] == [ref_a.id]
    assert {item["id"] for item in all_workspaces.json()["sessions"]} == {
        ref_a.id,
        ref_b.id,
    }


def test_native_session_preview_redacts_messages(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    ref = _ref(workspace=str(workspace))
    connector = FakeConnector(
        "codex-cli",
        refs=(ref,),
        preview_messages=(
            NativeTranscriptMessage(
                role="user",
                content="inspect sk-native-secret-123",
            ),
        ),
    )
    registry = NativeHistoryConnectorRegistry()
    registry.register(connector)
    client = _client(tmp_path, registry)
    client.post(
        "/api/native/sessions/sync",
        json={
            "harness_id": "codex-cli",
            "workspace": str(workspace),
            "include_external": True,
        },
    )

    response = client.get(f"/api/native/sessions/{ref.id}/preview")

    assert response.status_code == 200
    body = response.json()
    assert body["ref"]["id"] == ref.id
    assert "sk-native-secret" not in str(body)
    assert REDACTED in str(body)
    assert body["messages"][0]["role"] == "user"


def test_native_session_import_creates_normalized_session_and_link(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    ref = _ref(workspace=str(workspace), status=NativeSessionStatus.MANAGED_NATIVE)
    connector = FakeConnector(
        "codex-cli",
        refs=(ref,),
        import_messages=(
            NativeTranscriptMessage(
                role="user",
                content="please inspect sk-native-secret-456",
                created_at="2026-07-09T10:00:00Z",
            ),
            NativeTranscriptMessage(
                role="assistant",
                content="done",
                created_at="2026-07-09T10:01:00Z",
            ),
        ),
    )
    registry = NativeHistoryConnectorRegistry()
    registry.register(connector)
    store = InMemoryHarnessSessionStore()
    client = _client(tmp_path, registry, store=store)
    client.post(
        "/api/native/sessions/sync",
        json={"harness_id": "codex-cli", "workspace": str(workspace)},
    )

    imported = client.post(f"/api/native/sessions/{ref.id}/import")

    assert imported.status_code == 200
    body = imported.json()
    session_id = body["session"]["id"]
    assert body["session"]["default_harness_id"] == "codex-cli"
    assert body["session"]["metadata"]["source"] == "native_import"
    assert [message["role"] for message in body["messages"]] == [
        "user",
        "assistant",
    ]
    assert "sk-native-secret" not in str(body)
    assert REDACTED in str(body)
    assert body["native_link"]["status"] == "imported"
    assert body["native_link"]["native_ref_id"] == ref.id

    bundle = client.get(f"/api/sessions/{session_id}").json()
    assert len(bundle["messages"]) == 2
    assert bundle["native_links"][0]["status"] == "imported"


@pytest.mark.parametrize("harness_id", ("codex-cli", "claude-code", "gemini-cli"))
def test_native_session_import_supports_external_harness_ids(tmp_path, harness_id):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    ref = _ref(
        workspace=str(workspace),
        harness_id=harness_id,
        status=NativeSessionStatus.MANAGED_NATIVE,
    )
    connector = FakeConnector(
        harness_id,
        refs=(ref,),
        import_messages=(
            NativeTranscriptMessage(role="user", content="native user"),
            NativeTranscriptMessage(role="assistant", content="native assistant"),
        ),
    )
    registry = NativeHistoryConnectorRegistry()
    registry.register(connector)
    client = _client(tmp_path, registry)
    client.post(
        "/api/native/sessions/sync",
        json={"harness_id": harness_id, "workspace": str(workspace)},
    )

    imported = client.post(f"/api/native/sessions/{ref.id}/import")

    assert imported.status_code == 200
    assert imported.json()["session"]["default_harness_id"] == harness_id
    assert [message["role"] for message in imported.json()["messages"]] == [
        "user",
        "assistant",
    ]


def test_native_session_import_skips_unknown_roles_with_warning(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    ref = _ref(workspace=str(workspace), status=NativeSessionStatus.MANAGED_NATIVE)
    connector = FakeConnector(
        "codex-cli",
        refs=(ref,),
        import_messages=(
            NativeTranscriptMessage(role="user", content="known"),
            NativeTranscriptMessage(role="mystery", content="tool internals"),
            NativeTranscriptMessage(role="model", content="model answer"),
        ),
    )
    registry = NativeHistoryConnectorRegistry()
    registry.register(connector)
    client = _client(tmp_path, registry)
    client.post(
        "/api/native/sessions/sync",
        json={"harness_id": "codex-cli", "workspace": str(workspace)},
    )

    imported = client.post(f"/api/native/sessions/{ref.id}/import")
    session_id = imported.json()["session"]["id"]
    bundle = client.get(f"/api/sessions/{session_id}").json()

    assert imported.status_code == 200
    assert [message["role"] for message in imported.json()["messages"]] == [
        "user",
        "assistant",
    ]
    assert "tool internals" not in str(imported.json()["messages"])
    assert bundle["events"][0]["type"] == "native_import_warning"
    assert bundle["events"][0]["payload"]["role"] == "mystery"
    assert bundle["native_links"][0]["metadata"]["skipped_item_count"] == 1


def test_imported_native_session_can_continue_with_another_harness(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    ref = _ref(workspace=str(workspace), status=NativeSessionStatus.MANAGED_NATIVE)
    connector = FakeConnector(
        "codex-cli",
        refs=(ref,),
        import_messages=(
            NativeTranscriptMessage(role="user", content="native question"),
            NativeTranscriptMessage(role="assistant", content="native answer"),
        ),
    )
    native_registry = NativeHistoryConnectorRegistry()
    native_registry.register(connector)
    capture = CaptureHarness()
    harness_registry = HarnessRegistry()
    harness_registry.register(capture)
    client = _client(tmp_path, native_registry, registry=harness_registry)
    client.post(
        "/api/native/sessions/sync",
        json={"harness_id": "codex-cli", "workspace": str(workspace)},
    )
    imported = client.post(f"/api/native/sessions/{ref.id}/import")
    session_id = imported.json()["session"]["id"]

    continued = client.post(
        f"/api/sessions/{session_id}/run",
        json={"harness_id": "capture", "prompt": "continue here"},
    )

    assert continued.status_code == 200
    assert capture.last_request is not None
    assert [
        (message.role, message.content) for message in capture.last_request.messages
    ] == [
        ("user", "native question"),
        ("assistant", "native answer"),
        ("user", "continue here"),
    ]


def test_native_session_link_adds_link_to_existing_session(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    ref = _ref(workspace=str(workspace), status=NativeSessionStatus.MANAGED_NATIVE)
    connector = FakeConnector("codex-cli", refs=(ref,))
    registry = NativeHistoryConnectorRegistry()
    registry.register(connector)
    store = InMemoryHarnessSessionStore()
    session = store.create_session(title="Existing chat", default_harness_id="echo")
    client = _client(tmp_path, registry, store=store)
    client.post(
        "/api/native/sessions/sync",
        json={"harness_id": "codex-cli", "workspace": str(workspace)},
    )

    linked = client.post(
        f"/api/sessions/{session.id}/native/link",
        json={"native_ref_id": ref.id},
    )

    assert linked.status_code == 200
    assert linked.json()["native_link"]["status"] == "linked"
    assert linked.json()["native_link"]["native_ref_id"] == ref.id
    bundle = client.get(f"/api/sessions/{session.id}").json()
    assert bundle["native_links"][0]["status"] == "linked"


class FakeConnector:
    def __init__(
        self,
        harness_id: str,
        *,
        refs: tuple[NativeSessionRef, ...] = (),
        preview_messages: tuple[NativeTranscriptMessage, ...] = (),
        import_messages: tuple[NativeTranscriptMessage, ...] = (),
    ) -> None:
        self.harness_id = harness_id
        self.refs = refs
        self.preview_messages = preview_messages
        self.import_messages = import_messages or preview_messages
        self.discovery_calls: tuple[dict, ...] = ()

    def discover(
        self,
        *,
        workspace: str | None,
        include_external: bool,
    ) -> tuple[NativeSessionRef, ...]:
        self.discovery_calls = (
            *self.discovery_calls,
            {"workspace": workspace, "include_external": include_external},
        )
        refs = tuple(replace(ref, workspace=workspace) for ref in self.refs)
        if include_external:
            return refs
        return tuple(
            ref for ref in refs if ref.status is not NativeSessionStatus.EXTERNAL_NATIVE
        )

    def preview(
        self,
        ref: NativeSessionRef,
        *,
        max_messages: int = 20,
    ) -> tuple[NativeTranscriptMessage, ...]:
        return self.preview_messages[:max_messages]

    def import_ref(
        self,
        ref: NativeSessionRef,
    ) -> tuple[NativeTranscriptMessage, ...]:
        return self.import_messages

    def build_start_command(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> NativeCommandPlan:
        return NativeCommandPlan(command=(self.harness_id, request.prompt))

    def build_resume_command(
        self,
        ref: NativeSessionRef,
        context: HarnessContext,
    ) -> NativeCommandPlan:
        return NativeCommandPlan(
            command=(self.harness_id, "resume", ref.native_session_id or ref.id),
        )


def _client(
    tmp_path,
    native_registry: NativeHistoryConnectorRegistry,
    *,
    store=None,
    registry=None,
    native_index_store=None,
) -> TestClient:
    app = create_app(
        HarnessConfig(
            default_model="ConfiguredModel",
            data_dir=str(tmp_path / "data"),
        ),
        registry=registry or create_default_registry(include_entry_points=False),
        store=store or InMemoryHarnessSessionStore(),
        native_registry=native_registry,
        native_index_store=native_index_store,
    )
    return TestClient(app)


def _ref(
    *,
    workspace: str,
    harness_id: str = "codex-cli",
    status: NativeSessionStatus = NativeSessionStatus.EXTERNAL_NATIVE,
) -> NativeSessionRef:
    return NativeSessionRef(
        id=f"native_{harness_id.replace('-', '_')}_fake_1",
        harness_id=harness_id,
        native_session_id="codex-session-1",
        title="Fake native session",
        workspace=workspace,
        source="fake",
        status=status,
        created_at="2026-07-09T09:00:00Z",
        updated_at="2026-07-09T10:00:00Z",
        message_count=2,
        can_preview=True,
        can_import=True,
        can_resume=status is NativeSessionStatus.MANAGED_NATIVE,
        metadata={
            "project_id": "proj_fake",
            "model": "GigaChat-2-Max",
        },
    )


class CaptureHarness(BaseHarness):
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
        )

    def availability(self) -> Availability:
        return Availability.available("test")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        self.last_request = request
        return HarnessResult(ok=True, text="continued")
