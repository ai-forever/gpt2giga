from openai import OpenAI

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

response = client.responses.create(
    model="GigaChat-Pro",
    input=[
        {"role": "system", "content": "You are a helpful math tutor."},
        {"role": "user", "content": "solve 8x + 31 = 2"},
    ],
    text={"format": {"type": "json_schema", "json_schema": json_schema}},
)
print(response.output)
