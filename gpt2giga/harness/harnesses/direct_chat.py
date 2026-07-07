"""Direct Chat Completions harness through the local gpt2giga proxy."""

from __future__ import annotations

import json

from gpt2giga.harness import proxy
from gpt2giga.harness.harnesses.base import BaseHarness
from gpt2giga.harness.types import (
    Availability,
    HarnessCapability,
    HarnessContext,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
)


DEFAULT_MODEL = "GigaChat"


class DirectChatHarness(BaseHarness):
    """Call /v1 or /v2 Chat Completions on the local proxy."""

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="direct-chat",
            title="Direct Chat Completions",
            kind="built-in",
            description=("Direct OpenAI-style Chat Completions through gpt2giga"),
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
            supports_model_selection=True,
            supports_api_mode_selection=True,
            tags=("chat", "proxy"),
        )

    def availability(self) -> Availability:
        return Availability.available("built-in harness")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        model = request.model or context.default_model or DEFAULT_MODEL
        url = proxy.build_chat_completions_url(context.proxy_url, request.api_mode)
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": request.prompt}],
            "stream": bool(request.stream),
        }
        cli_command = (
            "giga",
            "chat",
            "--api-mode",
            request.api_mode.value,
            "--model",
            model,
            request.prompt,
        )
        curl_command = _curl_command(url, payload, bool(context.api_key))
        if request.extra.get("dry_run"):
            return HarnessResult(
                ok=True,
                text="dry run",
                raw={"url": url, "payload": payload, "curl_command": curl_command},
                command=cli_command,
            )
        try:
            data = proxy.request_json(
                "POST",
                url,
                payload=payload,
                api_key=context.api_key,
                timeout=context.timeout_seconds,
            )
        except proxy.ProxyRequestError as exc:
            return HarnessResult(
                ok=False,
                text="",
                raw={"url": url, "payload": payload, "curl_command": curl_command},
                command=cli_command,
                error=str(exc),
            )
        return HarnessResult(
            ok=True,
            text=proxy.extract_text(data),
            raw={
                **proxy.safe_raw(data),
                "url": url,
                "curl_command": curl_command,
            },
            command=cli_command,
        )


def _curl_command(
    url: str,
    payload: dict[str, object],
    include_auth: bool,
) -> tuple[str, ...]:
    command = ["curl", "-sS", url, "-H", "Content-Type: application/json"]
    if include_auth:
        command.extend(["-H", "Authorization: Bearer <redacted>"])
    command.extend(["-d", json.dumps(payload, ensure_ascii=False)])
    return tuple(command)
