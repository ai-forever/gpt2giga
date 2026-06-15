from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090/v2", api_key="0")

resp = client.responses.create(
    model="GigaChat-2-Max",
    input="Нарисуй красивую картинку с космосом",
    tools=[{"type": "image_generation"}],
    store=False,
    stream=True,
)

for elem in resp:
    print(elem)
