"""Installed GigaChat SDK native function schema contract."""

from importlib.metadata import version

from gigachat.models import ChatCompletionRequest, ChatMessage, ChatModelOptions
from gigachat.models.chat_completions import ChatFunctionCall
from packaging.version import Version


def test_installed_gigachat_supports_native_function_schemas() -> None:
    installed = Version(version("gigachat"))

    assert installed >= Version("0.2.4a1")
    assert installed < Version("0.3.0")


def test_installed_gigachat_supports_parallel_v2_function_calls() -> None:
    request = ChatCompletionRequest(
        messages=[ChatMessage(role="user", content="Call both functions")],
        model_options=ChatModelOptions(parallel_tool_calls=True),
    )

    payload = request.model_dump(mode="json", exclude_none=True, by_alias=True)
    call = ChatFunctionCall.model_validate(
        {
            "id": "weather-call",
            "name": "get_weather",
            "arguments": {"city": "Moscow"},
        }
    )

    assert payload["model_options"]["parallel_tool_calls"] is True
    assert call.id_ == "weather-call"
    assert call.model_dump(mode="json", exclude_none=True, by_alias=True)["id"] == (
        "weather-call"
    )
