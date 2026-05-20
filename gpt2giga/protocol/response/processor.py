import json
import time
import uuid
from typing import Dict, Literal, Optional

from gigachat.models import ChatCompletion, ChatCompletionChunk
from openai.types.responses import ResponseFunctionToolCall, ResponseTextDeltaEvent

from gpt2giga.common.reasoning import (
    ReasoningContent,
    ReasoningContentParser,
    extract_reasoning_from_content,
    merge_reasoning_text,
)
from gpt2giga.common.tools import map_tool_name_from_gigachat


class ResponseProcessor:
    """Обработчик ответов от GigaChat в формат OpenAI."""

    def __init__(
        self,
        logger=None,
        mode: str = "DEV",
        structured_output_mode: str = "function_call",
    ):
        if logger is None:
            from loguru import logger as default_logger

            logger = default_logger
        self.logger = logger
        self._mode = mode.upper() if isinstance(mode, str) else "DEV"
        self._structured_output_mode = (
            structured_output_mode.lower()
            if isinstance(structured_output_mode, str)
            else "function_call"
        )
        self._stream_reasoning_parsers: dict[str, ReasoningContentParser] = {}

    @property
    def _is_prod_mode(self) -> bool:
        return self._mode == "PROD"

    def _uses_structured_output_function_call(self) -> bool:
        return self._structured_output_mode == "function_call"

    def _is_chat_structured_output_function_call(
        self, request_data: Optional[Dict]
    ) -> bool:
        if not self._uses_structured_output_function_call():
            return False
        response_format = None
        if isinstance(request_data, dict):
            response_format = request_data.get("response_format")
        return (
            isinstance(response_format, dict)
            and response_format.get("type") == "json_schema"
        )

    def _is_responses_structured_output_function_call(self, data: dict) -> bool:
        if not self._uses_structured_output_function_call():
            return False
        text_param = data.get("text")
        if not isinstance(text_param, dict):
            return False
        fmt = text_param.get("format")
        return isinstance(fmt, dict) and fmt.get("type") == "json_schema"

    def process_response(
        self,
        giga_resp: ChatCompletion,
        gpt_model: str,
        response_id: str,
        request_data: Optional[Dict] = None,
    ) -> dict:
        """Обрабатывает обычный ответ от GigaChat."""
        giga_dict = giga_resp.model_dump()
        is_tool_call = giga_dict["choices"][0]["finish_reason"] == "function_call"

        is_structured_output = self._is_chat_structured_output_function_call(
            request_data
        )

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

    def process_response_api(
        self,
        data: dict,
        giga_resp: ChatCompletion,
        gpt_model: str,
        response_id: str,
    ) -> dict:
        giga_dict = giga_resp.model_dump()
        is_tool_call = giga_dict["choices"][0]["finish_reason"] == "function_call"

        text_param = data.get("text")
        is_structured_output = self._is_responses_structured_output_function_call(data)

        for choice in giga_dict["choices"]:
            self._process_choice_responses(choice, response_id)

        response_text = {"format": {"type": "text"}}
        if text_param and isinstance(text_param, dict):
            response_text = text_param

        result = self._build_responses_api_result(
            request_data=data,
            gpt_model=gpt_model,
            response_id=response_id,
            output=self._create_output_responses(
                giga_dict,
                is_tool_call,
                response_id,
                is_structured_output=is_structured_output,
            ),
            usage=self._build_response_usage(giga_dict.get("usage")),
            response_text=response_text,
        )
        if self._is_prod_mode:
            self.logger.bind(event="responses_api_response").debug(
                "Processed responses API response (payload omitted in PROD)"
            )
        else:
            output_count = len(result.get("output", []))
            usage = result.get("usage") or {}
            self.logger.bind(
                event="responses_api_response",
                response_id=result.get("id"),
                output_count=output_count,
                total_tokens=usage.get("total_tokens"),
            ).debug(
                f"Processed responses API: {output_count} outputs, "
                f"tokens={usage.get('total_tokens')}"
            )

        return result

    @staticmethod
    def _create_reasoning_item(reasoning_text: Optional[str], response_id: str) -> list:
        if not reasoning_text:
            return []
        return [
            {
                "id": f"rs_{response_id}",
                "type": "reasoning",
                "summary": [
                    {
                        "type": "summary_text",
                        "text": reasoning_text,
                    }
                ],
            }
        ]

    @staticmethod
    def _build_reasoning_config(
        request_data: Optional[Dict],
    ) -> dict[str, Optional[str]]:
        reasoning_data = (
            request_data.get("reasoning") if isinstance(request_data, dict) else None
        )
        if isinstance(reasoning_data, dict):
            return {
                "effort": reasoning_data.get("effort"),
                "summary": reasoning_data.get("summary"),
            }

        effort = (
            request_data.get("reasoning_effort")
            if isinstance(request_data, dict)
            else None
        )
        return {"effort": effort, "summary": None}

    @classmethod
    def _build_responses_api_result(
        cls,
        request_data: Optional[Dict],
        gpt_model: str,
        response_id: str,
        output: list,
        usage: Optional[Dict],
        response_text: dict,
    ) -> dict:
        request_data = request_data or {}
        return {
            "id": f"resp_{response_id}",
            "object": "response",
            "created_at": int(time.time()),
            "status": "completed",
            "error": None,
            "incomplete_details": None,
            "instructions": request_data.get("instructions"),
            "max_output_tokens": request_data.get("max_output_tokens"),
            "model": gpt_model,
            "output": output,
            "parallel_tool_calls": request_data.get("parallel_tool_calls", True),
            "previous_response_id": request_data.get("previous_response_id"),
            "reasoning": cls._build_reasoning_config(request_data),
            "store": request_data.get("store", True),
            "temperature": request_data.get("temperature", 1),
            "text": response_text,
            "tool_choice": request_data.get("tool_choice", "auto"),
            "tools": request_data.get("tools", []),
            "top_p": request_data.get("top_p", 1),
            "truncation": request_data.get("truncation", "disabled"),
            "usage": usage,
            "user": request_data.get("user"),
            "metadata": request_data.get("metadata", {}),
        }

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

    @staticmethod
    def _create_output_responses(
        data: dict,
        is_tool_call: bool = False,
        response_id: Optional[str] = None,
        message_key: Literal["message", "delta"] = "message",
        is_structured_output: bool = False,
    ) -> list:
        response_id = str(uuid.uuid4()) if response_id is None else response_id
        choice = data["choices"][0]
        message = choice.get(message_key, {})
        reasoning_items = ResponseProcessor._create_reasoning_item(
            message.get("reasoning_content"), response_id
        )
        try:
            if is_tool_call and not is_structured_output:
                return reasoning_items + [message["output"]]
            if is_tool_call and is_structured_output:
                output_item = message["output"]
                arguments = output_item.get("arguments", "{}")
                return reasoning_items + [
                    ResponseProcessor._create_message_item(arguments, response_id)
                ]
            return reasoning_items + [
                ResponseProcessor._create_message_item(
                    message.get("content"), response_id
                )
            ]
        except Exception:
            return reasoning_items + [
                ResponseProcessor._create_message_item(
                    message.get("content"), response_id
                )
            ]

    def process_stream_chunk(
        self,
        giga_resp: ChatCompletionChunk,
        gpt_model: str,
        response_id: str,
        request_data: Optional[Dict] = None,
    ) -> dict:
        """Обрабатывает стриминговый чанк от GigaChat."""
        giga_dict = giga_resp.model_dump()
        is_tool_call = giga_dict["choices"][0].get("finish_reason") == "function_call"

        is_structured_output = self._is_chat_structured_output_function_call(
            request_data
        )

        for choice in giga_dict["choices"]:
            self._process_choice(
                choice,
                is_tool_call,
                is_stream=True,
                response_id=response_id,
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

    def flush_stream_reasoning(
        self,
        response_id: str,
        *,
        family: Literal["chat", "responses"] = "chat",
    ) -> ReasoningContent:
        """Flush and remove any parser state for a completed stream."""
        parser = self._stream_reasoning_parsers.pop(f"{family}:{response_id}", None)
        if parser is None:
            return ReasoningContent(content="", reasoning_content="")
        return parser.flush()

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
        response_id: Optional[str] = None,
        is_structured_output: bool = False,
    ):
        """Обрабатывает отдельный choice."""
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
            self._extract_reasoning_from_message(
                message,
                is_stream=is_stream,
                parser_key=f"chat:{response_id}" if response_id else None,
                finish_reason=choice.get("finish_reason"),
            )

    def _extract_reasoning_from_message(
        self,
        message: Dict,
        *,
        is_stream: bool,
        parser_key: Optional[str] = None,
        finish_reason: Optional[str] = None,
    ):
        content = message.get("content")
        if not is_stream:
            if not isinstance(content, str):
                return

            parsed = extract_reasoning_from_content(content)
            message["content"] = parsed.content
            message["reasoning_content"] = merge_reasoning_text(
                message.get("reasoning_content"), parsed.reasoning_content
            )
            if message.get("reasoning_content") is None:
                message.pop("reasoning_content", None)
            return

        if parser_key is None:
            parser_key = f"anonymous:{id(message)}"
        parser = self._stream_reasoning_parsers.setdefault(
            parser_key, ReasoningContentParser()
        )

        parsed_content = None
        parsed_reasoning = None
        if isinstance(content, str):
            parsed = parser.feed(content)
            parsed_content = parsed.content
            parsed_reasoning = parsed.reasoning_content
            message["content"] = parsed_content

        if finish_reason is not None:
            parsed = parser.flush()
            if parsed.content:
                parsed_content = (parsed_content or "") + parsed.content
            if parsed.reasoning_content:
                parsed_reasoning = (parsed_reasoning or "") + parsed.reasoning_content
            if parsed_content:
                message["content"] = parsed_content
            self._stream_reasoning_parsers.pop(parser_key, None)

        message["reasoning_content"] = merge_reasoning_text(
            message.get("reasoning_content"), parsed_reasoning
        )
        if message.get("reasoning_content") is None:
            message.pop("reasoning_content", None)

    def _process_function_call(self, message: Dict, is_tool_call: bool):
        """Обрабатывает function call."""
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
                        "index": 0,  # Required for streaming tool calls
                        "id": f"call_{uuid.uuid4()}",
                        "type": "function",
                        "function": function_call,
                    }
                ]
                message.pop("function_call", None)
            else:
                message["function_call"] = function_call
            message.pop("functions_state_id", None)
        except Exception as e:
            self.logger.error(f"Error processing function call: {e}")

    def _process_choice_responses(
        self, choice: Dict, response_id: str, is_stream: bool = False
    ):
        """Обрабатывает отдельный choice (Responses API)."""
        message_key = "delta" if is_stream else "message"

        choice["index"] = 0
        choice["logprobs"] = None

        if message_key in choice:
            message = choice[message_key]
            message["refusal"] = None
            self._extract_reasoning_from_message(
                message,
                is_stream=is_stream,
                parser_key=f"responses:{response_id}",
                finish_reason=choice.get("finish_reason"),
            )

            if message.get("role") == "assistant" and message.get("function_call"):
                self._process_function_call_responses(message, response_id)

    def _process_function_call_responses(self, message: Dict, response_id: str):
        """Обрабатывает function call (Responses API)."""
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

        except Exception as e:
            self.logger.error(f"Error processing function call: {e}")

    @staticmethod
    def _build_usage(usage_data: Optional[Dict]) -> Optional[Dict]:
        """Строит объект usage."""
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
