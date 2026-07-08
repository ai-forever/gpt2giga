import pytest

from gpt2giga.harness.attachments import FilesystemAttachmentStore
from gpt2giga.harness.config import HarnessConfig
from gpt2giga.harness.harnesses.base import BaseHarness
from gpt2giga.harness.harnesses.echo import EchoHarness
from gpt2giga.harness.project import project_id_for_root
from gpt2giga.harness.registry import HarnessRegistry
from gpt2giga.harness.session_runner import HarnessSessionRunner
from gpt2giga.harness.sessions import FilesystemHarnessSessionStore
from gpt2giga.harness.types import (
    Availability,
    HarnessCapability,
    HarnessContext,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def test_session_runner_without_attachments_preserves_request_shape(tmp_path):
    harness = _CaptureHarness()
    runner, _, _ = _runner(harness, data_dir=tmp_path / "data")

    result = runner.create_and_run({"harness_id": "capture", "prompt": "hello"})

    assert harness.last_request is not None
    assert harness.last_request.attachments == ()
    assert "attachments" not in harness.last_request.extra
    assert "attachments" not in result.run.metadata
    assert "attachments" not in result.bundle.raw_requests[-1].payload


def test_session_runner_persists_uploaded_image_attachment_with_echo(tmp_path):
    data_dir = tmp_path / "data"
    runner, _, attachment_store = _runner(EchoHarness(), data_dir=data_dir)
    session = runner.create_session(default_harness_id="echo")
    attachment = attachment_store.create_upload(
        session_id=session.id,
        project_id=None,
        filename="screenshot.png",
        data=PNG_BYTES,
        mime_type="image/png",
        source="paste",
    )

    result = runner.run_in_session(
        session.id,
        {
            "harness_id": "echo",
            "prompt": "look at this",
            "attachment_ids": [attachment.id],
        },
    )

    assert result.result.ok is True
    assert result.run.metadata["attachment_ids"] == [attachment.id]
    run_attachment = result.run.metadata["attachments"][0]
    assert run_attachment["kind"] == "image"
    assert run_attachment["source"] == "paste"
    assert "storage_path" not in run_attachment
    assert result.bundle.raw_requests[-1].payload["attachment_ids"] == [attachment.id]
    assert result.bundle.raw_requests[-1].payload["attachments"][0]["id"] == (
        attachment.id
    )
    assert result.bundle.messages[0].metadata["attachment_ids"] == [attachment.id]
    assert result.to_dict()["attachments"][0]["id"] == attachment.id


def test_session_runner_persists_workspace_attachment_with_echo(tmp_path):
    data_dir = tmp_path / "data"
    workspace = tmp_path / "repo"
    workspace.mkdir()
    source = workspace / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("print('hello')\n", encoding="utf-8")
    runner, _, attachment_store = _runner(EchoHarness(), data_dir=data_dir)
    session = runner.create_session(
        workspace=str(workspace),
        default_harness_id="echo",
    )
    attachment = attachment_store.create_workspace_reference(
        session_id=session.id,
        project_id=project_id_for_root(workspace),
        workspace_root=workspace,
        path="src/app.py",
    )

    result = runner.run_in_session(
        session.id,
        {
            "harness_id": "echo",
            "prompt": "check file",
            "attachment_ids": [attachment.id],
        },
    )

    run_attachment = result.run.metadata["attachments"][0]
    assert run_attachment["kind"] == "workspace_file"
    assert run_attachment["workspace_path"] == "src/app.py"
    assert run_attachment["project_id"] == project_id_for_root(workspace)
    assert "storage_path" not in run_attachment
    assert result.bundle.messages[0].metadata["attachments"][0]["workspace_path"] == (
        "src/app.py"
    )


def test_session_runner_rejects_unknown_attachment_id(tmp_path):
    runner, _, _ = _runner(EchoHarness(), data_dir=tmp_path / "data")
    session = runner.create_session(default_harness_id="echo")

    with pytest.raises(ValueError, match="Unknown attachment id"):
        runner.run_in_session(
            session.id,
            {
                "harness_id": "echo",
                "prompt": "hello",
                "attachment_ids": ["att_missing"],
            },
        )


def test_session_runner_rejects_attachment_from_another_session(tmp_path):
    runner, _, attachment_store = _runner(EchoHarness(), data_dir=tmp_path / "data")
    first = runner.create_session(default_harness_id="echo")
    second = runner.create_session(default_harness_id="echo")
    attachment = attachment_store.create_upload(
        session_id=first.id,
        project_id=None,
        filename="note.txt",
        data=b"hello",
        mime_type="text/plain",
    )

    with pytest.raises(ValueError, match="does not belong to session"):
        runner.run_in_session(
            second.id,
            {
                "harness_id": "echo",
                "prompt": "hello",
                "attachment_ids": [attachment.id],
            },
        )


def _runner(
    harness: BaseHarness,
    *,
    data_dir,
) -> tuple[
    HarnessSessionRunner,
    FilesystemHarnessSessionStore,
    FilesystemAttachmentStore,
]:
    registry = HarnessRegistry()
    registry.register(harness)
    session_store = FilesystemHarnessSessionStore(data_dir)
    attachment_store = FilesystemAttachmentStore(data_dir)
    runner = HarnessSessionRunner(
        registry=registry,
        config=HarnessConfig(default_model="ConfiguredModel", data_dir=str(data_dir)),
        store=session_store,
        attachment_store=attachment_store,
    )
    return runner, session_store, attachment_store


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
        )

    def availability(self) -> Availability:
        return Availability.available("test")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        self.last_request = request
        return HarnessResult(ok=True, text=f"answer: {request.prompt}")
