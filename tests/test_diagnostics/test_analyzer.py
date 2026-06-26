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


def _tool_details(analysis):
    return [detail.to_json_dict() for detail in analysis.tools.details]


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
    assert {
        "source": "openai.tools",
        "category": "user_function",
        "decision": "supported",
        "name": "search_docs",
        "reason": "custom_function",
    } in _tool_details(analysis)
    assert {
        "source": "openai.tools",
        "category": "provider_builtin",
        "decision": "mapped",
        "name": "web_search_preview",
        "target": "web_search",
        "reason": "provider_alias",
        "field": "tools[1].type",
    } in _tool_details(analysis)
    assert {
        "source": "openai.tools",
        "category": "provider_builtin",
        "decision": "unsupported",
        "name": "file_search",
        "reason": "unsupported_tool_type",
        "field": "tools[2].type",
    } in _tool_details(analysis)
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


def test_analyze_openai_reports_disabled_builtin_mapping_and_forced_choice():
    analysis = analyze_compatibility_request(
        protocol="openai",
        route="/v2/chat/completions",
        body={
            "messages": [{"role": "user", "content": "hidden"}],
            "tools": [{"type": "web_search_preview"}],
            "tool_choice": {"type": "web_search_preview"},
        },
        config=_config(disable_builtin_tool_mapping=True),
    )

    assert analysis.tools.mapping_disabled is True
    assert analysis.tools.mapped_builtin_tools == []
    assert analysis.tools.unsupported_tools == ["web_search_preview"]
    assert analysis.tools.forced_tool_choice_supported is False
    assert {
        "source": "openai.tools",
        "category": "provider_builtin",
        "decision": "unsupported",
        "name": "web_search_preview",
        "target": "web_search",
        "reason": "builtin_tool_mapping_disabled",
        "field": "tools[0].type",
    } in _tool_details(analysis)
    assert {
        "source": "openai.tool_choice",
        "category": "tool_choice",
        "decision": "unsupported",
        "name": "web_search_preview",
        "target": "web_search",
        "reason": "builtin_tool_mapping_disabled",
        "field": "tool_choice.type",
    } in _tool_details(analysis)
    assert {warning.code for warning in analysis.warnings} == {
        "unsupported_forced_tool_choice",
        "unsupported_tool",
    }


def test_analyze_anthropic_reports_named_builtin_alias_and_disabled_choice():
    analysis = analyze_compatibility_request(
        protocol="anthropic",
        route="/v2/messages",
        body={
            "messages": [{"role": "user", "content": "hidden"}],
            "tools": [
                {"type": "custom", "name": "lookup"},
                {"type": "web_search_20250305", "name": "web_search"},
                {"name": "WebFetch"},
            ],
            "tool_choice": {"type": "tool", "name": "web_search"},
        },
        config=_config(disable_builtin_tool_mapping=True),
    )

    assert analysis.tools.user_functions == ["lookup"]
    assert analysis.tools.mapped_builtin_tools == []
    assert analysis.tools.unsupported_tools == ["web_search_20250305", "WebFetch"]
    assert analysis.tools.forced_tool_choice_supported is False
    assert {
        "source": "anthropic.tools",
        "category": "provider_builtin",
        "decision": "unsupported",
        "name": "web_search_20250305",
        "target": "web_search",
        "reason": "builtin_tool_mapping_disabled",
        "field": "tools[1].type",
    } in _tool_details(analysis)
    assert {
        "source": "anthropic.tools",
        "category": "provider_builtin",
        "decision": "unsupported",
        "name": "WebFetch",
        "target": "url_content_extraction",
        "reason": "builtin_tool_mapping_disabled",
        "field": "tools[2].name",
    } in _tool_details(analysis)
    assert {
        "source": "anthropic.tool_choice",
        "category": "tool_choice",
        "decision": "unsupported",
        "name": "web_search",
        "target": "web_search",
        "reason": "builtin_tool_mapping_disabled",
        "field": "tool_choice.name",
    } in _tool_details(analysis)


def test_analyze_gemini_reports_tool_key_and_forced_choice_limitations():
    analysis = analyze_compatibility_request(
        route="/v2/v1beta/models/gemini-pro:generateContent",
        body={
            "contents": [{"parts": [{"text": "hidden"}]}],
            "toolConfig": {
                "functionCallingConfig": {
                    "mode": "ANY",
                    "allowedFunctionNames": ["first", "second"],
                }
            },
            "tools": [
                {"googleSearch": {}},
                {
                    "functionDeclarations": [
                        {"name": "first"},
                        {"name": "second"},
                    ]
                },
                {"fileSearch": {}},
            ],
        },
        config=_config(gigachat_api_mode="v2"),
    )

    assert analysis.tools.user_functions == ["first", "second"]
    assert [item.to_json_dict() for item in analysis.tools.mapped_builtin_tools] == [
        {"from": "googleSearch", "to": "web_search", "reason": "provider_alias"}
    ]
    assert analysis.tools.unsupported_tools == ["fileSearch"]
    assert analysis.tools.forced_tool_choice_supported is False
    assert {
        "source": "gemini.tools",
        "category": "provider_builtin",
        "decision": "unsupported",
        "name": "fileSearch",
        "reason": "unsupported_tool_key",
        "field": "tools[2].fileSearch",
    } in _tool_details(analysis)
    assert {
        "source": "gemini.toolConfig",
        "category": "tool_choice",
        "decision": "unsupported",
        "reason": "backend_requires_single_forced_function",
        "field": "toolConfig.functionCallingConfig.allowedFunctionNames",
    } in _tool_details(analysis)
    assert {warning.code for warning in analysis.warnings} == {
        "unsupported_forced_tool_choice",
        "unsupported_tool",
    }


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
