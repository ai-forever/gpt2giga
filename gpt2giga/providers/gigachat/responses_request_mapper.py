"""GigaChat Responses API v2 request mapping helpers."""

import base64
from typing import Any, Dict, List, Optional

from gigachat import GigaChat
from gigachat.models import (
    ChatV2,
    ChatV2ModelOptions,
    ChatV2Reasoning,
    ChatV2ResponseFormat,
    ChatV2Storage,
    ChatV2Tool,
    ChatV2ToolConfig,
    ChatV2UserInfo,
)

from gpt2giga.core.constants import DEFAULT_MAX_AUDIO_IMAGE_TOTAL_SIZE_BYTES
from gpt2giga.core.logging.setup import sanitize_for_utf8
from gpt2giga.core.schema.json_schema import normalize_json_schema, resolve_schema_refs
from gpt2giga.providers.gigachat.tool_mapping import (
    convert_tool_to_giga_functions,
    map_tool_name_to_gigachat,
)


class RequestTransformerResponsesV2Mixin:
    """Helpers for native Responses API v2 payloads."""

    @staticmethod
    def _map_openai_tool_type_to_gigachat(type_: Any) -> Optional[str]:
        mapping = {
            "web_search": "web_search",
            "web_search_2025_08_26": "web_search",
            "web_search_preview": "web_search",
            "web_search_preview_2025_03_11": "web_search",
            "code_interpreter": "code_interpreter",
            "image_generation": "image_generate",
        }
        if not isinstance(type_, str):
            return None
        return mapping.get(type_)

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

            giga_tool_name = self._map_openai_tool_type_to_gigachat(tool_type)
            if giga_tool_name == "web_search":
                builtin_tools[giga_tool_name] = ChatV2Tool.web_search_tool()
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

    def _resolve_response_thread_id(
        self,
        data: Dict[str, Any],
        response_store: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        conversation = data.get("conversation")
        previous_response_id = data.get("previous_response_id")

        if conversation is not None and previous_response_id is not None:
            raise self._invalid_request(
                "`conversation` and `previous_response_id` cannot be used together.",
                param="conversation",
            )

        if conversation is not None:
            if not isinstance(conversation, dict) or not isinstance(
                conversation.get("id"),
                str,
            ):
                raise self._invalid_request(
                    "`conversation.id` must be a string.",
                    param="conversation",
                )
            return conversation["id"]

        if previous_response_id is not None:
            if not isinstance(previous_response_id, str):
                raise self._invalid_request(
                    "`previous_response_id` must be a string.",
                    param="previous_response_id",
                )
            metadata = (
                response_store.get(previous_response_id) if response_store else None
            )
            thread_id = (
                metadata.get("thread_id") if isinstance(metadata, dict) else None
            )
            if not isinstance(thread_id, str) or not thread_id:
                raise self._invalid_request(
                    f"Unknown `previous_response_id`: {previous_response_id}",
                    param="previous_response_id",
                )
            return thread_id

        return None

    async def _upload_response_file_part(
        self,
        giga_client: Optional[GigaChat],
        source: Any,
        *,
        filename: Optional[str] = None,
        size_totals: Optional[Dict[str, int]] = None,
    ) -> Optional[Dict[str, Any]]:
        if source is None or self.attachment_processor is None:
            return None
        if giga_client is None:
            self.logger.warning("giga_client not provided for file upload")
            return None

        max_audio_image_total = getattr(
            self.config.proxy_settings,
            "max_audio_image_total_size_bytes",
            DEFAULT_MAX_AUDIO_IMAGE_TOTAL_SIZE_BYTES,
        )
        remaining = max_audio_image_total
        if size_totals is not None:
            remaining = max(
                0,
                max_audio_image_total - size_totals.get("audio_image_total", 0),
            )

        upload_result = await self.attachment_processor.upload_file_with_meta(
            giga_client,
            source,
            filename,
            max_audio_image_total_remaining=remaining,
        )
        if not upload_result:
            return None
        if upload_result.file_kind in {"audio", "image"} and size_totals is not None:
            size_totals["audio_image_total"] = (
                size_totals.get("audio_image_total", 0) + upload_result.file_size_bytes
            )
        return {"files": [{"id": upload_result.file_id}]}

    async def _build_response_v2_content_parts(
        self,
        content: Any,
        giga_client: Optional[GigaChat] = None,
        *,
        size_totals: Optional[Dict[str, int]] = None,
        fallback_function_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if content is None:
            return []
        if isinstance(content, str):
            return [{"text": content}]
        if isinstance(content, dict):
            content = [content]
        if not isinstance(content, list):
            return [{"text": str(content)}]

        result: List[Dict[str, Any]] = []
        pending_multimodal_part: Dict[str, Any] = {}

        def flush_pending_multimodal_part() -> None:
            nonlocal pending_multimodal_part
            if pending_multimodal_part:
                result.append(pending_multimodal_part)
                pending_multimodal_part = {}

        def append_text_to_pending_part(text: str) -> None:
            existing_text = pending_multimodal_part.get("text")
            if isinstance(existing_text, str) and existing_text:
                pending_multimodal_part["text"] = f"{existing_text}\n{text}"
            else:
                pending_multimodal_part["text"] = text

        def append_files_to_pending_part(files_part: Dict[str, Any]) -> None:
            files = files_part.get("files")
            if not isinstance(files, list) or not files:
                return
            pending_multimodal_part.setdefault("files", []).extend(files)

        for content_part in content:
            if not isinstance(content_part, dict):
                continue
            ctype = content_part.get("type")

            if ctype in {"input_text", "output_text", "text"}:
                text = content_part.get("text")
                if text is not None:
                    append_text_to_pending_part(str(text))
                continue

            if ctype in {"input_image", "image_url"}:
                file_id = content_part.get("file_id")
                if isinstance(file_id, str) and file_id:
                    append_files_to_pending_part({"files": [{"id": file_id}]})
                    continue
                image_url = content_part.get("image_url")
                if isinstance(image_url, dict):
                    image_url = image_url.get("url")
                uploaded = await self._upload_response_file_part(
                    giga_client,
                    image_url,
                    size_totals=size_totals,
                )
                if uploaded:
                    append_files_to_pending_part(uploaded)
                continue

            if ctype in {"input_file", "file"}:
                if ctype == "input_file":
                    file_id = content_part.get("file_id")
                    if isinstance(file_id, str) and file_id:
                        append_files_to_pending_part({"files": [{"id": file_id}]})
                        continue
                    source = content_part.get("file_data") or content_part.get(
                        "file_url"
                    )
                    filename = content_part.get("filename")
                else:
                    file_payload = content_part.get("file") or {}
                    file_id = file_payload.get("file_id")
                    if isinstance(file_id, str) and file_id:
                        result.append({"files": [{"id": file_id}]})
                        continue
                    source = file_payload.get("file_data") or file_payload.get(
                        "file_url"
                    )
                    filename = file_payload.get("filename")

                uploaded = await self._upload_response_file_part(
                    giga_client,
                    source,
                    filename=filename,
                    size_totals=size_totals,
                )
                if uploaded:
                    append_files_to_pending_part(uploaded)
                continue

            if ctype == "input_audio":
                input_audio = content_part.get("input_audio") or {}
                audio_data = input_audio.get("data")
                audio_format = input_audio.get("format", "mp3")
                decoded_audio = audio_data
                if isinstance(audio_data, str):
                    try:
                        decoded_audio = base64.b64decode(audio_data)
                    except Exception:
                        decoded_audio = audio_data
                uploaded = await self._upload_response_file_part(
                    giga_client,
                    decoded_audio,
                    filename=f"input.{audio_format}",
                    size_totals=size_totals,
                )
                if uploaded:
                    append_files_to_pending_part(uploaded)
                continue

            if ctype == "function_call":
                flush_pending_multimodal_part()
                name = content_part.get("name")
                if not isinstance(name, str) or not name:
                    continue
                result.append(
                    {
                        "function_call": {
                            "name": map_tool_name_to_gigachat(name),
                            "arguments": self._decode_json_value(
                                content_part.get("arguments"),
                            ),
                        }
                    }
                )
                continue

            if ctype == "function_call_output":
                flush_pending_multimodal_part()
                name = content_part.get("name") or fallback_function_name
                if not isinstance(name, str) or not name:
                    continue
                result.append(
                    {
                        "function_result": {
                            "name": map_tool_name_to_gigachat(name),
                            "result": self._normalize_function_result_value(
                                content_part.get("output"),
                            ),
                        }
                    }
                )
                continue

            if ctype == "refusal":
                text = content_part.get("refusal") or content_part.get("text")
                if text is not None:
                    append_text_to_pending_part(str(text))

        flush_pending_multimodal_part()
        return result

    def _extract_response_v2_function_call(
        self, item: Dict[str, Any]
    ) -> tuple[Optional[str], Optional[str]]:
        item_type = item.get("type")
        if item_type == "function_call":
            name = item.get("name")
            call_id = item.get("call_id") or item.get("id")
            if isinstance(name, str) and name:
                return name, str(call_id) if call_id else None

        if item.get("role") != "assistant":
            return None, None

        function_call = item.get("function_call")
        if isinstance(function_call, dict):
            name = function_call.get("name")
            call_id = (
                item.get("tools_state_id")
                or item.get("tool_state_id")
                or item.get("tool_call_id")
                or item.get("call_id")
                or item.get("id")
            )
            if isinstance(name, str) and name:
                return name, str(call_id) if call_id else None

        tool_calls = item.get("tool_calls")
        if isinstance(tool_calls, list):
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function")
                if not isinstance(function, dict):
                    continue
                name = function.get("name")
                if not isinstance(name, str) or not name:
                    continue
                call_id = (
                    tool_call.get("id")
                    or item.get("tools_state_id")
                    or item.get("tool_state_id")
                    or item.get("call_id")
                    or item.get("id")
                )
                return name, str(call_id) if call_id else None

        return None, None

    @staticmethod
    def _is_response_v2_function_result_item(
        item: Dict[str, Any],
        pending_function_name: Optional[str],
        pending_call_id: Optional[str],
    ) -> bool:
        item_type = item.get("type")
        if item_type == "function_call_output":
            call_id = item.get("call_id") or item.get("id")
            if pending_call_id and call_id:
                return str(call_id) == pending_call_id
            name = item.get("name")
            if pending_function_name and isinstance(name, str) and name:
                return name == pending_function_name
            return True

        if item.get("role") != "tool":
            return False

        call_id = (
            item.get("tool_call_id")
            or item.get("tools_state_id")
            or item.get("tool_state_id")
            or item.get("call_id")
            or item.get("id")
        )
        if pending_call_id and call_id:
            return str(call_id) == pending_call_id

        name = item.get("name")
        if pending_function_name and isinstance(name, str) and name:
            return name == pending_function_name
        return True

    def _build_missing_response_v2_tool_result_item(
        self,
        function_name: str,
        call_id: Optional[str],
    ) -> Dict[str, Any]:
        item: Dict[str, Any] = {
            "role": "tool",
            "name": function_name,
            "content": self._build_missing_function_result_payload(),
        }
        if call_id:
            item["tool_call_id"] = call_id
        return item

    def _repair_response_v2_input_history(self, input_: Any) -> Any:
        if not isinstance(input_, list):
            return input_

        repaired_items: List[Any] = []
        pending_function_name: Optional[str] = None
        pending_call_id: Optional[str] = None

        for item in input_:
            current_item = item.copy() if isinstance(item, dict) else item

            if pending_function_name is not None:
                if isinstance(
                    current_item, dict
                ) and self._is_response_v2_function_result_item(
                    current_item,
                    pending_function_name,
                    pending_call_id,
                ):
                    if current_item.get("role") == "tool":
                        if not current_item.get("name"):
                            current_item["name"] = pending_function_name
                        if pending_call_id and not current_item.get("tool_call_id"):
                            current_item["tool_call_id"] = pending_call_id
                    elif current_item.get("type") == "function_call_output":
                        if not current_item.get("name"):
                            current_item["name"] = pending_function_name
                        if pending_call_id and not current_item.get("call_id"):
                            current_item["call_id"] = pending_call_id
                    pending_function_name = None
                    pending_call_id = None
                else:
                    repaired_items.append(
                        self._build_missing_response_v2_tool_result_item(
                            pending_function_name,
                            pending_call_id,
                        )
                    )
                    self.logger.warning(
                        "Inserted synthetic tool result for dangling Responses API "
                        f"function call '{pending_function_name}'"
                    )
                    pending_function_name = None
                    pending_call_id = None

            repaired_items.append(current_item)

            if isinstance(current_item, dict):
                next_function_name, next_call_id = (
                    self._extract_response_v2_function_call(current_item)
                )
                if next_function_name:
                    pending_function_name = next_function_name
                    pending_call_id = next_call_id

        if pending_function_name is not None:
            repaired_items.append(
                self._build_missing_response_v2_tool_result_item(
                    pending_function_name,
                    pending_call_id,
                )
            )
            self.logger.warning(
                "Inserted synthetic tool result for trailing Responses API "
                f"function call '{pending_function_name}'"
            )

        return repaired_items

    async def _build_response_v2_messages(
        self,
        data: Dict[str, Any],
        giga_client: Optional[GigaChat] = None,
    ) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = []
        size_totals = {"audio_image_total": 0}
        system_seen = False
        last_function_name: Optional[str] = None
        last_tools_state_id: Optional[str] = None

        instructions = data.get("instructions")
        if isinstance(instructions, str) and instructions:
            messages.append({"role": "system", "content": [{"text": instructions}]})
            system_seen = True

        input_ = self._repair_response_v2_input_history(data.get("input"))
        if isinstance(input_, str):
            messages.append({"role": "user", "content": [{"text": input_}]})
            return messages
        if not isinstance(input_, list):
            return messages

        for item in input_:
            if not isinstance(item, dict):
                continue

            item_type = item.get("type")
            if item_type == "function_call":
                name = item.get("name") or last_function_name
                if not isinstance(name, str) or not name:
                    continue
                last_function_name = name
                last_tools_state_id = (
                    str(
                        item.get("call_id")
                        or item.get("id")
                        or last_tools_state_id
                        or ""
                    ).strip()
                    or last_tools_state_id
                )
                message = {
                    "role": "assistant",
                    "content": [
                        {
                            "function_call": {
                                "name": map_tool_name_to_gigachat(name),
                                "arguments": self._decode_json_value(
                                    item.get("arguments")
                                ),
                            }
                        }
                    ],
                }
                if last_tools_state_id:
                    message["tools_state_id"] = last_tools_state_id
                messages.append(message)
                continue

            if item_type == "function_call_output":
                name = item.get("name") or last_function_name
                if not isinstance(name, str) or not name:
                    continue
                tool_state_id = (
                    item.get("call_id") or item.get("id") or last_tools_state_id
                )
                function_result_part = {
                    "function_result": {
                        "name": map_tool_name_to_gigachat(name),
                        "result": self._normalize_function_result_value(
                            item.get("output")
                        ),
                    }
                }
                message = {"role": "tool", "content": [function_result_part]}
                if tool_state_id:
                    message["tools_state_id"] = str(tool_state_id)
                messages.append(message)
                continue

            if item_type == "reasoning":
                reasoning_chunks: List[str] = []
                summary = item.get("summary")
                if isinstance(summary, list):
                    reasoning_chunks.extend(
                        part.get("text")
                        for part in summary
                        if isinstance(part, dict) and isinstance(part.get("text"), str)
                    )
                content = item.get("content")
                if isinstance(content, list):
                    reasoning_chunks.extend(
                        part.get("text")
                        for part in content
                        if isinstance(part, dict) and isinstance(part.get("text"), str)
                    )
                if reasoning_chunks:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": [{"text": "\n".join(reasoning_chunks)}],
                        }
                    )
                continue

            role = item.get("role")
            if role is None and item_type != "message":
                continue
            role = role or "user"

            if role == "tool":
                name = item.get("name") or last_function_name
                if not isinstance(name, str) or not name:
                    continue
                tool_state_id = item.get("tool_call_id")
                function_result_part = {
                    "function_result": {
                        "name": map_tool_name_to_gigachat(name),
                        "result": self._normalize_function_result_value(
                            item.get("content")
                        ),
                    }
                }
                message = {"role": "tool", "content": [function_result_part]}
                if tool_state_id:
                    message["tools_state_id"] = str(tool_state_id)
                messages.append(message)
                continue

            mapped_role = self._map_role(role, not system_seen)
            if mapped_role == "system":
                system_seen = True

            content_parts = await self._build_response_v2_content_parts(
                item.get("content"),
                giga_client,
                size_totals=size_totals,
                fallback_function_name=last_function_name,
            )

            function_call = item.get("function_call")
            if isinstance(function_call, dict):
                name = function_call.get("name")
                if isinstance(name, str) and name:
                    last_function_name = name
                    last_tools_state_id = (
                        str(
                            item.get("tools_state_id")
                            or item.get("tool_state_id")
                            or item.get("tool_call_id")
                            or item.get("call_id")
                            or item.get("id")
                            or last_tools_state_id
                            or ""
                        ).strip()
                        or last_tools_state_id
                    )
                    content_parts.append(
                        {
                            "function_call": {
                                "name": map_tool_name_to_gigachat(name),
                                "arguments": self._decode_json_value(
                                    function_call.get("arguments"),
                                ),
                            }
                        }
                    )

            tool_calls = item.get("tool_calls")
            if isinstance(tool_calls, list):
                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict):
                        continue
                    function = tool_call.get("function")
                    if not isinstance(function, dict):
                        continue
                    name = function.get("name")
                    if not isinstance(name, str) or not name:
                        continue
                    last_function_name = name
                    last_tools_state_id = (
                        str(tool_call.get("id") or last_tools_state_id or "").strip()
                        or last_tools_state_id
                    )
                    content_parts.append(
                        {
                            "function_call": {
                                "name": map_tool_name_to_gigachat(name),
                                "arguments": self._decode_json_value(
                                    function.get("arguments"),
                                ),
                            }
                        }
                    )

            if not content_parts:
                continue

            message: Dict[str, Any] = {
                "role": mapped_role,
                "content": content_parts,
            }

            tools_state_id = (
                item.get("tools_state_id")
                or item.get("tool_state_id")
                or item.get("call_id")
                or item.get("id")
                or last_tools_state_id
            )
            if isinstance(tools_state_id, str) and tools_state_id:
                message["tools_state_id"] = tools_state_id

            messages.append(message)

        return messages

    def _build_response_v2_model_options(
        self,
        data: Dict[str, Any],
    ) -> Optional[ChatV2ModelOptions]:
        options: Dict[str, Any] = {}

        temperature = data.get("temperature")
        if temperature == 0:
            options["top_p"] = 0
        elif isinstance(temperature, (int, float)) and temperature > 0:
            options["temperature"] = float(temperature)

        top_p = data.get("top_p")
        if top_p is not None and temperature != 0:
            options["top_p"] = top_p

        max_output_tokens = data.get("max_output_tokens")
        if max_output_tokens is not None:
            options["max_tokens"] = max_output_tokens

        top_logprobs = data.get("top_logprobs")
        if top_logprobs is not None:
            options["top_logprobs"] = top_logprobs

        reasoning = data.get("reasoning")
        if isinstance(reasoning, dict):
            effort = reasoning.get("effort")
            if effort in {"low", "medium", "high"}:
                options["reasoning"] = ChatV2Reasoning(effort=effort)
        elif getattr(self.config.proxy_settings, "enable_reasoning", False):
            options["reasoning"] = ChatV2Reasoning(effort="high")

        text_config = data.get("text")
        if isinstance(text_config, dict):
            response_format = text_config.get("format")
            if isinstance(response_format, dict):
                format_type = response_format.get("type")
                if format_type == "text":
                    options["response_format"] = ChatV2ResponseFormat(type="text")
                elif format_type == "json_schema":
                    schema_holder = response_format.get("json_schema")
                    if isinstance(schema_holder, dict):
                        schema = schema_holder.get("schema")
                        strict = schema_holder.get(
                            "strict", response_format.get("strict")
                        )
                    else:
                        schema = response_format.get("schema")
                        strict = response_format.get("strict")
                    if not isinstance(schema, dict):
                        raise self._invalid_request(
                            "`text.format.schema` must be an object for json_schema responses.",
                            param="text",
                        )
                    options["response_format"] = ChatV2ResponseFormat(
                        type="json_schema",
                        schema=normalize_json_schema(resolve_schema_refs(schema)),
                        strict=strict,
                    )

        return ChatV2ModelOptions(**options) if options else None

    async def prepare_response_v2(
        self,
        data: dict,
        giga_client: Optional[GigaChat] = None,
        response_store: Optional[Dict[str, Any]] = None,
    ) -> ChatV2:
        """Prepare a native GigaChat v2 payload for the Responses API."""
        request_data = data.copy()

        function_specs, builtin_tools, _unsupported_tools, user_timezone = (
            self._collect_response_tools(request_data.get("tools", []) or [])
        )

        tool_choice = request_data.get("tool_choice")
        if isinstance(tool_choice, dict) and tool_choice.get("type") == "allowed_tools":
            function_specs, builtin_tools = self._filter_allowed_response_tools(
                function_specs,
                builtin_tools,
                tool_choice.get("tools", []) or [],
            )

        tool_config = self._build_response_tool_config(
            tool_choice,
            function_specs,
            builtin_tools,
        )

        tools_payload: List[ChatV2Tool] = []
        if function_specs:
            tools_payload.append(
                ChatV2Tool.functions_tool(specifications=list(function_specs.values()))
            )
        tools_payload.extend(builtin_tools.values())

        payload: Dict[str, Any] = {
            "messages": await self._build_response_v2_messages(
                request_data,
                giga_client,
            ),
            "stream": bool(request_data.get("stream", False)),
            "additional_fields": self._merge_additional_fields(request_data),
        }

        thread_id = self._resolve_response_thread_id(request_data, response_store)
        if thread_id:
            payload["storage"] = ChatV2Storage(thread_id=thread_id)

        if not payload["messages"]:
            raise self._invalid_request(
                "Request must include at least one input item.",
                param="input",
            )

        model_options = self._build_response_v2_model_options(request_data)
        if model_options is not None:
            payload["model_options"] = model_options

        if tools_payload:
            payload["tools"] = tools_payload
        if tool_config is not None:
            payload["tool_config"] = tool_config
        if user_timezone:
            payload["user_info"] = ChatV2UserInfo(timezone=user_timezone)

        gpt_model = request_data.get("model")
        if self.config.proxy_settings.pass_model and gpt_model:
            payload["model"] = gpt_model

        sanitized_payload = sanitize_for_utf8(
            {
                key: value.model_dump(exclude_none=True, by_alias=True)
                if hasattr(value, "model_dump")
                else value
                for key, value in payload.items()
                if value is not None
            }
        )
        return ChatV2.model_validate(sanitized_payload)
