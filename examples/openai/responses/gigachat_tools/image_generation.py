from openai import OpenAI
import base64

client = OpenAI(base_url="http://localhost:8090", api_key="0")

with client.responses.stream(
    model="gpt-4.1-mini",
    input="Generate an image of gray tabby cat hugging an otter with an orange scarf",
    tools=[{"type": "image_generation"}],
    store=False,
) as stream:
    response = stream.get_final_response()

image_data = [
    output.result
    for output in response.output
    if output.type == "image_generation_call" and output.result
]

if image_data:
    image_base64 = image_data[0]
    with open("cat_and_otter.png", "wb") as f:
        f.write(base64.b64decode(image_base64))
