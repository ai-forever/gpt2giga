from dataclasses import replace

import pytest

from gpt2giga_harness.native.base import (
    NativeCommandPlan,
    discovery_result_to_dict,
    native_command_plan_to_dict,
)
from gpt2giga_harness.native.models import (
    NativeSessionRef,
    NativeSessionStatus,
    NativeTranscriptMessage,
)
from gpt2giga_harness.native.registry import (
    NativeHistoryConnectorRegistry,
    UnknownNativeHistoryConnectorError,
    create_default_native_registry,
)
from gpt2giga_harness.types import (
    GigaChatApiMode,
    HarnessCapability,
    HarnessContext,
    HarnessRequest,
    REDACTED,
)


def test_native_history_registry_registers_and_discovers_fake_connector():
    ref = _ref("native_codex_1")
    connector = FakeConnector("codex-cli", refs=(ref,))
    registry = NativeHistoryConnectorRegistry()

    registry.register(connector)
    result = registry.discover(
        harness_id="codex-cli",
        workspace="/repo",
        include_external=True,
    )

    assert registry.ids() == ("codex-cli",)
    assert registry.get("codex-cli") is connector
    assert registry.list() == (connector,)
    assert result.sessions == (ref,)
    assert result.errors == ()
    assert connector.discovery_calls == (
        {"workspace": "/repo", "include_external": True},
    )


def test_default_native_registry_uses_user_configured_executable(tmp_path):
    executable = tmp_path / "bin" / "codex"
    executable.parent.mkdir()
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[executables]\n"codex-cli" = "{executable}"\n',
        encoding="utf-8",
    )

    connector = create_default_native_registry(
        data_dir=tmp_path / "data",
        config_path=config_path,
    ).get("codex-cli")
    plan = connector.build_start_command(
        HarnessRequest(prompt="inspect", workspace=str(tmp_path)),
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    assert plan.command[0] == str(executable)


def test_native_history_registry_unknown_get_raises():
    registry = NativeHistoryConnectorRegistry()

    with pytest.raises(UnknownNativeHistoryConnectorError):
        registry.get("missing")


def test_native_history_registry_discovery_errors_are_structured(monkeypatch):
    secret = "sk-native-secret-456"
    monkeypatch.setenv("GPT2GIGA_API_KEY", secret)
    ok_ref = _ref("native_ok")
    registry = NativeHistoryConnectorRegistry()
    registry.register_many(
        (
            FakeConnector("codex-cli", refs=(ok_ref,)),
            FailingConnector("gemini-cli", RuntimeError(f"failed with {secret}")),
        )
    )

    result = registry.discover(workspace="/repo", include_external=False)
    payload = discovery_result_to_dict(result)

    assert result.sessions == (ok_ref,)
    assert len(result.errors) == 1
    assert result.errors[0].harness_id == "gemini-cli"
    assert result.errors[0].code == "connector_error"
    assert result.errors[0].detail == "RuntimeError"
    assert secret not in str(payload)
    assert REDACTED in str(payload)


def test_native_history_registry_unknown_discovery_returns_error():
    result = NativeHistoryConnectorRegistry().discover(harness_id="missing")

    assert result.sessions == ()
    assert len(result.errors) == 1
    assert result.errors[0].harness_id == "missing"
    assert result.errors[0].code == "unknown_connector"


def test_native_history_registry_paginates_discovery_with_cursor():
    first = _ref("native_1")
    second = replace(first, id="native_2", native_session_id="session-2")
    third = replace(first, id="native_3", native_session_id="session-3")
    registry = NativeHistoryConnectorRegistry()
    registry.register(FakeConnector("codex-cli", refs=(first, second, third)))

    page_one = registry.discover(harness_id="codex-cli", limit=2)
    page_two = registry.discover(
        harness_id="codex-cli",
        cursor=page_one.next_cursor,
        limit=2,
    )

    assert page_one.sessions == (first, second)
    assert page_one.next_cursor == "2"
    assert page_one.scanned_count == 3
    assert page_two.sessions == (third,)
    assert page_two.next_cursor is None
    with pytest.raises(ValueError, match="non-negative integer"):
        registry.discover(cursor="bad", limit=2)


def test_native_command_plan_serialization_redacts_secrets(monkeypatch):
    secret = "sk-native-secret-789"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    plan = NativeCommandPlan(
        command=("claude", "--api-key", secret),
        display_command=("claude", "--api-key", "<redacted>"),
        env={"ANTHROPIC_API_KEY": secret, "SAFE": "ok"},
        cwd="/repo",
        native_home=f"/tmp/{secret}/claude",
        metadata={"token": secret, "safe": "ok"},
    )

    payload = native_command_plan_to_dict(plan)

    assert secret not in str(payload)
    assert REDACTED in str(payload)
    assert payload["env"]["SAFE"] == "ok"
    assert payload["metadata"]["safe"] == "ok"


class FakeConnector:
    def __init__(
        self,
        harness_id: str,
        *,
        refs: tuple[NativeSessionRef, ...] = (),
    ) -> None:
        self.harness_id = harness_id
        self.refs = refs
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
        return self.refs

    def preview(
        self,
        ref: NativeSessionRef,
        *,
        max_messages: int = 20,
    ) -> tuple[NativeTranscriptMessage, ...]:
        return (
            NativeTranscriptMessage(
                role="user",
                content=f"{ref.id}:{max_messages}",
            ),
        )

    def import_ref(
        self,
        ref: NativeSessionRef,
    ) -> tuple[NativeTranscriptMessage, ...]:
        return (NativeTranscriptMessage(role="user", content=ref.id),)

    def build_start_command(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> NativeCommandPlan:
        return NativeCommandPlan(
            command=(self.harness_id, request.prompt),
            env={"API_BASE": context.api_base_url(request.api_mode)},
            cwd=request.workspace,
        )

    def build_resume_command(
        self,
        ref: NativeSessionRef,
        context: HarnessContext,
    ) -> NativeCommandPlan:
        return NativeCommandPlan(
            command=(self.harness_id, "resume", ref.native_session_id or ref.id),
            env={"API_BASE": context.api_base_url(GigaChatApiMode.V2)},
            cwd=ref.workspace,
        )


class FailingConnector(FakeConnector):
    def __init__(self, harness_id: str, exc: Exception) -> None:
        super().__init__(harness_id)
        self.exc = exc

    def discover(
        self,
        *,
        workspace: str | None,
        include_external: bool,
    ) -> tuple[NativeSessionRef, ...]:
        raise self.exc


def _ref(ref_id: str) -> NativeSessionRef:
    return NativeSessionRef(
        id=ref_id,
        harness_id="codex-cli",
        native_session_id="codex-session-1",
        title="Fix harness",
        workspace="/repo",
        source="test",
        status=NativeSessionStatus.MANAGED_NATIVE,
        created_at="2026-07-09T09:00:00Z",
        updated_at="2026-07-09T10:00:00Z",
        message_count=2,
        can_preview=True,
        can_import=True,
        can_resume=True,
        metadata={"capability": HarnessCapability.AGENT_CLI.value},
    )
