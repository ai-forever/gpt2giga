"""Gemini function calling example via gpt2giga."""

from google import genai
from google.genai import types

api_version = "v2"
client = genai.Client(
    api_key="0",
    http_options=types.HttpOptions(
        base_url="http://localhost:8090",
        api_version=api_version,
    ),
)

tools = [
    types.Tool(
        function_declarations=[
            {
                "name": "get_weather",
                "description": "Получить текущую погоду для указанного города.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "city": {
                            "type": "STRING",
                            "description": "Название города, например Москва.",
                        }
                    },
                    "required": ["city"],
                },
            }
        ]
    )
]

response = client.models.generate_content(
    model="gpt2giga/fusion-code",
    contents="Какая погода в Москве?",
    config=types.GenerateContentConfig(
        tools=tools,
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode="ANY",
                allowed_function_names=["get_weather"],
            )
        ),
    ),
)

if response.function_calls:
    function_call = response.function_calls[0]
    print("Модель вызвала функцию:")
    print(function_call)
    print(f"tool state id: {function_call.id}")

    tool_result = {
        "city": function_call.args["city"],
        "temperature_c": 5,
        "conditions": "облачно",
    }
    final = client.models.generate_content(
        model="gpt2giga/fusion-code",
        contents=[
            types.Content(
                role="user",
                parts=[types.Part(text="Какая погода в Москве?")],
            ),
            types.Content(
                role="model",
                parts=[
                    types.Part(
                        function_call=types.FunctionCall(
                            id=function_call.id,
                            name=function_call.name,
                            args=function_call.args,
                        )
                    )
                ],
            ),
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            id=function_call.id,
                            name=function_call.name,
                            response=tool_result,
                        )
                    )
                ],
            ),
        ],
        config=types.GenerateContentConfig(tools=tools),
    )
    print("\nФинальный ответ:")
    print(final.text)
else:
    print("Модель ответила текстом:")
    print(response.text)
