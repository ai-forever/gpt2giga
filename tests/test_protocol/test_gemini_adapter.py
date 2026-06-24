import json
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from gpt2giga.core.context import RequestContext
from gpt2giga.protocols.gemini import GeminiProtocolAdapter
from gpt2giga.protocols.gemini.response_adapter import (
    normalized_chat_response_to_gemini,
)
from gpt2giga.protocols.gemini.streaming import (
    normalized_stream_event_to_gemini_chunk,
)
from gpt2giga.protocols.normalized import (
    NormalizedChoice,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedStreamEvent,
    NormalizedToolCall,
    NormalizedUsage,
)


def test_gemini_adapter_maps_generate_content_to_normalized_request():
    adapter = GeminiProtocolAdapter()
    context = RequestContext(
        request_id="req-1",
        trace_id="trace-1",
        span_id=None,
        protocol="gemini",
        route="/v1beta/models/gemini-pro:generateContent",
        method="POST",
        started_at=datetime.now(timezone.utc),
        model_requested="gemini-pro",
    )

    normalized = adapter.generate_content_to_normalized(
        {
            "systemInstruction": {"parts": [{"text": "Be concise."}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": "Describe this image"},
                        {
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": "AA==",
                            }
                        },
                    ],
                }
            ],
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": "lookup",
                            "description": "Lookup data.",
                            "parameters": {
                                "type": "OBJECT",
                                "properties": {
                                    "q": {"type": "STRING"},
                                    "answers": {"type": "OBJECT"},
                                    "limit": {"type": ["INTEGER", "NULL"]},
                                },
                            },
                        }
                    ]
                }
            ],
            "toolConfig": {
                "functionCallingConfig": {
                    "mode": "ANY",
                    "allowedFunctionNames": ["lookup"],
                }
            },
            "generationConfig": {
                "temperature": 0.2,
                "topP": 0.8,
                "maxOutputTokens": 64,
                "stopSequences": ["</done>"],
                "responseMimeType": "application/json",
                "responseSchema": {"type": "object"},
                "topK": 20,
            },
            "safetySettings": [{"category": "HARM_CATEGORY_HARASSMENT"}],
        },
        model="gemini-pro",
        context=context,
    )

    payload = normalized.to_json_dict()

    assert payload["id"] == "req-1"
    assert payload["protocol"] == "gemini"
    assert payload["model"] == "gemini-pro"
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][1]["content"][0]["text"] == "Describe this image"
    assert payload["messages"][1]["content"][1]["type"] == "image_url"
    assert payload["tools"][0]["name"] == "lookup"
    assert payload["tools"][0]["parameters"]["type"] == "object"
    assert payload["tools"][0]["parameters"]["properties"]["q"]["type"] == "string"
    assert payload["tools"][0]["parameters"]["properties"]["answers"] == {
        "type": "object",
        "properties": {},
    }
    assert payload["tools"][0]["parameters"]["properties"]["limit"]["type"] == (
        "integer"
    )
    assert payload["tool_choice"] == {
        "type": "function",
        "function": {"name": "lookup"},
    }
    assert payload["generation_config"]["temperature"] == 0.2
    assert payload["generation_config"]["max_tokens"] == 64
    assert payload["generation_config"]["raw_extensions"]["topK"] == 20
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["raw_extensions"]["safetySettings"][0]["category"] == (
        "HARM_CATEGORY_HARASSMENT"
    )
    json.dumps(payload)


def test_gemini_adapter_maps_response_json_schema_alias_to_json_schema():
    adapter = GeminiProtocolAdapter()

    normalized = adapter.generate_content_to_normalized(
        {
            "contents": [{"parts": [{"text": "Recommend a movie"}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": {
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                    "required": ["title"],
                },
            },
        },
        model="gemini-pro",
    )

    payload = normalized.to_json_dict()

    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"] == {
        "schema": {
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
        }
    }
    assert payload["response_format"]["raw_extensions"] == {
        "responseMimeType": "application/json"
    }
    assert normalized.raw_extensions == {}


