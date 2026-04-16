"""Responses API v2 model-options helpers."""

from typing import Any, Dict, Optional

from gigachat.models import ChatV2ModelOptions, ChatV2Reasoning, ChatV2ResponseFormat

from gpt2giga.core.schema.json_schema import normalize_json_schema, resolve_schema_refs


class ResponsesV2ModelOptionsMixin:
    """Build GigaChat v2 model options for Responses API requests."""

    def _build_response_v2_model_options(
        self,
        data: Dict[str, Any],
    ) -> Optional[ChatV2ModelOptions]:
        options: Dict[str, Any] = {}

        temperature = data.get("temperature")
        if temperature == 0:
            options["top_p"] = 0
        elif isinstance(temperature, (int, float)) and temperature > 0:
            options["temperature"] = float(temperature)

        top_p = data.get("top_p")
        if top_p is not None and temperature != 0:
            options["top_p"] = top_p

        max_output_tokens = data.get("max_output_tokens")
        if max_output_tokens is not None:
            options["max_tokens"] = max_output_tokens

        top_logprobs = data.get("top_logprobs")
        if top_logprobs is not None:
            options["top_logprobs"] = top_logprobs

        reasoning = data.get("reasoning")
        if isinstance(reasoning, dict):
            effort = reasoning.get("effort")
            if effort in {"low", "medium", "high"}:
                options["reasoning"] = ChatV2Reasoning(effort=effort)
        elif getattr(self.config.proxy_settings, "enable_reasoning", False):
            options["reasoning"] = ChatV2Reasoning(effort="high")

        text_config = data.get("text")
        if isinstance(text_config, dict):
            response_format = text_config.get("format")
            if isinstance(response_format, dict):
                format_type = response_format.get("type")
                if format_type == "text":
                    options["response_format"] = ChatV2ResponseFormat(type="text")
                elif format_type == "json_schema":
                    schema_holder = response_format.get("json_schema")
                    if isinstance(schema_holder, dict):
                        schema = schema_holder.get("schema")
                        strict = schema_holder.get(
                            "strict",
                            response_format.get("strict"),
                        )
                    else:
                        schema = response_format.get("schema")
                        strict = response_format.get("strict")
                    if not isinstance(schema, dict):
                        raise self._invalid_request(
                            "`text.format.schema` must be an object for json_schema responses.",
                            param="text",
                        )
                    options["response_format"] = ChatV2ResponseFormat(
                        type="json_schema",
                        schema=normalize_json_schema(resolve_schema_refs(schema)),
                        strict=strict,
                    )

        return ChatV2ModelOptions(**options) if options else None
