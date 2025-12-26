from typing import List

from openai import OpenAI
from pydantic import BaseModel

client = OpenAI(base_url="http://localhost:8090", api_key="0")


class Step(BaseModel):
    explanation: str
    output: str


class MathResponse(BaseModel):
    steps: List[Step]
    final_answer: str


response = client.chat.completions.parse(
    model="gpt-4o",
    messages=[
        {"role": "system", "content": "Ты - профессиональный математик"},
        {
            "role": "user",
            "content": "Реши пример 8x^2 - 20x + 6 = 0",
        },
    ],
    response_format=MathResponse,
)

message = response.choices[0].message
if message.parsed:
    print(message.parsed.steps)
    print("answer: ", message.parsed.final_answer)
