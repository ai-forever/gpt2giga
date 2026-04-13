from gpt2giga.api.gemini.request_adapter import (
    build_batch_embeddings_request,
    build_count_tokens_texts,
    build_normalized_chat_request,
    build_single_embeddings_request,
    serialize_normalized_chat_request,
)
from gpt2giga.core.contracts import (
    NormalizedChatRequest,
    NormalizedMessage,
    NormalizedTool,
)


def test_build_normalized_chat_request_converts_contents_tools_and_config():
    request = build_normalized_chat_request(
        {
            "model": "models/gemini-2.5-pro",
            "systemInstruction": {"parts": [{"text": "Be brief"}]},
            "contents": [{"role": "user", "parts": [{"text": "Hello"}]}],
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": "lookup_weather",
                            "description": "Look up weather.",
                            "parameters": {"type": "OBJECT", "properties": {}},
                        }
                    ]
                }
            ],
            "toolConfig": {
                "functionCallingConfig": {
                    "mode": "ANY",
                    "allowedFunctionNames": ["lookup_weather"],
                }
            },
            "generationConfig": {
                "responseJsonSchema": {
                    "type": "OBJECT",
                    "properties": {"answer": {"type": "STRING"}},
                },
                "thinkingConfig": {"thinkingLevel": "MEDIUM"},
                "temperature": 0.3,
            },
        }
    )

    assert request.model == "gemini-2.5-pro"
    assert [message.role for message in request.messages] == ["system", "user"]
    assert request.messages[0].content == "Be brief"
    assert request.messages[1].content == "Hello"
    assert request.tools[0].parameters["type"] == "object"
    assert request.options["temperature"] == 0.3
    assert request.options["reasoning_effort"] == "medium"
    assert request.options["function_call"] == {"name": "lookup_weather"}
    assert request.options["response_format"]["type"] == "json_schema"
    assert len(request.options["functions"]) == 1


def test_build_count_tokens_and_embeddings_requests():
    texts = build_count_tokens_texts(
        {
            "systemInstruction": {"parts": [{"text": "Be brief"}]},
            "contents": [{"role": "user", "parts": [{"text": "Hello"}]}],
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": "lookup_weather",
                            "description": "Look up weather.",
                            "parameters": {"type": "object", "properties": {}},
                        }
                    ]
                }
            ],
        }
    )
    batch_request = build_batch_embeddings_request(
        [
            {
                "model": "models/gemini-embedding-001",
                "content": {"role": "user", "parts": [{"text": "hello"}]},
            },
            {
                "model": "models/gemini-embedding-001",
                "content": {"role": "user", "parts": [{"text": "world"}]},
            },
        ],
        "gemini-embedding-001",
    )
    single_request = build_single_embeddings_request(
        {"content": {"role": "user", "parts": [{"text": "solo"}]}},
        "models/gemini-embedding-001",
    )

    assert "Be brief" in texts
    assert "Hello" in texts
    assert any("lookup_weather" in text for text in texts)
    assert batch_request.model == "gemini-embedding-001"
    assert batch_request.input == ["hello", "world"]
    assert single_request.model == "gemini-embedding-001"
    assert single_request.input == ["solo"]


def test_serialize_normalized_chat_request_builds_gemini_payload():
    payload, warnings = serialize_normalized_chat_request(
        NormalizedChatRequest(
            model="gemini-2.5-pro",
            messages=[
                NormalizedMessage(role="system", content="Be brief"),
                NormalizedMessage(role="user", content="Hello"),
                NormalizedMessage(
                    role="assistant",
                    content="Checking",
                    tool_calls=[
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "lookup_weather",
                                "arguments": '{"city":"Moscow"}',
                            },
                        }
                    ],
                ),
                NormalizedMessage(
                    role="tool",
                    name="lookup_weather",
                    content='{"forecast":"sunny"}',
                ),
            ],
            tools=[
                NormalizedTool(
                    name="lookup_weather",
                    description="Look up weather.",
                    parameters={"type": "object", "properties": {}},
                )
            ],
            options={
                "temperature": 0.2,
                "top_p": 0.7,
                "max_tokens": 256,
                "stop": ["END"],
                "response_format": {"type": "json_object"},
                "reasoning_effort": "high",
                "function_call": {"name": "lookup_weather"},
                "presence_penalty": 1,
            },
        )
    )

    assert payload["model"] == "models/gemini-2.5-pro"
    assert payload["systemInstruction"] == {"parts": [{"text": "Be brief"}]}
    assert payload["contents"][0] == {"role": "user", "parts": [{"text": "Hello"}]}
    assert payload["contents"][1]["role"] == "model"
    assert payload["contents"][1]["parts"][0] == {"text": "Checking"}
    assert payload["contents"][1]["parts"][1]["functionCall"] == {
        "id": "call_1",
        "name": "lookup_weather",
        "args": {"city": "Moscow"},
    }
    assert payload["contents"][2] == {
        "role": "user",
        "parts": [
            {
                "functionResponse": {
                    "name": "lookup_weather",
                    "response": {"forecast": "sunny"},
                }
            }
        ],
    }
    assert payload["generationConfig"] == {
        "temperature": 0.2,
        "topP": 0.7,
        "maxOutputTokens": 256,
        "stopSequences": ["END"],
        "responseMimeType": "application/json",
        "thinkingConfig": {"thinkingLevel": "HIGH"},
    }
    assert payload["toolConfig"] == {
        "functionCallingConfig": {
            "mode": "ANY",
            "allowedFunctionNames": ["lookup_weather"],
        }
    }
    assert payload["tools"][0]["functionDeclarations"][0]["name"] == "lookup_weather"
    assert warnings == [
        "Gemini translation ignored unsupported options: presence_penalty"
    ]
