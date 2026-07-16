"""Opt-in installed-CLI attachment command smoke without task execution."""

from __future__ import annotations

import os

import pytest

from gpt2giga_harness.harnesses.claude_code import ClaudeCodeHarness
from gpt2giga_harness.harnesses.codex_cli import CodexCliHarness
from gpt2giga_harness.harnesses.gemini_cli import GeminiCliHarness
from gpt2giga_harness.types import HarnessContext, HarnessRequest


pytestmark = [pytest.mark.integration, pytest.mark.live_native_cli]


@pytest.mark.parametrize(
    ("harness_cls", "prompt_index"),
    (
        (CodexCliHarness, -1),
        (ClaudeCodeHarness, -1),
        (GeminiCliHarness, None),
    ),
)
def test_installed_cli_builds_reviewed_attachment_dry_run(harness_cls, prompt_index):
    if os.getenv("GPT2GIGA_RUN_CLI_ATTACHMENT_TESTS") != "1":
        pytest.skip("set GPT2GIGA_RUN_CLI_ATTACHMENT_TESTS=1 to run CLI smoke")
    harness = harness_cls()
    availability = harness.availability()
    if availability.status.value != "available":
        pytest.skip(availability.reason)
    path = "/tmp/gpt2giga-attachment-smoke.txt"
    request = HarnessRequest(
        prompt="Inspect the attachment",
        attachment_render_plan={
            "prompt_prefix": f"Attachments:\n- Local attachment path: {path}",
            "metadata": {
                "transport": "prompt_path_reference",
                "deliveries": [
                    {
                        "kind": "text",
                        "transport": "prompt_path_reference",
                        "rich": False,
                        "required_cli_capabilities": [],
                        "surfaces": ["headless_one_shot", "native"],
                    }
                ],
            },
        },
        extra={"dry_run": True},
    )

    result = harness.run(
        request,
        HarnessContext(proxy_url="http://127.0.0.1:8090", api_key="placeholder"),
    )

    assert result.ok is True
    prompt = (
        result.command[result.command.index("-p") + 1]
        if prompt_index is None
        else result.command[prompt_index]
    )
    assert path in prompt
    assert (
        result.raw["attachment_render_plan"]["metadata"]["deliveries"][0]["rich"]
        is False
    )
