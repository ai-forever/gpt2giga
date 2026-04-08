import json
from types import SimpleNamespace

import pytest
from loguru import logger

from gpt2giga.models.config import ProxyConfig
from gpt2giga.protocol import RequestTransformer
from gpt2giga.protocol.batches import (
    _resolve_batch_model,
    get_batch_target,
    transform_batch_input_file,
)


@pytest.mark.asyncio
async def test_transform_batch_input_file_keeps_request_model_when_pass_model_false():
    transformer = RequestTransformer(ProxyConfig(), logger=logger)
    giga_client = SimpleNamespace(_settings=SimpleNamespace(model=None))
    content = b'{"custom_id":"req-1","method":"POST","url":"/v1/chat/completions","body":{"model":"GigaChat-2-Pro","messages":[{"role":"user","content":"hello"}]}}\n'

    result = await transform_batch_input_file(
        content,
        target=get_batch_target("/v1/chat/completions"),
        request_transformer=transformer,
        giga_client=giga_client,
        embeddings_model="EmbeddingsGigaR",
    )

    row = json.loads(result.decode("utf-8").strip())
    assert row["body"]["model"] == "GigaChat-2-Pro"


@pytest.mark.asyncio
async def test_transform_batch_input_file_uses_client_default_model_when_missing():
    transformer = RequestTransformer(ProxyConfig(), logger=logger)
    giga_client = SimpleNamespace(_settings=SimpleNamespace(model="GigaChat-2-Max"))
    content = b'{"custom_id":"req-1","method":"POST","url":"/v1/chat/completions","body":{"messages":[{"role":"user","content":"hello"}]}}\n'

    result = await transform_batch_input_file(
        content,
        target=get_batch_target("/v1/chat/completions"),
        request_transformer=transformer,
        giga_client=giga_client,
        embeddings_model="EmbeddingsGigaR",
    )

    row = json.loads(result.decode("utf-8").strip())
    assert row["body"]["model"] == "GigaChat-2-Max"


def test_resolve_batch_model_prefers_request_model():
    giga_client = SimpleNamespace(_settings=SimpleNamespace(model="GigaChat-2-Max"))

    assert (
        _resolve_batch_model({"model": "GigaChat-2-Pro"}, giga_client)
        == "GigaChat-2-Pro"
    )
