#!/usr/bin/env python3
"""Smoke-test local GigaFusion routes against a running gpt2giga server."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable


DEFAULT_BASE_URL = "http://localhost:8090"
DEFAULT_MODEL = "gpt2giga/fusion-code"
DEFAULT_ROUTES = ("models", "responses", "chat", "anthropic", "gemini")


@dataclass(frozen=True)
class SmokeResult:
    route: str
    ok: bool
    duration_seconds: float
    detail: str


class SmokeFailure(RuntimeError):
    """Raised when a Fusion smoke check fails."""


def parse_routes(raw: str) -> tuple[str, ...]:
    allowed = set(DEFAULT_ROUTES)
    routes: list[str] = []
    for item in raw.split(","):
        route = item.strip().lower()
        if not route:
            continue
        if route not in allowed:
            raise argparse.ArgumentTypeError(
                f"unsupported route {route!r}; expected one of {sorted(allowed)}"
            )
        if route not in routes:
            routes.append(route)
    if not routes:
        raise argparse.ArgumentTypeError("at least one route is required")
    return tuple(routes)


def request_json(
    method: str,
    url: str,
    *,
    api_key: str | None,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float,
) -> dict[str, Any]:
    request_headers = {"Accept": "application/json"}
    if api_key:
        request_headers["Authorization"] = f"Bearer {api_key}"
    if headers:
        request_headers.update(headers)

    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url,
        data=data,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise SmokeFailure(
            f"{method} {url} returned HTTP {exc.code}: {payload}"
        ) from exc
    except (OSError, urllib.error.URLError) as exc:
        raise SmokeFailure(f"{method} {url} failed: {exc}") from exc

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SmokeFailure(
            f"{method} {url} returned non-JSON: {payload[:500]}"
        ) from exc
    if not isinstance(parsed, dict):
        raise SmokeFailure(f"{method} {url} returned non-object JSON")
    return parsed


def check_health(base_url: str, *, timeout: float) -> None:
    payload = request_json(
        "GET",
        f"{base_url.rstrip('/')}/health",
        api_key=None,
        timeout=timeout,
    )
    if payload.get("status") not in {"ok", "healthy"}:
        raise SmokeFailure(f"unexpected health payload: {payload}")


def check_models(
    base_url: str,
    *,
    api_key: str | None,
    model: str,
    timeout: float,
) -> str:
    payload = request_json(
        "GET",
        f"{base_url.rstrip('/')}/models",
        api_key=api_key,
        timeout=timeout,
    )
    data = payload.get("data")
    if not isinstance(data, list):
        raise SmokeFailure("/models response does not contain data[]")
    ids = {item.get("id") for item in data if isinstance(item, dict)}
    if model not in ids:
        raise SmokeFailure(
            f"Fusion alias {model!r} is missing from /models; "
            "set GPT2GIGA_FUSION_ENABLED=True and restart gpt2giga"
        )
    return f"found {model} in /models"


def check_chat(
    base_url: str,
    *,
    api_key: str | None,
    model: str,
    api_version: str,
    timeout: float,
) -> str:
    payload = request_json(
        "POST",
        f"{base_url.rstrip('/')}/{api_version}/chat/completions",
        api_key=api_key,
        body={
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": "Name one risk in this release plan.",
                }
            ],
        },
        timeout=timeout,
    )
    if "error" in payload:
        raise SmokeFailure(f"chat returned error: {payload['error']}")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise SmokeFailure("chat response has no choices")
    metadata = payload.get("metadata")
    if isinstance(metadata, dict) and metadata.get("gpt2giga_fusion") != "true":
        raise SmokeFailure(f"chat metadata does not mark Fusion: {metadata}")
    return "chat completion returned choices"


def check_responses(
    base_url: str,
    *,
    api_key: str | None,
    model: str,
    api_version: str,
    timeout: float,
) -> str:
    payload = request_json(
        "POST",
        f"{base_url.rstrip('/')}/{api_version}/responses",
        api_key=api_key,
        body={
            "model": model,
            "input": "Recommend one safe next step for this implementation plan.",
        },
        timeout=timeout,
    )
    if payload.get("status") == "failed" or payload.get("error"):
        raise SmokeFailure(f"responses returned error: {payload.get('error')}")
    if not payload.get("output_text") and not payload.get("output"):
        raise SmokeFailure("responses output is empty")
    metadata = payload.get("metadata")
    if isinstance(metadata, dict) and metadata.get("gpt2giga_fusion") != "true":
        raise SmokeFailure(f"responses metadata does not mark Fusion: {metadata}")
    return "responses returned output"


def check_anthropic(
    base_url: str,
    *,
    api_key: str | None,
    model: str,
    api_version: str,
    timeout: float,
) -> str:
    payload = request_json(
        "POST",
        f"{base_url.rstrip('/')}/{api_version}/messages",
        api_key=api_key,
        headers={"anthropic-version": "2023-06-01"},
        body={
            "model": model,
            "max_tokens": 2048,
            "messages": [
                {
                    "role": "user",
                    "content": "Compare two options and choose the safer one.",
                }
            ],
        },
        timeout=timeout,
    )
    if payload.get("type") != "message":
        raise SmokeFailure(f"anthropic response is not a message: {payload}")
    content = payload.get("content")
    if not isinstance(content, list) or not content:
        raise SmokeFailure("anthropic message content is empty")
    return "anthropic message returned content"


def check_gemini(
    base_url: str,
    *,
    api_key: str | None,
    model: str,
    timeout: float,
) -> str:
    headers = {"x-goog-api-key": api_key or "0"}
    payload = request_json(
        "POST",
        f"{base_url.rstrip('/')}/v1beta/models/{model}:generateContent",
        api_key=api_key,
        headers=headers,
        body={
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": "Find the highest risk in this checklist."}],
                }
            ]
        },
        timeout=timeout,
    )
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise SmokeFailure(f"gemini response has no candidates: {payload}")
    return "gemini generateContent returned candidates"


def run_check(name: str, func: Callable[[], str]) -> SmokeResult:
    started = time.monotonic()
    try:
        detail = func()
    except SmokeFailure as exc:
        return SmokeResult(
            route=name,
            ok=False,
            duration_seconds=time.monotonic() - started,
            detail=str(exc),
        )
    return SmokeResult(
        route=name,
        ok=True,
        duration_seconds=time.monotonic() - started,
        detail=detail,
    )


def print_result(result: SmokeResult) -> None:
    marker = "OK" if result.ok else "FAIL"
    print(
        f"[{marker}] {result.route} ({result.duration_seconds:.1f}s) - {result.detail}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a live GigaFusion smoke test against gpt2giga."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--api-key",
        default=os.getenv("GPT2GIGA_API_KEY") or os.getenv("OPENAI_API_KEY") or "0",
        help="Proxy API key. Defaults to GPT2GIGA_API_KEY, OPENAI_API_KEY or 0.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--api-version",
        default="v2",
        choices=("v1", "v2"),
        help="OpenAI-compatible route version for chat/responses. Default: v2.",
    )
    parser.add_argument(
        "--anthropic-api-version",
        default="v1",
        choices=("v1", "v2"),
        help="Anthropic Messages route version. Default: v1.",
    )
    parser.add_argument(
        "--routes",
        default=",".join(DEFAULT_ROUTES),
        type=parse_routes,
        help="Comma-separated routes to test. Default: all.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=240.0,
        help="HTTP timeout per route in seconds. Default: 240.",
    )
    parser.add_argument("--skip-health-check", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    base_url = args.base_url.rstrip("/")
    api_key = args.api_key or None

    if not args.skip_health_check:
        try:
            check_health(base_url, timeout=min(args.timeout, 10.0))
        except SmokeFailure as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    checks = {
        "models": lambda: check_models(
            base_url,
            api_key=api_key,
            model=args.model,
            timeout=args.timeout,
        ),
        "responses": lambda: check_responses(
            base_url,
            api_key=api_key,
            model=args.model,
            api_version=args.api_version,
            timeout=args.timeout,
        ),
        "chat": lambda: check_chat(
            base_url,
            api_key=api_key,
            model=args.model,
            api_version=args.api_version,
            timeout=args.timeout,
        ),
        "anthropic": lambda: check_anthropic(
            base_url,
            api_key=api_key,
            model=args.model,
            api_version=args.anthropic_api_version,
            timeout=args.timeout,
        ),
        "gemini": lambda: check_gemini(
            base_url,
            api_key=api_key,
            model=args.model,
            timeout=args.timeout,
        ),
    }

    results = [run_check(route, checks[route]) for route in args.routes]
    for result in results:
        print_result(result)

    failed = [result for result in results if not result.ok]
    if failed:
        print(f"\nFusion smoke failed: {len(failed)} of {len(results)} checks failed.")
        return 1

    print(f"\nFusion smoke passed: {len(results)} checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
