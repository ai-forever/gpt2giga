"""OpenSearch storage artifacts for optional traffic log mirror."""

from gpt2giga.storage.opensearch.template import (
    build_traffic_log_index_template,
    install_traffic_log_index_template,
)

__all__ = [
    "build_traffic_log_index_template",
    "install_traffic_log_index_template",
]
