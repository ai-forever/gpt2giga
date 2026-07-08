from dataclasses import replace

from fastapi.testclient import TestClient

from gpt2giga.harness.config import HarnessConfig
from gpt2giga.harness.native.base import NativeCommandPlan
from gpt2giga.harness.native.models import (
    NativeSessionRef,
    NativeSessionStatus,
    NativeTranscriptMessage,
)
from gpt2giga.harness.native.registry import NativeHistoryConnectorRegistry
from gpt2giga.harness.registry import create_default_registry
from gpt2giga.harness.sessions import InMemoryHarnessSessionStore
from gpt2giga.harness.types import (
    HarnessContext,
    HarnessRequest,
    REDACTED,
)
from gpt2giga.harness.ui.app import create_app


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
) -> TestClient:
    app = create_app(
        HarnessConfig(
            default_model="ConfiguredModel",
            data_dir=str(tmp_path / "data"),
        ),
        registry=create_default_registry(include_entry_points=False),
        store=store or InMemoryHarnessSessionStore(),
        native_registry=native_registry,
    )
    return TestClient(app)


def _ref(
    *,
    workspace: str,
    status: NativeSessionStatus = NativeSessionStatus.EXTERNAL_NATIVE,
) -> NativeSessionRef:
    return NativeSessionRef(
        id="native_codex_fake_1",
        harness_id="codex-cli",
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
