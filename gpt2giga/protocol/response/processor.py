import json
import time
import uuid
from typing import Any, Dict, Iterable, Literal, Optional

from gigachat.models import ChatCompletion, ChatCompletionChunk, ChatCompletionV2
from openai.types.responses import ResponseFunctionToolCall, ResponseTextDeltaEvent

from gpt2giga.common.tools import map_tool_name_from_gigachat


class ResponseProcessor:
    """Обработчик ответов от GigaChat в формат OpenAI."""

    def __init__(self, logger=None, mode: str = "DEV"):
        if logger is None:
            from loguru import logger as default_logger

            logger = default_logger
        self.logger = logger
        self._mode = mode.upper() if isinstance(mode, str) else "DEV"

    @property
    def _is_prod_mode(self) -> bool:
        return self._mode == "PROD"

    @staticmethod
    def _safe_model_dump(model: Any) -> Dict[str, Any]:
        if isinstance(model, dict):
            return model
        if hasattr(model, "model_dump"):
            try:
                return model.model_dump(exclude_none=True, by_alias=True)
            except TypeError:
                return model.model_dump()
        return dict(model)

    @staticmethod
    def _stringify_json(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _build_response_text_config(request_data: Optional[Dict]) -> dict:
        text_config = (
            request_data.get("text") if isinstance(request_data, dict) else None
        )
        if isinstance(text_config, dict):
            result = dict(text_config)
            result.setdefault("format", {"type": "text"})
            return result
        return {"format": {"type": "text"}}

    @staticmethod
    def _build_response_status(
        finish_reason: Optional[str],
    ) -> tuple[str, Optional[Dict[str, str]]]:
        if finish_reason in {"length", "max_tokens", "max_output_tokens"}:
            return "incomplete", {"reason": "max_output_tokens"}
        if finish_reason == "content_filter":
            return "incomplete", {"reason": "content_filter"}
        if finish_reason == "cancelled":
            return "cancelled", None
        if finish_reason == "queued":
            return "queued", None
        if finish_reason == "in_progress":
            return "in_progress", None
        if finish_reason == "error":
            return "failed", None
        return "completed", None

    @staticmethod
    def _build_output_item_status(response_status: str) -> str:
        if response_status == "in_progress":
            return "in_progress"
        if response_status == "completed":
            return "completed"
        return "incomplete"

    @staticmethod
    def _extract_web_search_action(
        additional_data: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        steps = []
        if isinstance(additional_data, dict):
            maybe_steps = additional_data.get("execution_steps")
            if isinstance(maybe_steps, list):
                steps = maybe_steps

        query = ""
        sources: list[Dict[str, str]] = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            query_value = step.get("query")
            if query_value is None and isinstance(step.get("arguments"), dict):
                query_value = step["arguments"].get("query")
            if isinstance(query_value, str) and query_value:
                query = query_value

            raw_sources = step.get("sources")
            if isinstance(raw_sources, list):
                for source in raw_sources:
                    if isinstance(source, str) and source:
                        sources.append({"type": "url", "url": source})
                    elif isinstance(source, dict):
                        url = source.get("url")
                        if isinstance(url, str) and url:
                            sources.append({"type": "url", "url": url})
            if query or sources:
                break

        action: Dict[str, Any] = {
            "type": "search",
            "query": query,
        }
        if query:
            action["queries"] = [query]
        if sources:
            action["sources"] = sources
        return action

    @staticmethod
    def _convert_logprobs(
        logprobs: Optional[Iterable[Dict[str, Any]]],
    ) -> Optional[list[Dict[str, Any]]]:
        if not logprobs:
            return None

        result: list[Dict[str, Any]] = []
        for entry in logprobs:
            if not isinstance(entry, dict):
                continue
            chosen = entry.get("chosen") or {}
            token = chosen.get("token")
            logprob = chosen.get("logprob")
            if not isinstance(token, str) or logprob is None:
                continue
            top_logprobs: list[Dict[str, Any]] = []
            for candidate in entry.get("top") or []:
                if not isinstance(candidate, dict):
                    continue
                candidate_token = candidate.get("token")
                candidate_logprob = candidate.get("logprob")
                if not isinstance(candidate_token, str) or candidate_logprob is None:
                    continue
                top_logprobs.append(
                    {
                        "token": candidate_token,
                        "bytes": list(candidate_token.encode("utf-8")),
                        "logprob": candidate_logprob,
                    }
                )
            result.append(
                {
                    "token": token,
                    "bytes": list(token.encode("utf-8")),
                    "logprob": logprob,
                    "top_logprobs": top_logprobs,
                }
            )

        return result or None

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

    @classmethod
    def build_response_api_result_v2(
        cls,
        request_data: Optional[Dict],
        gpt_model: str,
        response_id: str,
        output: list,
        usage: Optional[Dict],
        *,
        created_at: Optional[float] = None,
        completed_at: Optional[float] = None,
        status: str = "completed",
        incomplete_details: Optional[Dict[str, str]] = None,
        thread_id: Optional[str] = None,
    ) -> dict:
        request_data = request_data or {}
        return {
            "id": f"resp_{response_id}",
            "object": "response",
            "created_at": created_at if created_at is not None else int(time.time()),
            "status": status,
            "error": None,
            "incomplete_details": incomplete_details,
            "instructions": request_data.get("instructions"),
            "metadata": request_data.get("metadata"),
            "model": gpt_model,
            "output": output,
            "parallel_tool_calls": request_data.get("parallel_tool_calls", True),
            "temperature": request_data.get("temperature"),
            "tool_choice": request_data.get("tool_choice", "auto"),
            "tools": request_data.get("tools", []),
            "top_p": request_data.get("top_p"),
            "background": request_data.get("background"),
            "completed_at": completed_at,
            "conversation": {"id": thread_id} if thread_id else None,
            "max_output_tokens": request_data.get("max_output_tokens"),
            "max_tool_calls": request_data.get("max_tool_calls"),
            "previous_response_id": request_data.get("previous_response_id"),
            "prompt": request_data.get("prompt"),
            "prompt_cache_key": request_data.get("prompt_cache_key"),
            "prompt_cache_retention": request_data.get("prompt_cache_retention"),
            "reasoning": cls._build_reasoning_config(request_data),
            "safety_identifier": request_data.get("safety_identifier"),
            "service_tier": request_data.get("service_tier"),
            "text": cls._build_response_text_config(request_data),
            "top_logprobs": request_data.get("top_logprobs"),
            "truncation": request_data.get("truncation", "disabled"),
            "usage": usage,
            "user": request_data.get("user"),
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

    @staticmethod
    def store_response_metadata(
        response_store: Optional[Dict[str, Any]], response: Dict[str, Any]
    ) -> None:
        if not isinstance(response_store, dict):
            return
        response_id = response.get("id")
        conversation = response.get("conversation") or {}
        thread_id = conversation.get("id")
        if isinstance(response_id, str) and isinstance(thread_id, str) and thread_id:
            response_store[response_id] = {"thread_id": thread_id}

    def process_response(
        self,
        giga_resp: ChatCompletion,
        gpt_model: str,
        response_id: str,
        request_data: Optional[Dict] = None,
    ) -> dict:
        """Обрабатывает обычный ответ от GigaChat."""
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

    def process_response_api(
        self,
        data: dict,
        giga_resp: ChatCompletion,
        gpt_model: str,
        response_id: str,
    ) -> dict:
        giga_dict = self._safe_model_dump(giga_resp)
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

    def process_response_api_v2(
        self,
        data: dict,
        giga_resp: ChatCompletionV2,
        gpt_model: str,
        response_id: str,
        response_store: Optional[Dict[str, Any]] = None,
    ) -> dict:
        giga_dict = self._safe_model_dump(giga_resp)
        model = giga_dict.get("model") or gpt_model
        created_at = giga_dict.get("created_at", int(time.time()))
        thread_id = giga_dict.get("thread_id")
        response_status, incomplete_details = self._build_response_status(
            giga_dict.get("finish_reason")
        )

        result = self.build_response_api_result_v2(
            request_data=data,
            gpt_model=model,
            response_id=response_id,
            output=self._create_output_responses_v2(
                giga_dict,
                response_id,
                response_status=response_status,
            ),
            usage=self._build_response_usage_v2(giga_dict.get("usage")),
            created_at=created_at,
            completed_at=int(time.time()),
            status=response_status,
            incomplete_details=incomplete_details,
            thread_id=thread_id,
        )
        self.store_response_metadata(response_store, result)

        if self._is_prod_mode:
            self.logger.bind(event="responses_api_response_v2").debug(
                "Processed v2 responses API response (payload omitted in PROD)"
            )
        else:
            output_count = len(result.get("output", []))
            usage = result.get("usage") or {}
            self.logger.bind(
                event="responses_api_response_v2",
                response_id=result.get("id"),
                output_count=output_count,
                total_tokens=usage.get("total_tokens"),
                thread_id=thread_id,
            ).debug(
                f"Processed v2 responses API: {output_count} outputs, "
                f"tokens={usage.get('total_tokens')}"
            )

        return result

    def process_stream_chunk(
        self,
        giga_resp: ChatCompletionChunk,
        gpt_model: str,
        response_id: str,
        request_data: Optional[Dict] = None,
    ) -> dict:
        """Обрабатывает стриминговый чанк от GigaChat."""
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

    def process_stream_chunk_response(
        self,
        giga_resp: ChatCompletionChunk,
        sequence_number: int = 0,
        response_id: Optional[str] = None,
    ) -> dict:
        giga_dict = self._safe_model_dump(giga_resp)
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

    @staticmethod
    def _build_response_usage_v2(usage_data: Optional[Dict]) -> Optional[Dict]:
        if not usage_data:
            return None
        input_details = usage_data.get("input_tokens_details") or {}
        return {
            "input_tokens": usage_data.get("input_tokens", 0),
            "input_tokens_details": {
                "cached_tokens": input_details.get("cached_tokens", 0)
            },
            "output_tokens": usage_data.get("output_tokens", 0),
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": usage_data.get("total_tokens", 0),
        }
