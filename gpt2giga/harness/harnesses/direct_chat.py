"""Direct Chat Completions harness through the local gpt2giga proxy."""

from __future__ import annotations

import json

from gpt2giga.harness import proxy
from gpt2giga.harness.harnesses.base import BaseHarness
from gpt2giga.harness.types import (
    Availability,
    HarnessChatMessage,
    HarnessCapability,
    HarnessContext,
    HarnessEvent,
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
            supports_streaming=True,
            supports_attachments=True,
            accepted_attachment_kinds=("image", "text", "workspace_file"),
            attachment_transport=("openai_content_parts", "inline_text"),
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
        messages = _request_messages(request)
        payload = {
            "model": model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "stream": bool(request.stream),
        }
        api_key = context.api_key or proxy.cached_sidecar_api_key(context.proxy_url)
        cli_command = (
            "giga",
            "chat",
            "--api-mode",
            request.api_mode.value,
            "--model",
            model,
            request.prompt,
        )
        curl_command = _curl_command(url, payload, bool(api_key))
        if request.extra.get("dry_run"):
            return HarnessResult(
                ok=True,
                text="dry run",
                raw={"url": url, "payload": payload, "curl_command": curl_command},
                command=cli_command,
            )
        events: tuple[HarnessEvent, ...] = ()
        if context.auto_start_proxy:
            startup = proxy.ensure_proxy_available(context, request.api_mode)
            api_key = startup.api_key or api_key
            curl_command = _curl_command(url, payload, bool(api_key))
            if not startup.ok:
                return HarnessResult(
                    ok=False,
                    text="",
                    raw={
                        "url": url,
                        "payload": payload,
                        "curl_command": curl_command,
                        "proxy_start": {
                            "started": startup.started,
                            "detail": startup.detail,
                            "error": startup.error,
                        },
                    },
                    command=cli_command,
                    error=startup.error or "proxy is not reachable",
                )
            if startup.started:
                events = (
                    HarnessEvent(
                        type="proxy_sidecar",
                        message="Started local gpt2giga proxy sidecar.",
                        payload={
                            "proxy_url": context.proxy_url,
                            "pid": startup.pid,
                        },
                    ),
                )
        try:
            data = proxy.request_json(
                "POST",
                url,
                payload=payload,
                api_key=api_key,
                timeout=context.timeout_seconds,
            )
        except proxy.ProxyRequestError as exc:
            return HarnessResult(
                ok=False,
                text="",
                raw={"url": url, "payload": payload, "curl_command": curl_command},
                command=cli_command,
                events=events,
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
            events=events,
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


def _request_messages(request: HarnessRequest) -> tuple[HarnessChatMessage, ...]:
    if request.messages:
        return request.messages
    return (HarnessChatMessage(role="user", content=request.prompt),)
