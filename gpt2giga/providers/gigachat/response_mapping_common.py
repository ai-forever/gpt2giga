"""Shared helpers for GigaChat response mapping."""

import json
from typing import Any, Dict, Iterable, Optional


class ResponseProcessorCommonMixin:
    """Common helpers shared across chat and Responses API processors."""

    @property
    def _is_prod_mode(self) -> bool:
        return self._mode == "PROD"

    @staticmethod
    def _safe_model_dump(model: Any) -> Dict[str, Any]:
        if isinstance(model, dict):
            return model
        if hasattr(model, "model_dump"):
            return model.model_dump(exclude_none=True, by_alias=True)
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

        action: Dict[str, Any] = {"type": "search", "query": query}
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

    @staticmethod
    def _build_usage(usage_data: Optional[Dict]) -> Optional[Dict]:
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
