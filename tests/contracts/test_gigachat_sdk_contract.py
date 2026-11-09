"""Installed GigaChat SDK native function schema contract."""

from importlib.metadata import distribution, version
from pathlib import Path

from packaging.requirements import Requirement

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from gigachat.models import ChatCompletionRequest, ChatMessage, ChatModelOptions
from gigachat.models.chat_completions import ChatFunctionCall


def test_installed_gigachat_supports_native_function_schemas() -> None:
    assert version("gigachat") == "0.3.0a1"
    root = Path(__file__).resolve().parents[2]
    requirements = tomllib.loads((root / "pyproject.toml").read_text())["project"][
        "dependencies"
    ]
    for dependencies in (requirements, distribution("gpt2giga").requires):
        matches = [
            Requirement(item)
            for item in dependencies
            if Requirement(item).name == "gigachat"
        ]
        assert len(matches) == 1
        requirement = matches[0]
        assert requirement.extras == {"aiohttp"}
        assert str(requirement.specifier) == "==0.3.0a1"
        assert requirement.specifier.contains(version("gigachat"))


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
