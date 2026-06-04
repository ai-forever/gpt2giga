from types import SimpleNamespace

import pytest
from gigachat.models import ChatCompletionRequest
from loguru import logger

from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer


@pytest.mark.asyncio
async def test_prepare_chat_completion_v2_builds_primary_request():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion_v2(
        {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "hello"}],
            "max_completion_tokens": 64,
            "temperature": 0.4,
            "top_p": 0.8,
            "stream": True,
        }
    )

    assert isinstance(request, ChatCompletionRequest)
    assert request.model == "GigaChat-2-Max"
    assert request.stream is True
    assert request.messages[0].role == "user"
    assert request.messages[0].content[0].text == "hello"
    assert request.model_options.max_tokens == 64
    assert request.model_options.temperature == 0.4
    assert request.model_options.top_p == 0.8


@pytest.mark.asyncio
async def test_prepare_chat_completion_v2_maps_tools_and_forced_function_call():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion_v2(
        {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "search"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "description": "Search the web",
                        "parameters": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                        },
                    },
                }
            ],
            "tool_choice": {
                "type": "function",
                "function": {"name": "web_search"},
            },
        }
    )

    spec = request.tools[0].functions.specifications[0]
    assert spec.name == "__gpt2giga_user_search_web"
    assert spec.description == "Search the web"
    assert spec.parameters["properties"]["query"]["type"] == "string"
    assert request.tool_config.mode == "function"
    assert request.tool_config.function_name == "__gpt2giga_user_search_web"


@pytest.mark.asyncio
async def test_prepare_chat_completion_v2_maps_native_structured_output_and_reasoning():
    cfg = ProxyConfig(
        proxy=ProxySettings(
            enable_reasoning=True,
            structured_output_mode="native",
        )
    )
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion_v2(
        {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "return json"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "Output",
                    "schema": {"type": "object"},
                    "strict": True,
                },
            },
        }
    )

    assert request.model_options.reasoning.effort == "high"
    assert request.model_options.response_format.type == "json_schema"
    assert request.model_options.response_format.schema_ == {"type": "object"}
    assert request.model_options.response_format.strict is True
    assert request.tools is None


@pytest.mark.asyncio
async def test_prepare_response_v2_builds_primary_request_from_responses_input():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_response_v2(
        {
            "model": "GigaChat-2-Max",
            "instructions": "be concise",
            "input": "hello",
            "max_output_tokens": 32,
        }
    )

    assert request.model == "GigaChat-2-Max"
    assert [message.role for message in request.messages] == ["system", "user"]
    assert request.messages[0].content[0].text == "be concise"
    assert request.messages[1].content[0].text == "hello"
    assert request.model_options.max_tokens == 32


@pytest.mark.asyncio
async def test_prepare_response_v2_maps_function_call_output():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_response_v2(
        {
            "model": "GigaChat-2-Max",
            "input": [
                {"type": "function_call", "name": "sum", "arguments": '{"a": 1}'},
                {
                    "type": "function_call_output",
                    "name": "sum",
                    "output": {"result": 2},
                },
            ],
        }
    )

    assert request.messages[0].role == "assistant"
    assert request.messages[0].function_call.name == "sum"
    assert request.messages[0].function_call.arguments == {"a": 1}
    assert request.messages[1].role == "function"
    result = request.messages[1].content[0].function_result
    assert result.name == "sum"
    assert result.result == {"result": 2}


@pytest.mark.asyncio
async def test_prepare_chat_completion_v2_maps_additional_fields():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion_v2(
        {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "hello"}],
            "extra_body": {
                "flags": ["beta"],
                "repetition_penalty": 1.2,
                "custom_flag": "on",
            },
        }
    )

    assert request.flags == ["beta"]
    assert request.model_options.repetition_penalty == 1.2
    assert request.model_extra["custom_flag"] == "on"


@pytest.mark.asyncio
async def test_prepare_chat_completion_v2_reuses_attachment_uploads():
    class AttachmentProcessor:
        async def upload_file_with_meta(self, *_args, **_kwargs):
            return SimpleNamespace(
                file_id="file_1",
                file_kind="image",
                file_size_bytes=1,
            )

    cfg = ProxyConfig()
    cfg.proxy_settings.enable_images = True
    rt = RequestTransformer(
        cfg,
        logger=logger,
        attachment_processor=AttachmentProcessor(),
    )

    request = await rt.prepare_chat_completion_v2(
        {
            "model": "GigaChat-2-Max",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "look"},
                        {"type": "image_url", "image_url": {"url": "data:image/png"}},
                    ],
                }
            ],
        },
        giga_client=object(),
    )

    content = request.messages[0].content
    assert content[0].text == "look"
    assert content[1].files[0].id_ == "file_1"
