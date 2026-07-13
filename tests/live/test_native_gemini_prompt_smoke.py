"""Opt-in smoke test for one real Gemini native initial prompt."""

from __future__ import annotations

import os
import shutil
import time

import pytest

from gpt2giga_harness.native.gemini import GeminiNativeHistoryConnector
from gpt2giga_harness.native.process import NativeProcessManager, NativeProcessStatus
from gpt2giga_harness.sessions import InMemoryHarnessSessionStore
from gpt2giga_harness.types import GigaChatApiMode, HarnessContext, HarnessRequest


pytestmark = [pytest.mark.integration, pytest.mark.live_native_cli, pytest.mark.slow]


def test_live_gemini_native_delivers_one_prompt(tmp_path):
    if os.getenv("GPT2GIGA_RUN_NATIVE_CLI_TESTS") != "1":
        pytest.skip("set GPT2GIGA_RUN_NATIVE_CLI_TESTS=1 to run native CLI smoke")
    executable = shutil.which("gemini")
    if executable is None:
        pytest.skip("Gemini CLI is not installed")
    proxy_url = os.getenv("GPT2GIGA_NATIVE_PROXY_URL")
    if not proxy_url:
        pytest.skip("set GPT2GIGA_NATIVE_PROXY_URL to a ready local proxy")

    store = InMemoryHarnessSessionStore()
    session = store.create_session(
        title="Live Gemini prompt",
        workspace=str(tmp_path),
        default_harness_id="gemini-cli",
    )
    connector = GeminiNativeHistoryConnector(
        data_dir=tmp_path / "data",
        executable=executable,
    )
    plan = connector.build_start_command(
        HarnessRequest(
            prompt="Reply with exactly OK. Do not use tools.",
            model=os.getenv("GPT2GIGA_LIVE_MODEL"),
            api_mode=GigaChatApiMode.V2,
            mode="plan",
            workspace=str(tmp_path),
            extra={"native_prompt_idempotency_key": "nprompt_live_smoke"},
        ),
        HarnessContext(
            proxy_url=proxy_url,
            api_key=os.getenv("GPT2GIGA_NATIVE_PROXY_KEY"),
        ),
    )
    manager = NativeProcessManager(session_store=store, use_pty=False)

    ref = manager.start(plan, session_id=session.id)
    deadline = time.monotonic() + 30.0
    saw_output = False
    try:
        while time.monotonic() < deadline:
            chunk = manager.read_since(ref.id, 0)
            saw_output = saw_output or bool(chunk.outputs)
            if chunk.status is not NativeProcessStatus.RUNNING:
                break
            if saw_output:
                break
            time.sleep(0.1)
    finally:
        if manager.status(ref.id).status is NativeProcessStatus.RUNNING:
            manager.stop(ref.id)

    assert ref.metadata["prompt_delivery"]["status"] == "delivered"
    assert saw_output
