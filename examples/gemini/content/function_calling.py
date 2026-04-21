"""Gemini function calling example via gpt2giga."""

from google import genai
from google.genai import types

client = genai.Client(
    api_key="0",
    http_options=types.HttpOptions(base_url="http://localhost:8090"),
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
    model="GigaChat-2-Max",
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

    tool_result = {
        "city": function_call.args["city"],
        "temperature_c": 5,
        "conditions": "облачно",
    }
    final = client.models.generate_content(
        model="GigaChat-2-Max",
        contents=[
            types.Content(
                role="user",
                parts=[types.Part(text="Какая погода в Москве?")],
            ),
            types.Content(
                role="model",
                parts=[
                    types.Part.from_function_call(
                        name=function_call.name,
                        args=function_call.args,
                    )
                ],
            ),
            types.Content(
                role="user",
                parts=[
                    types.Part.from_function_response(
                        name=function_call.name,
                        response=tool_result,
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
