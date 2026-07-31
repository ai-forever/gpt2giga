from gigachat.models import Function

from gpt2giga.common.tools import (
    convert_tool_to_giga_functions,
    split_gigachat_tool_name,
)


def test_convert_tool_to_giga_functions_tools_format():
    data = {
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "func1",
                    "description": "desc1",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
    }
    funcs = convert_tool_to_giga_functions(data)
    assert len(funcs) == 1
    assert isinstance(funcs[0], Function)
    assert funcs[0].name == "func1"


def test_convert_tool_to_giga_functions_adds_properties_to_empty_schema():
    data = {
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "no_args",
                    "description": "No args.",
                    "parameters": {},
                },
            }
        ]
    }

    funcs = convert_tool_to_giga_functions(data)

    assert len(funcs) == 1
    params = (
        funcs[0].parameters.model_dump(by_alias=True)
        if hasattr(funcs[0].parameters, "model_dump")
        else dict(funcs[0].parameters)
    )
    assert params["type"] == "object"
    assert params["properties"] == {}


def test_convert_tool_to_giga_functions_functions_format():
    # Deprecated format support
    data = {
        "functions": [
            {
                "name": "func2",
                "description": "desc2",
                "parameters": {"type": "object", "properties": {}},
            }
        ]
    }
    funcs = convert_tool_to_giga_functions(data)
    assert len(funcs) == 1
    assert funcs[0].name == "func2"


def test_convert_tool_to_giga_functions_namespace_tools():
    data = {
        "tools": [
            {
                "type": "namespace",
                "name": "mcp__playwright",
                "tools": [
                    {
                        "type": "function",
                        "name": "browser_navigate",
                        "description": "Navigate",
                        "parameters": {
                            "type": "object",
                            "properties": {"url": {"type": "string"}},
                        },
                    }
                ],
            }
        ]
    }

    funcs = convert_tool_to_giga_functions(data)

    assert len(funcs) == 1
    assert funcs[0].name == "mcp__playwright__browser_navigate"
    assert split_gigachat_tool_name(
        funcs[0].name,
        request_tools=data["tools"],
    ) == ("browser_navigate", "mcp__playwright")
