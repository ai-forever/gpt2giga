import json
import os
from collections.abc import Iterator
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE_URL = os.getenv("GEMINI_BASE_URL", "http://localhost:8090/v1").rstrip("/")
API_KEY = os.getenv("GPT2GIGA_API_KEY")


def request_json(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{BASE_URL}{path}",
        data=data,
        method=method,
        headers=_headers(),
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{exc.code} {exc.reason}: {body}") from exc


def stream_sse(path: str, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    request = Request(
        f"{BASE_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers=_headers(),
    )
    try:
        with urlopen(request, timeout=60) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if not data:
                    continue
                yield json.loads(data)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{exc.code} {exc.reason}: {body}") from exc


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _headers() -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Client": "gpt2giga-gemini-examples/1.0",
    }
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    return headers
