import pytest

from gpt2giga_harness.harnesses.claude_code import ClaudeCodeHarness
from gpt2giga_harness.harnesses.codex_cli import CodexCliHarness
from gpt2giga_harness.harnesses.direct_chat import DirectChatHarness
from gpt2giga_harness.harnesses.echo import EchoHarness
from gpt2giga_harness.harnesses.gemini_cli import GeminiCliHarness
from gpt2giga_harness.types import (
    HarnessChatMessage,
    HarnessContext,
    HarnessRequest,
)


def test_echo_reports_attachment_summary_and_events():
    request = HarnessRequest(
        prompt="inspect",
        attachments=(
            {
                "id": "att_note",
                "filename": "note.txt",
                "kind": "text",
                "mime_type": "text/plain",
                "size_bytes": 12,
            },
        ),
        attachment_render_plan={"metadata": {"transport": "metadata_only"}},
    )

    result = EchoHarness().run(
        request,
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    assert result.ok is True
    assert "Attachments:" in result.text
    assert "note.txt" in result.text
    assert result.raw["attachments"][0]["id"] == "att_note"
    assert result.raw["attachment_render_plan"]["metadata"]["transport"] == (
        "metadata_only"
    )
    assert result.events[0].type == "attachment"
    assert result.events[0].payload["filename"] == "note.txt"


def test_direct_chat_dry_run_applies_content_parts_and_warnings():
    request = HarnessRequest(
        prompt="Describe this",
        messages=(
            HarnessChatMessage(role="user", content="Previous"),
            HarnessChatMessage(role="assistant", content="Done"),
            HarnessChatMessage(role="user", content="Describe this"),
        ),
        attachments=(
            {
                "id": "att_screenshot",
                "filename": "screenshot.png",
                "kind": "image",
                "mime_type": "image/png",
                "size_bytes": 24,
            },
        ),
        attachment_render_plan={
            "prompt_prefix": "Attachment note.",
            "content_parts": [
                {"type": "text", "text": "Describe this"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,AAAA"},
                },
            ],
            "warnings": ["screenshot.png is path-only in some harnesses."],
            "metadata": {"transport": "openai_content_parts"},
        },
        extra={"dry_run": True},
    )

    result = DirectChatHarness().run(
        request,
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    assert result.ok is True
    messages = result.raw["payload"]["messages"]
    assert messages[0]["content"] == "Previous"
    assert messages[-1]["content"][0] == {
        "type": "text",
        "text": "Attachment note.\n\nDescribe this",
    }
    assert messages[-1]["content"][1]["type"] == "image_url"
    assert result.raw["attachment_warnings"] == [
        "screenshot.png is path-only in some harnesses."
    ]
    assert result.events[0].type == "attachment_warning"


@pytest.mark.parametrize(
    ("harness", "prompt_from_command"),
    (
        (CodexCliHarness(), lambda command: command[-1]),
        (ClaudeCodeHarness(), lambda command: command[-1]),
        (GeminiCliHarness(), lambda command: command[command.index("-p") + 1]),
    ),
)
def test_agent_cli_dry_runs_apply_attachment_prompt_prefix(
    harness,
    prompt_from_command,
):
    request = HarnessRequest(
        prompt="Inspect",
        attachment_render_plan={
            "prompt_prefix": "Attachments:\n- @src/app.py",
            "warnings": ["image attachments use path references only."],
            "metadata": {"transport": "prompt_path_reference"},
        },
        extra={"dry_run": True},
    )

    result = harness.run(
        request,
        HarnessContext(proxy_url="http://127.0.0.1:8090", api_key="proxy-key"),
    )

    assert result.ok is True
    assert (
        prompt_from_command(result.command) == "Attachments:\n- @src/app.py\n\nInspect"
    )
    assert result.raw["attachment_warnings"] == [
        "image attachments use path references only."
    ]
    assert result.events[0].type == "attachment_warning"
