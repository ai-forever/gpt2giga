from gpt2giga_harness.attachments import (
    FilesystemAttachmentStore,
    render_attachments_for_harness,
    render_for_claude_code,
    render_for_codex_cli,
    render_for_direct_chat,
    render_for_gemini_cli,
)
from gpt2giga_harness.sessions import FilesystemHarnessSessionStore
from gpt2giga_harness.types import REDACTED

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def test_direct_chat_renderer_builds_image_content_part_and_redacts_text(tmp_path):
    session, store = _session_and_store(tmp_path)
    image = store.create_upload(
        session_id=session.id,
        project_id=None,
        filename="screenshot.png",
        data=PNG_BYTES,
        mime_type="image/png",
    )
    text = store.create_upload(
        session_id=session.id,
        project_id=None,
        filename="note.txt",
        data=b"token = 'sk-supersecret12345'\n",
        mime_type="text/plain",
    )

    plan = render_for_direct_chat((image, text), store, prompt="Describe")

    assert plan.content_parts[0] == {"type": "text", "text": "Describe"}
    assert plan.content_parts[1]["type"] == "image_url"
    assert plan.content_parts[1]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )
    assert "note.txt" in plan.prompt_prefix
    assert "sk-supersecret12345" not in plan.prompt_prefix
    assert REDACTED in plan.prompt_prefix
    assert plan.metadata["transport"] == "openai_content_parts"
    assert plan.metadata["content_part_count"] == 2


def test_direct_chat_renderer_truncates_inline_text(tmp_path):
    session, store = _session_and_store(tmp_path)
    text = store.create_upload(
        session_id=session.id,
        project_id=None,
        filename="long.txt",
        data=b"hello world",
        mime_type="text/plain",
    )

    plan = render_for_direct_chat((text,), store, inline_text_limit=5)

    assert "hello" in plan.prompt_prefix
    assert "world" not in plan.prompt_prefix
    assert plan.warnings == ("long.txt was truncated at 5 bytes.",)


def test_agent_renderers_use_workspace_and_uploaded_path_references(tmp_path):
    session_store = FilesystemHarnessSessionStore(tmp_path / "data")
    session = session_store.create_session(title="renderers")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    source = workspace / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("print('hello')\n", encoding="utf-8")
    store = FilesystemAttachmentStore(tmp_path / "data")
    workspace_attachment = store.create_workspace_reference(
        session_id=session.id,
        project_id="proj_demo",
        workspace_root=workspace,
        path="src/app.py",
    )
    image = store.create_upload(
        session_id=session.id,
        project_id="proj_demo",
        filename="screenshot.png",
        data=PNG_BYTES,
        mime_type="image/png",
    )

    codex_plan = render_for_codex_cli((workspace_attachment, image), store)
    gemini_plan = render_for_gemini_cli((workspace_attachment, image), store)

    assert "@src/app.py" in codex_plan.prompt_prefix
    assert "screenshot.png" not in codex_plan.prompt_prefix
    assert codex_plan.cli_args == ("--image", image.storage_path)
    assert codex_plan.warnings == ()
    assert codex_plan.metadata["transport"] == (
        "cli_image_flag_and_prompt_path_reference"
    )
    assert codex_plan.metadata["image_count"] == 1
    assert codex_plan.metadata["required_cli_capabilities"] == ["--image"]
    assert codex_plan.metadata["deliveries"] == [
        {
            "attachment_id": workspace_attachment.id,
            "kind": "text",
            "transport": "at_file_reference",
            "rich": False,
            "required_cli_capabilities": [],
            "surfaces": [
                "headless",
                "headless_one_shot",
                "structured_thread",
                "native",
            ],
        },
        {
            "attachment_id": image.id,
            "kind": "image",
            "transport": "cli_image_flag",
            "rich": True,
            "required_cli_capabilities": ["--image"],
            "surfaces": ["headless_one_shot", "native"],
        },
    ]
    assert "@src/app.py" in gemini_plan.prompt_prefix
    assert gemini_plan.warnings == (
        "Gemini CLI will receive this image as a path reference only.",
    )
    assert gemini_plan.metadata["deliveries"][1]["rich"] is False


def test_claude_and_gemini_documents_remain_explicit_path_references(tmp_path):
    session, store = _session_and_store(tmp_path)
    document = store.create_upload(
        session_id=session.id,
        project_id=None,
        filename="report.pdf",
        data=b"%PDF-1.7\nfixture",
        mime_type="application/pdf",
    )

    claude_plan = render_for_claude_code((document,), store)
    gemini_plan = render_for_gemini_cli((document,), store)

    assert claude_plan.metadata["deliveries"][0]["transport"] == (
        "prompt_path_reference"
    )
    assert claude_plan.metadata["deliveries"][0]["rich"] is False
    assert claude_plan.warnings == (
        "Claude Code will receive this document as a path reference only.",
    )
    assert gemini_plan.warnings == (
        "Gemini CLI will receive this document as a path reference only.",
    )


def test_render_dispatcher_reports_unknown_harness(tmp_path):
    session, store = _session_and_store(tmp_path)
    attachment = store.create_upload(
        session_id=session.id,
        project_id=None,
        filename="note.txt",
        data=b"hello",
        mime_type="text/plain",
    )

    plan = render_attachments_for_harness("custom", (attachment,), store)

    assert plan.metadata["transport"] == "unsupported"
    assert plan.warnings == ("custom has no attachment renderer.",)


def _session_and_store(tmp_path):
    session_store = FilesystemHarnessSessionStore(tmp_path)
    session = session_store.create_session(title="renderers")
    return session, FilesystemAttachmentStore(tmp_path)
