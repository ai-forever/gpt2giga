from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
import json
from pathlib import Path
import stat
import threading
from typing import Any, Mapping

from gpt2giga_harness.codex_app_server import (
    CodexAppServerSupervisor,
    _collab_child_tool_events,
    _normalize_notification,
    _structured_link_id,
    build_execution_snapshot,
    build_structured_execution_snapshot,
)
from gpt2giga_harness.executables import ExecutableResolution
from gpt2giga_harness.structured_sessions import (
    StructuredSessionLinkStore,
    structured_session_link_from_dict,
)
from gpt2giga_harness.types import (
    GigaChatApiMode,
    HarnessContext,
    HarnessRequest,
)


class _FakeAppServerClient:
    def __init__(
        self,
        *,
        runtime_id: str,
        recorder: list[tuple[str, dict[str, Any]]],
        **_kwargs,
    ) -> None:
        self.runtime_id = runtime_id
        self.recorder = recorder
        self.messages: deque[dict[str, Any]] = deque()
        self.turn_number = 0
        self._alive = True

    @property
    def alive(self) -> bool:
        return self._alive

    def request(
        self, method: str, params: Mapping[str, Any], *, timeout: float
    ) -> Mapping[str, Any]:
        del timeout
        payload = dict(params)
        self.recorder.append((method, payload))
        if method == "thread/start":
            return {"thread": {"id": "thread-1"}}
        if method == "thread/fork":
            return {"thread": {"id": "thread-fork"}}
        if method in {"thread/read", "thread/resume"}:
            return {"thread": {"id": payload["threadId"]}}
        if method == "turn/start":
            self.turn_number += 1
            turn_id = f"turn-{self.turn_number}"
            thread_id = str(payload["threadId"])
            answer = f"answer {self.turn_number}"
            self.messages.extend(
                (
                    {
                        "method": "item/started",
                        "params": {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "item": {
                                "id": f"tool-{self.turn_number}",
                                "type": "commandExecution",
                                "command": "pwd",
                                "cwd": "/workspace",
                                "status": "inProgress",
                            },
                        },
                    },
                    {
                        "method": "item/completed",
                        "params": {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "item": {
                                "id": f"tool-{self.turn_number}",
                                "type": "commandExecution",
                                "command": "pwd",
                                "cwd": "/workspace",
                                "status": "completed",
                            },
                        },
                    },
                    {
                        "method": "item/agentMessage/delta",
                        "params": {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "itemId": f"msg-{self.turn_number}",
                            "delta": answer,
                        },
                    },
                    {
                        "method": "item/completed",
                        "params": {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "item": {
                                "id": f"msg-{self.turn_number}",
                                "type": "agentMessage",
                                "text": answer,
                            },
                        },
                    },
                    {
                        "method": "turn/completed",
                        "params": {
                            "threadId": thread_id,
                            "turn": {
                                "id": turn_id,
                                "status": "completed",
                                "items": [
                                    {
                                        "id": f"msg-{self.turn_number}",
                                        "type": "agentMessage",
                                        "text": answer,
                                    }
                                ],
                            },
                        },
                    },
                )
            )
            return {"turn": {"id": turn_id, "status": "inProgress", "items": []}}
        if method == "turn/interrupt":
            return {}
        raise AssertionError(f"unexpected app-server method: {method}")

    def next_message(self, *, timeout: float) -> Mapping[str, Any] | None:
        del timeout
        return self.messages.popleft() if self.messages else None

    def respond(
        self,
        request_id: str | int,
        *,
        result: Mapping[str, Any] | None = None,
        error: Mapping[str, Any] | None = None,
    ) -> None:
        self.recorder.append(
            ("response", {"id": request_id, "result": result, "error": error})
        )

    def close(self) -> None:
        self._alive = False