@pytest.mark.parametrize(
    "schema_key",
    ["parametersJsonSchema", "parameters_json_schema"],
)
def test_gemini_adapter_maps_function_parameters_json_schema(schema_key):
    adapter = GeminiProtocolAdapter()

    normalized = adapter.generate_content_to_normalized(
        {
            "contents": [{"parts": [{"text": "Read a file"}]}],
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": "read_file",
                            "description": "Read a file.",
                            schema_key: {
                                "type": "object",
                                "properties": {
                                    "path": {"type": "string"},
                                    "start_line": {"type": "integer"},
                                },
                                "required": ["path"],
                            },
                        }
                    ]
                }
            ],
        },
        model="gemini-pro",
    )

    tool = normalized.tools[0]

    assert tool.name == "read_file"
    assert tool.parameters == {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer"},
        },
        "required": ["path"],
    }
    assert schema_key not in tool.raw_extensions


def _gemini_tool_config_payload(
    function_calling_config,
    *,
    declarations=("first", "second"),
):
    return {
        "contents": [{"parts": [{"text": "hello"}]}],
        "tools": [
            {
                "functionDeclarations": [
                    {"name": name, "parameters": {"type": "object"}}
                    for name in declarations
                ]
            }
        ],
        "toolConfig": {"functionCallingConfig": function_calling_config},
    }


@pytest.mark.parametrize(
    ("function_calling_config", "declarations", "expected_tool_choice", "expected"),
    [
        ({"mode": "AUTO"}, ("first", "second"), "auto", ["first", "second"]),
        (
            {"mode": "AUTO", "allowedFunctionNames": ["first"]},
            ("first", "second"),
            "auto",
            ["first"],
        ),
        (
            {"mode": "AUTO", "allowedFunctionNames": ["first", "second"]},
            ("first", "second"),
            "auto",
            ["first", "second"],
        ),
        ({"mode": "NONE"}, ("first", "second"), "none", ["first", "second"]),
        (
            {"mode": "ANY", "allowedFunctionNames": ["first"]},
            ("first", "second"),
            {"type": "function", "function": {"name": "first"}},
            ["first"],
        ),
        (
            {"mode": "ANY"},
            ("first",),
            {"type": "function", "function": {"name": "first"}},
            ["first"],
        ),
        (
            {"allowedFunctionNames": ["second"]},
            ("first", "second"),
            "auto",
            ["second"],
        ),
    ],
)
def test_gemini_adapter_maps_function_calling_config(
    function_calling_config,
    declarations,
    expected_tool_choice,
    expected,
):
    adapter = GeminiProtocolAdapter()

    normalized = adapter.generate_content_to_normalized(
        _gemini_tool_config_payload(
            function_calling_config,
            declarations=declarations,
        ),
        model="gemini-pro",
    )

    assert normalized.tool_choice == expected_tool_choice
    assert [tool.name for tool in normalized.tools] == expected


