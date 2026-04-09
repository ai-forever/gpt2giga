"""Shared helpers for GigaChat request mapping."""

import json
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from gpt2giga.core.schema.json_schema import normalize_json_schema, resolve_schema_refs
from gpt2giga.providers.gigachat.message_utils import (
    limit_attachments,
    map_role,
    merge_consecutive_messages,
)
from gpt2giga.providers.gigachat.tool_mapping import map_tool_name_to_gigachat


class RequestTransformerBaseMixin:
    """Common request transformation helpers."""

    def _map_role(self, role: str, is_first: bool) -> str:
        """Map a role to a valid GigaChat role."""
        return map_role(role, is_first, self.logger)

    def _merge_consecutive_messages(self, messages: List[Dict]) -> List[Dict]:
        """Merge consecutive messages with the same role."""
        return merge_consecutive_messages(messages)

    def _limit_attachments(self, messages: List[Dict]) -> None:
        """Limit the number of attachments in messages."""
        limit_attachments(messages, max_total=10, logger=self.logger)

    def _transform_common_parameters(self, data: Dict) -> Dict:
        """Apply shared parameter normalization for request payloads."""
        transformed = data.copy()

        extra_body = transformed.pop("extra_body", None)
        additional_fields = transformed.get("additional_fields")
        if isinstance(extra_body, dict):
            if isinstance(additional_fields, dict):
                transformed["additional_fields"] = {**extra_body, **additional_fields}
            elif additional_fields is None:
                transformed["additional_fields"] = extra_body
        elif extra_body is not None and additional_fields is None:
            transformed["additional_fields"] = extra_body

        reasoning = transformed.pop("reasoning", None)
        if isinstance(reasoning, dict):
            effort = reasoning.get("effort")
            if effort is not None:
                transformed["reasoning_effort"] = effort

        if getattr(self.config.proxy_settings, "enable_reasoning", False):
            transformed.setdefault("reasoning_effort", "high")

        gpt_model = data.get("model")
        if not self.config.proxy_settings.pass_model and gpt_model:
            del transformed["model"]

        temperature = transformed.pop("temperature", 0)
        if temperature == 0:
            transformed["top_p"] = 0
        elif temperature > 0:
            transformed["temperature"] = temperature

        max_tokens = transformed.pop("max_output_tokens", None)
        if max_tokens:
            transformed["max_tokens"] = max_tokens

        if "functions" not in transformed and "tools" in transformed:
            functions = []
            for tool in transformed["tools"]:
                if tool["type"] == "function":
                    functions.append(tool.get("function", tool))
            transformed["functions"] = functions
            self.logger.debug(f"Transformed {len(functions)} tools to functions")

        function_call = transformed.get("function_call")
        if isinstance(function_call, dict) and function_call.get("name"):
            function_call["name"] = map_tool_name_to_gigachat(function_call["name"])

        functions_list = transformed.get("functions")
        if isinstance(functions_list, list):
            for fn in functions_list:
                if isinstance(fn, dict) and fn.get("name"):
                    fn["name"] = map_tool_name_to_gigachat(fn["name"])
                elif hasattr(fn, "name") and getattr(fn, "name", None):
                    setattr(fn, "name", map_tool_name_to_gigachat(getattr(fn, "name")))

        return transformed

    @staticmethod
    def _apply_json_schema_as_function(
        transformed: Dict, schema_name: str, schema: Dict
    ) -> None:
        """Apply JSON schema as a synthetic function for structured output."""
        resolved_schema = resolve_schema_refs(schema)
        resolved_schema = normalize_json_schema(resolved_schema)

        function_def = {
            "name": schema_name,
            "description": f"Output response in structured format: {schema_name}",
            "parameters": resolved_schema,
        }

        if "functions" not in transformed:
            transformed["functions"] = []

        transformed["functions"].append(function_def)
        transformed["function_call"] = {"name": schema_name}

    @staticmethod
    def _invalid_request(
        message: str,
        *,
        param: Optional[str] = None,
        code: Optional[str] = None,
    ) -> HTTPException:
        return HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": message,
                    "type": "invalid_request_error",
                    "param": param,
                    "code": code,
                }
            },
        )

    @staticmethod
    def _merge_additional_fields(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        extra_body = data.get("extra_body")
        additional_fields = data.get("additional_fields")
        if isinstance(extra_body, dict):
            if isinstance(additional_fields, dict):
                return {**extra_body, **additional_fields}
            return dict(extra_body)
        if isinstance(additional_fields, dict):
            return dict(additional_fields)
        if extra_body is not None:
            return extra_body
        return None

    @staticmethod
    def _decode_json_value(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    @staticmethod
    def _normalize_function_result_value(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                return {"output": value}
            return decoded if isinstance(decoded, dict) else {"output": decoded}
        return {"output": value}

    @staticmethod
    def _build_missing_function_result_payload() -> Dict[str, Any]:
        return {
            "status": "interrupted",
            "error": {
                "type": "missing_tool_result",
                "message": "Tool result missing from client-supplied history.",
            },
        }
