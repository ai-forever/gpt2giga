import os
import sys
import time

from fastapi.testclient import TestClient

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.native.base import NativeCommandPlan
from gpt2giga_harness.native.models import (
    NativeSessionRef,
    NativeSessionStatus,
)
from gpt2giga_harness.native.process import NativeProcessManager
from gpt2giga_harness.native.registry import NativeHistoryConnectorRegistry
from gpt2giga_harness.native.store import FilesystemNativeSessionIndexStore
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.sessions import (
    FilesystemHarnessSessionStore,
    InMemoryHarnessSessionStore,
)
from gpt2giga_harness.types import HarnessContext, HarnessRequest, REDACTED
from gpt2giga_harness.ui.app import create_app


def test_native_process_api_start_poll_input_and_stop(tmp_path):
    script = _write_echo_cli(tmp_path)
    client, store = _client(tmp_path, FakeProcessConnector(start_script=script))
    session = store.create_session(
        title="Native API",
        workspace=str(tmp_path),
        default_harness_id="fake-cli",
    )

    started = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "fake-cli",
            "action": "start",
            "prompt": "boot",
            "workspace": str(tmp_path),
        },
    )

    assert started.status_code == 200, started.text
    process_id = started.json()["process"]["id"]
    assert started.json()["process"]["status"] == "running"
    assert started.json()["run"]["invocation_mode"] == "native"

    cursor, output = _wait_for_output(client, process_id, 0, "ready")
    assert "ready" in output

    sent = client.post(
        f"/api/native/processes/{process_id}/input",
        json={"data": "hello\n"},
    )
    assert sent.status_code == 200, sent.text
    cursor, output = _wait_for_output(client, process_id, cursor, "echo:hello")
    assert "echo:hello" in output

    stopped = client.delete(f"/api/native/processes/{process_id}")

    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["process"]["status"] in {"stopped", "exited"}
    event_types = {event.type for event in store.list_events(session.id)}
    assert event_types >= {
        "terminal_start",
        "terminal_input",
        "terminal_output",
        "terminal_stop",
    }


def test_native_process_api_start_creates_managed_native_link(tmp_path):
    script = _write_once_cli(tmp_path)
    client, store = _client(
        tmp_path,
        FakeProcessConnector(
            start_script=script,
            native_session_id="managed-native-1",
        ),
    )
    session = store.create_session(
        title="Native API",
        workspace=str(tmp_path),
        default_harness_id="fake-cli",
    )

    started = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "fake-cli",
            "action": "start",
            "workspace": str(tmp_path),
        },
    )

    assert started.status_code == 200, started.text
    assert started.json()["run"]["native_session_id"] == "managed-native-1"
    link = started.json()["native_link"]
    assert link["status"] == "managed_native"
    assert link["native_session_id"] == "managed-native-1"
    assert link["metadata"]["can_resume"] is True
    assert link["metadata"]["native_process_id"] == started.json()["process"]["id"]
    bundle = store.get_session_bundle(session.id)
    assert bundle.native_links[-1].native_session_id == "managed-native-1"


def test_native_process_api_start_preserves_attachment_render_plan(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    source = workspace / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("print('hello')\n", encoding="utf-8")
    script = _write_once_cli(tmp_path)
    data_dir = tmp_path / "data"
    session_store = FilesystemHarnessSessionStore(data_dir)
    client, store = _client(
        tmp_path,
        FakeProcessConnector(
            start_script=script,
            harness_id="codex-cli",
            native_session_id="managed-native-attachments",
        ),
        config=HarnessConfig(
            default_model="ConfiguredModel",
            data_dir=str(data_dir),
        ),
        store=session_store,
    )
    session = store.create_session(
        title="Native API",
        workspace=str(workspace),
        default_harness_id="codex-cli",
    )
    attachment = client.post(
        f"/api/sessions/{session.id}/attachments/workspace",
        json={"path": "src/app.py", "workspace": str(workspace)},
    ).json()["attachment"]

    started = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "codex-cli",
            "action": "start",
            "prompt": "Inspect",
            "workspace": str(workspace),
            "attachment_ids": [attachment["id"]],
        },
    )

    assert started.status_code == 200, started.text
    process_id = started.json()["process"]["id"]
    metadata = started.json()["run"]["metadata"]
    assert metadata["attachment_ids"] == [attachment["id"]]
    assert metadata["attachments"][0]["workspace_path"] == "src/app.py"
    assert "@src/app.py" in metadata["attachment_render_plan"]["prompt_prefix"]
    output = client.get(f"/api/native/processes/{process_id}/output").json()
    assert (
        output["run"]["metadata"]["attachment_render_plan"]["prompt_prefix"]
        == metadata["attachment_render_plan"]["prompt_prefix"]
    )


