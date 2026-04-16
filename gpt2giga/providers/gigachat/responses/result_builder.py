"""Responses API response/result assembly helpers."""

import time
from typing import Any, Dict, Optional


class ResponsesResultBuilderMixin:
    """Assemble top-level Responses API payloads."""

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
    def store_response_metadata(
        response_store: Optional[Dict[str, Any]],
        response: Dict[str, Any],
    ) -> None:
        if not isinstance(response_store, dict):
            return
        response_id = response.get("id")
        conversation = response.get("conversation") or {}
        thread_id = conversation.get("id")
        model = response.get("model")
        if isinstance(response_id, str) and isinstance(thread_id, str) and thread_id:
            metadata = {"thread_id": thread_id}
            if isinstance(model, str) and model:
                metadata["model"] = model
            response_store[response_id] = metadata

    def process_response_api(
        self,
        data: dict,
        giga_resp,
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
        giga_resp,
        gpt_model: str,
        response_id: str,
        response_store: Optional[Dict[str, Any]] = None,
    ) -> dict:
        giga_dict = self._safe_model_dump(giga_resp)
        model = giga_dict.get("model") or gpt_model
        created_at = giga_dict.get("created_at", int(time.time()))
        thread_id = giga_dict.get("thread_id")
        response_status, incomplete_details = self._build_response_status(
            giga_dict.get("finish_reason"),
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
