from openai import OpenAI
import json

client = OpenAI(base_url="http://localhost:8090/v1", api_key="0")
json_schema = {
    "name": "math_response",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "explanation": {"type": "string"},
                        "result": {"type": "string"},
                    },
                    "required": ["explanation", "result"],
                    "additionalProperties": False,
                },
            },
            "final_answer": {"type": "string"},
        },
        "required": ["steps", "final_answer"],
        "additionalProperties": False,
    },
}

response = client.chat.completions.create(
    model="GigaChat-2-Max",
    messages=[
        {"role": "system", "content": "You are a helpful math tutor."},
        {"role": "user", "content": "solve 8x + 31 = 2"},
    ],
    response_format={"type": "json_schema", "json_schema": json_schema},
)

message = response.choices[0].message
if message.content:
    print("Raw content:", message.content)
    try:
        data = json.loads(message.content)
        print("\nParsed data:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except json.JSONDecodeError:
        print("Could not parse JSON")
