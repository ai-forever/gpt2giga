from types import SimpleNamespace

import pytest
from starlette.datastructures import Headers, QueryParams

from gpt2giga.common.conversation import (
    MemoryConversationStore,
    commit_anthropic_response,
    commit_chat_completion_response,
    commit_conversation_turn,
    commit_responses_response,
    stitch_anthropic_stream,
    stitch_chat_completion_stream,
    stitch_chat_payload,
    stitch_responses_stream,
)
from gpt2giga.models.config import ProxyConfig, ProxySettings


def make_request(settings: ProxySettings, headers: dict[str, str] | None = None):
    state = SimpleNamespace(
        config=ProxyConfig(proxy=settings),
        conversation_store=MemoryConversationStore(),
    )
    return SimpleNamespace(
        app=SimpleNamespace(state=state),
        headers=Headers(headers or {}),
        query_params=QueryParams(""),
    )


async def test_stitch_chat_payload_uses_overlap_without_duplicates():
    request = make_request(ProxySettings(conversation_stitching_enabled=True))
    first = {
        "conversation": "conv-1",
        "messages": [{"role": "user", "content": "hello"}],
    }

    turn = await stitch_chat_payload(request, first, protocol="openai")
    await commit_conversation_turn(
        request,
        turn,
        [{"role": "assistant", "content": "hi"}],
    )

    second = {
        "conversation": "conv-1",
        "messages": [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "again"},
        ],
    }
    second_turn = await stitch_chat_payload(request, second, protocol="openai")

    assert second["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": "again"},
    ]
    assert second_turn.stitched is False
    assert second_turn.divergent is False


async def test_stitch_chat_payload_forks_on_divergence():
    request = make_request(
        ProxySettings(
            conversation_stitching_enabled=True,
            conversation_on_divergence="fork",
        )
    )
    first = {
        "conversation": "conv-1",
        "messages": [{"role": "user", "content": "hello"}],
    }
    turn = await stitch_chat_payload(request, first, protocol="openai")
    await commit_conversation_turn(
        request,
        turn,
        [{"role": "assistant", "content": "hi"}],
    )

    divergent = {
        "conversation": "conv-1",
        "messages": [
            {"role": "system", "content": "different rules"},
            {"role": "user", "content": "new root"},
        ],
    }
    divergent_turn = await stitch_chat_payload(request, divergent, protocol="openai")

    assert divergent["messages"] == [
        {"role": "system", "content": "different rules"},
        {"role": "user", "content": "new root"},
    ]
    assert divergent_turn.divergent is True
    assert divergent_turn.save_key.conversation_id == "conv-1:fork:2"


async def test_stitch_chat_payload_trims_history_and_keeps_system_message():
    request = make_request(
        ProxySettings(
            conversation_stitching_enabled=True,
            conversation_max_messages=3,
        )
    )
    payload = {
        "conversation": "conv-1",
        "messages": [
            {"role": "system", "content": "rules"},
            {"role": "user", "content": "one"},
        ],
    }
    turn = await stitch_chat_payload(request, payload, protocol="openai")
    await commit_conversation_turn(
        request,
        turn,
        [
            {"role": "assistant", "content": "two"},
            {"role": "user", "content": "three"},
            {"role": "assistant", "content": "four"},
        ],
    )

    record = await request.app.state.conversation_store.get(
        turn.key,
        ttl_seconds=3_600,
    )

    assert record.messages == [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "three"},
        {"role": "assistant", "content": "four"},
    ]


async def test_stitch_chat_payload_uses_session_id_only_when_enabled():
    default_request = make_request(
        ProxySettings(conversation_stitching_enabled=True),
        headers={"x-session-id": "session-1"},
    )
    payload = {"messages": [{"role": "user", "content": "hello"}]}

    assert (
        await stitch_chat_payload(default_request, payload, protocol="openai") is None
    )

    enabled_request = make_request(
        ProxySettings(
            conversation_stitching_enabled=True,
            conversation_use_session_id=True,
        ),
        headers={"x-session-id": "session-1"},
    )
    turn = await stitch_chat_payload(enabled_request, payload, protocol="openai")

    assert turn is not None
    assert turn.key.conversation_id == "session-1"


async def test_disabled_stitching_does_not_copy_chat_messages():
    class CopyTrap:
        def __deepcopy__(self, memo):
            raise AssertionError("disabled stitching must not copy message content")

    request = make_request(ProxySettings(conversation_stitching_enabled=False))
    content = CopyTrap()
    payload = {"messages": [{"role": "user", "content": content}]}

    turn = await stitch_chat_payload(request, payload, protocol="openai")

    assert turn is None
    assert payload["messages"][0]["content"] is content


class UnreadableResponse(dict):
    def get(self, key, default=None):
        raise AssertionError("missing turns must not inspect response payloads")


@pytest.mark.parametrize(
    "commit_response",
    [
        commit_chat_completion_response,
        commit_responses_response,
        commit_anthropic_response,
    ],
)
async def test_response_commit_skips_payload_without_turn(commit_response):
    request = make_request(ProxySettings())

    await commit_response(request, None, UnreadableResponse())


@pytest.mark.parametrize(
    "stitch_stream",
    [
        stitch_chat_completion_stream,
        stitch_responses_stream,
        stitch_anthropic_stream,
    ],
)
async def test_stream_stitching_passes_through_without_turn(stitch_stream):
    class UnparseableChunk:
        def __str__(self):
            raise AssertionError("missing turns must not parse stream chunks")

    chunk = UnparseableChunk()

    async def stream():
        yield chunk

    request = make_request(ProxySettings())
    chunks = [item async for item in stitch_stream(request, None, stream())]

    assert chunks == [chunk]