def test_turn_plan_update_is_normalized_for_workbench_rendering():
    event, text = _normalize_notification(
        "turn/plan/updated",
        {
            "turnId": "turn-1",
            "plan": [
                {"step": "Inspect stream", "status": "completed"},
                {"step": "Render tools", "status": "inProgress"},
            ],
        },
    )

    assert text is None
    assert event is not None
    assert event.type == "plan_updated"
    assert event.payload == {
        "tool_call_id": "plan:turn-1",
        "name": "update_plan",
        "status": "running",
        "arguments": {
            "plan": [
                {"step": "Inspect stream", "status": "completed"},
                {"step": "Render tools", "status": "in_progress"},
            ]
        },
    }


def test_reasoning_usage_and_tool_result_are_normalized_for_workbench():
    reasoning, _ = _normalize_notification(
        "item/reasoning/summaryTextDelta",
        {"delta": "Inspecting files", "itemId": "reason-1"},
    )
    usage, _ = _normalize_notification(
        "thread/tokenUsage/updated",
        {
            "tokenUsage": {
                "last": {
                    "inputTokens": 21,
                    "outputTokens": 8,
                    "totalTokens": 29,
                    "cachedInputTokens": 3,
                },
                "total": {
                    "inputTokens": 100,
                    "outputTokens": 50,
                    "totalTokens": 150,
                    "cachedInputTokens": 20,
                },
            }
        },
    )
    tool, _ = _normalize_notification(
        "item/completed",
        {
            "item": {
                "id": "tool-1",
                "type": "commandExecution",
                "command": "pwd",
                "cwd": "/workspace",
                "status": "completed",
                "aggregatedOutput": "/workspace\n",
            }
        },
    )
    failed_tool, _ = _normalize_notification(
        "item/completed",
        {
            "item": {
                "id": "tool-2",
                "type": "commandExecution",
                "command": "ls missing",
                "cwd": "/workspace",
                "status": "failed",
                "exitCode": 2,
                "stderr": "No such file or directory",
            }
        },
    )

    assert reasoning is not None
    assert reasoning.type == "reasoning_delta"
    assert reasoning.payload == {
        "delta": "Inspecting files",
        "item_id": "reason-1",
        "kind": "summary",
    }
    assert usage is not None
    assert usage.type == "usage"
    assert usage.payload == {
        "input_tokens": 21,
        "output_tokens": 8,
        "total_tokens": 29,
        "cached_input_tokens": 3,
    }
    assert tool is not None
    assert tool.payload["result"] == "/workspace\n"
    assert failed_tool is not None
    assert failed_tool.payload["status"] == "failed"
    assert failed_tool.payload["result"] == {
        "exitCode": 2,
        "stderr": "No such file or directory",
    }


def test_collab_tool_exposes_subagent_identity_and_prompt():
    event, text = _normalize_notification(
        "item/completed",
        {
            "item": {
                "id": "spawn-1",
                "type": "collabToolCall",
                "tool": "spawnAgent",
                "status": "completed",
                "prompt": "Inspect the repository configuration",
                "receiverThreadIds": ["thread-child"],
                "subagents": [
                    {
                        "id": "thread-child",
                        "name": "Hypatia",
                        "role": "explorer",
                        "status": "completed",
                    }
                ],
            }
        },
    )

    assert text is None
    assert event is not None
    assert event.type == "tool_call_finished"
    assert event.payload["name"] == "spawn_agent"
    assert event.payload["arguments"] == {
        "prompt": "Inspect the repository configuration",
        "subagents": [
            {
                "id": "thread-child",
                "name": "Hypatia",
                "role": "explorer",
                "status": "completed",
            }
        ],
    }


