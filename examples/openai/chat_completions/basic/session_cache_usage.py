"""Show inclusive OpenAI input usage and reuse a session across two requests."""

from uuid import uuid4

from openai import OpenAI

api_version = "v2"
client = OpenAI(base_url=f"http://localhost:8090/{api_version}/", api_key="0")
# A new conversation gets a new ID; do not share it between unrelated users.
headers = {"X-Session-ID": str(uuid4())}
context = "\n".join(
    f"Аудитория A-{number}: {20 + number} мест, есть проектор."
    for number in range(1, 81)
)
for question in ("Сколько мест в A-12?", "А в A-25?"):
    response = client.chat.completions.create(
        model="GigaChat-2-Max",
        messages=[
            {"role": "system", "content": f"Отвечай по справочнику:\n{context}"},
            {"role": "user", "content": question},
        ],
        max_completion_tokens=128,
        extra_headers=headers,
    )
    print(response.choices[0].message.content)
    if response.usage:
        usage = response.usage
        cached = (
            usage.prompt_tokens_details.cached_tokens or 0
            if usage.prompt_tokens_details
            else 0
        )
        print(
            f"Весь вход: {usage.prompt_tokens}; из кэша: {cached}; "
            f"без кэша: {usage.prompt_tokens - cached}; выход: {usage.completion_tokens}"
        )
        # cached_tokens is already part of prompt_tokens: do not add it again.
# Reusing X-Session-ID enables session continuity; cache hits are not guaranteed.