@pytest.mark.parametrize(
    ("function_calling_config", "declarations", "expected_param"),
    [
        (
            {"mode": "ANY"},
            ("first", "second"),
            "toolConfig.functionCallingConfig.allowedFunctionNames",
        ),
        (
            {"mode": "ANY", "allowedFunctionNames": ["first", "second"]},
            ("first", "second"),
            "toolConfig.functionCallingConfig.allowedFunctionNames",
        ),
        (
            {"mode": "AUTO", "allowedFunctionNames": ["missing"]},
            ("first",),
            "toolConfig.functionCallingConfig.allowedFunctionNames",
        ),
        (
            {"mode": "AUTO", "allowedFunctionNames": []},
            ("first",),
            "toolConfig.functionCallingConfig.allowedFunctionNames",
        ),
        (
            {"mode": "AUTO", "allowedFunctionNames": "first"},
            ("first",),
            "toolConfig.functionCallingConfig.allowedFunctionNames",
        ),
    ],
)
def test_gemini_adapter_rejects_unsupported_function_calling_config(
    function_calling_config,
    declarations,
    expected_param,
):
    adapter = GeminiProtocolAdapter()

    with pytest.raises(HTTPException) as exc_info:
        adapter.generate_content_to_normalized(
            _gemini_tool_config_payload(
                function_calling_config,
                declarations=declarations,
            ),
            model="gemini-pro",
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"]["param"] == expected_param


@pytest.mark.parametrize(
    ("payload", "expected_param"),
    [
        ({}, "contents"),
        ({"contents": "hello"}, "contents"),
        ({"contents": []}, "contents"),
        ({"contents": [{"parts": "bad"}]}, "contents[0].parts"),
        (
            {"contents": [{"parts": [{"unknown": {"value": 1}}]}]},
            "contents[0].parts[0]",
        ),
        ({"contents": [{"parts": [{"text": 123}]}]}, "contents[0].parts[0].text"),
        (
            {"contents": [{"parts": [{"functionCall": {"args": {}}}]}]},
            "contents[0].parts[0].functionCall.name",
        ),
        (
            {
                "contents": [
                    {
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": "lookup",
                                    "response": "bad",
                                }
                            }
                        ]
                    }
                ]
            },
            "contents[0].parts[0].functionResponse.response",
        ),
        (
            {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": "do not drop",
                                "functionResponse": {
                                    "name": "lookup",
                                    "response": {},
                                },
                            }
                        ]
                    }
                ]
            },
            "contents[0].parts[0]",
        ),
        (
            {
                "contents": [{"parts": [{"text": "hello"}]}],
                "generationConfig": "bad",
            },
            "generationConfig",
        ),
        (
            {
                "contents": [{"parts": [{"text": "hello"}]}],
                "generationConfig": {"responseMimeType": "application/xml"},
            },
            "generationConfig.responseMimeType",
        ),
        (
            {
                "contents": [{"parts": [{"text": "hello"}]}],
                "generationConfig": {"responseSchema": {"type": "object"}},
            },
            "generationConfig.responseSchema",
        ),
        (
            {
                "contents": [{"parts": [{"text": "hello"}]}],
                "generationConfig": {"responseMimeType": "application/json"},
            },
            "generationConfig.responseMimeType",
        ),
        (
            {
                "contents": [{"parts": [{"text": "hello"}]}],
                "generationConfig": {
                    "responseJsonSchema": {"type": "object"},
                },
            },
            "generationConfig.responseJsonSchema",
        ),
        (
            {"contents": [{"parts": [{"text": "hello"}]}], "tools": "bad"},
            "tools",
        ),
        (
            {
                "contents": [{"parts": [{"text": "hello"}]}],
                "tools": [
                    {"functionDeclarations": [{"name": "lookup", "parameters": "bad"}]}
                ],
            },
            "tools[0].functionDeclarations[0].parameters",
        ),
        (
            {
                "contents": [{"parts": [{"text": "hello"}]}],
                "tools": [
                    {
                        "functionDeclarations": [
                            {"name": "lookup", "parametersJsonSchema": "bad"}
                        ]
                    }
                ],
            },
            "tools[0].functionDeclarations[0].parametersJsonSchema",
        ),
        (
            {
                "contents": [{"parts": [{"text": "hello"}]}],
                "tools": [
                    {
                        "functionDeclarations": [
                            {
                                "name": "lookup",
                                "parameters": {"type": "object"},
                                "parametersJsonSchema": {"type": "object"},
                            }
                        ]
                    }
                ],
            },
            "tools[0].functionDeclarations[0].parametersJsonSchema",
        ),
        (
            {"contents": [{"parts": [{"text": "hello"}]}], "toolConfig": "bad"},
            "toolConfig",
        ),
    ],
)
def test_gemini_adapter_rejects_invalid_generate_payloads(
    payload,
    expected_param,
):
    adapter = GeminiProtocolAdapter()

    with pytest.raises(HTTPException) as exc_info:
        adapter.generate_content_to_normalized(payload, model="gemini-pro")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"]["param"] == expected_param