def test_collab_child_tools_are_nested_under_spawn_call():
    events = _collab_child_tool_events(
        (
            {
                "id": "thread-child",
                "name": "Hypatia",
                "role": "explorer",
                "prompt": "Inspect the repository configuration",
                "turns": [
                    {
                        "items": [
                            {
                                "id": "command-1",
                                "type": "commandExecution",
                                "command": "rg --files",
                                "cwd": "/workspace",
                                "status": "completed",
                                "aggregatedOutput": "pyproject.toml\n",
                            }
                        ]
                    }
                ],
            },
        ),
        subagent_parents={"thread-child": "spawn-1"},
        seen=set(),
    )

    assert len(events) == 1
    assert events[0].type == "tool_call_finished"
    assert events[0].payload == {
        "tool_call_id": "thread-child:command-1",
        "parent_tool_call_id": "spawn-1",
        "name": "shell",
        "status": "completed",
        "arguments": {"command": "rg --files", "cwd": "/workspace"},
        "source": "codex-app-server-subagent",
        "subagent_id": "thread-child",
        "subagent_name": "Hypatia",
        "subagent_role": "explorer",
        "subagent_description": "Inspect the repository configuration",
        "result": "pyproject.toml\n",
    }


class _ApprovalAppServerClient(_FakeAppServerClient):
    def request(
        self, method: str, params: Mapping[str, Any], *, timeout: float
    ) -> Mapping[str, Any]:
        result = super().request(method, params, timeout=timeout)
        if method == "turn/start":
            self.messages.appendleft(
                {
                    "id": "approval-1",
                    "method": "item/commandExecution/requestApproval",
                    "params": {
                        "threadId": params["threadId"],
                        "turnId": result["turn"]["id"],
                        "command": "dangerous",
                    },
                }
            )
        return result


class _CollabAppServerClient(_FakeAppServerClient):
    def request(
        self, method: str, params: Mapping[str, Any], *, timeout: float
    ) -> Mapping[str, Any]:
        if method == "thread/read" and params.get("threadId") == "thread-child":
            self.recorder.append((method, dict(params)))
            return {
                "thread": {
                    "id": "thread-child",
                    "agentNickname": "Hypatia",
                    "agentRole": "explorer",
                    "status": {"type": "idle"},
                    "turns": [
                        {
                            "items": [
                                {
                                    "id": "child-command",
                                    "type": "commandExecution",
                                    "command": "rg --files",
                                    "cwd": "/workspace",
                                    "status": "completed",
                                    "aggregatedOutput": "pyproject.toml\n",
                                }
                            ]
                        }
                    ],
                }
            }
        result = super().request(method, params, timeout=timeout)
        if method == "turn/start":
            completed = self.messages.pop()
            thread_id = str(params["threadId"])
            turn_id = str(result["turn"]["id"])
            shared = {
                "threadId": thread_id,
                "turnId": turn_id,
                "item": {
                    "status": "completed",
                    "receiverThreadIds": ["thread-child"],
                    "agentsStates": {
                        "thread-child": {
                            "status": "completed",
                            "message": "Repository inspected",
                        }
                    },
                },
            }
            self.messages.extend(
                (
                    {
                        "method": "item/completed",
                        "params": {
                            **shared,
                            "item": {
                                **shared["item"],
                                "id": "spawn-1",
                                "type": "collabToolCall",
                                "tool": "spawnAgent",
                                "prompt": "Inspect repository configuration",
                            },
                        },
                    },
                    {
                        "method": "item/completed",
                        "params": {
                            **shared,
                            "item": {
                                **shared["item"],
                                "id": "wait-1",
                                "type": "collabToolCall",
                                "tool": "wait",
                            },
                        },
                    },
                    completed,
                )
            )
        return result


