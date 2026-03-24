from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090", api_key="0")
tools = [
    {
        "type": "function",
        "name": "get_horoscope",
        "description": "Get today's horoscope for an astrological sign.",
        "parameters": {
            "type": "object",
            "properties": {
                "sign": {
                    "type": "string",
                    "description": "An astrological sign like Taurus or Aquarius",
                },
            },
            "required": ["sign"],
        },
    },
]


def get_horoscope(sign):
    return f"{sign}: Next Tuesday you will befriend a baby otter."


response = client.chat.completions.create(
    model="GigaChat-2-Max",
    tools=tools,
    messages=[{"role": "user", "content": "What is my horoscope? I am an Aquarius."}],
    # stream=True
)
print(response)
