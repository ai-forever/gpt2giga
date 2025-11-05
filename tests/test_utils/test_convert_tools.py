from gpt2giga.utils import convert_tool_to_giga_functions


def test_convert_from_tools_function_objects():
    data = {
        "tools": [
            {
                "function": {
                    "name": "fn1",
                    "description": "desc1",
                    "parameters": {"type": "object", "properties": {}},
                }
            }
        ]
    }
    out = convert_tool_to_giga_functions(data)
    assert len(out) == 1
    assert out[0].name == "fn1"


def test_convert_from_functions_list():
    data = {
        "functions": [
            {
                "name": "fn2",
                "description": "desc2",
                "parameters": {
                    "type": "object",
                    "properties": {"a": {"type": "string"}},
                },
            }
        ]
    }
    out = convert_tool_to_giga_functions(data)
    assert len(out) == 1
    assert out[0].name == "fn2"