def test_native_process_api_resume_uses_cached_native_ref(tmp_path):
    resume_script = tmp_path / "resume_cli.py"
    resume_script.write_text(
        "import sys\nprint('resumed:' + sys.argv[1], flush=True)\n",
        encoding="utf-8",
    )
    native_index = FilesystemNativeSessionIndexStore(tmp_path / "data")
    ref = _native_ref(workspace=str(tmp_path))
    native_index.upsert_ref(ref, project_id="proj_native")
    client, store = _client(
        tmp_path,
        FakeProcessConnector(start_script=resume_script, resume_script=resume_script),
        native_index_store=native_index,
    )
    session = store.create_session(
        title="Native API",
        workspace=str(tmp_path),
        default_harness_id="fake-cli",
    )

    started = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "action": "resume",
            "native_ref_id": ref.id,
        },
    )

    assert started.status_code == 200, started.text
    process_id = started.json()["process"]["id"]
    assert started.json()["run"]["native_session_id"] == "native-session-1"
    _wait_for_output(client, process_id, 0, "resumed:native-session-1")
    completed = _wait_for_process_status(client, process_id, {"succeeded", "failed"})
    assert completed["run"]["status"] == "succeeded"


def test_native_process_api_resume_uses_stored_managed_link(tmp_path):
    start_script = _write_once_cli(tmp_path)
    resume_script = tmp_path / "resume_cli.py"
    resume_script.write_text(
        "import sys\nprint('resumed-link:' + sys.argv[1], flush=True)\n",
        encoding="utf-8",
    )
    client, store = _client(
        tmp_path,
        FakeProcessConnector(
            start_script=start_script,
            resume_script=resume_script,
            native_session_id="managed-native-2",
        ),
    )
    session = store.create_session(
        title="Native API",
        workspace=str(tmp_path),
        default_harness_id="fake-cli",
    )
    started = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "fake-cli",
            "action": "start",
            "workspace": str(tmp_path),
        },
    )
    assert started.status_code == 200, started.text

    resumed = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "fake-cli",
            "action": "resume",
        },
    )

    assert resumed.status_code == 200, resumed.text
    process_id = resumed.json()["process"]["id"]
    assert resumed.json()["run"]["native_session_id"] == "managed-native-2"
    assert resumed.json()["native_link"]["native_session_id"] == "managed-native-2"
    _wait_for_output(client, process_id, 0, "resumed-link:managed-native-2")


def test_native_process_api_resume_reports_missing_native_id_from_link(tmp_path):
    script = _write_once_cli(tmp_path)
    client, store = _client(tmp_path, FakeProcessConnector(start_script=script))
    session = store.create_session(
        title="Native API",
        workspace=str(tmp_path),
        default_harness_id="fake-cli",
    )
    started = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "fake-cli",
            "action": "start",
            "workspace": str(tmp_path),
        },
    )
    assert started.status_code == 200, started.text
    assert started.json()["native_link"]["metadata"]["can_resume"] is False

    resumed = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "fake-cli",
            "action": "resume",
        },
    )

    assert resumed.status_code == 400
    assert "Native session id was not detected" in resumed.json()["detail"]


def test_native_process_api_redacts_start_output_and_events(tmp_path):
    secret = "native-process-api-secret-value"
    script = tmp_path / "print_secret.py"
    script.write_text(
        "import os\nprint(os.environ['GPT2GIGA_API_KEY'], flush=True)\n",
        encoding="utf-8",
    )
    client, store = _client(
        tmp_path,
        FakeProcessConnector(start_script=script, pass_context_api_key=True),
        config=HarnessConfig(
            api_key=secret,
            data_dir=str(tmp_path / "data"),
        ),
    )
    session = store.create_session(
        title="Native API",
        workspace=str(tmp_path),
        default_harness_id="fake-cli",
    )

    started = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "fake-cli",
            "action": "start",
            "workspace": str(tmp_path),
        },
    )

    assert started.status_code == 200, started.text
    assert secret not in str(started.json())
    assert REDACTED in str(started.json())
    process_id = started.json()["process"]["id"]
    _wait_for_process_status(client, process_id, {"succeeded"})
    output = client.get(f"/api/native/processes/{process_id}/output").json()

    assert secret not in str(output)
    assert secret not in str(store.list_events(session.id))
    assert REDACTED in str(output)
    assert REDACTED in str(store.list_events(session.id))