class _RolloutFunctionCallAppServerClient(_FakeAppServerClient):
    def __init__(self, **kwargs) -> None:
        self.home = Path(kwargs["env"]["CODEX_HOME"])
        self.rollout_path = self.home / "sessions" / "parent.jsonl"
        super().__init__(**kwargs)

    def request(
        self, method: str, params: Mapping[str, Any], *, timeout: float
    ) -> Mapping[str, Any]:
        if method == "thread/read" and params.get("threadId") == "thread-1":
            self.recorder.append((method, dict(params)))
            return {
                "thread": {
                    "id": "thread-1",
                    "path": str(self.rollout_path),
                    "turns": [],
                }
            }
        if method == "thread/read" and params.get("threadId") == "thread-child":
            self.recorder.append((method, dict(params)))
            return {
                "thread": {
                    "id": "thread-child",
                    "agentNickname": "Hilbert",
                    "status": {"type": "notLoaded"},
                    "turns": [
                        {
                            "status": "completed",
                            "items": [
                                {
                                    "id": "child-command",
                                    "type": "commandExecution",
                                    "command": "rg --files",
                                    "cwd": "/workspace",
                                    "status": "completed",
                                    "aggregatedOutput": "pyproject.toml\n",
                                }
                            ],
                        }
                    ],
                }
            }
        result = super().request(method, params, timeout=timeout)
        if method == "turn/start":
            turn_id = str(result["turn"]["id"])
            records = (
                {
                    "type": "event_msg",
                    "payload": {"type": "task_started", "turn_id": turn_id},
                },
                {
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "id": "fc-spawn",
                        "name": "spawn_agent",
                        "namespace": "multi_agent_v1",
                        "arguments": json.dumps(
                            {"message": "Inspect repository configuration"}
                        ),
                        "call_id": "call-spawn",
                        "internal_chat_message_metadata_passthrough": {
                            "turn_id": turn_id
                        },
                    },
                },
                {
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-spawn",
                        "output": json.dumps(
                            {"agent_id": "thread-child", "nickname": "Hilbert"}
                        ),
                        "internal_chat_message_metadata_passthrough": {
                            "turn_id": turn_id
                        },
                    },
                },
            )
            self.rollout_path.parent.mkdir(parents=True, exist_ok=True)
            self.rollout_path.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
        return result


@dataclass
class _Factory:
    recorder: list[tuple[str, dict[str, Any]]]
    clients: list[_FakeAppServerClient]

    def __call__(self, **kwargs) -> _FakeAppServerClient:
        client = _FakeAppServerClient(recorder=self.recorder, **kwargs)
        self.clients.append(client)
        return client


def test_two_prompts_share_one_app_server_thread_and_process(tmp_path):
    recorder: list[tuple[str, dict[str, Any]]] = []
    factory = _Factory(recorder, [])
    supervisor = CodexAppServerSupervisor(tmp_path, client_factory=factory)
    context = HarnessContext(
        proxy_url="http://127.0.0.1:8090",
        api_key="test-key",
        data_dir=str(tmp_path),
    )
    request = _request(tmp_path, session_id="sess-1")
    snapshot = build_execution_snapshot(request, managed_home_id="apphome-test")

    first = supervisor.run_turn(
        request,
        context,
        resolution=_resolution(),
        prompt="first prompt",
        continuation=_continuation(snapshot, prompt_id="msg-1"),
    )
    second = supervisor.run_turn(
        request,
        context,
        resolution=_resolution(),
        prompt="second prompt",
        continuation=_continuation(snapshot, prompt_id="msg-2", action="continue"),
    )

    assert first.ok is True
    assert second.ok is True
    assert first.text == "answer 1"
    assert second.text == "answer 2"
    assert [event.type for event in first.events] == [
        "tool_call_started",
        "tool_call_finished",
        "message_delta",
        "external_turn_completed",
    ]
    assert len(factory.clients) == 1
    assert [method for method, _params in recorder] == [
        "thread/start",
        "turn/start",
        "thread/read",
        "turn/start",
        "thread/read",
    ]
    turn_starts = [params for method, params in recorder if method == "turn/start"]
    assert [params["threadId"] for params in turn_starts] == [
        "thread-1",
        "thread-1",
    ]
    assert [params["clientUserMessageId"] for params in turn_starts] == [
        "msg-1",
        "msg-2",
    ]
    assert all(
        "first prompt" not in item.read_text(encoding="utf-8")
        for item in tmp_path.rglob("*.json")
    )


