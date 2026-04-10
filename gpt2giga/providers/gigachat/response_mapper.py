"""GigaChat response mapping entry point."""

import json
import time
import uuid
from typing import Any, Dict, Optional

from gigachat.models import ChatCompletion, ChatCompletionChunk

from gpt2giga.providers.gigachat.response_mapping_common import (
    ResponseProcessorCommonMixin,
)
from gpt2giga.providers.gigachat.responses_response_mapper import (
    ResponseProcessorResponsesMixin,
)
from gpt2giga.providers.gigachat.tool_mapping import map_tool_name_from_gigachat


class ResponseProcessor(
    ResponseProcessorResponsesMixin,
    ResponseProcessorCommonMixin,
):
    """Transform GigaChat responses into OpenAI-compatible payloads."""

    def __init__(self, logger=None, mode: str = "DEV"):
        if logger is None:
            from loguru import logger as default_logger

            logger = default_logger
        self.logger = logger
        self._mode = mode.upper() if isinstance(mode, str) else "DEV"

    def process_response(
        self,
        giga_resp: ChatCompletion,
        gpt_model: str,
        response_id: str,
        request_data: Optional[Dict] = None,
    ) -> dict:
        """Process a non-streaming chat-completions response."""
        giga_dict = self._safe_model_dump(giga_resp)
        is_tool_call = giga_dict["choices"][0]["finish_reason"] == "function_call"

        is_structured_output = False
        if (
            request_data
            and request_data.get("response_format", {}).get("type") == "json_schema"
        ):
            is_structured_output = True

        for choice in giga_dict["choices"]:
            self._process_choice(
                choice, is_tool_call, is_structured_output=is_structured_output
            )
        result = {
            "id": f"chatcmpl-{response_id}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": gpt_model,
            "choices": giga_dict["choices"],
            "usage": self._build_usage(giga_dict["usage"]),
            "system_fingerprint": f"fp_{response_id}",
        }

        if self._is_prod_mode:
            self.logger.bind(event="chat_completion_response").debug(
                "Processed chat completion response (payload omitted in PROD)"
            )
        else:
            choice_count = len(result.get("choices", []))
            usage = result.get("usage") or {}
            self.logger.bind(
                event="chat_completion_response",
                response_id=result.get("id"),
                choice_count=choice_count,
                total_tokens=usage.get("total_tokens"),
            ).debug(
                f"Processed chat completion: {choice_count} choices, "
                f"tokens={usage.get('total_tokens')}"
            )
        return result

    @classmethod
    def normalize_chat_v2_response(cls, giga_resp: Any) -> dict[str, Any]:
        """Convert a v2 chat payload to the legacy chat response shape."""
        giga_dict = cls._safe_model_dump(giga_resp)
        message: dict[str, Any] = {
            "role": "assistant",
            "content": "",
        }
        saw_function_call = False

        for raw_message in giga_dict.get("messages") or []:
            if (
                not isinstance(raw_message, dict)
                or raw_message.get("role") != "assistant"
            ):
                continue
            tools_state_id = raw_message.get("tools_state_id")
            for part_index, part in enumerate(raw_message.get("content") or []):
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str):
                    message["content"] = f"{message.get('content', '')}{text}"

                function_call = part.get("function_call")
                if isinstance(function_call, dict):
                    saw_function_call = True
                    message["function_call"] = {
                        "name": function_call.get("name"),
                        "arguments": function_call.get("arguments"),
                    }
                    if tools_state_id is not None:
                        message["functions_state_id"] = str(tools_state_id)
                    continue

                tool_execution = part.get("tool_execution")
                if isinstance(tool_execution, dict) and not saw_function_call:
                    tool_name = tool_execution.get("name")
                    if isinstance(tool_name, str) and tool_name:
                        saw_function_call = True
                        message["function_call"] = {
                            "name": tool_name,
                            "arguments": {},
                        }
                        message["functions_state_id"] = str(
                            tools_state_id or f"tool_{part_index}"
                        )

        finish_reason = giga_dict.get("finish_reason")
        if saw_function_call and finish_reason in {None, "stop"}:
            finish_reason = "function_call"

        return {
            "choices": [
                {
                    "message": message,
                    "finish_reason": finish_reason,
                }
            ],
            "usage": cls._build_legacy_usage_from_v2(giga_dict.get("usage")),
            "model": giga_dict.get("model"),
        }

    @classmethod
    def normalize_chat_v2_stream_chunk(cls, giga_resp: Any) -> dict[str, Any]:
        """Convert a v2 chat stream chunk to the legacy streaming delta shape."""
        giga_dict = cls._safe_model_dump(giga_resp)
        delta: dict[str, Any] = {}
        saw_function_call = False

        for raw_message in giga_dict.get("messages") or []:
            if not isinstance(raw_message, dict):
                continue
            role = raw_message.get("role")
            if isinstance(role, str) and role:
                delta.setdefault("role", role)
            tools_state_id = raw_message.get("tools_state_id")
            for part_index, part in enumerate(raw_message.get("content") or []):
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str):
                    delta["content"] = f"{delta.get('content', '')}{text}"

                function_call = part.get("function_call")
                if isinstance(function_call, dict):
                    saw_function_call = True
                    delta["function_call"] = {
                        "name": function_call.get("name"),
                        "arguments": function_call.get("arguments"),
                    }
                    if tools_state_id is not None:
                        delta["functions_state_id"] = str(tools_state_id)
                    continue

                tool_execution = part.get("tool_execution")
                if isinstance(tool_execution, dict) and not saw_function_call:
                    tool_name = tool_execution.get("name")
                    if isinstance(tool_name, str) and tool_name:
                        saw_function_call = True
                        delta["function_call"] = {
                            "name": tool_name,
                            "arguments": {},
                        }
                        delta["functions_state_id"] = str(
                            tools_state_id or f"tool_{part_index}"
                        )

        finish_reason = giga_dict.get("finish_reason")
        if saw_function_call and finish_reason in {None, "stop"}:
            finish_reason = "function_call"

        return {
            "choices": [
                {
                    "delta": delta,
                    "finish_reason": finish_reason,
                }
            ],
            "usage": cls._build_legacy_usage_from_v2(giga_dict.get("usage")),
            "model": giga_dict.get("model"),
        }

    def process_response_v2(
        self,
        giga_resp: Any,
        gpt_model: str,
        response_id: str,
        request_data: Optional[Dict] = None,
    ) -> dict:
        """Process a native v2 chat response into OpenAI chat-completions."""
        return self.process_response(
            self.normalize_chat_v2_response(giga_resp),
            gpt_model,
            response_id,
            request_data=request_data,
        )

    def process_stream_chunk(
        self,
        giga_resp: ChatCompletionChunk,
        gpt_model: str,
        response_id: str,
        request_data: Optional[Dict] = None,
    ) -> dict:
        """Process a streaming chat-completions chunk."""
        giga_dict = self._safe_model_dump(giga_resp)
        is_tool_call = giga_dict["choices"][0].get("finish_reason") == "function_call"

        is_structured_output = False
        if (
            request_data
            and request_data.get("response_format", {}).get("type") == "json_schema"
        ):
            is_structured_output = True

        for choice in giga_dict["choices"]:
            self._process_choice(
                choice,
                is_tool_call,
                is_stream=True,
                is_structured_output=is_structured_output,
            )

        result = {
            "id": f"chatcmpl-{response_id}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": gpt_model,
            "choices": giga_dict["choices"],
            "usage": self._build_usage(giga_dict.get("usage")),
            "system_fingerprint": f"fp_{response_id}",
        }

        if self._is_prod_mode:
            self.logger.bind(event="stream_chunk").debug(
                "Processed stream chunk (payload omitted in PROD)"
            )
        else:
            self.logger.bind(
                event="stream_chunk",
                response_id=result.get("id"),
            ).debug("Processed stream chunk")
        return result

    def process_stream_chunk_v2(
        self,
        giga_resp: Any,
        gpt_model: str,
        response_id: str,
        request_data: Optional[Dict] = None,
    ) -> dict:
        """Process a native v2 chat stream chunk into OpenAI chat deltas."""
        return self.process_stream_chunk(
            self.normalize_chat_v2_stream_chunk(giga_resp),
            gpt_model,
            response_id,
            request_data=request_data,
        )

    def _process_choice(
        self,
        choice: Dict,
        is_tool_call: bool,
        is_stream: bool = False,
        is_structured_output: bool = False,
    ):
        """Process a single chat choice."""
        message_key = "delta" if is_stream else "message"

        choice["index"] = 0
        choice["logprobs"] = None

        if is_structured_output and is_tool_call:
            choice["finish_reason"] = (
                "stop" if not is_stream or choice.get("finish_reason") else None
            )

            if message_key in choice:
                message = choice[message_key]
                message["refusal"] = None
                if message.get("function_call"):
                    args = message["function_call"]["arguments"]
                    if isinstance(args, (dict, list)):
                        content = json.dumps(args, ensure_ascii=False)
                    else:
                        content = str(args)

                    message["content"] = content
                    message.pop("function_call", None)

        elif is_tool_call:
            choice["finish_reason"] = "tool_calls"

        if message_key in choice:
            message = choice[message_key]
            message["refusal"] = None
            if message.get("function_call") and not is_structured_output:
                self._process_function_call(message, is_tool_call)

    def _process_function_call(self, message: Dict, is_tool_call: bool):
        """Process a chat-completions function call."""
        try:
            arguments = json.dumps(
                message["function_call"]["arguments"],
                ensure_ascii=False,
            )
            tool_name = map_tool_name_from_gigachat(message["function_call"]["name"])
            function_call = {
                "name": tool_name,
                "arguments": arguments,
            }
            if is_tool_call:
                message["tool_calls"] = [
                    {
                        "index": 0,
                        "id": f"call_{uuid.uuid4()}",
                        "type": "function",
                        "function": function_call,
                    }
                ]
                message.pop("function_call", None)
            else:
                message["function_call"] = function_call
            message.pop("functions_state_id", None)
        except Exception as exc:
            self.logger.error(f"Error processing function call: {exc}")
