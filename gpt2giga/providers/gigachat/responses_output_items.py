"""Responses API output-item shaping helpers."""

import json
import uuid
from typing import Any, Dict, Literal, Optional

from openai.types.responses import ResponseFunctionToolCall, ResponseTextDeltaEvent

from gpt2giga.providers.gigachat.tool_mapping import map_tool_name_from_gigachat


class ResponsesOutputItemsMixin:
    """Build Responses API output items from normalized GigaChat payloads."""

    @staticmethod
    def _create_message_item(text: Optional[str], response_id: str) -> dict:
        return {
            "type": "message",
            "id": f"msg_{response_id}",
            "status": "completed",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": text,
                    "annotations": [],
                    "logprobs": [],
                }
            ],
        }

    @classmethod
    def _create_output_responses(
        cls,
        data: dict,
        is_tool_call: bool = False,
        response_id: Optional[str] = None,
        message_key: Literal["message", "delta"] = "message",
        is_structured_output: bool = False,
    ) -> list:
        response_id = str(uuid.uuid4()) if response_id is None else response_id
        choice = data["choices"][0]
        message = choice.get(message_key, {})
        reasoning_items = cls._create_reasoning_item(
            message.get("reasoning_content"),
            response_id,
        )
        try:
            if is_tool_call and not is_structured_output:
                return reasoning_items + [message["output"]]
            if is_tool_call and is_structured_output:
                output_item = message["output"]
                arguments = output_item.get("arguments", "{}")
                return reasoning_items + [
                    cls._create_message_item(arguments, response_id),
                ]
            return reasoning_items + [
                cls._create_message_item(message.get("content"), response_id),
            ]
        except Exception:
            return reasoning_items + [
                cls._create_message_item(message.get("content"), response_id),
            ]

    @classmethod
    def _build_message_output_item(
        cls,
        *,
        item_id: str,
        text: str,
        status: str,
        logprobs: Optional[list[Dict[str, Any]]] = None,
    ) -> dict:
        part = {
            "type": "output_text",
            "text": text,
            "annotations": [],
        }
        if logprobs is not None:
            part["logprobs"] = logprobs
        return {
            "id": item_id,
            "type": "message",
            "status": status,
            "role": "assistant",
            "content": [part],
        }

    @classmethod
    def _build_function_call_output_item(
        cls,
        *,
        item_id: str,
        call_id: str,
        name: str,
        arguments: Any,
        status: str,
    ) -> dict:
        return ResponseFunctionToolCall(
            arguments=cls._stringify_json(arguments),
            call_id=call_id,
            name=map_tool_name_from_gigachat(name),
            id=item_id,
            status=status,
            type="function_call",
        ).model_dump(exclude_none=True)

    @classmethod
    def _build_builtin_tool_output_item(
        cls,
        *,
        tool_name: str,
        item_id: str,
        tools_state_id: Optional[str],
        response_status: str,
        raw_status: Optional[str],
        related_files: Optional[list[Dict[str, Any]]] = None,
        additional_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[dict]:
        status = raw_status or cls._build_output_item_status(response_status)
        related_files = related_files or []

        if tool_name == "web_search":
            if status not in {"in_progress", "searching", "completed", "failed"}:
                status = (
                    "completed" if response_status == "completed" else "in_progress"
                )
            return {
                "id": item_id,
                "type": "web_search_call",
                "status": status,
                "action": cls._extract_web_search_action(additional_data),
            }

        if tool_name == "code_interpreter":
            if status not in {
                "in_progress",
                "completed",
                "incomplete",
                "interpreting",
                "failed",
            }:
                status = cls._build_output_item_status(response_status)
            outputs = [
                {"type": "image", "url": file_desc["id"]}
                for file_desc in related_files
                if isinstance(file_desc, dict) and isinstance(file_desc.get("id"), str)
            ]
            result = {
                "id": item_id,
                "type": "code_interpreter_call",
                "status": status,
                "container_id": tools_state_id or item_id,
            }
            if outputs:
                result["outputs"] = outputs
            return result

        if tool_name == "image_generate":
            if status not in {"in_progress", "generating", "completed", "failed"}:
                status = (
                    "completed" if response_status == "completed" else "in_progress"
                )
            result = {
                "id": item_id,
                "type": "image_generation_call",
                "status": status,
            }
            first_file = next(
                (
                    file_desc["id"]
                    for file_desc in related_files
                    if isinstance(file_desc, dict)
                    and isinstance(file_desc.get("id"), str)
                ),
                None,
            )
            if first_file:
                result["result"] = first_file
            return result

        return None

    @classmethod
    def _create_output_responses_v2(
        cls,
        data: Dict[str, Any],
        response_id: str,
        *,
        response_status: str,
    ) -> list[dict]:
        output: list[dict] = []
        item_status = cls._build_output_item_status(response_status)
        additional_data = data.get("additional_data")

        for message_index, message in enumerate(data.get("messages") or []):
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue

            message_id = (
                message.get("message_id") or f"msg_{response_id}_{message_index}"
            )
            tools_state_id = message.get("tools_state_id")
            contents = message.get("content") or []
            pending_text: list[str] = []
            pending_logprobs: list[Dict[str, Any]] = []
            text_segment_index = 0
            last_tool_item: Optional[dict] = None

            def flush_text() -> None:
                nonlocal pending_text
                nonlocal pending_logprobs
                nonlocal text_segment_index
                if not pending_text:
                    return
                output.append(
                    cls._build_message_output_item(
                        item_id=f"{message_id}_{text_segment_index}",
                        text="".join(pending_text),
                        status=item_status,
                        logprobs=pending_logprobs or None,
                    )
                )
                pending_text = []
                pending_logprobs = []
                text_segment_index += 1

            for part_index, part in enumerate(contents):
                if not isinstance(part, dict):
                    continue

                text = part.get("text")
                if isinstance(text, str):
                    pending_text.append(text)
                    converted_logprobs = cls._convert_logprobs(part.get("logprobs"))
                    if converted_logprobs:
                        pending_logprobs.extend(converted_logprobs)

                function_call = part.get("function_call")
                if isinstance(function_call, dict):
                    flush_text()
                    name = function_call.get("name")
                    if isinstance(name, str) and name:
                        call_id = (
                            str(tools_state_id)
                            if tools_state_id is not None
                            else f"call_{message_id}_{part_index}"
                        )
                        output.append(
                            cls._build_function_call_output_item(
                                item_id=f"fc_{call_id}",
                                call_id=call_id,
                                name=name,
                                arguments=function_call.get("arguments"),
                                status=item_status,
                            )
                        )
                    last_tool_item = None

                tool_execution = part.get("tool_execution")
                if isinstance(tool_execution, dict):
                    flush_text()
                    tool_name = tool_execution.get("name")
                    if isinstance(tool_name, str) and tool_name:
                        mapped_item = cls._build_builtin_tool_output_item(
                            tool_name=tool_name,
                            item_id=f"tool_{tools_state_id or message_id}_{part_index}",
                            tools_state_id=tools_state_id,
                            response_status=response_status,
                            raw_status=tool_execution.get("status"),
                            additional_data=additional_data,
                        )
                        if mapped_item is not None:
                            output.append(mapped_item)
                            last_tool_item = mapped_item
                        else:
                            last_tool_item = None

                files = part.get("files")
                if isinstance(files, list) and last_tool_item is not None:
                    if last_tool_item.get("type") == "image_generation_call":
                        first_file = next(
                            (
                                file_desc.get("id")
                                for file_desc in files
                                if isinstance(file_desc, dict)
                                and isinstance(file_desc.get("id"), str)
                            ),
                            None,
                        )
                        if first_file:
                            last_tool_item["result"] = first_file
                    elif last_tool_item.get("type") == "code_interpreter_call":
                        images = [
                            {"type": "image", "url": file_desc["id"]}
                            for file_desc in files
                            if isinstance(file_desc, dict)
                            and isinstance(file_desc.get("id"), str)
                        ]
                        if images:
                            last_tool_item["outputs"] = images

            flush_text()

        return output

    def process_stream_chunk_response(
        self,
        giga_resp,
        sequence_number: int = 0,
        response_id: Optional[str] = None,
    ) -> dict:
        giga_dict = self._safe_model_dump(giga_resp)
        response_id = str(uuid.uuid4()) if response_id is None else response_id
        for choice in giga_dict["choices"]:
            self._process_choice_responses(choice, response_id, is_stream=True)
        delta = giga_dict["choices"][0]["delta"]
        if delta["content"]:
            return ResponseTextDeltaEvent(
                content_index=0,
                delta=delta["content"],
                item_id=f"msg_{response_id}",
                output_index=0,
                logprobs=[],
                type="response.output_text.delta",
                sequence_number=sequence_number,
            ).dict()
        return self._create_output_responses(
            giga_dict,
            is_tool_call=True,
            message_key="delta",
            response_id=response_id,
        )

    def _process_choice_responses(
        self,
        choice: Dict,
        response_id: str,
        is_stream: bool = False,
    ) -> None:
        """Process a single Responses API choice."""
        message_key = "delta" if is_stream else "message"

        choice["index"] = 0
        choice["logprobs"] = None

        if message_key in choice:
            message = choice[message_key]
            message["refusal"] = None

            if message.get("role") == "assistant" and message.get("function_call"):
                self._process_function_call_responses(message, response_id)

    def _process_function_call_responses(self, message: Dict, response_id: str) -> None:
        """Process a Responses API function call."""
        try:
            arguments = json.dumps(
                message["function_call"]["arguments"],
                ensure_ascii=False,
            )
            message["output"] = ResponseFunctionToolCall(
                arguments=arguments,
                call_id=f"call_{response_id}",
                name=map_tool_name_from_gigachat(message["function_call"]["name"]),
                id=f"fc_{message['functions_state_id']}",
                status="completed",
                type="function_call",
            ).model_dump()

        except Exception as exc:
            self.logger.error(f"Error processing function call: {exc}")