def test_app_server_uses_generic_driver_and_private_structured_link(tmp_path):
    recorder: list[tuple[str, dict[str, Any]]] = []
    supervisor = CodexAppServerSupervisor(
        tmp_path,
        client_factory=_Factory(recorder, []),
    )
    request = replace(_request(tmp_path, session_id="sess-generic"), run_id="run-1")
    context = HarnessContext(
        proxy_url="http://127.0.0.1:8090",
        api_key="test-key",
        data_dir=str(tmp_path),
    )
    snapshot = build_execution_snapshot(request, managed_home_id="apphome-test")
    continuation = _continuation(snapshot, prompt_id="msg-generic")
    continuation["cli_version"] = "0.144.5"

    result = supervisor.run_turn(
        request,
        context,
        resolution=_resolution(),
        prompt="generic driver prompt",
        continuation=continuation,
    )

    assert result.ok is True
    assert result.raw["structured_session_driver"] == "codex-app-server"
    link = structured_session_link_from_dict(result.raw["structured_session_link"])
    assert link.harness_session_id == "sess-generic"
    assert link.harness_run_id == "run-1"
    assert link.external_session_id == "thread-1"
    assert link.latest_external_turn_id == "turn-1"
    assert link.execution_snapshot.transport.value == "native_structured"
    assert link.execution_snapshot.runtime_ownership.value == "durable"
    assert link.config_snapshot.protocol == "codex-app-server-json-rpc-v2"
    assert link.config_snapshot.cli_sdk_version == "0.144.5"
    assert link.capability_snapshot.resume is True
    assert link.capability_snapshot.live_approvals is False
    stored = StructuredSessionLinkStore(tmp_path).load(
        _structured_link_id("sess-generic")
    )
    assert stored == link
    link_path = next((tmp_path / "structured_sessions" / "links").glob("*.json"))
    assert stat.S_IMODE(link_path.stat().st_mode) == 0o600
    assert "generic driver prompt" not in link_path.read_text(encoding="utf-8")


def test_existing_app_server_link_migrates_without_history_replay(tmp_path):
    recorder: list[tuple[str, dict[str, Any]]] = []
    supervisor = CodexAppServerSupervisor(
        tmp_path,
        client_factory=_Factory(recorder, []),
    )
    request = _request(tmp_path, session_id="sess-legacy")
    context = HarnessContext(
        proxy_url="http://127.0.0.1:8090",
        api_key="test-key",
        data_dir=str(tmp_path),
    )
    snapshot = build_execution_snapshot(request, managed_home_id="apphome-test")
    supervisor.link_store.save(
        "sess-legacy",
        {
            "schema_version": 1,
            "protocol": "codex-app-server-json-rpc-v2",
            "runtime_id": "old-runtime",
            "thread_id": "thread-legacy",
            "latest_turn_id": "turn-old",
            "forked_from_thread_id": None,
            "snapshot": snapshot,
            "snapshot_hash": snapshot["snapshot_hash"],
            "runtime_status": "loaded",
            "recovery_outcome": "not_required",
            "created_at": "2026-07-17T00:00:00+00:00",
            "resumed_at": None,
            "updated_at": "2026-07-17T00:00:00+00:00",
            "last_prompt_id": "msg-old",
            "last_prompt_status": "completed",
        },
    )

    result = supervisor.run_turn(
        request,
        context,
        resolution=_resolution(),
        prompt="new prompt only",
        continuation=_continuation(
            snapshot,
            prompt_id="msg-new",
            action="continue",
        ),
    )

    assert result.ok is True
    methods = [method for method, _params in recorder]
    assert methods[:3] == ["thread/read", "thread/resume", "turn/start"]
    assert "thread/start" not in methods
    turn_start = next(params for method, params in recorder if method == "turn/start")
    assert turn_start["threadId"] == "thread-legacy"
    assert turn_start["input"] == [{"type": "text", "text": "new prompt only"}]
    assert "old" not in str(turn_start["input"])
    migrated = structured_session_link_from_dict(result.raw["structured_session_link"])
    assert migrated.external_session_id == "thread-legacy"
    assert migrated.latest_external_turn_id == "turn-1"
    assert result.raw["app_server_thread"]["recovery_outcome"] == (
        "resumed_after_owner_change"
    )


