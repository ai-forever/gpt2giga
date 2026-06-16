import base64
from pathlib import Path

from openai import OpenAI


def encode_file(file_path: Path) -> str:
    return base64.b64encode(file_path.read_bytes()).decode("utf-8")


api_version = "v2"
client = OpenAI(base_url=f"http://localhost:8090/{api_version}/", api_key="0")
file_path = Path("sample.pdf")

# Getting the base64 string
base64_pdf = encode_file(file_path)
completion = client.chat.completions.create(
    model="GigaChat-2-Max",
    messages=[
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Create a comprehensive summary of this pdf.",
                },
                {
                    "type": "file",
                    "file": {
                        "filename": "sample.pdf",
                        "file_data": f"data:application/pdf;base64,{base64_pdf}",
                    },
                },
            ],
        }
    ],
)
print(completion.choices[0].message.content)
