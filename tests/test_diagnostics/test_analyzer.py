from types import SimpleNamespace

from gpt2giga.diagnostics import analyze_compatibility_request


def _config(
    *,
    pass_model=True,
    gigachat_model="GigaChat-Pro",
    embeddings="EmbeddingsGigaR",
    gigachat_api_mode="v1",
    disable_builtin_tool_mapping=False,
):
    return SimpleNamespace(
        proxy_settings=SimpleNamespace(
            pass_model=pass_model,
            embeddings=embeddings,
            gigachat_api_mode=gigachat_api_mode,
            disable_builtin_tool_mapping=disable_builtin_tool_mapping,
        ),
        gigachat_settings=SimpleNamespace(model=gigachat_model),
    )


def test_analyze_openai_chat_reports_fields_tools_model_and_redaction():
    analysis = analyze_compatibility_request(
        protocol="openai",
        route="/v2/chat/completions",
        headers={"Authorization": "Bearer secret", "x-request-id": "safe"},
        query={"key": "secret"},
        body={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hidden"}],
            "temperature": 0.2,
            "parallel_tool_calls": False,
            "seed": 123,
            "custom_flag": True,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "search_docs",
                        "parameters": {"type": "object"},
                    },
                },
                {"type": "web_search_preview"},
                {"type": "file_search"},
            ],
        },
        config=_config(pass_model=False),
    )

    assert analysis.backend_mode == "gigachat_v2"
    assert analysis.operation == "chat_completions"
    assert analysis.model.requested == "gpt-4o"
    assert analysis.model.effective == "GigaChat-Pro"
    assert analysis.model.pass_model is False
    assert analysis.model.source == "GIGACHAT_MODEL"
    assert analysis.fields.supported == ["messages", "model", "temperature", "tools"]
    assert analysis.fields.accepted_ignored == ["parallel_tool_calls", "seed"]
    assert analysis.fields.accepted_diagnostic_only == ["custom_flag"]
    assert analysis.tools.user_functions == ["search_docs"]
    assert [item.to_json_dict() for item in analysis.tools.mapped_builtin_tools] == [
        {
            "from": "web_search_preview",
            "to": "web_search",
            "reason": "provider_alias",
        }
    ]
    assert analysis.tools.unsupported_tools == ["file_search"]
    assert analysis.security.headers_redacted == ["authorization"]
    assert analysis.security.query_redacted == ["key"]
    assert {warning.code for warning in analysis.warnings} == {
        "accepted_ignored_field",
        "unsupported_tool",
    }


def test_analyze_gemini_stream_generate_content_reports_tool_aliases():
    analysis = analyze_compatibility_request(
        route="/v1beta/models/gemini-pro:streamGenerateContent?key=secret",
        query={"key": "secret"},
        body={
            "contents": [{"parts": [{"text": "hidden"}]}],
            "generationConfig": {"temperature": 0},
            "safetySettings": [{"category": "HARM_CATEGORY_DANGEROUS_CONTENT"}],
            "toolConfig": {
                "functionCallingConfig": {
                    "mode": "ANY",
                    "allowedFunctionNames": ["search_docs"],
                }
            },
            "tools": [
                {"googleSearch": {}},
                {
                    "functionDeclarations": [
                        {
                            "name": "search_docs",
                            "parametersJsonSchema": {"type": "object"},
                        }
                    ]
                },
                {"fileSearch": {}},
            ],
        },
        config=_config(gigachat_api_mode="v2"),
    )

    assert analysis.protocol == "gemini"
    assert analysis.backend_mode == "gigachat_v2"
    assert analysis.operation == "stream_generate_content"
    assert analysis.model.requested == "gemini-pro"
    assert analysis.model.effective == "gemini-pro"
    assert analysis.fields.supported == [
        "contents",
        "generationConfig",
        "toolConfig",
        "tools",
    ]
    assert analysis.fields.accepted_diagnostic_only == ["safetySettings"]
    assert analysis.tools.user_functions == ["search_docs"]
    assert [item.to_json_dict() for item in analysis.tools.mapped_builtin_tools] == [
        {"from": "googleSearch", "to": "web_search", "reason": "provider_alias"}
    ]
    assert analysis.tools.unsupported_tools == ["fileSearch"]
    assert analysis.tools.forced_tool_choice_supported is True
    assert analysis.security.query_redacted == ["key"]


def test_analyze_openai_responses_stateful_fields_depend_on_v2_backend():
    body = {
        "model": "gpt-4o",
        "input": "hidden",
        "previous_response_id": "resp_1",
        "store": True,
    }

    v1_analysis = analyze_compatibility_request(
        route="/v1/responses",
        body=body,
        config=_config(),
    )
    v2_analysis = analyze_compatibility_request(
        route="/v2/responses",
        body=body,
        config=_config(),
    )

    assert v1_analysis.fields.accepted_ignored == ["previous_response_id", "store"]
    assert "previous_response_id" in v2_analysis.fields.supported
    assert "store" in v2_analysis.fields.supported


def test_analyze_unknown_route_reports_warning_and_body_keys_only():
    analysis = analyze_compatibility_request(
        route="/not-a-real-route",
        body={"api_key": "secret", "foo": "bar"},
    )

    assert analysis.protocol == "unknown"
    assert analysis.operation == "unknown"
    assert analysis.fields.accepted_diagnostic_only == ["api_key", "foo"]
    assert analysis.security.body_fields_redacted == ["api_key"]
    assert [warning.code for warning in analysis.warnings] == ["unknown_operation"]


def test_analyze_missing_required_field_reports_error_warning():
    analysis = analyze_compatibility_request(route="/embeddings", body={"model": "m"})

    assert analysis.operation == "embeddings"
    assert analysis.warnings[-1].code == "missing_required_field"
    assert analysis.warnings[-1].severity == "error"
    assert analysis.warnings[-1].field == "input"


def test_analyze_protocol_routes_from_roadmap():
    cases = [
        ("/chat/completions", "openai", "chat_completions"),
        ("/responses", "openai", "responses"),
        ("/embeddings", "openai", "embeddings"),
        ("/messages", "anthropic", "messages"),
        ("/messages/count_tokens", "anthropic", "count_tokens"),
        ("/v1beta/models/gemini-pro:generateContent", "gemini", "generate_content"),
        (
            "/v1beta/models/gemini-pro:streamGenerateContent",
            "gemini",
            "stream_generate_content",
        ),
        ("/v1beta/models/gemini-pro:countTokens", "gemini", "count_tokens"),
        ("/v1beta/models/embedding-001:embedContent", "gemini", "embed_content"),
        (
            "/v1beta/models/embedding-001:batchEmbedContents",
            "gemini",
            "batch_embed_contents",
        ),
        ("/models", "openai", "model_discovery"),
        ("/v1beta/models", "gemini", "model_discovery"),
        ("/model/info", "litellm", "model_info"),
    ]

    for route, protocol, operation in cases:
        analysis = analyze_compatibility_request(protocol=protocol, route=route)

        assert analysis.protocol == protocol
        assert analysis.operation == operation
