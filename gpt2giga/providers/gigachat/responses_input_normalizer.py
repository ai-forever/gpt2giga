"""Responses API v2 input normalization helpers."""

import base64
from typing import Any, Dict, List, Optional

from gigachat import GigaChat

from gpt2giga.core.constants import DEFAULT_MAX_AUDIO_IMAGE_TOTAL_SIZE_BYTES
from gpt2giga.providers.gigachat.tool_mapping import map_tool_name_to_gigachat


class ResponsesV2InputNormalizerMixin:
    """Normalize Responses API inputs into GigaChat v2 messages."""

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
        self,
        item: Dict[str, Any],
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
                    current_item,
                    dict,
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
                                    item.get("arguments"),
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
                            item.get("output"),
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
                            item.get("content"),
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
