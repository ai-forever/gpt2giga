"""Responses API v2 message assembly helpers."""

from typing import Any, Dict, List, Optional

from gigachat import GigaChat

from gpt2giga.providers.gigachat.request_mapping_base import RequestTransformerBaseMixin
from gpt2giga.providers.gigachat.responses.input_content import (
    ResponsesV2ContentPartsMixin,
)
from gpt2giga.providers.gigachat.responses.input_history import (
    ResponsesV2HistoryRepairMixin,
)
from gpt2giga.providers.gigachat.tool_mapping import map_tool_name_to_gigachat


class ResponsesV2MessageBuilderMixin(
    ResponsesV2HistoryRepairMixin,
    ResponsesV2ContentPartsMixin,
    RequestTransformerBaseMixin,
):
    """Assemble GigaChat v2 messages from normalized Responses input items."""

    @staticmethod
    def _collect_response_v2_reasoning_chunks(item: Dict[str, Any]) -> List[str]:
        reasoning_chunks: List[str] = []
        summary = item.get("summary")
        if isinstance(summary, list):
            reasoning_chunks.extend(
                part["text"]
                for part in summary
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            )
        content = item.get("content")
        if isinstance(content, list):
            reasoning_chunks.extend(
                part["text"]
                for part in content
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            )
        return reasoning_chunks

    def _build_response_v2_function_call_message(
        self,
        item: Dict[str, Any],
        last_function_name: Optional[str],
        last_tools_state_id: Optional[str],
    ) -> tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
        name = item.get("name") or last_function_name
        if not isinstance(name, str) or not name:
            return None, last_function_name, last_tools_state_id

        tools_state_id = (
            str(
                item.get("call_id") or item.get("id") or last_tools_state_id or ""
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
        if tools_state_id:
            message["tools_state_id"] = tools_state_id
        return message, name, tools_state_id

    def _build_response_v2_function_result_message(
        self,
        item: Dict[str, Any],
        last_function_name: Optional[str],
        last_tools_state_id: Optional[str],
    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        name = item.get("name") or last_function_name
        if not isinstance(name, str) or not name:
            return None, last_tools_state_id

        tool_state_id = item.get("call_id") or item.get("id") or last_tools_state_id
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
        return message, str(tool_state_id) if tool_state_id else last_tools_state_id

    def _append_response_v2_function_calls(
        self,
        item: Dict[str, Any],
        content_parts: List[Dict[str, Any]],
        last_function_name: Optional[str],
        last_tools_state_id: Optional[str],
    ) -> tuple[Optional[str], Optional[str]]:
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

        return last_function_name, last_tools_state_id

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
                message, last_function_name, last_tools_state_id = (
                    self._build_response_v2_function_call_message(
                        item,
                        last_function_name,
                        last_tools_state_id,
                    )
                )
                if message:
                    messages.append(message)
                continue

            if item_type == "function_call_output":
                message, last_tools_state_id = (
                    self._build_response_v2_function_result_message(
                        item,
                        last_function_name,
                        last_tools_state_id,
                    )
                )
                if message:
                    messages.append(message)
                continue

            if item_type == "reasoning":
                reasoning_chunks = self._collect_response_v2_reasoning_chunks(item)
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
            last_function_name, last_tools_state_id = (
                self._append_response_v2_function_calls(
                    item,
                    content_parts,
                    last_function_name,
                    last_tools_state_id,
                )
            )
            if not content_parts:
                continue

            message = {
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