def test_structured_snapshot_hashes_workspace_without_persisting_path(tmp_path):
    source = tmp_path / "source"
    worktree = tmp_path / "private-worktree"
    request = replace(
        _request(tmp_path, session_id="sess-worktree"),
        workspace=str(worktree),
        extra={"workspace_execution": {"source_workspace": str(source)}},
    )
    legacy = build_execution_snapshot(request, managed_home_id="apphome-test")

    snapshot = build_structured_execution_snapshot(
        legacy,
        adapter_version="0.144.5",
    )

    serialized = json.dumps(snapshot, default=str)
    assert snapshot.workspace_id.startswith("workspace-")
    assert snapshot.worktree_id is not None
    assert str(source) not in serialized
    assert str(worktree) not in serialized


def test_driver_version_change_fails_before_provider_protocol_request(tmp_path):
    first_recorder: list[tuple[str, dict[str, Any]]] = []
    request = _request(tmp_path, session_id="sess-version")
    context = HarnessContext(
        proxy_url="http://127.0.0.1:8090",
        api_key="test-key",
        data_dir=str(tmp_path),
    )
    snapshot = build_execution_snapshot(request, managed_home_id="apphome-test")
    first_continuation = _continuation(snapshot, prompt_id="msg-1")
    first_continuation["cli_version"] = "0.144.5"
    first = CodexAppServerSupervisor(
        tmp_path,
        client_factory=_Factory(first_recorder, []),
    )
    assert first.run_turn(
        request,
        context,
        resolution=_resolution(),
        prompt="first",
        continuation=first_continuation,
    ).ok

    second_recorder: list[tuple[str, dict[str, Any]]] = []
    second_continuation = _continuation(
        snapshot,
        prompt_id="msg-2",
        action="continue",
    )
    second_continuation["cli_version"] = "0.145.0"
    second = CodexAppServerSupervisor(
        tmp_path,
        client_factory=_Factory(second_recorder, []),
    ).run_turn(
        request,
        context,
        resolution=_resolution(),
        prompt="second",
        continuation=second_continuation,
    )

    assert second.ok is False
    assert "snapshot changed" in str(second.error).lower()
    assert second_recorder == []
    assert second.raw["app_server_thread"]["runtime_status"] == "loaded"


def test_app_server_projects_named_subagent_with_nested_tools(tmp_path):
    recorder: list[tuple[str, dict[str, Any]]] = []
    supervisor = CodexAppServerSupervisor(
        tmp_path,
        client_factory=lambda **kwargs: _CollabAppServerClient(
            recorder=recorder, **kwargs
        ),
    )
    context = HarnessContext(
        proxy_url="http://127.0.0.1:8090",
        api_key="test-key",
        data_dir=str(tmp_path),
    )
    request = _request(tmp_path, session_id="sess-collab")
    snapshot = build_execution_snapshot(request, managed_home_id="apphome-test")

    result = supervisor.run_turn(
        request,
        context,
        resolution=_resolution(),
        prompt="delegate",
        continuation=_continuation(snapshot, prompt_id="msg-collab"),
    )

    assert result.ok is True
    spawn = next(
        event
        for event in result.events
        if event.payload.get("tool_call_id") == "spawn-1"
    )
    child = next(
        event
        for event in result.events
        if event.payload.get("tool_call_id") == "thread-child:child-command"
    )
    assert spawn.payload["arguments"]["subagents"][0] == {
        "id": "thread-child",
        "name": "Hypatia",
        "role": "explorer",
        "status": "completed",
        "message": "Repository inspected",
        "prompt": "Inspect repository configuration",
    }
    assert child.payload["parent_tool_call_id"] == "spawn-1"
    assert child.payload["subagent_name"] == "Hypatia"


