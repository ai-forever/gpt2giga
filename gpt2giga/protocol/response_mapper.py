import json
import time
import uuid
from typing import Optional, Dict, Literal

from gigachat.models import ChatCompletion, ChatCompletionChunk
from openai.types.responses import ResponseFunctionToolCall, ResponseTextDeltaEvent


class ResponseProcessor:
    """Обработчик ответов от GigaChat в формат OpenAI"""

    def __init__(self, logger):
        self.logger = logger

    def process_response(
        self,
        giga_resp: ChatCompletion,
        gpt_model: str,
        response_id: str,
        request_data: Optional[Dict] = None,
    ) -> dict:
        """Обрабатывает обычный ответ от GigaChat"""
        giga_dict = giga_resp.model_dump()
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

        self.logger.debug("Processed chat completion response")
        self.logger.debug(f"Response: {result}")
        return result

    def process_response_api(
        self,
        data: dict,
        giga_resp: ChatCompletion,
        gpt_model: str,
        response_id: str,
    ) -> dict:
        giga_dict = giga_resp.model_dump()
        is_tool_call = giga_dict["choices"][0]["finish_reason"] == "function_call"

        is_structured_output = False
        text_param = data.get("text")
        if text_param and isinstance(text_param, dict):
            fmt = text_param.get("format")
            if fmt and isinstance(fmt, dict) and fmt.get("type") == "json_schema":
                is_structured_output = True

        for choice in giga_dict["choices"]:
            self._process_choice_responses(choice, response_id)

        response_text = {"format": {"type": "text"}}
        if text_param and isinstance(text_param, dict):
            response_text = text_param

        result = {
            "id": f"resp_{response_id}",
            "object": "response",
            "created_at": int(time.time()),
            "status": "completed",
            "instructions": data.get("instructions"),
            "model": gpt_model,
            "output": self._create_output_responses(
                giga_dict,
                is_tool_call,
                response_id,
                is_structured_output=is_structured_output,
            ),
            "text": response_text,
            "usage": self._build_response_usage(giga_dict.get("usage")),
        }
        self.logger.debug("Processed responses API response")
        self.logger.debug(f"Response: {result}")

        return result

    @staticmethod
    def _create_output_responses(
        data: dict,
        is_tool_call: bool = False,
        response_id: Optional[str] = None,
        message_key: Literal["message", "delta"] = "message",
        is_structured_output: bool = False,
    ) -> list:
        response_id = str(uuid.uuid4()) if response_id is None else response_id
        try:
            if is_tool_call and not is_structured_output:
                return [data["choices"][0][message_key]["output"]]
            elif is_tool_call and is_structured_output:
                output_item = data["choices"][0][message_key]["output"]
                arguments = output_item.get("arguments", "{}")
                return [
                    {
                        "type": "message",
                        "id": f"msg_{response_id}",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": arguments,
                            }
                        ],
                    }
                ]
            else:
                return [
                    {
                        "type": "message",
                        "id": f"msg_{response_id}",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": data["choices"][0][message_key]["content"],
                            }
                        ],
                    }
                ]
        except Exception:
            return [
                {
                    "type": "message",
                    "id": f"msg_{response_id}",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": data["choices"][0][message_key]["content"],
                        }
                    ],
                }
            ]

    def process_stream_chunk(
        self,
        giga_resp: ChatCompletionChunk,
        gpt_model: str,
        response_id: str,
        request_data: Optional[Dict] = None,
    ) -> dict:
        """Обрабатывает стриминговый чанк от GigaChat"""
        giga_dict = giga_resp.model_dump()
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

        self.logger.debug(f"Processed stream chunk: {result}")
        return result

    def process_stream_chunk_response(
        self,
        giga_resp: ChatCompletionChunk,
        sequence_number: int = 0,
        response_id: Optional[str] = None,
    ) -> dict:
        giga_dict = giga_resp.model_dump()
        response_id = str(uuid.uuid4()) if response_id is None else response_id
        for choice in giga_dict["choices"]:
            self._process_choice_responses(choice, response_id, is_stream=True)
        delta = giga_dict["choices"][0]["delta"]
        if delta["content"]:
            result = ResponseTextDeltaEvent(
                content_index=0,
                delta=delta["content"],
                item_id=f"msg_{response_id}",
                output_index=0,
                logprobs=[],
                type="response.output_text.delta",
                sequence_number=sequence_number,
            ).dict()
        else:
            result = self._create_output_responses(
                giga_dict,
                is_tool_call=True,
                message_key="delta",
                response_id=response_id,
            )

        return result

    def _process_choice(
        self,
        choice: Dict,
        is_tool_call: bool,
        is_stream: bool = False,
        is_structured_output: bool = False,
    ):
        """Обрабатывает отдельный choice"""
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
                    # For streaming, we might need to handle incremental updates if GigaChat streams function args.
                    # But here we assume we are just converting structure.

        elif is_tool_call:
            choice["finish_reason"] = "tool_calls"

        if message_key in choice:
            message = choice[message_key]
            message["refusal"] = None
            if message.get("function_call") and not is_structured_output:
                self._process_function_call(message, is_tool_call)

    def _process_function_call(self, message: Dict, is_tool_call: bool):
        """Обрабатывает function call"""
        try:
            arguments = json.dumps(
                message["function_call"]["arguments"],
                ensure_ascii=False,
            )
            function_call = {
                "name": message["function_call"]["name"],
                "arguments": arguments,
            }
            if is_tool_call:
                message["tool_calls"] = [
                    {
                        "id": f"call_{uuid.uuid4()}",
                        "type": "function",
                        "function": function_call,
                    }
                ]
            else:
                message["function_call"] = function_call
            message.pop("functions_state_id", None)
        except Exception as e:
            self.logger.error(f"Error processing function call: {e}")

    def _process_choice_responses(
        self, choice: Dict, response_id: str, is_stream: bool = False
    ):
        """Обрабатывает отдельный choice"""
        message_key = "delta" if is_stream else "message"

        choice["index"] = 0
        choice["logprobs"] = None

        if message_key in choice:
            message = choice[message_key]
            message["refusal"] = None

            if message.get("role") == "assistant" and message.get("function_call"):
                self._process_function_call_responses(message, response_id)

    def _process_function_call_responses(self, message: Dict, response_id: str):
        """Обрабатывает function call"""
        try:
            arguments = json.dumps(
                message["function_call"]["arguments"],
                ensure_ascii=False,
            )
            message["output"] = ResponseFunctionToolCall(
                arguments=arguments,
                call_id=f"call_{response_id}",
                name=message["function_call"]["name"],
                id=f"fc_{message['functions_state_id']}",
                status="completed",
                type="function_call",
            ).model_dump()

        except Exception as e:
            self.logger.error(f"Error processing function call: {e}")

    @staticmethod
    def _build_usage(usage_data: Optional[Dict]) -> Optional[Dict]:
        """Строит объект usage"""
        if not usage_data:
            return None

        return {
            "prompt_tokens": usage_data["prompt_tokens"],
            "completion_tokens": usage_data["completion_tokens"],
            "total_tokens": usage_data["total_tokens"],
            "prompt_tokens_details": {
                "cached_tokens": usage_data.get("precached_prompt_tokens", 0)
            },
            "completion_tokens_details": {"reasoning_tokens": 0},
        }

    @staticmethod
    def _build_response_usage(usage_data: Optional[Dict]) -> Optional[Dict]:
        if not usage_data:
            return None
        return {
            "input_tokens": usage_data.get("prompt_tokens", 0),
            "output_tokens": usage_data.get("completion_tokens", 0),
            "total_tokens": usage_data["total_tokens"],
            "prompt_tokens_details": {
                "cached_tokens": usage_data.get("precached_prompt_tokens", 0)
            },
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        }