def test_gemini_adapter_preserves_ignored_generation_fields_and_unsupported_tools():
    adapter = GeminiProtocolAdapter()

    normalized = adapter.generate_content_to_normalized(
        {
            "contents": [{"parts": [{"text": "hello"}]}],
            "generationConfig": {
                "candidateCount": 2,
                "topK": 40,
                "responseModalities": ["TEXT"],
                "responseMimeType": "text/plain",
            },
            "safetySettings": [{"category": "HARM_CATEGORY_HARASSMENT"}],
            "cachedContent": "cachedContents/1",
            "serviceTier": "flex",
            "tools": [{"googleMaps": {"api_key": "secret-gemini-key"}}],
        },
        model="gemini-pro",
    )

    assert normalized.response_format is None
    assert normalized.generation_config.raw_extensions == {
        "candidateCount": 2,
        "topK": 40,
        "responseModalities": ["TEXT"],
    }
    assert normalized.tools == []
    assert normalized.raw_extensions["safetySettings"] == [
        {"category": "HARM_CATEGORY_HARASSMENT"}
    ]
    assert normalized.raw_extensions["cachedContent"] == "cachedContents/1"
    assert normalized.raw_extensions["serviceTier"] == "flex"
    assert normalized.raw_extensions["unsupportedTools"] == [
        {"googleMaps": {"api_key": "secret-gemini-key"}}
    ]


def test_gemini_adapter_maps_supported_builtin_tools_to_gigachat_tools():
    adapter = GeminiProtocolAdapter()

    normalized = adapter.generate_content_to_normalized(
        {
            "contents": [{"parts": [{"text": "hello"}]}],
            "tools": [
                {"googleSearch": {"indexes": ["web"]}},
                {"urlContext": {"max_uses": 2}, "codeExecution": {}},
                {"googleMaps": {"api_key": "secret-gemini-key"}},
            ],
        },
        model="gemini-pro",
    )

    assert [
        (tool.type, tool.name, tool.raw_extensions) for tool in normalized.tools
    ] == [
        ("web_search", "web_search", {"web_search": {"indexes": ["web"]}}),
        (
            "url_content_extraction",
            "url_content_extraction",
            {"url_content_extraction": {"max_uses": 2}},
        ),
        ("code_interpreter", "code_interpreter", {"code_interpreter": {}}),
    ]
    assert normalized.raw_extensions["unsupportedTools"] == [
        {"googleMaps": {"api_key": "secret-gemini-key"}}
    ]


def test_gemini_adapter_keeps_provider_tools_diagnostics_only_when_mapping_disabled():
    adapter = GeminiProtocolAdapter()

    normalized = adapter.generate_content_to_normalized(
        {
            "contents": [{"parts": [{"text": "hello"}]}],
            "tools": [
                {"googleSearch": {"indexes": ["web"]}},
                {"urlContext": {"max_uses": 2}, "codeExecution": {}},
                {"googleMaps": {"api_key": "secret-gemini-key"}},
            ],
        },
        model="gemini-pro",
        builtin_tool_mapping_enabled=False,
    )

    assert normalized.tools == []
    assert normalized.raw_extensions["unsupportedTools"] == [
        {"googleSearch": {"indexes": ["web"]}},
        {"urlContext": {"max_uses": 2}, "codeExecution": {}},
        {"googleMaps": {"api_key": "secret-gemini-key"}},
    ]


def test_gemini_adapter_function_calling_config_filters_only_function_tools():
    adapter = GeminiProtocolAdapter()

    normalized = adapter.generate_content_to_normalized(
        {
            "contents": [{"parts": [{"text": "hello"}]}],
            "tools": [
                {"googleSearch": {}},
                {
                    "functionDeclarations": [
                        {"name": "lookup", "parameters": {"type": "object"}},
                        {"name": "ignored", "parameters": {"type": "object"}},
                    ]
                },
            ],
            "toolConfig": {
                "functionCallingConfig": {
                    "mode": "ANY",
                    "allowedFunctionNames": ["lookup"],
                }
            },
        },
        model="gemini-pro",
    )

    assert [(tool.type, tool.name) for tool in normalized.tools] == [
        ("web_search", "web_search"),
        ("function", "lookup"),
    ]
    assert normalized.tool_choice == {
        "type": "function",
        "function": {"name": "lookup"},
    }


