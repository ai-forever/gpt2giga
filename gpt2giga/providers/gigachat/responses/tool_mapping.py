"""Responses API v2 tool normalization helpers."""

from typing import Any, Dict, List, Optional

from gigachat.models import ChatV2Tool, ChatV2ToolConfig

from gpt2giga.providers.gigachat.request_mapping_base import RequestTransformerBaseMixin
from gpt2giga.providers.gigachat.tool_mapping import (
    convert_tool_to_giga_functions,
    map_tool_name_to_gigachat,
)

_RESPONSE_BUILTIN_TOOL_ALIASES = {
    "web_search": "web_search",
    "web_search_2025_08_26": "web_search",
    "web_search_preview": "web_search",
    "web_search_preview_2025_03_11": "web_search",
    "code_interpreter": "code_interpreter",
    "image_generation": "image_generate",
    "image_generate": "image_generate",
    "url_content_extraction": "url_content_extraction",
    "model_3d_generate": "model_3d_generate",
}


class ResponsesV2ToolMappingMixin(RequestTransformerBaseMixin):
    """Normalize external Responses API tools into GigaChat v2 tool payloads."""

    @staticmethod
    def _map_openai_tool_type_to_gigachat(type_: Any) -> Optional[str]:
        if not isinstance(type_, str):
            return None
        return _RESPONSE_BUILTIN_TOOL_ALIASES.get(type_)

    @classmethod
    def _resolve_response_tool_name(cls, tool: Dict[str, Any]) -> Optional[str]:
        tool_type = tool.get("type")
        mapped_type = cls._map_openai_tool_type_to_gigachat(tool_type)
        if mapped_type is not None:
            return mapped_type

        for key in _RESPONSE_BUILTIN_TOOL_ALIASES.values():
            if key in tool:
                return key

        return None

    @staticmethod
    def _coerce_optional_string_list(value: Any) -> Optional[List[str]]:
        if not isinstance(value, list):
            return None
        coerced = [
            item.strip() for item in value if isinstance(item, str) and item.strip()
        ]
        return coerced or None

    @classmethod
    def _build_web_search_tool(cls, tool: Dict[str, Any]) -> ChatV2Tool:
        raw_config = tool.get("web_search")
        config = raw_config if isinstance(raw_config, dict) else {}

        raw_type = config.get("type")
        search_type = (
            raw_type.strip() if isinstance(raw_type, str) and raw_type.strip() else None
        )
        indexes = cls._coerce_optional_string_list(
            config.get("indexes", tool.get("indexes"))
        )
        flags = cls._coerce_optional_string_list(config.get("flags", tool.get("flags")))
        return ChatV2Tool.web_search_tool(
            type=search_type,
            indexes=indexes,
            flags=flags,
        )

    def _collect_response_tools(
        self,
        tools: List[Dict[str, Any]],
    ) -> tuple[
        Dict[str, Any],
        Dict[str, ChatV2Tool],
        List[Dict[str, Any]],
        Optional[str],
    ]:
        function_specs: Dict[str, Any] = {}
        builtin_tools: Dict[str, ChatV2Tool] = {}
        unsupported_tools: List[Dict[str, Any]] = []
        user_timezone: Optional[str] = None

        for tool in tools:
            if not isinstance(tool, dict):
                continue

            tool_type = tool.get("type")
            if tool_type == "function":
                raw_function = tool.get("function", tool)
                visible_name = raw_function.get("name")
                if not visible_name:
                    continue
                giga_functions = convert_tool_to_giga_functions({"tools": [tool]})
                if giga_functions:
                    function_specs[visible_name] = giga_functions[0]
                else:
                    unsupported_tools.append(tool)
                continue

            giga_tool_name = self._resolve_response_tool_name(tool)
            if giga_tool_name == "web_search":
                builtin_tools[giga_tool_name] = self._build_web_search_tool(tool)
                user_location = tool.get("user_location")
                if isinstance(user_location, dict):
                    timezone = user_location.get("timezone")
                    if isinstance(timezone, str) and timezone.strip():
                        user_timezone = timezone.strip()
                continue
            if giga_tool_name == "code_interpreter":
                builtin_tools[giga_tool_name] = ChatV2Tool.code_interpreter_tool()
                continue
            if giga_tool_name == "image_generate":
                builtin_tools[giga_tool_name] = ChatV2Tool.image_generate_tool()
                continue
            if giga_tool_name == "url_content_extraction":
                builtin_tools[giga_tool_name] = ChatV2Tool.url_content_extraction_tool()
                continue
            if giga_tool_name == "model_3d_generate":
                builtin_tools[giga_tool_name] = ChatV2Tool.model_3d_generate_tool()
                continue

            unsupported_tools.append(tool)

        return function_specs, builtin_tools, unsupported_tools, user_timezone

    def _filter_allowed_response_tools(
        self,
        function_specs: Dict[str, Any],
        builtin_tools: Dict[str, ChatV2Tool],
        allowed_tools: List[Dict[str, Any]],
    ) -> tuple[Dict[str, Any], Dict[str, ChatV2Tool]]:
        allowed_functions: Dict[str, Any] = {}
        allowed_builtins: Dict[str, ChatV2Tool] = {}

        for tool in allowed_tools:
            if not isinstance(tool, dict):
                continue
            if tool.get("type") == "function":
                name = tool.get("name")
                if isinstance(name, str) and name in function_specs:
                    allowed_functions[name] = function_specs[name]
                continue

            giga_tool_name = self._map_openai_tool_type_to_gigachat(tool.get("type"))
            if giga_tool_name and giga_tool_name in builtin_tools:
                allowed_builtins[giga_tool_name] = builtin_tools[giga_tool_name]

        return allowed_functions, allowed_builtins

    def _single_tool_target_config(
        self,
        function_specs: Dict[str, Any],
        builtin_tools: Dict[str, ChatV2Tool],
    ) -> Optional[ChatV2ToolConfig]:
        target_count = len(function_specs) + len(builtin_tools)
        if target_count != 1:
            return None
        if function_specs:
            name = next(iter(function_specs))
            return ChatV2ToolConfig(
                mode="forced",
                function_name=map_tool_name_to_gigachat(name),
            )
        giga_tool_name = next(iter(builtin_tools))
        return ChatV2ToolConfig(mode="forced", tool_name=giga_tool_name)

    def _build_response_tool_config(
        self,
        tool_choice: Any,
        function_specs: Dict[str, Any],
        builtin_tools: Dict[str, ChatV2Tool],
    ) -> Optional[ChatV2ToolConfig]:
        if tool_choice is None:
            return None

        if isinstance(tool_choice, str):
            if tool_choice == "none":
                return ChatV2ToolConfig(mode="none")
            if tool_choice == "auto":
                return ChatV2ToolConfig(mode="auto")
            if tool_choice == "required":
                return self._single_tool_target_config(
                    function_specs,
                    builtin_tools,
                ) or ChatV2ToolConfig(mode="auto")
            return ChatV2ToolConfig(mode="auto")

        if not isinstance(tool_choice, dict):
            return None

        tool_type = tool_choice.get("type")
        if tool_type == "allowed_tools":
            mode = tool_choice.get("mode")
            if mode == "required":
                return self._single_tool_target_config(
                    function_specs,
                    builtin_tools,
                ) or ChatV2ToolConfig(mode="auto")
            return ChatV2ToolConfig(mode="auto")

        if tool_type == "function":
            name = tool_choice.get("name")
            if not isinstance(name, str) or name not in function_specs:
                raise self._invalid_request(
                    f"Unsupported forced tool choice for function {name!r}.",
                    param="tool_choice",
                )
            return ChatV2ToolConfig(
                mode="forced",
                function_name=map_tool_name_to_gigachat(name),
            )

        giga_tool_name = self._map_openai_tool_type_to_gigachat(tool_type)
        if giga_tool_name:
            if giga_tool_name not in builtin_tools:
                raise self._invalid_request(
                    f"Unsupported forced tool choice for tool type {tool_type!r}.",
                    param="tool_choice",
                )
            return ChatV2ToolConfig(mode="forced", tool_name=giga_tool_name)

        raise self._invalid_request(
            f"Unsupported forced tool choice for tool type {tool_type!r}.",
            param="tool_choice",
        )
