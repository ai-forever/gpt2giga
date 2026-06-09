"""Infer safe caller metadata from incoming request headers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

MAX_CALLER_VALUE_LENGTH = 256


@dataclass(frozen=True)
class CallerInfo:
    """Describe the likely external caller of one gateway request."""

    name: str
    category: str
    client_family: str | None = None
    sdk: str | None = None
    agent: str | None = None
    ui: str | None = None
    user_agent: str | None = None
    agent_id: str | None = None

    def to_attributes(self) -> dict[str, str]:
        """Return scalar attributes suitable for trace filtering."""
        fields = {
            "caller.name": self.name,
            "caller.category": self.category,
            "caller.client_family": self.client_family,
            "caller.sdk": self.sdk,
            "caller.agent": self.agent,
            "caller.ui": self.ui,
            "caller.user_agent": self.user_agent,
            "caller.agent_id": self.agent_id,
        }
        return {key: value for key, value in fields.items() if value}

    def to_annotations(self) -> dict[str, Any]:
        """Return structured annotations for observability metadata."""
        caller = {
            "name": self.name,
            "category": self.category,
            "client_family": self.client_family,
            "sdk": self.sdk,
            "agent": self.agent,
            "ui": self.ui,
            "user_agent": self.user_agent,
            "agent_id": self.agent_id,
        }
        return {"caller": {key: value for key, value in caller.items() if value}}


def infer_request_caller(headers: Mapping[str, Any]) -> CallerInfo:
    """Infer the caller family from safe, non-secret request headers."""
    normalized = _normalize_headers(headers)
    user_agent = _clean_header_value(normalized.get("user-agent"))
    agent_id = _clean_header_value(normalized.get("x-agent-id"))
    client_family = _client_family_from_headers(normalized, user_agent)

    ui = _ui_from_referer(normalized.get("referer"))
    if ui is not None:
        return CallerInfo(
            name=f"{ui}-ui",
            category="ui",
            client_family=client_family,
            ui=ui,
            user_agent=user_agent,
            agent_id=agent_id,
        )

    agent = _agent_from_user_agent(user_agent)
    if agent is not None:
        return CallerInfo(
            name=agent,
            category="agent",
            client_family=client_family or _client_family_for_agent(agent),
            agent=agent,
            user_agent=user_agent,
            agent_id=agent_id,
        )

    sdk = _sdk_from_user_agent(user_agent, client_family)
    if sdk is not None:
        return CallerInfo(
            name=sdk,
            category="sdk",
            client_family=client_family or _client_family_for_sdk(sdk),
            sdk=sdk,
            user_agent=user_agent,
            agent_id=agent_id,
        )

    if user_agent and _looks_like_browser(user_agent):
        return CallerInfo(
            name="browser",
            category="browser",
            client_family=client_family,
            user_agent=user_agent,
            agent_id=agent_id,
        )

    if user_agent:
        return CallerInfo(
            name=_generic_client_name(user_agent),
            category="http_client",
            client_family=client_family,
            user_agent=user_agent,
            agent_id=agent_id,
        )

    return CallerInfo(
        name="unknown",
        category="unknown",
        client_family=client_family,
        agent_id=agent_id,
    )


def _normalize_headers(headers: Mapping[str, Any]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for name, value in headers.items():
        if not isinstance(name, str) or value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            normalized[name.strip().lower()] = str(value)
    return normalized


def _clean_header_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    if not cleaned:
        return None
    return cleaned[:MAX_CALLER_VALUE_LENGTH]


def _client_family_from_headers(
    headers: Mapping[str, str],
    user_agent: str | None,
) -> str | None:
    if "anthropic-version" in headers or "anthropic-beta" in headers:
        return "anthropic"
    if any(name.startswith("anthropic-") for name in headers):
        return "anthropic"
    if any(name.startswith("openai-") for name in headers):
        return "openai"
    lowered = (user_agent or "").lower()
    if "anthropic" in lowered or "claude-code" in lowered:
        return "anthropic"
    if "openai" in lowered or "codex" in lowered:
        return "openai"
    return None


def _ui_from_referer(referer: str | None) -> str | None:
    value = _clean_header_value(referer)
    if value is None:
        return None
    path = urlsplit(value).path.rstrip("/") or "/"
    if path.endswith("/docs"):
        return "swagger"
    if path.endswith("/redoc"):
        return "redoc"
    return None


def _agent_from_user_agent(user_agent: str | None) -> str | None:
    lowered = (user_agent or "").lower()
    if "claude-code" in lowered or "claude code" in lowered:
        return "claude-code"
    if "qwen-code" in lowered or "qwen_code" in lowered or "qwen code" in lowered:
        return "qwen-code"
    if "openai-codex" in lowered or "codex-cli" in lowered or "codex" in lowered:
        return "codex"
    return None


def _client_family_for_agent(agent: str) -> str | None:
    if agent == "claude-code":
        return "anthropic"
    if agent == "codex":
        return "openai"
    return None


def _sdk_from_user_agent(
    user_agent: str | None,
    client_family: str | None,
) -> str | None:
    lowered = (user_agent or "").lower()
    if "openai/python" in lowered or "openai-python" in lowered:
        return "openai-python"
    if "openai/node" in lowered or "openai-js" in lowered or "openai-node" in lowered:
        return "openai-node"
    if "anthropic/python" in lowered or "anthropic-python" in lowered:
        return "anthropic-python"
    if "anthropic/typescript" in lowered or "anthropic-js" in lowered:
        return "anthropic-node"
    if lowered.startswith("openai/"):
        return "openai-sdk"
    if lowered.startswith("anthropic/"):
        return "anthropic-sdk"
    if client_family == "openai":
        return "openai-compatible"
    if client_family == "anthropic":
        return "anthropic-compatible"
    return None


def _client_family_for_sdk(sdk: str) -> str | None:
    if sdk.startswith("openai"):
        return "openai"
    if sdk.startswith("anthropic"):
        return "anthropic"
    return None


def _looks_like_browser(user_agent: str) -> bool:
    lowered = user_agent.lower()
    return "mozilla/" in lowered or "chrome/" in lowered or "safari/" in lowered


def _generic_client_name(user_agent: str) -> str:
    token = user_agent.split(" ", 1)[0].split("/", 1)[0].strip().lower()
    token = re.sub(r"[^a-z0-9_.-]+", "-", token).strip("-")
    return token or "http-client"
