"""OpenSearch index template helpers for traffic logs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def build_traffic_log_index_template(
    *,
    index_pattern: str = "gpt2giga-traffic*",
    data_stream: bool = True,
) -> dict[str, Any]:
    """Build an OpenSearch index template for traffic log mirror documents."""
    template: dict[str, Any] = {
        "index_patterns": [index_pattern],
        "template": {
            "settings": {
                "number_of_shards": 1,
                "number_of_replicas": 1,
            },
            "mappings": {
                "dynamic": True,
                "properties": {
                    "@timestamp": {"type": "date"},
                    "created_at": {"type": "date"},
                    "request_id": {"type": "keyword"},
                    "trace_id": {"type": "keyword"},
                    "span_id": {"type": "keyword"},
                    "protocol": {"type": "keyword"},
                    "route": {"type": "keyword"},
                    "method": {"type": "keyword"},
                    "status_code": {"type": "integer"},
                    "model": {"type": "keyword"},
                    "model_requested": {"type": "keyword"},
                    "model_effective": {"type": "keyword"},
                    "provider": {"type": "keyword"},
                    "upstream_status_code": {"type": "integer"},
                    "latency_ms": {"type": "float"},
                    "upstream_latency_ms": {"type": "float"},
                    "input_tokens": {"type": "integer"},
                    "output_tokens": {"type": "integer"},
                    "total_tokens": {"type": "integer"},
                    "error_type": {"type": "keyword"},
                    "api_key_hash": {"type": "keyword"},
                    "client_ip_hash": {"type": "keyword"},
                    "has_error": {"type": "boolean"},
                    "metadata": {"type": "object", "enabled": True},
                },
            },
        },
    }
    if data_stream:
        template["data_stream"] = {}
    return deepcopy(template)


async def install_traffic_log_index_template(
    client: Any,
    *,
    name: str = "gpt2giga-traffic-template",
    index_pattern: str = "gpt2giga-traffic*",
    data_stream: bool = True,
) -> Any:
    """Install the traffic log index template using an OpenSearch client."""
    body = build_traffic_log_index_template(
        index_pattern=index_pattern,
        data_stream=data_stream,
    )
    return await client.indices.put_index_template(name=name, body=body)
