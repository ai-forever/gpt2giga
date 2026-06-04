from gpt2giga.openapi_specs.anthropic import (
    anthropic_count_tokens_openapi_extra,
    anthropic_message_batches_openapi_extra,
    anthropic_messages_openapi_extra,
)
from gpt2giga.openapi_specs.openai import (
    chat_completions_openapi_extra,
    embeddings_openapi_extra,
    responses_openapi_extra,
)


def _request_body_description(extra):
    return extra["requestBody"]["description"]


def _full_schema(extra):
    return extra["requestBody"]["content"]["application/json"]["schema"]["oneOf"][1]


def test_openapi_openai_documents_client_parameter_policy():
    chat_extra = chat_completions_openapi_extra()
    chat_schema = _full_schema(chat_extra)
    chat_properties = chat_schema["properties"]

    assert "SDK `extra_body` compatibility" in chat_schema["description"]
    assert "max_completion_tokens" in chat_properties
    assert "extra_body" in chat_properties
    assert "extra_headers" in chat_properties
    assert "extra_query" in chat_properties
    assert (
        "Rejected: log probabilities are not supported."
        in (chat_properties["logprobs"]["description"])
    )
    assert "Known unsupported optional parameters may be rejected" in (
        _request_body_description(chat_extra)
    )


def test_openapi_openai_documents_embeddings_and_responses_policy():
    embeddings_extra = embeddings_openapi_extra()
    embeddings_properties = _full_schema(embeddings_extra)["properties"]
    responses_extra = responses_openapi_extra()
    responses_properties = _full_schema(responses_extra)["properties"]

    assert (
        "Rejected for embeddings" in embeddings_properties["extra_body"]["description"]
    )
    assert "`extra_body` and unknown top-level fields are rejected" in (
        _request_body_description(embeddings_extra)
    )
    assert "previous_response_id" in responses_properties
    assert "conversation" in responses_properties
    assert "maps to GigaChat `storage.thread_id`" in _request_body_description(
        responses_extra
    )


def test_openapi_anthropic_documents_client_parameter_policy():
    messages_extra = anthropic_messages_openapi_extra()
    messages_schema = _full_schema(messages_extra)
    messages_properties = messages_schema["properties"]

    assert "SDK `extra_body` compatibility" in messages_schema["description"]
    assert "extra_body" in messages_properties
    assert "extra_headers" in messages_properties
    assert "extra_query" in messages_properties
    assert "metadata" in messages_properties
    assert "mcp_servers" in messages_properties
    assert "document/file/container/search/thinking input blocks are rejected" in (
        _request_body_description(messages_extra)
    )


def test_openapi_anthropic_documents_count_tokens_and_disabled_batches_policy():
    count_extra = anthropic_count_tokens_openapi_extra()
    count_properties = _full_schema(count_extra)["properties"]
    batches_extra = anthropic_message_batches_openapi_extra()

    assert "extra_body" in count_properties
    assert "Generation-only options and `extra_body` are accepted but ignored" in (
        _request_body_description(count_extra)
    )
    assert "default public Anthropic router omits batch routes" in (
        _request_body_description(batches_extra)
    )
