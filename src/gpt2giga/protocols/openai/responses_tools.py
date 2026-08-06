"""Lossless, fail-closed decoding for OpenAI Responses tool definitions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NoReturn

from gpt2giga.common.client_params import ClientCompatibilityError
from gpt2giga.protocols.normalized.models import NormalizedTool, NormalizedToolKind


_INVALID_MESSAGE = "The Responses request is invalid for normalized execution."
_UNSUPPORTED_MESSAGE = "The selected bridge route cannot preserve this semantic."

_WEB_SEARCH_TYPES = frozenset(
    {
        "web_search",
        "web_search_2025_08_26",
        "web_search_preview",
        "web_search_preview_2025_03_11",
    }
)
_HOSTED_TOOL_TYPES = _WEB_SEARCH_TYPES | frozenset(
    {
        "code_interpreter",
        "computer_use_preview",
        "file_search",
        "image_generation",
    }
)
_WEB_SEARCH_FIELDS = frozenset(
    {
        "filters",
        "search_content_types",
        "search_context_size",
        "type",
        "user_location",
    }
)
_IMAGE_GENERATION_FIELDS = frozenset(
    {
        "action",
        "background",
        "input_fidelity",
        "input_image_mask",
        "model",
        "moderation",
        "output_compression",
        "output_format",
        "partial_images",
        "quality",
        "size",
        "type",
    }
)


def normalize_responses_tools(value: Any) -> list[NormalizedTool]:
    """Decode known Responses tools without making route capability decisions."""
    if value is None:
        return []
    if not isinstance(value, list):
        _invalid("tools")

    tools: list[NormalizedTool] = []
    names: set[str] = set()
    for index, item in enumerate(value):
        path = f"tools[{index}]"
        if not isinstance(item, Mapping):
            _invalid(path)
        tool_type = item.get("type")
        if not isinstance(tool_type, str) or not tool_type:
            _invalid(f"{path}.type")

        if tool_type == "function":
            tool = _normalize_function_tool(item, path=path)
        elif tool_type == "namespace":
            tool = _normalize_namespace_tool(item, path=path)
        elif tool_type in _HOSTED_TOOL_TYPES:
            tool = _normalize_hosted_tool(item, path=path, tool_type=tool_type)
        else:
            _unsupported(f"{path}.type")

        if tool.name is not None:
            if tool.name in names:
                _invalid(f"{path}.name")
            names.add(tool.name)
        tools.append(tool)
    return tools


def normalize_responses_tool_choice(
    value: Any,
    tools: list[NormalizedTool],
) -> Any | None:
    """Decode a function or hosted tool choice without admitting the route."""
    if value is None:
        return None
    if isinstance(value, str) and value in {"auto", "none", "required"}:
        return value
    if not isinstance(value, Mapping):
        _invalid("tool_choice")
    _reject_unknown_fields(value, {"name", "type"}, path="tool_choice")

    tool_type = value.get("type")
    if tool_type == "function":
        name = _required_string(value.get("name"), "tool_choice.name")
        if name not in {
            tool.name for tool in tools if tool.kind is NormalizedToolKind.FUNCTION
        }:
            _invalid("tool_choice.name")
        return {"type": "function", "function": {"name": name}}
    if tool_type in _HOSTED_TOOL_TYPES:
        if not any(tool.type == tool_type for tool in tools):
            _invalid("tool_choice.type")
        return {"type": tool_type}
    if isinstance(tool_type, str):
        _unsupported("tool_choice.type")
    _invalid("tool_choice.type")


def _normalize_function_tool(
    item: Mapping[str, Any],
    *,
    path: str,
) -> NormalizedTool:
    _reject_unknown_fields(
        item,
        {"description", "name", "parameters", "strict", "type"},
        path=path,
    )
    name = _required_string(item.get("name"), f"{path}.name")
    description = item.get("description")
    if description is not None and not isinstance(description, str):
        _invalid(f"{path}.description")
    parameters = item.get("parameters", {})
    if not isinstance(parameters, Mapping):
        _invalid(f"{path}.parameters")
    strict = item.get("strict")
    if strict is not None and not isinstance(strict, bool):
        _invalid(f"{path}.strict")
    return NormalizedTool(
        kind=NormalizedToolKind.FUNCTION,
        type="function",
        name=name,
        description=description,
        parameters=dict(parameters),
        raw_extensions=({"function": {"strict": strict}} if strict is not None else {}),
    )


def _normalize_namespace_tool(
    item: Mapping[str, Any],
    *,
    path: str,
) -> NormalizedTool:
    _reject_unknown_fields(item, {"description", "name", "tools", "type"}, path=path)
    name = _required_string(item.get("name"), f"{path}.name")
    description = item.get("description")
    if description is not None and not isinstance(description, str):
        _invalid(f"{path}.description")
    nested = item.get("tools")
    if not isinstance(nested, list) or not nested:
        _invalid(f"{path}.tools")

    normalized_nested: list[dict[str, Any]] = []
    nested_names: set[str] = set()
    for index, nested_item in enumerate(nested):
        nested_path = f"{path}.tools[{index}]"
        if not isinstance(nested_item, Mapping):
            _invalid(nested_path)
        if nested_item.get("type", "function") != "function":
            _unsupported(f"{nested_path}.type")
        function_item = dict(nested_item)
        function_item.setdefault("type", "function")
        tool = _normalize_function_tool(function_item, path=nested_path)
        if tool.name in nested_names:
            _invalid(f"{nested_path}.name")
        nested_names.add(tool.name)
        normalized_nested.append(tool.to_json_dict())

    return NormalizedTool(
        kind=NormalizedToolKind.NAMESPACE,
        type="namespace",
        name=name,
        description=description,
        configuration={"tools": normalized_nested},
    )


def _normalize_hosted_tool(
    item: Mapping[str, Any],
    *,
    path: str,
    tool_type: str,
) -> NormalizedTool:
    if tool_type in _WEB_SEARCH_TYPES:
        configuration = _normalize_web_search_configuration(item, path=path)
    elif tool_type == "code_interpreter":
        configuration = _normalize_code_interpreter_configuration(item, path=path)
    elif tool_type == "computer_use_preview":
        configuration = _normalize_computer_use_configuration(item, path=path)
    elif tool_type == "file_search":
        configuration = _normalize_file_search_configuration(item, path=path)
    else:
        configuration = _normalize_image_generation_configuration(item, path=path)
    return NormalizedTool(
        kind=NormalizedToolKind.HOSTED,
        type=tool_type,
        configuration=configuration,
    )


def _normalize_web_search_configuration(
    item: Mapping[str, Any],
    *,
    path: str,
) -> dict[str, Any]:
    _reject_unknown_fields(item, _WEB_SEARCH_FIELDS, path=path)
    context_size = item.get("search_context_size")
    if context_size is not None and context_size not in {"low", "medium", "high"}:
        _invalid(f"{path}.search_context_size")
    content_types = item.get("search_content_types")
    if content_types is not None:
        _string_list(
            content_types,
            f"{path}.search_content_types",
            allowed={"text", "image"},
        )
    location = item.get("user_location")
    if location is not None:
        if not isinstance(location, Mapping):
            _invalid(f"{path}.user_location")
        _reject_unknown_fields(
            location,
            {"city", "country", "region", "timezone", "type"},
            path=f"{path}.user_location",
        )
        if location.get("type") not in {None, "approximate"}:
            _invalid(f"{path}.user_location.type")
        for field in ("city", "country", "region", "timezone"):
            if field in location and location[field] is not None:
                _required_string(location[field], f"{path}.user_location.{field}")
    filters = item.get("filters")
    if filters is not None:
        if not isinstance(filters, Mapping):
            _invalid(f"{path}.filters")
        _reject_unknown_fields(
            filters,
            {"allowed_domains"},
            path=f"{path}.filters",
        )
        if "allowed_domains" in filters and filters["allowed_domains"] is not None:
            _string_list(filters["allowed_domains"], f"{path}.filters.allowed_domains")
    return {key: _copy_value(value) for key, value in item.items() if key != "type"}


def _normalize_code_interpreter_configuration(
    item: Mapping[str, Any],
    *,
    path: str,
) -> dict[str, Any]:
    _reject_unknown_fields(item, {"allowed_callers", "container", "type"}, path=path)
    container = item.get("container")
    if isinstance(container, str):
        _required_string(container, f"{path}.container")
    elif isinstance(container, Mapping):
        _reject_unknown_fields(
            container,
            {"file_ids", "memory_limit", "network_policy", "type"},
            path=f"{path}.container",
        )
        if container.get("type") != "auto":
            _invalid(f"{path}.container.type")
        if "file_ids" in container:
            _string_list(container["file_ids"], f"{path}.container.file_ids")
        if container.get("memory_limit") not in {None, "1g", "4g", "16g", "64g"}:
            _invalid(f"{path}.container.memory_limit")
        if "network_policy" in container and not isinstance(
            container["network_policy"], Mapping
        ):
            _invalid(f"{path}.container.network_policy")
    else:
        _invalid(f"{path}.container")
    _validate_allowed_callers(item.get("allowed_callers"), path=path)
    return {key: _copy_value(value) for key, value in item.items() if key != "type"}


def _normalize_computer_use_configuration(
    item: Mapping[str, Any],
    *,
    path: str,
) -> dict[str, Any]:
    _reject_unknown_fields(
        item,
        {"display_height", "display_width", "environment", "type"},
        path=path,
    )
    _positive_int(item.get("display_height"), f"{path}.display_height")
    _positive_int(item.get("display_width"), f"{path}.display_width")
    if item.get("environment") not in {
        "windows",
        "mac",
        "linux",
        "ubuntu",
        "browser",
    }:
        _invalid(f"{path}.environment")
    return {key: _copy_value(value) for key, value in item.items() if key != "type"}


def _normalize_file_search_configuration(
    item: Mapping[str, Any],
    *,
    path: str,
) -> dict[str, Any]:
    _reject_unknown_fields(
        item,
        {"filters", "max_num_results", "ranking_options", "type", "vector_store_ids"},
        path=path,
    )
    vector_store_ids = item.get("vector_store_ids")
    if not isinstance(vector_store_ids, list) or not vector_store_ids:
        _invalid(f"{path}.vector_store_ids")
    _string_list(vector_store_ids, f"{path}.vector_store_ids")
    max_num_results = item.get("max_num_results")
    if max_num_results is not None and (
        isinstance(max_num_results, bool)
        or not isinstance(max_num_results, int)
        or not 1 <= max_num_results <= 50
    ):
        _invalid(f"{path}.max_num_results")
    for field in ("filters", "ranking_options"):
        if (
            field in item
            and item[field] is not None
            and not isinstance(item[field], Mapping)
        ):
            _invalid(f"{path}.{field}")
    return {key: _copy_value(value) for key, value in item.items() if key != "type"}


def _normalize_image_generation_configuration(
    item: Mapping[str, Any],
    *,
    path: str,
) -> dict[str, Any]:
    _reject_unknown_fields(item, _IMAGE_GENERATION_FIELDS, path=path)
    enums = {
        "action": {"generate", "edit", "auto"},
        "background": {"transparent", "opaque", "auto"},
        "input_fidelity": {"high", "low"},
        "moderation": {"auto", "low"},
        "output_format": {"png", "webp", "jpeg"},
        "quality": {"low", "medium", "high", "auto"},
    }
    for field, allowed in enums.items():
        if field in item and item[field] is not None and item[field] not in allowed:
            _invalid(f"{path}.{field}")
    for field in ("model", "size"):
        if field in item and item[field] is not None:
            _required_string(item[field], f"{path}.{field}")
    compression = item.get("output_compression")
    if compression is not None and (
        isinstance(compression, bool)
        or not isinstance(compression, int)
        or not 0 <= compression <= 100
    ):
        _invalid(f"{path}.output_compression")
    partial_images = item.get("partial_images")
    if partial_images is not None and (
        isinstance(partial_images, bool)
        or not isinstance(partial_images, int)
        or not 0 <= partial_images <= 3
    ):
        _invalid(f"{path}.partial_images")
    mask = item.get("input_image_mask")
    if mask is not None:
        if not isinstance(mask, Mapping):
            _invalid(f"{path}.input_image_mask")
        _reject_unknown_fields(
            mask,
            {"file_id", "image_url"},
            path=f"{path}.input_image_mask",
        )
        for field in ("file_id", "image_url"):
            if field in mask:
                _required_string(mask[field], f"{path}.input_image_mask.{field}")
    return {key: _copy_value(value) for key, value in item.items() if key != "type"}


def _validate_allowed_callers(value: Any, *, path: str) -> None:
    if value is None:
        return
    _string_list(
        value,
        f"{path}.allowed_callers",
        allowed={"direct", "programmatic"},
    )


def _copy_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _copy_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_value(item) for item in value]
    return value


def _positive_int(value: Any, param: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _invalid(param)
    return value


def _string_list(
    value: Any,
    param: str,
    *,
    allowed: set[str] | None = None,
) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        _invalid(param)
    if allowed is not None and any(item not in allowed for item in value):
        _invalid(param)
    return value


def _required_string(value: Any, param: str) -> str:
    if not isinstance(value, str) or not value:
        _invalid(param)
    return value


def _reject_unknown_fields(
    value: Mapping[str, Any],
    allowed: set[str] | frozenset[str],
    *,
    path: str,
) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        _unsupported(f"{path}.{unknown[0]}")


def _invalid(param: str) -> NoReturn:
    raise ClientCompatibilityError(
        _INVALID_MESSAGE,
        param=param,
        code="invalid_request",
    )


def _unsupported(param: str) -> NoReturn:
    raise ClientCompatibilityError(
        _UNSUPPORTED_MESSAGE,
        param=param,
        code="unsupported_semantic",
    )