def test_gemini_adapter_maps_single_function_call_from_model():
    adapter = GeminiProtocolAdapter()

    normalized = adapter.generate_content_to_normalized(
        {
            "contents": [
                {
                    "role": "model",
                    "parts": [
                        {"text": "I need a lookup."},
                        {
                            "functionCall": {
                                "id": "state-1",
                                "name": "lookup",
                                "args": {"q": "ping"},
                            }
                        },
                    ],
                }
            ]
        },
        model="gemini-pro",
    )

    message = normalized.messages[0]
    assert message.role == "assistant"
    assert message.content == "I need a lookup."
    assert len(message.tool_calls) == 1
    assert message.tool_calls[0].id == "state-1"
    assert message.tool_calls[0].name == "lookup"
    assert message.tool_calls[0].arguments == {"q": "ping"}


def test_gemini_adapter_preserves_one_function_response_and_followup():
    adapter = GeminiProtocolAdapter()

    normalized = adapter.generate_content_to_normalized(
        {
            "contents": [
                {
                    "role": "model",
                    "parts": [
                        {
                            "functionCall": {
                                "name": "lookup",
                                "args": {"q": "ping"},
                            }
                        }
                    ],
                },
                {
                    "role": "function",
                    "parts": [
                        {
                            "functionResponse": {
                                "id": "state-1",
                                "name": "lookup",
                                "response": {"answer": "pong"},
                            }
                        }
                    ],
                },
                {"role": "user", "parts": [{"text": "continue"}]},
            ]
        },
        model="gemini-pro",
    )

    assert [message.role for message in normalized.messages] == [
        "assistant",
        "tool",
        "user",
    ]
    assert normalized.messages[0].tool_calls[0].name == "lookup"
    assert normalized.messages[1].name == "lookup"
    assert normalized.messages[1].tool_call_id == "state-1"
    assert json.loads(normalized.messages[1].content) == {"answer": "pong"}
    assert normalized.messages[2].content == "continue"


def test_gemini_adapter_preserves_multiple_function_response_parts():
    adapter = GeminiProtocolAdapter()

    normalized = adapter.generate_content_to_normalized(
        {
            "contents": [
                {
                    "role": "function",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": "first",
                                "response": {"value": 1},
                            }
                        },
                        {
                            "functionResponse": {
                                "name": "second",
                                "response": {"value": 2},
                            }
                        },
                    ],
                }
            ]
        },
        model="gemini-pro",
    )

    assert [message.role for message in normalized.messages] == ["tool", "tool"]
    assert [message.name for message in normalized.messages] == ["first", "second"]
    assert [json.loads(message.content) for message in normalized.messages] == [
        {"value": 1},
        {"value": 2},
    ]
    assert normalized.messages[0].raw_extensions["functionResponse"] == {
        "name": "first",
        "response": {"value": 1},
    }


def test_gemini_adapter_preserves_mixed_text_and_function_response_parts():
    adapter = GeminiProtocolAdapter()

    normalized = adapter.generate_content_to_normalized(
        {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": "before"},
                        {
                            "functionResponse": {
                                "name": "lookup",
                                "response": {"answer": "pong"},
                            }
                        },
                        {"text": "after"},
                    ],
                }
            ]
        },
        model="gemini-pro",
    )

    assert [message.role for message in normalized.messages] == [
        "user",
        "tool",
        "user",
    ]
    assert normalized.messages[0].content == "before"
    assert normalized.messages[1].name == "lookup"
    assert json.loads(normalized.messages[1].content) == {"answer": "pong"}
    assert normalized.messages[2].content == "after"


def test_gemini_adapter_preserves_multiple_function_calls():
    adapter = GeminiProtocolAdapter()

    normalized = adapter.generate_content_to_normalized(
        {
            "contents": [
                {
                    "role": "model",
                    "parts": [
                        {
                            "functionCall": {
                                "name": "first",
                                "args": {"value": 1},
                            }
                        },
                        {
                            "functionCall": {
                                "name": "second",
                                "args": {"value": 2},
                            }
                        },
                    ],
                }
            ]
        },
        model="gemini-pro",
    )

    message = normalized.messages[0]
    assert message.role == "assistant"
    assert message.content is None
    assert [tool_call.name for tool_call in message.tool_calls] == [
        "first",
        "second",
    ]
    assert [tool_call.arguments for tool_call in message.tool_calls] == [
        {"value": 1},
        {"value": 2},
    ]


