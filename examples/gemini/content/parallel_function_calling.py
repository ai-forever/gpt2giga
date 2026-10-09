"""Parallel function calling through the Gemini Developer API."""

from google import genai
from google.genai import types

api_version = "v2"
if api_version != "v2":
    print("Parallel function calling requires the GigaChat v2 contract; skipping.")
    raise SystemExit(0)
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
                "description": "Получить текущую погоду для города.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"city": {"type": "STRING"}},
                    "required": ["city"],
                },
            },
            {
                "name": "get_rate",
                "description": "Получить курс валюты к рублю.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"currency": {"type": "STRING"}},
                    "required": ["currency"],
                },
            },
        ]
    )
]


def get_weather(city: str) -> dict:
    """Return a deterministic weather stub."""
    return {"city": city, "temperature_c": 5, "conditions": "облачно"}


def get_rate(currency: str) -> dict:
    """Return a deterministic exchange-rate stub."""
    return {"currency": currency, "rubles": 90.5}


functions = {"get_weather": get_weather, "get_rate": get_rate}
prompt = (
    "Одновременно вызови обе функции одним ответом: узнай погоду в Москве и курс "
    "USD. Не отвечай текстом до получения результатов функций."
)
user_content = types.Content(role="user", parts=[types.Part(text=prompt)])

response = client.models.generate_content(
    model="GigaChat-2-Max",
    contents=[user_content],
    config=types.GenerateContentConfig(
        tools=tools,
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="AUTO")
        ),
    ),
)
function_calls = response.function_calls or []
names = [function_call.name for function_call in function_calls]
if len(function_calls) != 2 or set(names) != set(functions):
    raise RuntimeError(f"Ожидались два параллельных вызова, получено: {names}")
if any(not function_call.id for function_call in function_calls):
    raise RuntimeError("Каждый параллельный вызов должен иметь собственный id")

function_responses = [
    types.Part(
        function_response=types.FunctionResponse(
            id=function_call.id,
            name=function_call.name,
            response=functions[function_call.name](**function_call.args),
        )
    )
    for function_call in function_calls
]
final = client.models.generate_content(
    model="GigaChat-2-Max",
    contents=[
        user_content,
        response.candidates[0].content,
        types.Content(role="user", parts=function_responses),
    ],
    config=types.GenerateContentConfig(
        tools=tools,
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="NONE")
        ),
    ),
)

print("Параллельные вызовы:")
for function_call in function_calls:
    print(f"- {function_call.id}: {function_call.name}")
print("\nФинальный ответ:")
print(final.text)
