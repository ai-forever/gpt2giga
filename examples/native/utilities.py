"""Call native GigaChat utilities; availability depends on the upstream account."""

import httpx


with httpx.Client(
    base_url="http://localhost:8090/bridge/gigachat",
    headers={"Authorization": "Bearer 0"},
) as client:
    for path, body in (
        ("tokens/count", {"input": ["Привет, мир!"]}),
        (
            "functions/validate",
            {"name": "lookup", "parameters": {"type": "object", "properties": {}}},
        ),
        ("ai/check", {"input": "Небольшой русский текст для проверки."}),
    ):
        response = client.post(path, json=body)
        response.raise_for_status()
        print(path, response.json())
    response = client.get("balance")
    response.raise_for_status()
    print("balance", response.json())