def test_app_server_backfills_rollout_function_calls_omitted_from_thread_items(
    tmp_path,
):
    recorder: list[tuple[str, dict[str, Any]]] = []
    supervisor = CodexAppServerSupervisor(
        tmp_path,
        client_factory=lambda **kwargs: _RolloutFunctionCallAppServerClient(
            recorder=recorder, **kwargs
        ),
    )
    context = HarnessContext(
        proxy_url="http://127.0.0.1:8090",
        api_key="test-key",
        data_dir=str(tmp_path),
    )
    request = _request(tmp_path, session_id="sess-rollout-collab")
    snapshot = build_execution_snapshot(request, managed_home_id="apphome-test")

    result = supervisor.run_turn(
        request,
        context,
        resolution=_resolution(),
        prompt="delegate",
        continuation=_continuation(snapshot, prompt_id="msg-rollout-collab"),
    )

    assert result.ok is True
    spawn = next(
        event
        for event in result.events
        if event.payload.get("tool_call_id") == "call-spawn"
    )
    child = next(
        event
        for event in result.events
        if event.payload.get("tool_call_id") == "thread-child:child-command"
    )
    assert spawn.type == "tool_call_finished"
    assert spawn.payload["name"] == "spawn_agent"
    assert spawn.payload["source"] == "codex-app-server-rollout"
    assert spawn.payload["arguments"]["prompt"] == ("Inspect repository configuration")
    assert spawn.payload["arguments"]["subagents"] == [
        {
            "id": "thread-child",
            "name": "Hilbert",
            "status": "completed",
            "prompt": "Inspect repository configuration",
        }
    ]
    assert child.payload["parent_tool_call_id"] == "call-spawn"
    assert child.payload["subagent_name"] == "Hilbert"


def test_owner_change_reads_and_resumes_persisted_thread(tmp_path):
    first_recorder: list[tuple[str, dict[str, Any]]] = []
    context = HarnessContext(
        proxy_url="http://127.0.0.1:8090",
        api_key="test-key",
        data_dir=str(tmp_path),
    )
    request = _request(tmp_path, session_id="sess-recover")
    snapshot = build_execution_snapshot(request, managed_home_id="apphome-test")
    first = CodexAppServerSupervisor(
        tmp_path,
        client_factory=_Factory(first_recorder, []),
    )
    assert first.run_turn(
        request,
        context,
        resolution=_resolution(),
        prompt="first",
        continuation=_continuation(snapshot, prompt_id="msg-1"),
    ).ok

    recovered_recorder: list[tuple[str, dict[str, Any]]] = []
    recovered = CodexAppServerSupervisor(
        tmp_path,
        client_factory=_Factory(recovered_recorder, []),
    )
    result = recovered.run_turn(
        request,
        context,
        resolution=_resolution(),
        prompt="continue",
        continuation=_continuation(snapshot, prompt_id="msg-2", action="continue"),
    )

    assert result.ok is True
    assert [method for method, _params in recovered_recorder] == [
        "thread/read",
        "thread/resume",
        "turn/start",
        "thread/read",
    ]
    resume_params = next(
        params for method, params in recovered_recorder if method == "thread/resume"
    )
    assert "excludeTurns" not in resume_params
    link = result.raw["app_server_thread"]
    assert link["thread_id"] == "thread-1"
    assert link["recovery_outcome"] == "resumed_after_owner_change"


