import base64
from openai import OpenAI


def encode_file(file_path):
    with open(file_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


client = OpenAI(base_url="http://localhost:8090", api_key="0")
file_path = "../../Day_2_v6.pdf"

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
                    "text": "Create a comprehensive summary of this pdf, Tools and tool calling",
                },
                {
                    "type": "file",
                    "file": {
                        "filename": "Day_2_v6.pdf",
                        "file_data": f"data:application/pdf;base64,{base64_pdf}",
                    },
                },
            ],
        }
    ],
)
print(completion.choices[0].message.content)
