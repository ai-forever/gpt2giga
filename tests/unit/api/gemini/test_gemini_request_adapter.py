from gpt2giga.api.gemini.request_adapter import (
    build_batch_embeddings_request,
    build_count_tokens_texts,
    build_normalized_chat_request,
    build_single_embeddings_request,
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