def test_gemini_adapter_rejects_malformed_function_response():
    adapter = GeminiProtocolAdapter()

    with pytest.raises(HTTPException) as exc_info:
        adapter.generate_content_to_normalized(
            {
                "contents": [
                    {
                        "parts": [
                            {
                                "functionResponse": "not an object",
                            }
                        ],
                    }
                ]
            },
            model="gemini-pro",
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"]["param"] == (
        "contents[0].parts[0].functionResponse"
    )


def test_gemini_response_adapter_maps_normalized_response():
    response = NormalizedResponse(
        id="req-1",
        model="gemini-pro",
        provider="gigachat",
        choices=[
            NormalizedChoice(
                index=0,
                message=NormalizedMessage(
                    role="assistant",
                    content="ok",
                    tool_calls=[
                        NormalizedToolCall(
                            id="state-1",
                            name="lookup",
                            arguments='{"q":"ping"}',
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )
        ],
        usage=NormalizedUsage(input_tokens=2, output_tokens=3, total_tokens=5),
    )

    payload = normalized_chat_response_to_gemini(
        response,
        requested_model="gemini-pro",
    )

    assert payload["responseId"] == "req-1"
    assert payload["usageMetadata"] == {
        "promptTokenCount": 2,
        "candidatesTokenCount": 3,
        "totalTokenCount": 5,
    }
    candidate = payload["candidates"][0]
    assert candidate["content"]["role"] == "model"
    assert candidate["content"]["parts"][0] == {"text": "ok"}
    assert candidate["content"]["parts"][1] == {
        "functionCall": {
            "id": "state-1",
            "name": "lookup",
            "args": {"q": "ping"},
        }
    }
    assert candidate["finishReason"] == "STOP"


def test_gemini_stream_message_end_includes_usage_metadata():
    payload = normalized_stream_event_to_gemini_chunk(
        NormalizedStreamEvent(
            type="message_end",
            id="req-1",
            model="gemini-pro",
            finish_reason="stop",
            usage=NormalizedUsage(input_tokens=2, output_tokens=3, total_tokens=5),
        ),
        requested_model="gemini-pro",
        response_id="fallback",
    )

    assert payload["candidates"][0]["finishReason"] == "STOP"
    assert payload["usageMetadata"] == {
        "promptTokenCount": 2,
        "candidatesTokenCount": 3,
        "totalTokenCount": 5,
    }


def test_gemini_stream_tool_call_includes_state_id():
    payload = normalized_stream_event_to_gemini_chunk(
        NormalizedStreamEvent(
            type="tool_call_start",
            id="req-1",
            model="gemini-pro",
            tool_call=NormalizedToolCall(
                id="state-1",
                name="lookup",
                arguments={"q": "ping"},
            ),
        ),
        requested_model="gemini-pro",
        response_id="fallback",
    )

    assert payload["candidates"][0]["content"]["parts"][0] == {
        "functionCall": {
            "id": "state-1",
            "name": "lookup",
            "args": {"q": "ping"},
        }
    }


def test_gemini_stream_message_end_preserves_final_text_delta():
    payload = normalized_stream_event_to_gemini_chunk(
        NormalizedStreamEvent(
            type="message_end",
            id="req-1",
            model="gemini-pro",
            content_delta="?",
            finish_reason="stop",
            usage=NormalizedUsage(input_tokens=2, output_tokens=3, total_tokens=5),
        ),
        requested_model="gemini-pro",
        response_id="fallback",
    )

    candidate = payload["candidates"][0]
    assert candidate["content"] == {
        "role": "model",
        "parts": [{"text": "?"}],
    }
    assert candidate["finishReason"] == "STOP"
    assert payload["usageMetadata"]["totalTokenCount"] == 5
