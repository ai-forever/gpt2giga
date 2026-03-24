from openai import OpenAI
from pydantic import BaseModel, Field

client = OpenAI(base_url="http://localhost:8090", api_key="0")


class ResponseFormat(BaseModel):
    """Формат ответа для модели"""

    thinking: str = Field(description="Размышления модели")
    output: str = Field(description="Ответ")


response = client.responses.parse(
    model="gpt-4o-2024-08-06",
    input=[
        {"role": "system", "content": "Ты - профессиональный математик"},
        {
            "role": "user",
            "content": "Реши пример 8x^2 - 20x + 6 = 0",
        },
    ],
    text_format=ResponseFormat,
)

event = response.output_parsed
print(event)
