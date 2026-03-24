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


response = client.responses.parse(
    model="gpt-4o",
    input=[
        {"role": "system", "content": "Ты - профессиональный математик"},
        {
            "role": "user",
            "content": "Реши пример 8x^2 - 20x + 6 = 0",
        },
    ],
    text_format=MathResponse,
)

message = response.output_parsed
print(message)
if message:
    print(message.steps)
    print("answer: ", message.final_answer)
