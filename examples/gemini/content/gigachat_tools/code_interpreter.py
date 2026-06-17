"""Gemini example for GigaChat v2 code interpreter tool."""

from google import genai
from google.genai import types

api_version = "v2"
if api_version != "v2":
    print("SKIP: GigaChat built-in tools require /v2 chat completions.")
    raise SystemExit(0)

client = genai.Client(
    api_key="0",
    http_options=types.HttpOptions(
        base_url="http://localhost:8090",
        api_version=api_version,
    ),
)

response = client.models.generate_content(
    model="GigaChat-2-Max",
    contents=(
        "Используй code execution, чтобы посчитать сумму квадратов "
        "чисел от 1 до 20, и кратко покажи результат."
    ),
    config=types.GenerateContentConfig(
        tools=[types.Tool(code_execution=types.ToolCodeExecution())],
    ),
)

print(response)
