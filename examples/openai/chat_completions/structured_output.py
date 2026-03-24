from openai import OpenAI
from pydantic import BaseModel, Field

client = OpenAI(base_url="http://localhost:8090", api_key="0")


class ResponseFormat(BaseModel):
    """Формат ответа для модели"""

    thinking: str = Field(description="Размышления модели")
    output: str = Field(description="Ответ")


response = client.chat.completions.parse(
    model="GigaChat-2-Max",
    messages=[
        {"role": "system", "content": "Ты - профессиональный математик"},
        {
            "role": "user",
            "content": "Реши пример 8x^2 - 20x + 6 = 0",
        },
    ],
    response_format=ResponseFormat,
)

message = response.choices[0].message
print(message)
print(message.parsed)
