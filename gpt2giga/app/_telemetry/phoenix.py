"""Phoenix/OpenInference-specific OTLP adapters."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .otlp import (
    OtlpHttpTraceSink,
    _build_default_resource_attributes,
    _build_otlp_headers,
)
from .utils import _label_value, _safe_int


class PhoenixTraceSink(OtlpHttpTraceSink):
    """Export normalized request events to Phoenix via its OTLP/HTTP endpoint."""

    name = "phoenix"


def _build_phoenix_resource_attributes(config: Any | None) -> dict[str, Any]:
    resource_attributes = _build_default_resource_attributes(config)
    proxy_settings = getattr(config, "proxy_settings", None)
    observability = getattr(proxy_settings, "observability", None)
    phoenix = getattr(observability, "phoenix", None)
    project_name = getattr(
        phoenix,
        "project_name",
        getattr(proxy_settings, "phoenix_project_name", None),
    )
    normalized_project_name = (
        str(project_name).strip() if project_name is not None else ""
    )
    if normalized_project_name:
        resource_attributes["openinference.project.name"] = normalized_project_name
    return resource_attributes


def _build_phoenix_attributes(event: Mapping[str, Any]) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        "openinference.span.kind": _resolve_openinference_span_kind(event),
    }
    session_id = _label_value(event.get("session_id"), default="")
    if session_id:
        attributes["session.id"] = session_id
    model = _label_value(event.get("model"), default="")
    if model:
        attributes["llm.model_name"] = model
        attributes["llm.system"] = "gigachat"
        attributes["llm.provider"] = "gigachat"

    input_value = _label_value(event.get("input_value"), default="")
    if input_value:
        attributes["input.value"] = input_value
        input_mime_type = _label_value(event.get("input_mime_type"), default="")
        if input_mime_type:
            attributes["input.mime_type"] = input_mime_type

    output_value = _label_value(event.get("output_value"), default="")
    if output_value:
        attributes["output.value"] = output_value
        output_mime_type = _label_value(event.get("output_mime_type"), default="")
        if output_mime_type:
            attributes["output.mime_type"] = output_mime_type

    _add_phoenix_message_attributes(
        attributes,
        "llm.input_messages",
        event.get("input_messages"),
    )
    _add_phoenix_message_attributes(
        attributes,
        "llm.output_messages",
        event.get("output_messages"),
    )
    _add_phoenix_tools_attributes(attributes, event.get("available_tools"))

    invocation_parameters = _label_value(event.get("invocation_parameters"), default="")
    if invocation_parameters:
        attributes["llm.invocation_parameters"] = invocation_parameters

    usage = event.get("token_usage")
    if isinstance(usage, Mapping):
        attributes["llm.token_count.prompt"] = _safe_int(
            usage.get("prompt_tokens"), default=0
        )
        attributes["llm.token_count.completion"] = _safe_int(
            usage.get("completion_tokens"), default=0
        )
        attributes["llm.token_count.total"] = _safe_int(
            usage.get("total_tokens"), default=0
        )
    return attributes


def _add_phoenix_message_attributes(
    attributes: dict[str, Any],
    prefix: str,
    messages: Any,
) -> None:
    if not isinstance(messages, list):
        return
    for index, message in enumerate(messages):
        if not isinstance(message, Mapping):
            continue
        role = _label_value(message.get("role"), default="")
        content = _label_value(message.get("content"), default="")
        if role:
            attributes[f"{prefix}.{index}.message.role"] = role
        if content:
            attributes[f"{prefix}.{index}.message.content"] = content
        name = _label_value(message.get("name"), default="")
        if name:
            attributes[f"{prefix}.{index}.message.name"] = name
        tool_call_id = _label_value(message.get("tool_call_id"), default="")
        if tool_call_id:
            attributes[f"{prefix}.{index}.message.tool_call_id"] = tool_call_id
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        for tool_index, tool_call in enumerate(tool_calls):
            if not isinstance(tool_call, Mapping):
                continue
            tool_call_id = _label_value(tool_call.get("id"), default="")
            function_name = _label_value(tool_call.get("function_name"), default="")
            function_arguments = _label_value(
                tool_call.get("function_arguments"),
                default="",
            )
            if tool_call_id:
                attributes[
                    f"{prefix}.{index}.message.tool_calls.{tool_index}.tool_call.id"
                ] = tool_call_id
            if function_name:
                attributes[
                    f"{prefix}.{index}.message.tool_calls.{tool_index}.tool_call.function.name"
                ] = function_name
            if function_arguments:
                attributes[
                    f"{prefix}.{index}.message.tool_calls.{tool_index}.tool_call.function.arguments"
                ] = function_arguments


def _add_phoenix_tools_attributes(
    attributes: dict[str, Any],
    tools: Any,
) -> None:
    if not isinstance(tools, list):
        return
    for index, tool in enumerate(tools):
        if not isinstance(tool, Mapping):
            continue
        tool_type = _label_value(tool.get("type"), default="")
        if tool_type:
            attributes[f"llm.tools.{index}.tool.type"] = tool_type
        tool_name = _label_value(tool.get("name"), default="")
        if not tool_name and tool_type == "function":
            function = tool.get("function")
            if isinstance(function, Mapping):
                tool_name = _label_value(function.get("name"), default="")
        if tool_name:
            attributes[f"llm.tools.{index}.tool.name"] = tool_name
        tool_schema = json.dumps(tool, ensure_ascii=False, separators=(",", ":"))
        attributes[f"llm.tools.{index}.tool.json_schema"] = tool_schema


def _resolve_openinference_span_kind(event: Mapping[str, Any]) -> str:
    endpoint = _label_value(event.get("endpoint"), default="")
    if "embed" in endpoint:
        return "EMBEDDING"
    if endpoint:
        return "LLM"
    return "UNKNOWN"


def _build_phoenix_endpoint(config: Any | None) -> str:
    proxy_settings = getattr(config, "proxy_settings", None)
    observability = getattr(proxy_settings, "observability", None)
    phoenix = getattr(observability, "phoenix", None)
    base_url = getattr(
        phoenix,
        "base_url",
        getattr(proxy_settings, "phoenix_base_url", None),
    )
    normalized = str(base_url).strip().rstrip("/") if base_url is not None else ""
    if not normalized:
        raise RuntimeError(
            "Phoenix sink requires GPT2GIGA_PHOENIX_BASE_URL to be configured."
        )
    return f"{normalized}/v1/traces"


def _build_phoenix_headers(config: Any | None) -> dict[str, str]:
    proxy_settings = getattr(config, "proxy_settings", None)
    observability = getattr(proxy_settings, "observability", None)
    phoenix = getattr(observability, "phoenix", None)
    api_key = str(
        getattr(phoenix, "api_key", getattr(proxy_settings, "phoenix_api_key", ""))
        or ""
    ).strip()
    headers = _build_otlp_headers(config)
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    return headers
