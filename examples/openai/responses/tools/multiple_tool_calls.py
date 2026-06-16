import json
from typing import Any

from openai import OpenAI

api_version = "v2"
client = OpenAI(base_url=f"http://localhost:8090/{api_version}/", api_key="0")

MODEL = "GigaChat-2-Max"

tools = [
    {
        "type": "function",
        "name": "get_weather",
        "description": "Get a short weather forecast for a city and date.",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "City name, for example Saint Petersburg",
                },
                "date": {
                    "type": "string",
                    "description": "Date or relative date, for example tomorrow",
                },
            },
            "required": ["city", "date"],
        },
    },
    {
        "type": "function",
        "name": "find_hotel",
        "description": "Find a hotel option for a short trip.",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "City name",
                },
                "nights": {
                    "type": "integer",
                    "description": "Number of nights",
                },
                "max_price_rub": {
                    "type": "integer",
                    "description": "Maximum nightly price in RUB",
                },
            },
            "required": ["city", "nights", "max_price_rub"],
        },
    },
    {
        "type": "function",
        "name": "convert_currency",
        "description": "Convert money between currencies.",
        "parameters": {
            "type": "object",
            "properties": {
                "amount": {
                    "type": "number",
                    "description": "Amount to convert",
                },
                "from_currency": {
                    "type": "string",
                    "description": "Source currency code, for example USD",
                },
                "to_currency": {
                    "type": "string",
                    "description": "Target currency code, for example RUB",
                },
            },
            "required": ["amount", "from_currency", "to_currency"],
        },
    },
]


def get_weather(city: str, date: str) -> dict[str, str]:
    return {
        "city": city,
        "date": date,
        "forecast": "cloudy, +7 C",
        "advice": "take a windproof jacket",
    }


def find_hotel(city: str, nights: int, max_price_rub: int) -> dict[str, Any]:
    return {
        "city": city,
        "nights": nights,
        "max_price_rub": max_price_rub,
        "hotel": "Nevsky Central",
        "nightly_price_rub": 11400,
        "rating": 4.6,
    }


def convert_currency(
    amount: float,
    from_currency: str,
    to_currency: str,
) -> dict[str, Any]:
    rate = 93.5
    return {
        "amount": amount,
        "from_currency": from_currency,
        "to_currency": to_currency,
        "rate": rate,
        "converted_amount": round(amount * rate, 2),
    }


def parse_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, str):
        return json.loads(arguments or "{}")
    if isinstance(arguments, dict):
        return arguments
    return {}


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "get_weather":
        return get_weather(
            city=str(arguments["city"]),
            date=str(arguments["date"]),
        )
    if name == "find_hotel":
        return find_hotel(
            city=str(arguments["city"]),
            nights=int(arguments["nights"]),
            max_price_rub=int(arguments["max_price_rub"]),
        )
    if name == "convert_currency":
        return convert_currency(
            amount=float(arguments["amount"]),
            from_currency=str(arguments["from_currency"]),
            to_currency=str(arguments["to_currency"]),
        )
    msg = f"Unknown tool: {name}"
    raise ValueError(msg)


input_list: list[Any] = [
    {
        "role": "user",
        "content": (
            "Plan a 2-night trip to Saint Petersburg tomorrow. "
            "Use tools to check weather, find a hotel under 15000 RUB per night, "
            "and convert 200 USD to RUB. Then answer in Russian."
        ),
    },
]

last_response = None
needs_final_answer = True

# The model can return several function calls at once or ask for them one by one.
for _ in range(3):
    response = client.responses.create(
        model=MODEL,
        instructions=(
            "Before the final answer, call tools for weather, hotel search, "
            "and currency conversion when that data is missing."
        ),
        tools=tools,
        input=input_list,
    )
    last_response = response

    input_list += response.output
    function_calls = [item for item in response.output if item.type == "function_call"]
    if not function_calls:
        needs_final_answer = False
        break

    for item in function_calls:
        arguments = parse_arguments(item.arguments)
        result = call_tool(item.name, arguments)
        input_list.append(
            {
                "type": "function_call_output",
                "call_id": item.call_id,
                "output": json.dumps(result),
            }
        )

print("Final input:")
print(json.dumps(input_list, indent=2, default=str))

if not needs_final_answer and last_response:
    final_response = last_response
else:
    final_response = client.responses.create(
        model=MODEL,
        instructions=(
            "Use only tool results from the conversation. "
            "Answer in Russian in 3 short bullets."
        ),
        tools=tools,
        input=input_list,
    )

print("Final output:")
print(final_response.model_dump_json(indent=2))
print(final_response.metadata.get("gigachat_called_tools"))
print("\n" + final_response.output_text)
