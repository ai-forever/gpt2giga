import json
import re
import time
import uuid
from typing import Any, Dict, Literal, Mapping, Optional

from gigachat.models import ChatCompletion, ChatCompletionChunk
from openai.types.responses import ResponseFunctionToolCall, ResponseTextDeltaEvent

from gpt2giga.common.client_params import (
    extract_gigachat_response_metadata,
    merge_openai_response_metadata,
)
from gpt2giga.common.debug_logging import log_debug_payload
from gpt2giga.common.reasoning import (
    ReasoningContent,
    ReasoningContentParser,
    extract_reasoning_from_content,
    merge_reasoning_text,
)
from gpt2giga.common.tools import map_tool_name_from_gigachat, split_gigachat_tool_name
from gpt2giga.protocol.response.gigachat_chat_completion_adapter import (
    GIGACHAT_PROVIDER_METADATA_KEY,
)


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
        response_metadata = extract_gigachat_response_metadata(
            giga_dict.get("x_headers")
        )
        is_tool_call = giga_dict["choices"][0]["finish_reason"] == "function_call"

        is_structured_output = self._is_chat_structured_output_function_call(
            request_data
        )
        provider_metadata = self._extract_provider_response_metadata(giga_dict)
        if is_structured_output:
            provider_metadata.pop("gigachat_called_tools", None)
        else:
            called_tools = self._extract_chat_messages_called_tool_items(
                request_data or {}
            )
            called_tools.extend(
                self._extract_called_tool_items_from_metadata(
                    provider_metadata.pop("gigachat_called_tools", None)
                )
            )
            called_tools.extend(
                self._extract_called_tool_items_from_response(
                    giga_dict,
                    request_tools=(request_data or {}).get("tools"),
                )
            )
            response_metadata.update(self._called_tools_metadata(called_tools))
        response_metadata.update(provider_metadata)

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
        if response_metadata:
            result["metadata"] = response_metadata

        choice_count = len(result.get("choices", []))
        usage = result.get("usage") or {}
        log_debug_payload(
            self.logger,
            self._mode,
            event="chat_completion_response",
            message="Processed chat completion response",
            payload_key="response",
            payload=result,
            response_id=result.get("id"),
            choice_count=choice_count,
            total_tokens=usage.get("total_tokens"),
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
        response_metadata = extract_gigachat_response_metadata(
            giga_dict.get("x_headers")
        )
        is_tool_call = giga_dict["choices"][0]["finish_reason"] == "function_call"

        text_param = data.get("text")
        is_structured_output = self._is_responses_structured_output_function_call(data)
        provider_metadata = self._extract_provider_response_metadata(giga_dict)
        if is_structured_output:
            provider_metadata.pop("gigachat_called_tools", None)
        else:
            called_tools = self._extract_responses_input_called_tool_items(data)
            called_tools.extend(
                self._extract_called_tool_items_from_metadata(
                    provider_metadata.pop("gigachat_called_tools", None)
                )
            )
            called_tools.extend(
                self._extract_called_tool_items_from_response(
                    giga_dict,
                    request_tools=data.get("tools"),
                )
            )
            response_metadata.update(self._called_tools_metadata(called_tools))
        response_metadata.update(provider_metadata)

        for choice in giga_dict["choices"]:
            self._process_choice_responses(
                choice,
                response_id,
                request_tools=data.get("tools"),
            )

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
                request_data=data,
            ),
            usage=self._build_response_usage(giga_dict.get("usage")),
            response_text=response_text,
            response_metadata=response_metadata,
        )
        output_count = len(result.get("output", []))
        usage = result.get("usage") or {}
        log_debug_payload(
            self.logger,
            self._mode,
            event="responses_api_response",
            message="Processed responses API response",
            payload_key="response",
            payload=result,
            response_id=result.get("id"),
            output_count=output_count,
            total_tokens=usage.get("total_tokens"),
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
        response_metadata: Optional[Mapping[str, str]] = None,
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
            "metadata": merge_openai_response_metadata(
                request_data.get("metadata", {}), response_metadata
            ),
        }

    @staticmethod
    def _create_message_item(
        text: Optional[str],
        response_id: str,
        *,
        annotations: Optional[list] = None,
        inline_data: Optional[dict] = None,
    ) -> dict:
        content_part = {
            "type": "output_text",
            "text": text or "",
            "annotations": annotations or [],
            "logprobs": [],
        }
        if inline_data:
            content_part["inline_data"] = inline_data

        return {
            "type": "message",
            "id": f"msg_{response_id}",
            "status": "completed",
            "role": "assistant",
            "content": [content_part],
        }

    @staticmethod
    def _create_output_responses(
        data: dict,
        is_tool_call: bool = False,
        response_id: Optional[str] = None,
        message_key: Literal["message", "delta"] = "message",
        is_structured_output: bool = False,
        request_data: Optional[dict] = None,
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
            builtin_items = ResponseProcessor._create_builtin_tool_items(
                message,
                response_id,
                request_data=request_data,
            )
            content = message.get("content")
            if content or not builtin_items:
                inline_data = ResponseProcessor._normalize_inline_data(
                    message.get("inline_data")
                )
                annotations = ResponseProcessor._create_url_annotations(
                    content,
                    inline_data,
                )
                builtin_items.append(
                    ResponseProcessor._create_message_item(
                        content,
                        response_id,
                        annotations=annotations,
                        inline_data=inline_data,
                    )
                )
            return reasoning_items + builtin_items
        except Exception:
            return reasoning_items + [
                ResponseProcessor._create_message_item(
                    message.get("content"), response_id
                )
            ]

    @staticmethod
    def _create_builtin_tool_items(
        message: Mapping[str, Any],
        response_id: str,
        *,
        request_data: Optional[dict] = None,
    ) -> list[dict[str, Any]]:
        items = []
        inline_data = ResponseProcessor._normalize_inline_data(
            message.get("inline_data")
        )
        sources = ResponseProcessor._extract_sources(inline_data)
        tool_names = ResponseProcessor._tool_execution_names(message)
        files = ResponseProcessor._extract_files(message)

        if sources or "web_search" in tool_names:
            items.append(
                {
                    "id": f"ws_{response_id}",
                    "type": "web_search_call",
                    "status": ResponseProcessor._tool_status(
                        message, "web_search", default="completed"
                    ),
                    "action": {
                        "type": "search",
                        "query": ResponseProcessor._request_input_text(request_data),
                        "sources": [
                            {"type": "url", "url": source["url"]}
                            for source in sources.values()
                            if source.get("url")
                        ],
                    },
                }
            )

        image_files = [
            file_data
            for file_data in files
            if ResponseProcessor._is_image_file(file_data)
        ]
        if image_files or "image_generate" in tool_names:
            if image_files:
                for index, file_data in enumerate(image_files):
                    item = {
                        "id": f"ig_{response_id}_{index}",
                        "type": "image_generation_call",
                        "status": "completed"
                        if file_data.get("content")
                        else ResponseProcessor._tool_status(
                            message, "image_generate", default="completed"
                        ),
                        "result": file_data.get("content"),
                    }
                    ResponseProcessor._copy_file_metadata(item, file_data)
                    items.append(item)
            else:
                items.append(
                    {
                        "id": f"ig_{response_id}_0",
                        "type": "image_generation_call",
                        "status": ResponseProcessor._tool_status(
                            message, "image_generate", default="in_progress"
                        ),
                        "result": None,
                    }
                )

        return items

    @staticmethod
    def _normalize_inline_data(value: Any) -> dict[str, Any]:
        if isinstance(value, Mapping):
            return dict(value)
        return {}

    @staticmethod
    def _extract_sources(inline_data: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        sources = inline_data.get("sources")
        if not isinstance(sources, Mapping):
            return {}

        normalized_sources: dict[str, dict[str, Any]] = {}
        for key, source in sources.items():
            if isinstance(source, Mapping):
                normalized_sources[str(key)] = dict(source)
        return normalized_sources

    @staticmethod
    def _create_url_annotations(
        text: Any,
        inline_data: Mapping[str, Any],
        *,
        include_unreferenced: bool = True,
    ) -> list:
        if not isinstance(text, str) or not text:
            return []

        sources = ResponseProcessor._extract_sources(inline_data)
        if not sources:
            return []

        annotations = []
        annotated_sources: set[str] = set()
        for match in re.finditer(r"\[sources=\[([^\]]+)\]\]", text):
            source_ids = [
                item.strip()
                for item in re.split(r"[,;\s]+", match.group(1))
                if item.strip()
            ]
            for source_id in source_ids:
                source = sources.get(source_id)
                if not source or not source.get("url"):
                    continue
                annotations.append(
                    ResponseProcessor._create_url_annotation(
                        source,
                        start_index=match.start(),
                        end_index=match.end(),
                    )
                )
                annotated_sources.add(source_id)

        if include_unreferenced:
            for source_id, source in sources.items():
                if source_id in annotated_sources or not source.get("url"):
                    continue
                annotations.append(
                    ResponseProcessor._create_url_annotation(
                        source,
                        start_index=len(text),
                        end_index=len(text),
                    )
                )

        return annotations

    @staticmethod
    def _create_url_annotation(
        source: Mapping[str, Any], *, start_index: int, end_index: int
    ) -> dict:
        return {
            "type": "url_citation",
            "start_index": start_index,
            "end_index": end_index,
            "url": source.get("url", ""),
            "title": source.get("title") or source.get("url", ""),
        }

    @staticmethod
    def _tool_execution_names(message: Mapping[str, Any]) -> set[str]:
        names = set()
        for execution in message.get("tool_executions") or []:
            if isinstance(execution, Mapping):
                name = execution.get("name")
                if isinstance(name, str) and name:
                    names.add(ResponseProcessor._normalize_builtin_tool_name(name))
        return names

    @staticmethod
    def _tool_status(
        message: Mapping[str, Any], tool_name: str, *, default: str
    ) -> str:
        for execution in message.get("tool_executions") or []:
            if not isinstance(execution, Mapping):
                continue
            name = execution.get("name")
            if ResponseProcessor._normalize_builtin_tool_name(name) != tool_name:
                continue
            status = execution.get("status")
            if status in {"success", "completed"}:
                return "completed"
            if status == "failed":
                return "failed"
            if status in {"generating", "in_progress"}:
                return status
        return default

    @staticmethod
    def _extract_files(message: Mapping[str, Any]) -> list[dict[str, Any]]:
        files = message.get("files")
        if not isinstance(files, list):
            return []
        return [
            dict(file_data) for file_data in files if isinstance(file_data, Mapping)
        ]

    @staticmethod
    def _is_image_file(file_data: Mapping[str, Any]) -> bool:
        target = file_data.get("target")
        mime = file_data.get("mime")
        return target == "image" or (
            isinstance(mime, str) and mime.startswith("image/")
        )

    @staticmethod
    def _copy_file_metadata(item: dict[str, Any], file_data: Mapping[str, Any]) -> None:
        for source_key, target_key in (
            ("id", "file_id"),
            ("mime", "mime"),
            ("target", "target"),
        ):
            value = file_data.get(source_key)
            if value:
                item[target_key] = value

    @staticmethod
    def _normalize_builtin_tool_name(name: Any) -> str:
        if not isinstance(name, str):
            return ""
        if name.startswith("web_search"):
            return "web_search"
        if name in {"image_generation", "image_generate"}:
            return "image_generate"
        return name

    @staticmethod
    def _request_input_text(request_data: Optional[dict]) -> str:
        if not isinstance(request_data, Mapping):
            return ""

        input_data = request_data.get("input")
        if isinstance(input_data, str):
            return input_data
        if not isinstance(input_data, list):
            return ""

        texts = []
        for item in input_data:
            if not isinstance(item, Mapping) or item.get("role") != "user":
                continue
            content = item.get("content")
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                for content_part in content:
                    if (
                        isinstance(content_part, Mapping)
                        and content_part.get("type") == "input_text"
                        and isinstance(content_part.get("text"), str)
                    ):
                        texts.append(content_part["text"])
        return "\n".join(texts)

    def process_stream_chunk(
        self,
        giga_resp: ChatCompletionChunk,
        gpt_model: str,
        response_id: str,
        request_data: Optional[Dict] = None,
    ) -> dict:
        """Обрабатывает стриминговый чанк от GigaChat."""
        giga_dict = giga_resp.model_dump()
        response_metadata = extract_gigachat_response_metadata(
            giga_dict.get("x_headers")
        )
        provider_metadata = self._extract_provider_response_metadata(giga_dict)
        is_tool_call = giga_dict["choices"][0].get("finish_reason") == "function_call"

        is_structured_output = self._is_chat_structured_output_function_call(
            request_data
        )
        if is_structured_output:
            provider_metadata.pop("gigachat_called_tools", None)
        else:
            called_tools: list[dict[str, Any]] = []
            if self._is_terminal_stream_chunk(giga_dict):
                called_tools = self._extract_chat_messages_called_tool_items(
                    request_data or {}
                )
            called_tools.extend(
                self._extract_called_tool_items_from_metadata(
                    provider_metadata.pop("gigachat_called_tools", None)
                )
            )
            response_metadata.update(self._called_tools_metadata(called_tools))
        response_metadata.update(provider_metadata)

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
        if response_metadata:
            result["metadata"] = response_metadata

        log_debug_payload(
            self.logger,
            self._mode,
            event="stream_chunk",
            message="Processed stream chunk",
            payload_key="response",
            payload=result,
            response_id=result.get("id"),
        )
        return result

    @staticmethod
    def _is_terminal_stream_chunk(data: Mapping[str, Any]) -> bool:
        if data.get("usage"):
            return True

        choices = data.get("choices")
        if not isinstance(choices, list):
            return False

        return any(
            isinstance(choice, Mapping) and choice.get("finish_reason") is not None
            for choice in choices
        )

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

        log_debug_payload(
            self.logger,
            self._mode,
            event="responses_stream_chunk",
            message="Processed responses stream chunk",
            payload_key="response",
            payload=result,
            response_id=response_id,
            sequence_number=sequence_number,
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
            tool_call_id = self._backend_state_id_from_message(message)
            function_call = {
                "name": tool_name,
                "arguments": arguments,
            }
            if is_tool_call:
                message["tool_calls"] = [
                    {
                        "index": 0,  # Required for streaming tool calls
                        "id": tool_call_id or f"call_{uuid.uuid4()}",
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

    @classmethod
    def _backend_state_id_from_message(
        cls, message: Mapping[str, Any]
    ) -> Optional[str]:
        for field_name in (
            "tools_state_id",
            "tool_state_id",
            "functions_state_id",
            "function_state_id",
            "tool_call_id",
        ):
            state_id = cls._normalize_backend_state_id(message.get(field_name))
            if state_id:
                return state_id
        return None

    @staticmethod
    def _normalize_backend_state_id(value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        state_id = value.strip()
        if not state_id:
            return None
        for prefix in ("fc_", "call_"):
            if state_id.startswith(prefix) and len(state_id) > len(prefix):
                return state_id.removeprefix(prefix)
        return state_id

    def _process_choice_responses(
        self,
        choice: Dict,
        response_id: str,
        is_stream: bool = False,
        request_tools: Any = None,
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
                self._process_function_call_responses(
                    message,
                    response_id,
                    request_tools=request_tools,
                )

    def _process_function_call_responses(
        self,
        message: Dict,
        response_id: str,
        request_tools: Any = None,
    ):
        """Обрабатывает function call (Responses API)."""
        try:
            arguments = json.dumps(
                message["function_call"]["arguments"],
                ensure_ascii=False,
            )
            state_id = self._backend_state_id_from_message(message) or response_id
            tool_name, namespace = split_gigachat_tool_name(
                message["function_call"]["name"],
                request_tools=request_tools,
            )
            output = ResponseFunctionToolCall(
                arguments=arguments,
                call_id=state_id,
                name=tool_name,
                id=f"fc_{state_id}",
                status="completed",
                type="function_call",
            ).model_dump()
            if namespace:
                output["namespace"] = namespace
            message["output"] = output

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

    @staticmethod
    def _extract_provider_response_metadata(data: Mapping[str, Any]) -> dict[str, str]:
        raw_metadata = data.get(GIGACHAT_PROVIDER_METADATA_KEY)
        if not isinstance(raw_metadata, Mapping):
            return {}

        metadata: dict[str, str] = {}
        for key, value in raw_metadata.items():
            if isinstance(key, str) and isinstance(value, str):
                metadata[key] = value
        return metadata

    @classmethod
    def _extract_called_tools_metadata(
        cls,
        data: Mapping[str, Any],
    ) -> dict[str, str]:
        return cls._called_tools_metadata(
            cls._extract_called_tool_items_from_response(data)
        )

    @classmethod
    def _extract_called_tool_items_from_response(
        cls,
        data: Mapping[str, Any],
        *,
        request_tools: Any = None,
    ) -> list[dict[str, Any]]:
        choices = data.get("choices")
        if not isinstance(choices, list):
            return []

        called_tools: list[dict[str, Any]] = []
        for choice_index, raw_choice in enumerate(choices):
            if not isinstance(raw_choice, Mapping):
                continue
            message = raw_choice.get("message")
            if not isinstance(message, Mapping):
                continue
            function_call = message.get("function_call")
            if not isinstance(function_call, Mapping):
                continue
            name = function_call.get("name")
            if not isinstance(name, str) or not name:
                continue

            tool_name, namespace = split_gigachat_tool_name(
                name,
                request_tools=request_tools,
            )
            item: dict[str, Any] = {
                "index": len(called_tools),
                "choice_index": choice_index,
                "name": tool_name,
                "arguments": cls._normalize_called_tool_arguments(
                    function_call.get("arguments", {})
                ),
            }
            if namespace:
                item["namespace"] = namespace
            role = message.get("role")
            if isinstance(role, str) and role:
                item["role"] = role
            state_id = cls._raw_backend_state_id_from_message(message)
            if state_id:
                item["tools_state_id"] = state_id
            called_tools.append(item)
        return called_tools

    @classmethod
    def _extract_responses_input_called_tool_items(
        cls,
        request_data: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        input_items = request_data.get("input")
        if not isinstance(input_items, list):
            return []

        called_tools: list[dict[str, Any]] = []
        for input_index, raw_item in enumerate(input_items):
            if not isinstance(raw_item, Mapping):
                continue
            if raw_item.get("type") != "function_call":
                continue
            name = raw_item.get("name")
            if not isinstance(name, str) or not name:
                continue

            item: dict[str, Any] = {
                "index": len(called_tools),
                "input_index": input_index,
                "name": map_tool_name_from_gigachat(name),
                "arguments": cls._normalize_called_tool_arguments(
                    raw_item.get("arguments", {})
                ),
            }
            namespace = cls._normalize_metadata_string(raw_item.get("namespace"))
            if namespace:
                item["namespace"] = namespace
            call_id = cls._normalize_metadata_string(raw_item.get("call_id"))
            if call_id:
                item["call_id"] = call_id
                item["tools_state_id"] = call_id
            item_id = cls._normalize_metadata_string(raw_item.get("id"))
            if item_id:
                item["id"] = item_id
            status = cls._normalize_metadata_string(raw_item.get("status"))
            if status:
                item["status"] = status
            called_tools.append(item)
        return called_tools

    @classmethod
    def _extract_chat_messages_called_tool_items(
        cls,
        request_data: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        messages = request_data.get("messages")
        if not isinstance(messages, list):
            return []

        called_tools: list[dict[str, Any]] = []
        for message_index, raw_message in enumerate(messages):
            if not isinstance(raw_message, Mapping):
                continue

            tool_calls = raw_message.get("tool_calls")
            if isinstance(tool_calls, list):
                for tool_call_index, raw_tool_call in enumerate(tool_calls):
                    if not isinstance(raw_tool_call, Mapping):
                        continue
                    function = raw_tool_call.get("function")
                    if not isinstance(function, Mapping):
                        continue
                    item = cls._chat_tool_call_item(
                        function,
                        raw_message,
                        raw_tool_call,
                        call_index=len(called_tools),
                        message_index=message_index,
                        tool_call_index=tool_call_index,
                    )
                    if item:
                        called_tools.append(item)

            function_call = raw_message.get("function_call")
            if isinstance(function_call, Mapping):
                item = cls._chat_tool_call_item(
                    function_call,
                    raw_message,
                    raw_message,
                    call_index=len(called_tools),
                    message_index=message_index,
                )
                if item:
                    called_tools.append(item)

            content = raw_message.get("content")
            if isinstance(content, list):
                for content_index, raw_part in enumerate(content):
                    if not isinstance(raw_part, Mapping):
                        continue
                    function_call = raw_part.get("function_call")
                    if not isinstance(function_call, Mapping):
                        continue
                    item = cls._chat_tool_call_item(
                        function_call,
                        raw_message,
                        raw_message,
                        call_index=len(called_tools),
                        message_index=message_index,
                        content_index=content_index,
                    )
                    if item:
                        called_tools.append(item)

        return called_tools

    @classmethod
    def _chat_tool_call_item(
        cls,
        function: Mapping[str, Any],
        message: Mapping[str, Any],
        tool_call: Mapping[str, Any],
        *,
        call_index: int,
        message_index: int,
        tool_call_index: Optional[int] = None,
        content_index: Optional[int] = None,
    ) -> Optional[dict[str, Any]]:
        name = function.get("name")
        if not isinstance(name, str) or not name:
            return None

        item: dict[str, Any] = {
            "index": call_index,
            "message_index": message_index,
            "name": map_tool_name_from_gigachat(name),
            "arguments": cls._normalize_called_tool_arguments(
                function.get("arguments", {})
            ),
        }
        namespace = cls._normalize_metadata_string(
            tool_call.get("namespace") or function.get("namespace")
        )
        if namespace:
            item["namespace"] = namespace
        if tool_call_index is not None:
            item["tool_call_index"] = tool_call_index
        if content_index is not None:
            item["content_index"] = content_index
        role = message.get("role")
        if isinstance(role, str) and role:
            item["role"] = role
        call_id = cls._normalize_metadata_string(tool_call.get("id"))
        if call_id:
            item["call_id"] = call_id
            item["tools_state_id"] = call_id
        state_id = cls._raw_backend_state_id_from_message(message)
        if state_id:
            item["tools_state_id"] = state_id
        return item

    @classmethod
    def _extract_called_tool_items_from_metadata(
        cls,
        raw_called_tools: Any,
    ) -> list[dict[str, Any]]:
        if not isinstance(raw_called_tools, str) or not raw_called_tools:
            return []
        try:
            decoded = json.loads(raw_called_tools)
        except json.JSONDecodeError:
            return []
        if not isinstance(decoded, list):
            return []
        return [dict(item) for item in decoded if isinstance(item, Mapping)]

    @classmethod
    def _called_tools_metadata(
        cls,
        called_tools: list[dict[str, Any]],
    ) -> dict[str, str]:
        if not called_tools:
            return {}

        called_tools = cls._dedupe_called_tool_items(called_tools)
        return {
            "gigachat_called_tools": json.dumps(
                called_tools,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        }

    @classmethod
    def _dedupe_called_tool_items(
        cls,
        called_tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in called_tools:
            key = cls._called_tool_item_key(item)
            if key in seen:
                continue
            seen.add(key)
            normalized = dict(item)
            normalized["index"] = len(deduped)
            deduped.append(normalized)
        return deduped

    @staticmethod
    def _called_tool_item_key(item: Mapping[str, Any]) -> str:
        return json.dumps(
            {
                "name": item.get("name"),
                "namespace": item.get("namespace"),
                "arguments": item.get("arguments"),
                "call_id": item.get("call_id"),
                "tools_state_id": item.get("tools_state_id"),
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

    @staticmethod
    def _normalize_called_tool_arguments(arguments: Any) -> Any:
        if not isinstance(arguments, str):
            return arguments
        try:
            return json.loads(arguments)
        except json.JSONDecodeError:
            return arguments

    @classmethod
    def _raw_backend_state_id_from_message(
        cls, message: Mapping[str, Any]
    ) -> Optional[str]:
        for field_name in (
            "tools_state_id",
            "tool_state_id",
            "functions_state_id",
            "function_state_id",
            "tool_call_id",
        ):
            state_id = cls._normalize_metadata_string(message.get(field_name))
            if state_id:
                return state_id
        return None

    @staticmethod
    def _normalize_metadata_string(value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None