class FakeProcessConnector:
    harness_id = "fake-cli"

    def __init__(
        self,
        *,
        start_script,
        resume_script=None,
        pass_context_api_key: bool = False,
        native_session_id: str | None = None,
        harness_id: str = "fake-cli",
    ) -> None:
        self.harness_id = harness_id
        self.start_script = start_script
        self.resume_script = resume_script or start_script
        self.pass_context_api_key = pass_context_api_key
        self.native_session_id = native_session_id

    def discover(self, *, workspace, include_external):
        return ()

    def preview(self, ref, *, max_messages=20):
        return ()

    def import_ref(self, ref):
        return ()

    def build_start_command(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> NativeCommandPlan:
        env = _python_env()
        if self.pass_context_api_key and context.api_key:
            env["GPT2GIGA_API_KEY"] = context.api_key
        metadata = {"harness_id": self.harness_id}
        if self.native_session_id is not None:
            metadata["native_session_id"] = self.native_session_id
        return NativeCommandPlan(
            command=(sys.executable, str(self.start_script)),
            env=env,
            cwd=request.workspace,
            native_home=str(request.workspace) if request.workspace else None,
            metadata=metadata,
        )

    def build_resume_command(
        self,
        ref: NativeSessionRef,
        context: HarnessContext,
    ) -> NativeCommandPlan:
        return NativeCommandPlan(
            command=(
                sys.executable,
                str(self.resume_script),
                ref.native_session_id or ref.id,
            ),
            env=_python_env(),
            cwd=ref.workspace,
            metadata={
                "harness_id": self.harness_id,
                "native_ref_id": ref.id,
            },
        )


def _client(
    tmp_path,
    connector: FakeProcessConnector,
    *,
    config: HarnessConfig | None = None,
    native_index_store=None,
    store=None,
):
    store = store or InMemoryHarnessSessionStore()
    native_registry = NativeHistoryConnectorRegistry()
    native_registry.register(connector)
    manager = NativeProcessManager(session_store=store, use_pty=False)
    app = create_app(
        config
        or HarnessConfig(
            default_model="ConfiguredModel",
            data_dir=str(tmp_path / "data"),
        ),
        registry=create_default_registry(include_entry_points=False),
        store=store,
        native_registry=native_registry,
        native_index_store=native_index_store,
        native_process_manager=manager,
    )
    return TestClient(app), store


def _write_echo_cli(tmp_path):
    script = tmp_path / "echo_cli.py"
    script.write_text(
        "import sys\n"
        "print('ready', flush=True)\n"
        "for line in sys.stdin:\n"
        "    text = line.strip()\n"
        "    print(f'echo:{text}', flush=True)\n",
        encoding="utf-8",
    )
    return script


def _write_once_cli(tmp_path):
    script = tmp_path / "once_cli.py"
    script.write_text(
        "print('started', flush=True)\n",
        encoding="utf-8",
    )
    return script


def _native_ref(*, workspace: str) -> NativeSessionRef:
    return NativeSessionRef(
        id="native_fake_1",
        harness_id="fake-cli",
        native_session_id="native-session-1",
        title="Fake native session",
        workspace=workspace,
        source="fake",
        status=NativeSessionStatus.MANAGED_NATIVE,
        created_at="2026-07-09T09:00:00Z",
        updated_at="2026-07-09T10:00:00Z",
        message_count=1,
        can_preview=True,
        can_import=True,
        can_resume=True,
        metadata={"project_id": "proj_native"},
    )


def _python_env():
    env = {"PYTHONUNBUFFERED": "1"}
    for key in ("PATH", "SYSTEMROOT"):
        if value := os.environ.get(key):
            env[key] = value
    return env


def _wait_for_output(client: TestClient, process_id: str, cursor: int, expected: str):
    deadline = time.monotonic() + 3.0
    seen = ""
    latest_cursor = cursor
    while time.monotonic() < deadline:
        response = client.get(
            f"/api/native/processes/{process_id}/output",
            params={"cursor": latest_cursor},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        latest_cursor = body["cursor"]
        seen += "".join(output["text"] for output in body["outputs"])
        if expected in seen:
            return latest_cursor, seen
        time.sleep(0.02)
    raise AssertionError(f"Timed out waiting for {expected!r}; saw {seen!r}")


def _wait_for_process_status(
    client: TestClient,
    process_id: str,
    run_statuses: set[str],
):
    deadline = time.monotonic() + 3.0
    body = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/native/processes/{process_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        if body["run"]["status"] in run_statuses:
            return body
        time.sleep(0.02)
    raise AssertionError(f"Timed out waiting for {run_statuses}; last body was {body}")
