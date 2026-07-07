"""Doctor command for Unified Harness diagnostics."""

from __future__ import annotations

import os
import platform

from gpt2giga.harness import proxy
from gpt2giga.harness.config import HarnessConfig, pass_model_env_note
from gpt2giga.harness.registry import HarnessRegistry, create_default_registry


def run_doctor(
    config: HarnessConfig,
    registry: HarnessRegistry | None = None,
) -> str:
    """Build a human-readable diagnostic report without printing secrets."""
    registry = registry or create_default_registry()
    health = proxy.health_check(config)
    models = proxy.discover_models(config, config.default_api_mode)
    lines = [
        "gpt2giga Unified Harness doctor",
        "",
        "Runtime:",
        f"  Python: {platform.python_version()}",
        "  Package import: OK",
        "",
        "Proxy:",
        f"  URL: {config.proxy_url}",
        f"  Health: {_health_text(health)}",
        f"  API key: {'configured (redacted)' if config.api_key else 'not configured'}",
        "",
        "GigaChat:",
        f"  Credentials: {_credentials_text()}",
        f"  Default model: {config.default_model or 'not configured'}",
        f"  API mode env: {os.getenv('GPT2GIGA_GIGACHAT_API_MODE') or 'not set'}",
        f"  PASS_MODEL: {pass_model_env_note() or 'not set'}",
        "",
        "Routes:",
        "  /v1/chat/completions: mounted by proxy; live POST not attempted",
        "  /v2/chat/completions: mounted by proxy; live POST not attempted",
        (f"  model discovery: {len(models.models)} candidate(s) from {models.source}"),
        "",
        "Harnesses:",
    ]
    for harness in registry.list():
        spec = harness.spec()
        availability = harness.availability()
        suffix = f" - {availability.reason}" if availability.reason else ""
        lines.append(f"  {spec.id}: {availability.status.value}{suffix}")
    if registry.discovery_errors:
        lines.extend(["", "Plugin discovery errors:"])
        lines.extend(f"  {error}" for error in registry.discovery_errors)
    lines.extend(
        [
            "",
            "UI:",
            f"  Default bind: {config.ui_host}:{config.ui_port}",
            "  Remote bind requires --allow-remote",
        ]
    )
    return "\n".join(lines)


def _health_text(health: proxy.ProxyHealth) -> str:
    if health.ok:
        return f"OK via {health.path} ({health.status_code})"
    return f"unreachable ({health.error})"


def _credentials_text() -> str:
    for name in (
        "GIGACHAT_CREDENTIALS",
        "GIGACHAT_ACCESS_TOKEN",
        "GIGACHAT_USER",
    ):
        value = os.getenv(name)
        if value:
            return f"present via {name} (redacted)"
    return "not configured"
