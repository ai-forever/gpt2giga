"""Gemini structured output example via gpt2giga."""

import json

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

client = genai.Client(
    api_key="0",
    http_options=types.HttpOptions(base_url="http://localhost:8090"),
)


class MovieRecommendation(BaseModel):
    title: str = Field(description="Название фильма")
    genre: str = Field(description="Жанр фильма")
    reason: str = Field(description="Короткая причина рекомендации")


response = client.models.generate_content(
    model="GigaChat-2-Max",
    contents="Порекомендуй один фантастический фильм для вечернего просмотра.",
    config=types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=MovieRecommendation.model_json_schema(),
    ),
)

parsed = response.parsed if response.parsed is not None else json.loads(response.text)
print(parsed)
