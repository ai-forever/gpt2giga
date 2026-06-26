"""Compatibility analysis entry points."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlsplit

from gpt2giga.common.client_params import normalize_header_name
from gpt2giga.common.model_concurrency import DEFAULT_GIGACHAT_MODEL
from gpt2giga.common.tools import (
    iter_function_tool_payloads,
    normalize_gigachat_builtin_tool_type,
)
from gpt2giga.diagnostics.fields import build_field_compatibility
from gpt2giga.diagnostics.models import (
    BackendMode,
    BuiltinToolMappingDiagnostic,
    CompatibilityAnalysis,
    CompatibilityProtocol,
    FieldCompatibility,
    ModelResolutionDiagnostic,
    ProtocolDiagnosticWarning,
    SecurityRedactionDiagnostic,
    ToolDecisionDiagnostic,
    ToolCompatibility,
)
from gpt2giga.diagnostics.tools import build_builtin_tool_mapping, build_tool_decision
from gpt2giga.protocol.anthropic.params import (
    ANTHROPIC_ACCEPTED_IGNORED_PARAMS,
    ANTHROPIC_MESSAGES_SUPPORTED_PARAMS,
)
from gpt2giga.protocol.request.params import (
    OPENAI_ACCEPTED_IGNORED_PARAMS,
    OPENAI_CHAT_SUPPORTED_PARAMS,
    OPENAI_GIGACHAT_ADDITIONAL_FIELD_KEYS,
    OPENAI_RESPONSES_SUPPORTED_PARAMS,
)

_OPENAI_EMBEDDINGS_SUPPORTED_PARAMS = frozenset(
    {
        "encoding_format",
        "extra_body",
        "extra_headers",
        "extra_query",
        "input",
        "model",
    }
)
_OPENAI_MODEL_DISCOVERY_SUPPORTED_QUERY_PARAMS = frozenset(
    {"after_id", "before_id", "limit", "model"}
)
_GEMINI_GENERATE_SUPPORTED_PARAMS = frozenset(
    {
        "contents",
        "generationConfig",
        "generation_config",
        "metadata",
        "systemInstruction",
        "system_instruction",
        "toolConfig",
        "tool_config",
        "tools",
    }
)
_GEMINI_GENERATE_DIAGNOSTIC_ONLY_PARAMS = frozenset(
    {
        "cachedContent",
        "cached_content",
        "safetySettings",
        "safety_settings",
        "serviceTier",
        "service_tier",
        "store",
    }
)
_GEMINI_COUNT_TOKENS_SUPPORTED_PARAMS = frozenset(
    {
        "contents",
        "generateContentRequest",
        "generate_content_request",
        "model",
        "tools",
    }
)
_GEMINI_EMBED_SUPPORTED_PARAMS = frozenset(
    {
        "content",
        "model",
        "taskType",
        "task_type",
        "title",
    }
)
_GEMINI_BATCH_EMBED_SUPPORTED_PARAMS = frozenset({"requests"})
_SENSITIVE_HEADER_NAMES = frozenset(
    {
        "authorization",
        "cookie",
        "proxy-authorization",
        "set-cookie",
        "x-api-key",
        "x-goog-api-key",
    }
)
_SENSITIVE_QUERY_NAMES = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "key",
        "token",
        "x-api-key",
        "x-goog-api-key",
    }
)
_SENSITIVE_BODY_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
)
_ANTHROPIC_NAMED_BUILTIN_TOOLS = {
    "CodeExecution": "code_interpreter",
    "WebFetch": "url_content_extraction",
    "WebSearch": "web_search",
}
_GEMINI_OPERATION_RE = re.compile(r"^/v1beta/models/(?P<model>[^:]+):(?P<method>.+)$")
_MODEL_ROUTE_RE = re.compile(r"^/models(?:/[^/]+)?$")


def build_empty_analysis(
    *,
    protocol: CompatibilityProtocol,
    route: str,
    operation: str,
    backend_mode: BackendMode = "unknown",
) -> CompatibilityAnalysis:
    """Build an empty compatibility analysis envelope."""
    return CompatibilityAnalysis(
        protocol=protocol,
        route=route,
        operation=operation,
        backend_mode=backend_mode,
    )


def analyze_compatibility_request(
    *,
    route: str,
    protocol: CompatibilityProtocol | None = None,
    headers: Mapping[str, Any] | None = None,
    query: Mapping[str, Any] | None = None,
    body: Mapping[str, Any] | None = None,
    config: Any | None = None,
) -> CompatibilityAnalysis:
    """Analyze a gateway request shape without calling the upstream provider."""
    request_body = dict(body or {})
    normalized_route = _normalize_route(route)
    backend_mode = _resolve_backend_mode(normalized_route, config)
    routed_path = _strip_backend_prefix(normalized_route)
    inferred_protocol = protocol or _infer_protocol(
        routed_path,
        headers=headers,
        query=query,
    )
    operation = _operation_for_route(inferred_protocol, routed_path)
    fields = _field_compatibility(
        protocol=inferred_protocol,
        operation=operation,
        backend_mode=backend_mode,
        body=request_body,
    )
    tools = _tool_compatibility(
        protocol=inferred_protocol,
        operation=operation,
        backend_mode=backend_mode,
        body=request_body,
        config=config,
    )
    security = _security_redaction(headers=headers, query=query, body=request_body)
    warnings = _warnings_for_analysis(
        protocol=inferred_protocol,
        operation=operation,
        fields=fields,
        tools=tools,
        body=request_body,
    )

    return CompatibilityAnalysis(
        protocol=inferred_protocol,
        route=normalized_route,
        operation=operation,
        backend_mode=backend_mode,
        model=_model_resolution(
            protocol=inferred_protocol,
            operation=operation,
            route=routed_path,
            body=request_body,
            config=config,
        ),
        fields=fields,
        tools=tools,
        security=security,
        warnings=warnings,
    )


def _normalize_route(route: str) -> str:
    path = urlsplit(route).path if "://" in route or "?" in route else route
    path = f"/{path}" if not path.startswith("/") else path
    return path.rstrip("/") or "/"


def _resolve_backend_mode(route: str, config: Any | None) -> BackendMode:
    if route == "/v1" or route.startswith("/v1/"):
        return "gigachat_v1"
    if route == "/v2" or route.startswith("/v2/"):
        return "gigachat_v2"

    mode = getattr(_proxy_settings(config), "gigachat_api_mode", None)
    if mode == "v1":
        return "gigachat_v1"
    if mode == "v2":
        return "gigachat_v2"
    return "unknown"


def _strip_backend_prefix(route: str) -> str:
    if route.startswith("/v1/v1beta/"):
        return route.removeprefix("/v1")
    if route.startswith("/v2/v1beta/"):
        return route.removeprefix("/v2")
    for prefix in ("/v1", "/v2"):
        if route == prefix:
            return "/"
        if route.startswith(f"{prefix}/"):
            return route.removeprefix(prefix)
    return route


def _infer_protocol(
    path: str,
    *,
    headers: Mapping[str, Any] | None,
    query: Mapping[str, Any] | None,
) -> CompatibilityProtocol:
    if path.startswith("/v1beta/"):
        return "gemini"
    if path.startswith("/messages"):
        return "anthropic"
    if path == "/model/info":
        return "litellm"
    if path.startswith("/models"):
        normalized_headers = {
            normalize_header_name(key)
            for key in (headers or {})
            if isinstance(key, str)
        }
        if "x-goog-api-key" in normalized_headers or (query or {}).get("key"):
            return "gemini"
        if "anthropic-version" in normalized_headers:
            return "anthropic"
    if path.startswith(("/chat/", "/responses", "/embeddings", "/models")):
        return "openai"
    return "unknown"


def _operation_for_route(protocol: CompatibilityProtocol, path: str) -> str:
    if protocol == "openai":
        if path == "/chat/completions":
            return "chat_completions"
        if path == "/responses":
            return "responses"
        if path == "/embeddings":
            return "embeddings"
        if _MODEL_ROUTE_RE.match(path):
            return "model_discovery"
    if protocol == "anthropic":
        if path == "/messages/count_tokens":
            return "count_tokens"
        if path == "/messages":
            return "messages"
        if _MODEL_ROUTE_RE.match(path):
            return "model_discovery"
    if protocol == "gemini":
        match = _GEMINI_OPERATION_RE.match(path)
        if match:
            return _gemini_method_operation(match.group("method"))
        if path == "/v1beta/models" or re.match(r"^/v1beta/models/[^:]+$", path):
            return "model_discovery"
    if protocol == "litellm" and path == "/model/info":
        return "model_info"
    return "unknown"


def _gemini_method_operation(method: str) -> str:
    return {
        "batchEmbedContents": "batch_embed_contents",
        "countTokens": "count_tokens",
        "embedContent": "embed_content",
        "generateContent": "generate_content",
        "streamGenerateContent": "stream_generate_content",
    }.get(method, "unknown")


def _field_compatibility(
    *,
    protocol: CompatibilityProtocol,
    operation: str,
    backend_mode: BackendMode,
    body: Mapping[str, Any],
) -> FieldCompatibility:
    supported: Iterable[str]
    accepted_ignored: Iterable[str] = ()
    diagnostic_only: Iterable[str] = ()
    approximated: Iterable[str] = ()

    if protocol == "openai" and operation == "chat_completions":
        supported = OPENAI_CHAT_SUPPORTED_PARAMS | OPENAI_GIGACHAT_ADDITIONAL_FIELD_KEYS
        accepted_ignored = OPENAI_ACCEPTED_IGNORED_PARAMS
    elif protocol == "openai" and operation == "responses":
        supported_set = (
            OPENAI_RESPONSES_SUPPORTED_PARAMS | OPENAI_GIGACHAT_ADDITIONAL_FIELD_KEYS
        )
        if backend_mode == "gigachat_v2":
            supported_set = supported_set | {"previous_response_id", "store"}
        supported = supported_set
        accepted_ignored = OPENAI_ACCEPTED_IGNORED_PARAMS - set(supported_set)
    elif protocol == "openai" and operation == "embeddings":
        supported = _OPENAI_EMBEDDINGS_SUPPORTED_PARAMS
        accepted_ignored = {"dimensions", "user"}
    elif protocol in {"openai", "anthropic", "gemini"} and operation == (
        "model_discovery"
    ):
        supported = ()
        diagnostic_only = _OPENAI_MODEL_DISCOVERY_SUPPORTED_QUERY_PARAMS
    elif protocol == "anthropic" and operation in {"messages", "count_tokens"}:
        supported = ANTHROPIC_MESSAGES_SUPPORTED_PARAMS
        accepted_ignored = ANTHROPIC_ACCEPTED_IGNORED_PARAMS
        if operation == "count_tokens":
            approximated = {"tools", "output_config", "output_format"}
    elif protocol == "gemini" and operation in {
        "generate_content",
        "stream_generate_content",
    }:
        supported = _GEMINI_GENERATE_SUPPORTED_PARAMS
        diagnostic_only = _GEMINI_GENERATE_DIAGNOSTIC_ONLY_PARAMS
    elif protocol == "gemini" and operation == "count_tokens":
        supported = _GEMINI_COUNT_TOKENS_SUPPORTED_PARAMS
        approximated = {"tools"}
    elif protocol == "gemini" and operation == "embed_content":
        supported = _GEMINI_EMBED_SUPPORTED_PARAMS
        diagnostic_only = {"outputDimensionality", "output_dimensionality"}
    elif protocol == "gemini" and operation == "batch_embed_contents":
        supported = _GEMINI_BATCH_EMBED_SUPPORTED_PARAMS
    else:
        supported = ()
        diagnostic_only = body.keys()

    return _classify_body_fields(
        body.keys(),
        supported=supported,
        accepted_ignored=accepted_ignored,
        accepted_diagnostic_only=diagnostic_only,
        approximated=approximated,
    )


def _classify_body_fields(
    field_names: Iterable[str],
    *,
    supported: Iterable[str],
    accepted_ignored: Iterable[str] = (),
    accepted_diagnostic_only: Iterable[str] = (),
    approximated: Iterable[str] = (),
    rejected: Iterable[str] = (),
) -> FieldCompatibility:
    supported_set = set(supported)
    ignored_set = set(accepted_ignored)
    diagnostic_set = set(accepted_diagnostic_only)
    approximated_set = set(approximated)
    rejected_set = set(rejected)
    actual_supported = []
    actual_ignored = []
    actual_diagnostic = []
    actual_approximated = []
    actual_rejected = []

    for name in field_names:
        if name in supported_set:
            actual_supported.append(name)
        elif name in ignored_set:
            actual_ignored.append(name)
        elif name in diagnostic_set:
            actual_diagnostic.append(name)
        elif name in approximated_set:
            actual_approximated.append(name)
        elif name in rejected_set:
            actual_rejected.append(name)
        else:
            actual_diagnostic.append(name)

    return build_field_compatibility(
        supported=actual_supported,
        accepted_ignored=actual_ignored,
        accepted_diagnostic_only=actual_diagnostic,
        approximated=actual_approximated,
        rejected=actual_rejected,
    )


def _tool_compatibility(
    *,
    protocol: CompatibilityProtocol,
    operation: str,
    backend_mode: BackendMode,
    body: Mapping[str, Any],
    config: Any | None,
) -> ToolCompatibility:
    if operation not in {
        "chat_completions",
        "responses",
        "messages",
        "generate_content",
        "stream_generate_content",
        "count_tokens",
    }:
        return ToolCompatibility()

    mapping_enabled = _builtin_tool_mapping_enabled(config)
    builtin_mapping_available = backend_mode == "gigachat_v2" and mapping_enabled
    mapping_unavailable_reason = _builtin_mapping_unavailable_reason(
        backend_mode,
        mapping_enabled,
    )
    if protocol == "anthropic":
        return _anthropic_tool_compatibility(
            body,
            builtin_mapping_available,
            mapping_unavailable_reason=mapping_unavailable_reason,
        )
    if protocol == "gemini":
        return _gemini_tool_compatibility(
            body,
            builtin_mapping_available,
            mapping_unavailable_reason=mapping_unavailable_reason,
        )
    return _openai_tool_compatibility(
        body,
        builtin_mapping_available,
        mapping_unavailable_reason=mapping_unavailable_reason,
    )


def _openai_tool_compatibility(
    body: Mapping[str, Any],
    builtin_mapping_available: bool,
    *,
    mapping_unavailable_reason: str | None,
) -> ToolCompatibility:
    user_functions = _openai_user_function_names(body)
    mapped_builtin_tools, unsupported_tools, builtin_details = _openai_builtin_tools(
        body.get("tools"),
        mapping_available=builtin_mapping_available,
        mapping_unavailable_reason=mapping_unavailable_reason,
    )
    forced_tool_choice_supported = _openai_forced_tool_choice_supported(
        body,
        mapped_builtin_tools=mapped_builtin_tools,
        mapping_available=builtin_mapping_available,
    )
    return ToolCompatibility(
        user_functions=user_functions,
        mapped_builtin_tools=mapped_builtin_tools,
        unsupported_tools=unsupported_tools,
        details=[
            *_user_function_details(
                source=_openai_user_function_source(body),
                names=user_functions,
            ),
            *builtin_details,
            *_openai_tool_choice_details(
                body,
                supported=forced_tool_choice_supported,
                mapping_unavailable_reason=mapping_unavailable_reason,
            ),
        ],
        mapping_disabled=not builtin_mapping_available,
        forced_tool_choice_supported=forced_tool_choice_supported,
    )


def _openai_user_function_names(body: Mapping[str, Any]) -> list[str]:
    names = []
    for payload in iter_function_tool_payloads(dict(body), require_parameters=False):
        name = payload.get("name")
        if isinstance(name, str) and name and name not in names:
            names.append(name)
    return names


def _openai_user_function_source(body: Mapping[str, Any]) -> str:
    tools = body.get("tools")
    if isinstance(tools, list) and tools:
        return "openai.tools"
    return "openai.functions"


def _openai_builtin_tools(
    tools: Any,
    *,
    mapping_available: bool,
    mapping_unavailable_reason: str | None,
) -> tuple[
    list[BuiltinToolMappingDiagnostic],
    list[str],
    list[ToolDecisionDiagnostic],
]:
    if not isinstance(tools, list):
        return [], [], []

    mapped = []
    unsupported = []
    details = []
    for index, tool in enumerate(tools):
        if not isinstance(tool, Mapping):
            continue
        tool_type = tool.get("type")
        target = normalize_gigachat_builtin_tool_type(tool_type)
        if target is None:
            if tool_type not in {None, "function", "namespace"}:
                unsupported.append(str(tool_type))
                details.append(
                    build_tool_decision(
                        source="openai.tools",
                        category="provider_builtin",
                        decision="unsupported",
                        name=str(tool_type),
                        reason="unsupported_tool_type",
                        field=f"tools[{index}].type",
                    )
                )
            continue
        if mapping_available:
            mapped.append(
                build_builtin_tool_mapping(
                    from_name=str(tool_type),
                    to_name=target,
                    reason="provider_alias",
                )
            )
            details.append(
                build_tool_decision(
                    source="openai.tools",
                    category="provider_builtin",
                    decision="mapped",
                    name=str(tool_type),
                    target=target,
                    reason="provider_alias",
                    field=f"tools[{index}].type",
                )
            )
        else:
            unsupported.append(str(tool_type))
            details.append(
                build_tool_decision(
                    source="openai.tools",
                    category="provider_builtin",
                    decision="unsupported",
                    name=str(tool_type),
                    target=target,
                    reason=mapping_unavailable_reason,
                    field=f"tools[{index}].type",
                )
            )
    return mapped, _dedupe(unsupported), details


def _openai_forced_tool_choice_supported(
    body: Mapping[str, Any],
    *,
    mapped_builtin_tools: list[BuiltinToolMappingDiagnostic],
    mapping_available: bool,
) -> bool | None:
    tool_choice = body.get("tool_choice")
    function_call = body.get("function_call")
    if tool_choice is None and function_call is None:
        return None
    if isinstance(function_call, Mapping) and function_call.get("name"):
        return True
    if isinstance(tool_choice, str):
        return tool_choice in {"auto", "none"}
    if not isinstance(tool_choice, Mapping):
        return False
    choice_type = tool_choice.get("type")
    if choice_type in {"function", "namespace"}:
        return True
    target = normalize_gigachat_builtin_tool_type(choice_type)
    if target is None:
        return False
    return mapping_available and any(
        item.to_name == target for item in mapped_builtin_tools
    )


def _openai_tool_choice_details(
    body: Mapping[str, Any],
    *,
    supported: bool | None,
    mapping_unavailable_reason: str | None,
) -> list[ToolDecisionDiagnostic]:
    tool_choice = body.get("tool_choice")
    function_call = body.get("function_call")
    if tool_choice is None and function_call is None:
        return []
    if isinstance(function_call, Mapping) and function_call.get("name"):
        return [
            build_tool_decision(
                source="openai.function_call",
                category="tool_choice",
                decision="supported",
                name=str(function_call["name"]),
                reason="forced_function_call",
                field="function_call.name",
            )
        ]
    if isinstance(tool_choice, str):
        reason = {
            "auto": "automatic_tool_choice",
            "none": "tools_disabled_by_choice",
            "required": "required_tool_choice_not_enforced",
        }.get(tool_choice, "unsupported_tool_choice")
        return [
            build_tool_decision(
                source="openai.tool_choice",
                category="tool_choice",
                decision="supported" if supported else "unsupported",
                name=tool_choice,
                reason=reason,
                field="tool_choice",
            )
        ]
    if not isinstance(tool_choice, Mapping):
        return [
            build_tool_decision(
                source="openai.tool_choice",
                category="tool_choice",
                decision="unsupported",
                reason="invalid_tool_choice_shape",
                field="tool_choice",
            )
        ]
    choice_type = tool_choice.get("type")
    target = normalize_gigachat_builtin_tool_type(choice_type)
    if choice_type in {"function", "namespace"}:
        function = tool_choice.get("function")
        name = function.get("name") if isinstance(function, Mapping) else None
        if name is None:
            name = tool_choice.get("name")
        return [
            build_tool_decision(
                source="openai.tool_choice",
                category="tool_choice",
                decision="supported" if supported else "unsupported",
                name=str(name) if name else None,
                reason=(
                    "forced_function_tool"
                    if choice_type == "function"
                    else "forced_namespace_tool"
                ),
                field="tool_choice",
            )
        ]
    return [
        build_tool_decision(
            source="openai.tool_choice",
            category="tool_choice",
            decision="supported" if supported else "unsupported",
            name=str(choice_type) if choice_type is not None else None,
            target=target,
            reason=(
                "forced_builtin_tool"
                if supported and target
                else mapping_unavailable_reason or "unsupported_tool_choice"
            ),
            field="tool_choice.type",
        )
    ]


def _anthropic_tool_compatibility(
    body: Mapping[str, Any],
    builtin_mapping_available: bool,
    *,
    mapping_unavailable_reason: str | None,
) -> ToolCompatibility:
    tools = body.get("tools")
    user_functions: list[str] = []
    mapped: list[BuiltinToolMappingDiagnostic] = []
    unsupported: list[str] = []
    details: list[ToolDecisionDiagnostic] = []
    if isinstance(tools, list):
        for index, tool in enumerate(tools):
            if not isinstance(tool, Mapping):
                continue
            name = tool.get("name")
            tool_type = tool.get("type")
            builtin_target = normalize_gigachat_builtin_tool_type(tool_type)
            if builtin_target is None and isinstance(name, str):
                builtin_target = _ANTHROPIC_NAMED_BUILTIN_TOOLS.get(name)
            if builtin_target is not None:
                source = str(tool_type or name)
                field = f"tools[{index}].type" if tool_type else f"tools[{index}].name"
                if builtin_mapping_available:
                    mapped.append(
                        build_builtin_tool_mapping(
                            from_name=source,
                            to_name=builtin_target,
                            reason="provider_alias",
                        )
                    )
                    details.append(
                        build_tool_decision(
                            source="anthropic.tools",
                            category="provider_builtin",
                            decision="mapped",
                            name=source,
                            target=builtin_target,
                            reason="provider_alias",
                            field=field,
                        )
                    )
                else:
                    unsupported.append(source)
                    details.append(
                        build_tool_decision(
                            source="anthropic.tools",
                            category="provider_builtin",
                            decision="unsupported",
                            name=source,
                            target=builtin_target,
                            reason=mapping_unavailable_reason,
                            field=field,
                        )
                    )
                continue
            if tool_type not in {None, "custom"}:
                unsupported.append(str(tool_type))
                details.append(
                    build_tool_decision(
                        source="anthropic.tools",
                        category="provider_builtin",
                        decision="unsupported",
                        name=str(tool_type),
                        reason="unsupported_tool_type",
                        field=f"tools[{index}].type",
                    )
                )
                continue
            if isinstance(name, str) and name and name not in user_functions:
                user_functions.append(name)
                details.append(
                    build_tool_decision(
                        source="anthropic.tools",
                        category="user_function",
                        decision="supported",
                        name=name,
                        reason="custom_function",
                        field=f"tools[{index}].name",
                    )
                )
    forced_tool_choice_supported = _anthropic_forced_tool_choice_supported(
        body,
        mapping_available=builtin_mapping_available,
    )
    return ToolCompatibility(
        user_functions=user_functions,
        mapped_builtin_tools=mapped,
        unsupported_tools=_dedupe(unsupported),
        details=[
            *details,
            *_anthropic_tool_choice_details(
                body,
                supported=forced_tool_choice_supported,
                mapping_available=builtin_mapping_available,
                mapping_unavailable_reason=mapping_unavailable_reason,
            ),
        ],
        mapping_disabled=not builtin_mapping_available,
        forced_tool_choice_supported=forced_tool_choice_supported,
    )


def _anthropic_forced_tool_choice_supported(
    body: Mapping[str, Any],
    *,
    mapping_available: bool,
) -> bool | None:
    tool_choice = body.get("tool_choice")
    if tool_choice is None:
        return None
    if not isinstance(tool_choice, Mapping):
        return False
    choice_type = tool_choice.get("type")
    if choice_type in {"auto", "none"}:
        return True
    if choice_type != "tool":
        return False
    name = tool_choice.get("name")
    if not isinstance(name, str) or not name:
        return False
    builtin_target = _anthropic_builtin_tool_choice_target(name, body.get("tools"))
    if builtin_target is not None:
        return mapping_available
    return True


def _anthropic_tool_choice_details(
    body: Mapping[str, Any],
    *,
    supported: bool | None,
    mapping_available: bool,
    mapping_unavailable_reason: str | None,
) -> list[ToolDecisionDiagnostic]:
    tool_choice = body.get("tool_choice")
    if tool_choice is None:
        return []
    if not isinstance(tool_choice, Mapping):
        return [
            build_tool_decision(
                source="anthropic.tool_choice",
                category="tool_choice",
                decision="unsupported",
                reason="invalid_tool_choice_shape",
                field="tool_choice",
            )
        ]
    choice_type = tool_choice.get("type")
    if choice_type in {"auto", "none"}:
        return [
            build_tool_decision(
                source="anthropic.tool_choice",
                category="tool_choice",
                decision="supported",
                name=str(choice_type),
                reason=(
                    "automatic_tool_choice"
                    if choice_type == "auto"
                    else "tools_disabled_by_choice"
                ),
                field="tool_choice.type",
            )
        ]
    name = tool_choice.get("name")
    if choice_type != "tool" or not isinstance(name, str) or not name:
        return [
            build_tool_decision(
                source="anthropic.tool_choice",
                category="tool_choice",
                decision="unsupported",
                reason="unsupported_tool_choice",
                field="tool_choice",
            )
        ]
    builtin_target = _anthropic_builtin_tool_choice_target(name, body.get("tools"))
    if builtin_target is not None:
        return [
            build_tool_decision(
                source="anthropic.tool_choice",
                category="tool_choice",
                decision="supported"
                if mapping_available and supported
                else "unsupported",
                name=name,
                target=builtin_target,
                reason=(
                    "forced_builtin_tool"
                    if mapping_available
                    else mapping_unavailable_reason
                ),
                field="tool_choice.name",
            )
        ]
    return [
        build_tool_decision(
            source="anthropic.tool_choice",
            category="tool_choice",
            decision="supported" if supported else "unsupported",
            name=name,
            reason="forced_function_tool",
            field="tool_choice.name",
        )
    ]


def _anthropic_builtin_tool_choice_target(
    tool_name: str,
    tools: Any,
) -> str | None:
    builtin_target = _ANTHROPIC_NAMED_BUILTIN_TOOLS.get(tool_name)
    if builtin_target is not None:
        return builtin_target
    if not isinstance(tools, list):
        return None
    for tool in tools:
        if not isinstance(tool, Mapping) or tool.get("name") != tool_name:
            continue
        return normalize_gigachat_builtin_tool_type(tool.get("type"))
    return None


def _gemini_tool_compatibility(
    body: Mapping[str, Any],
    builtin_mapping_available: bool,
    *,
    mapping_unavailable_reason: str | None,
) -> ToolCompatibility:
    tools = body.get("tools")
    user_functions: list[str] = []
    mapped: list[BuiltinToolMappingDiagnostic] = []
    unsupported: list[str] = []
    details: list[ToolDecisionDiagnostic] = []
    if isinstance(tools, list):
        for tool_index, tool in enumerate(tools):
            if not isinstance(tool, Mapping):
                continue
            for key in tool:
                if key in {"functionDeclarations", "function_declarations"}:
                    continue
                target = normalize_gigachat_builtin_tool_type(key)
                if target is None:
                    unsupported.append(str(key))
                    details.append(
                        build_tool_decision(
                            source="gemini.tools",
                            category="provider_builtin",
                            decision="unsupported",
                            name=str(key),
                            reason="unsupported_tool_key",
                            field=f"tools[{tool_index}].{key}",
                        )
                    )
                elif builtin_mapping_available:
                    mapped.append(
                        build_builtin_tool_mapping(
                            from_name=str(key),
                            to_name=target,
                            reason="provider_alias",
                        )
                    )
                    details.append(
                        build_tool_decision(
                            source="gemini.tools",
                            category="provider_builtin",
                            decision="mapped",
                            name=str(key),
                            target=target,
                            reason="provider_alias",
                            field=f"tools[{tool_index}].{key}",
                        )
                    )
                else:
                    unsupported.append(str(key))
                    details.append(
                        build_tool_decision(
                            source="gemini.tools",
                            category="provider_builtin",
                            decision="unsupported",
                            name=str(key),
                            target=target,
                            reason=mapping_unavailable_reason,
                            field=f"tools[{tool_index}].{key}",
                        )
                    )
            declarations = tool.get("functionDeclarations")
            if declarations is None:
                declarations = tool.get("function_declarations")
            for declaration_index, declaration in enumerate(_as_list(declarations)):
                if not isinstance(declaration, Mapping):
                    continue
                name = declaration.get("name")
                if isinstance(name, str) and name and name not in user_functions:
                    user_functions.append(name)
                    details.append(
                        build_tool_decision(
                            source="gemini.tools",
                            category="user_function",
                            decision="supported",
                            name=name,
                            reason="function_declaration",
                            field=(
                                f"tools[{tool_index}]."
                                f"functionDeclarations[{declaration_index}].name"
                            ),
                        )
                    )
    forced_tool_choice_supported = _gemini_forced_tool_choice_supported(
        body,
        user_functions=user_functions,
    )
    return ToolCompatibility(
        user_functions=user_functions,
        mapped_builtin_tools=mapped,
        unsupported_tools=_dedupe(unsupported),
        details=[
            *details,
            *_gemini_tool_choice_details(
                body,
                user_functions=user_functions,
                supported=forced_tool_choice_supported,
            ),
        ],
        mapping_disabled=not builtin_mapping_available,
        forced_tool_choice_supported=forced_tool_choice_supported,
    )


def _gemini_forced_tool_choice_supported(
    body: Mapping[str, Any],
    *,
    user_functions: list[str],
) -> bool | None:
    tool_config = _first_mapping(body, "toolConfig", "tool_config")
    function_config = _first_mapping(
        tool_config,
        "functionCallingConfig",
        "function_calling_config",
    )
    if not function_config:
        return None
    mode = function_config.get("mode")
    if not isinstance(mode, str):
        return False
    normalized_mode = mode.strip().upper()
    if normalized_mode in {"AUTO", "MODE_UNSPECIFIED", "NONE"}:
        return True
    if normalized_mode != "ANY":
        return False
    allowed = function_config.get("allowedFunctionNames")
    if allowed is None:
        allowed = function_config.get("allowed_function_names")
    if allowed is None:
        return len(user_functions) == 1
    if not isinstance(allowed, list):
        return False
    allowed_names = [item for item in allowed if isinstance(item, str) and item]
    return len(allowed_names) == 1 and all(
        item in user_functions for item in allowed_names
    )


def _gemini_tool_choice_details(
    body: Mapping[str, Any],
    *,
    user_functions: list[str],
    supported: bool | None,
) -> list[ToolDecisionDiagnostic]:
    tool_config = _first_mapping(body, "toolConfig", "tool_config")
    function_config = _first_mapping(
        tool_config,
        "functionCallingConfig",
        "function_calling_config",
    )
    if not function_config:
        return []
    mode = function_config.get("mode")
    allowed = function_config.get("allowedFunctionNames")
    if allowed is None:
        allowed = function_config.get("allowed_function_names")
    if not isinstance(mode, str):
        return [
            build_tool_decision(
                source="gemini.toolConfig",
                category="tool_choice",
                decision="unsupported",
                reason="invalid_function_calling_mode",
                field="toolConfig.functionCallingConfig.mode",
            )
        ]
    normalized_mode = mode.strip().upper()
    if normalized_mode in {"AUTO", "MODE_UNSPECIFIED", "NONE"}:
        return [
            build_tool_decision(
                source="gemini.toolConfig",
                category="tool_choice",
                decision="supported",
                name=normalized_mode,
                reason=(
                    "automatic_tool_choice"
                    if normalized_mode != "NONE"
                    else "tools_disabled_by_choice"
                ),
                field="toolConfig.functionCallingConfig.mode",
            )
        ]
    if normalized_mode != "ANY":
        return [
            build_tool_decision(
                source="gemini.toolConfig",
                category="tool_choice",
                decision="unsupported",
                name=mode,
                reason="unsupported_function_calling_mode",
                field="toolConfig.functionCallingConfig.mode",
            )
        ]
    if allowed is not None and not isinstance(allowed, list):
        return [
            build_tool_decision(
                source="gemini.toolConfig",
                category="tool_choice",
                decision="unsupported",
                reason="invalid_allowed_function_names",
                field="toolConfig.functionCallingConfig.allowedFunctionNames",
            )
        ]
    allowed_names = (
        [item for item in allowed if isinstance(item, str) and item]
        if isinstance(allowed, list)
        else []
    )
    if isinstance(allowed, list) and len(allowed_names) != len(allowed):
        return [
            build_tool_decision(
                source="gemini.toolConfig",
                category="tool_choice",
                decision="unsupported",
                reason="invalid_allowed_function_names",
                field="toolConfig.functionCallingConfig.allowedFunctionNames",
            )
        ]
    candidate_names = allowed_names or user_functions
    missing_names = [name for name in candidate_names if name not in user_functions]
    if missing_names:
        return [
            build_tool_decision(
                source="gemini.toolConfig",
                category="tool_choice",
                decision="unsupported",
                name=",".join(missing_names),
                reason="undeclared_allowed_function",
                field="toolConfig.functionCallingConfig.allowedFunctionNames",
            )
        ]
    if len(candidate_names) != 1:
        return [
            build_tool_decision(
                source="gemini.toolConfig",
                category="tool_choice",
                decision="unsupported",
                reason="backend_requires_single_forced_function",
                field="toolConfig.functionCallingConfig.allowedFunctionNames",
            )
        ]
    return [
        build_tool_decision(
            source="gemini.toolConfig",
            category="tool_choice",
            decision="supported" if supported else "unsupported",
            name=candidate_names[0],
            reason="single_forced_function",
            field="toolConfig.functionCallingConfig.allowedFunctionNames",
        )
    ]


def _model_resolution(
    *,
    protocol: CompatibilityProtocol,
    operation: str,
    route: str,
    body: Mapping[str, Any],
    config: Any | None,
) -> ModelResolutionDiagnostic:
    if operation == "model_discovery":
        return ModelResolutionDiagnostic(pass_model=_pass_model(config))

    requested = _requested_model(
        protocol=protocol, operation=operation, route=route, body=body
    )
    if operation in {"embeddings", "embed_content", "batch_embed_contents"}:
        effective, source = _embedding_model(requested, config)
    elif requested and _pass_model(config):
        effective, source = requested, "request.model"
    else:
        effective, source = _configured_chat_model(config)
    return ModelResolutionDiagnostic(
        requested=requested,
        effective=effective,
        pass_model=_pass_model(config),
        source=source,
    )


def _requested_model(
    *,
    protocol: CompatibilityProtocol,
    operation: str,
    route: str,
    body: Mapping[str, Any],
) -> str | None:
    if protocol == "gemini" and operation in {
        "batch_embed_contents",
        "count_tokens",
        "embed_content",
        "generate_content",
        "stream_generate_content",
    }:
        match = _GEMINI_OPERATION_RE.match(route)
        if match:
            return match.group("model").removeprefix("models/")
    model = body.get("model")
    return model.strip() if isinstance(model, str) and model.strip() else None


def _embedding_model(
    requested: str | None,
    config: Any | None,
) -> tuple[str | None, str | None]:
    if requested and _pass_model(config):
        return requested, "request.model"
    embeddings = getattr(_proxy_settings(config), "embeddings", None)
    if embeddings:
        return str(embeddings), "GPT2GIGA_EMBEDDINGS"
    return None, None


def _configured_chat_model(config: Any | None) -> tuple[str, str]:
    configured_model = getattr(_gigachat_settings(config), "model", None)
    if configured_model:
        return str(configured_model), "GIGACHAT_MODEL"
    return DEFAULT_GIGACHAT_MODEL, "default"


def _security_redaction(
    *,
    headers: Mapping[str, Any] | None,
    query: Mapping[str, Any] | None,
    body: Mapping[str, Any],
) -> SecurityRedactionDiagnostic:
    return SecurityRedactionDiagnostic(
        headers_redacted=_redacted_headers(headers),
        query_redacted=_redacted_query(query),
        body_fields_redacted=_redacted_body_fields(body),
    )


def _redacted_headers(headers: Mapping[str, Any] | None) -> list[str]:
    if not headers:
        return []
    redacted = []
    for name in headers:
        if not isinstance(name, str):
            continue
        normalized = normalize_header_name(name)
        if normalized in _SENSITIVE_HEADER_NAMES or _is_sensitive_name(normalized):
            redacted.append(normalized)
    return sorted(set(redacted))


def _redacted_query(query: Mapping[str, Any] | None) -> list[str]:
    if not query:
        return []
    redacted = []
    for name in query:
        if not isinstance(name, str):
            continue
        normalized = name.strip().lower()
        if normalized in _SENSITIVE_QUERY_NAMES or _is_sensitive_name(normalized):
            redacted.append(normalized)
    return sorted(set(redacted))


def _redacted_body_fields(body: Mapping[str, Any]) -> list[str]:
    return sorted(set(_collect_sensitive_body_paths(body)))


def _collect_sensitive_body_paths(
    value: Any,
    *,
    prefix: str = "",
    depth: int = 0,
) -> list[str]:
    if depth > 6:
        return []
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                continue
            path = f"{prefix}.{key}" if prefix else key
            if _is_sensitive_name(key):
                paths.append(path)
                continue
            paths.extend(
                _collect_sensitive_body_paths(item, prefix=path, depth=depth + 1)
            )
    elif isinstance(value, list):
        for item in value[:20]:
            paths.extend(
                _collect_sensitive_body_paths(
                    item,
                    prefix=f"{prefix}[]",
                    depth=depth + 1,
                )
            )
    return paths


def _warnings_for_analysis(
    *,
    protocol: CompatibilityProtocol,
    operation: str,
    fields: FieldCompatibility,
    tools: ToolCompatibility,
    body: Mapping[str, Any],
) -> list[ProtocolDiagnosticWarning]:
    warnings: list[ProtocolDiagnosticWarning] = []
    if operation == "unknown":
        warnings.append(
            ProtocolDiagnosticWarning(
                code="unknown_operation",
                message="The route is not recognized by the compatibility analyzer.",
                severity="warning",
            )
        )
    for field_name in _missing_required_fields(protocol, operation, body):
        warnings.append(
            ProtocolDiagnosticWarning(
                code="missing_required_field",
                message=f"`{field_name}` is required for this operation.",
                severity="error",
                field=field_name,
            )
        )
    for field_name in fields.accepted_ignored:
        warnings.append(
            ProtocolDiagnosticWarning(
                code="accepted_ignored_field",
                message=f"`{field_name}` is accepted for compatibility but ignored.",
                field=field_name,
            )
        )
    for tool_name in tools.unsupported_tools:
        warnings.append(
            ProtocolDiagnosticWarning(
                code="unsupported_tool",
                message=(
                    f"`{tool_name}` is accepted for diagnostics but is not executable "
                    "by the current backend path."
                ),
                field="tools",
            )
        )
    if tools.forced_tool_choice_supported is False:
        warnings.append(
            ProtocolDiagnosticWarning(
                code="unsupported_forced_tool_choice",
                message=(
                    "The requested forced tool choice cannot be enforced by the "
                    "current backend path."
                ),
                field="tool_choice",
            )
        )
    return warnings


def _missing_required_fields(
    protocol: CompatibilityProtocol,
    operation: str,
    body: Mapping[str, Any],
) -> list[str]:
    required: dict[tuple[CompatibilityProtocol, str], tuple[str, ...]] = {
        ("anthropic", "count_tokens"): ("messages",),
        ("anthropic", "messages"): ("messages",),
        ("gemini", "batch_embed_contents"): ("requests",),
        ("gemini", "count_tokens"): ("contents",),
        ("gemini", "embed_content"): ("content",),
        ("gemini", "generate_content"): ("contents",),
        ("gemini", "stream_generate_content"): ("contents",),
        ("openai", "chat_completions"): ("messages",),
        ("openai", "embeddings"): ("input",),
        ("openai", "responses"): ("input",),
    }
    return [
        field_name
        for field_name in required.get((protocol, operation), ())
        if field_name not in body
    ]


def _user_function_details(
    *,
    source: str,
    names: Iterable[str],
) -> list[ToolDecisionDiagnostic]:
    return [
        build_tool_decision(
            source=source,
            category="user_function",
            decision="supported",
            name=name,
            reason="custom_function",
        )
        for name in names
    ]


def _proxy_settings(config: Any | None) -> Any | None:
    return getattr(config, "proxy_settings", config)


def _gigachat_settings(config: Any | None) -> Any | None:
    return getattr(config, "gigachat_settings", None)


def _pass_model(config: Any | None) -> bool:
    value = getattr(_proxy_settings(config), "pass_model", True)
    return bool(value)


def _builtin_tool_mapping_enabled(config: Any | None) -> bool:
    value = getattr(_proxy_settings(config), "disable_builtin_tool_mapping", False)
    return not bool(value)


def _builtin_mapping_unavailable_reason(
    backend_mode: BackendMode,
    mapping_enabled: bool,
) -> str | None:
    if not mapping_enabled:
        return "builtin_tool_mapping_disabled"
    if backend_mode != "gigachat_v2":
        return "requires_gigachat_v2"
    return None


def _is_sensitive_name(name: str) -> bool:
    normalized = name.strip().lower().replace("-", "_")
    return any(fragment in normalized for fragment in _SENSITIVE_BODY_KEY_FRAGMENTS)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _first_mapping(value: Mapping[str, Any], *keys: str) -> Mapping[str, Any]:
    for key in keys:
        item = value.get(key)
        if isinstance(item, Mapping):
            return item
    return {}


def _dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
