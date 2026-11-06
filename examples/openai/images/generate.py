"""Generate one real image through the GigaChat v2 image tool."""

import base64
from pathlib import Path

from openai import OpenAI


client = OpenAI(base_url="http://localhost:8090/v2", api_key="0")
result = client.images.generate(
    model="gpt-image-1",  # Resolves to configured GIGACHAT_MODEL.
    prompt="A small lighthouse on a quiet rocky coast, watercolor",
    n=1,
    response_format="b64_json",
)
image = result.data[0].b64_json
if image is None:
    raise RuntimeError("No image bytes returned")
Path("generated-image.bin").write_bytes(base64.b64decode(image))
print("Saved generated-image.bin (format chosen by GigaChat)")
