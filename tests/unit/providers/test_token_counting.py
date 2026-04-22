from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gpt2giga.providers.token_counting import count_input_tokens


class FakeTokenCountAdapter:
    def __init__(self, texts: list[str]):
        self._texts = texts

    def build_normalized_request(self, payload, *, logger=None):
        raise NotImplementedError

    def build_token_count_texts(self, payload):
        return list(self._texts)


@pytest.mark.asyncio
async def test_count_input_tokens_skips_client_when_payload_has_no_countable_text():
    giga_client = SimpleNamespace(atokens_count=AsyncMock())

    total = await count_input_tokens(
        FakeTokenCountAdapter([]),
        {},
        giga_client=giga_client,
        model="gigachat-pro",
    )

    assert total == 0
    giga_client.atokens_count.assert_not_awaited()


@pytest.mark.asyncio
async def test_count_input_tokens_sums_upstream_token_counts():
    giga_client = SimpleNamespace(
        atokens_count=AsyncMock(
            return_value=[
                SimpleNamespace(tokens=2),
                SimpleNamespace(tokens=5),
            ]
        )
    )

    total = await count_input_tokens(
        FakeTokenCountAdapter(["hello", "world"]),
        {"model": "gigachat-pro"},
        giga_client=giga_client,
        model="gigachat-pro",
    )

    assert total == 7
    giga_client.atokens_count.assert_awaited_once_with(
        ["hello", "world"],
        model="gigachat-pro",
    )