def test_fork_uses_thread_fork_and_duplicate_prompt_is_rejected(tmp_path):
    recorder: list[tuple[str, dict[str, Any]]] = []
    supervisor = CodexAppServerSupervisor(
        tmp_path,
        client_factory=_Factory(recorder, []),
    )
    context = HarnessContext(
        proxy_url="http://127.0.0.1:8090",
        api_key="test-key",
        data_dir=str(tmp_path),
    )
    request = _request(tmp_path, session_id="sess-fork")
    snapshot = build_execution_snapshot(request, managed_home_id="apphome-test")
    continuation = _continuation(snapshot, prompt_id="msg-fork", action="fork")
    continuation["fork_thread_id"] = "thread-source"
    continuation["fork_turn_id"] = "turn-source"

    first = supervisor.run_turn(
        request,
        context,
        resolution=_resolution(),
        prompt="fork prompt",
        continuation=continuation,
    )
    duplicate = supervisor.run_turn(
        request,
        context,
        resolution=_resolution(),
        prompt="fork prompt",
        continuation=continuation,
    )

    assert first.ok is True
    assert first.raw["app_server_thread"]["forked_from_thread_id"] == "thread-source"
    assert duplicate.ok is False
    assert "already submitted" in str(duplicate.error)
    fork_params = next(params for method, params in recorder if method == "thread/fork")
    assert "excludeTurns" not in fork_params
    assert [method for method, _params in recorder].count("thread/fork") == 1
    assert [method for method, _params in recorder].count("turn/start") == 1


def test_cancel_event_maps_to_turn_interrupt(tmp_path):
    recorder: list[tuple[str, dict[str, Any]]] = []
    supervisor = CodexAppServerSupervisor(
        tmp_path,
        client_factory=_Factory(recorder, []),
    )
    context = HarnessContext(
        proxy_url="http://127.0.0.1:8090",
        api_key="test-key",
        data_dir=str(tmp_path),
    )
    cancel_event = threading.Event()
    cancel_event.set()
    request = replace(
        _request(tmp_path, session_id="sess-cancel"),
        cancel_event=cancel_event,
    )
    snapshot = build_execution_snapshot(request, managed_home_id="apphome-test")

    result = supervisor.run_turn(
        request,
        context,
        resolution=_resolution(),
        prompt="cancel me",
        continuation=_continuation(snapshot, prompt_id="msg-cancel"),
    )

    assert result.ok is True
    assert [method for method, _params in recorder].count("turn/interrupt") == 1


def test_unexpected_app_server_approval_is_declined_fail_closed(tmp_path):
    recorder: list[tuple[str, dict[str, Any]]] = []

    def factory(**kwargs):
        return _ApprovalAppServerClient(recorder=recorder, **kwargs)

    supervisor = CodexAppServerSupervisor(tmp_path, client_factory=factory)
    context = HarnessContext(
        proxy_url="http://127.0.0.1:8090",
        api_key="test-key",
        data_dir=str(tmp_path),
    )
    request = _request(tmp_path, session_id="sess-approval")
    snapshot = build_execution_snapshot(request, managed_home_id="apphome-test")

    result = supervisor.run_turn(
        request,
        context,
        resolution=_resolution(),
        prompt="approval",
        continuation=_continuation(snapshot, prompt_id="msg-approval"),
    )

    response = next(params for method, params in recorder if method == "response")
    assert response["id"] == "approval-1"
    assert response["result"] == {"decision": "decline"}
    warning = next(event for event in result.events if event.type == "warning")
    assert warning.payload == {
        "method": "item/commandExecution/requestApproval",
        "enforcement": "fail_closed",
    }


def _request(tmp_path, *, session_id: str) -> HarnessRequest:
    return HarnessRequest(
        prompt="prompt",
        model="GigaChat-2-Max",
        api_mode=GigaChatApiMode.V2,
        mode="plan",
        workspace=str(tmp_path),
        session_id=session_id,
        stream=True,
        extra={"workspace_execution": {"source_workspace": str(tmp_path)}},
    )


def _resolution() -> ExecutableResolution:
    return ExecutableResolution(
        harness_id="codex-cli",
        command_name="codex",
        executable="/fake/codex",
        source="test",
        argv=("/fake/codex",),
    )


def _continuation(
    snapshot: Mapping[str, Any],
    *,
    prompt_id: str,
    action: str = "start",
) -> dict[str, Any]:
    return {
        "strategy": "structured_thread",
        "action": action,
        "prompt_id": prompt_id,
        "snapshot": dict(snapshot),
    }
