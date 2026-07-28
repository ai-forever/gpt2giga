"""Configuration helpers for Unified Harness commands and UI."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from gpt2giga_harness.types import GigaChatApiMode, HarnessContext, parse_api_mode

DEFAULT_PROXY_URL = "http://127.0.0.1:8090"
DEFAULT_UI_HOST = "127.0.0.1"
DEFAULT_UI_PORT = 8091
DEFAULT_UI_REMOTE_ABSOLUTE_TTL_SECONDS = 8 * 60 * 60
DEFAULT_UI_REMOTE_IDLE_TTL_SECONDS = 30 * 60
DEFAULT_PROXY_START_TIMEOUT_SECONDS = 15.0
DEFAULT_HARNESS_TIMEOUT_SECONDS = 3600.0
DEFAULT_HARNESS_DATA_DIR = "~/.gpt2giga/harness"
DEFAULT_CHAT_MODEL = "GigaChat-3.5-432B-A28B"
DEFAULT_TITLE_MODEL = "GigaChat-3-Lightning"
DEFAULT_MODEL_HINTS = (
    DEFAULT_CHAT_MODEL,
    DEFAULT_TITLE_MODEL,
    "GigaChat-3-Ultra",
    "GigaChat-2-Pro",
    "GigaChat",
)


@dataclass(frozen=True)
class HarnessConfig:
    """Runtime config for Unified Harness commands."""

    proxy_url: str = DEFAULT_PROXY_URL
    api_key: str | None = None
    harness_model_key: str | None = field(default=None, repr=False)
    default_model: str | None = None
    default_api_mode: GigaChatApiMode = GigaChatApiMode.V2
    ui_host: str = DEFAULT_UI_HOST
    ui_port: int = DEFAULT_UI_PORT
    ui_bootstrap_token: str | None = field(default=None, repr=False)
    ui_allowed_hosts: tuple[str, ...] = ()
    ui_oidc_issuer: str | None = None
    ui_oidc_client_id: str | None = None
    ui_oidc_client_secret: str | None = field(default=None, repr=False)
    ui_oidc_public_origin: str | None = None
    ui_oidc_role_map: tuple[tuple[str, str], ...] = ()
    ui_trusted_proxies: tuple[str, ...] = ()
    ui_remote_absolute_ttl_seconds: int = DEFAULT_UI_REMOTE_ABSOLUTE_TTL_SECONDS
    ui_remote_idle_ttl_seconds: int = DEFAULT_UI_REMOTE_IDLE_TTL_SECONDS
    timeout_seconds: float = DEFAULT_HARNESS_TIMEOUT_SECONDS
    auto_start_proxy: bool = True
    proxy_start_timeout_seconds: float = DEFAULT_PROXY_START_TIMEOUT_SECONDS
    data_dir: str = DEFAULT_HARNESS_DATA_DIR

    @classmethod
    def from_env(cls) -> "HarnessConfig":
        """Load config from environment variables."""
        proxy_url = _env_first("GPT2GIGA_HARNESS_PROXY_URL") or DEFAULT_PROXY_URL
        api_key = _env_first("GPT2GIGA_HARNESS_API_KEY", "GPT2GIGA_API_KEY")
        harness_model_key = _env_first("GPT2GIGA_HARNESS_MODEL_KEY")
        default_model = _env_first("GPT2GIGA_HARNESS_DEFAULT_MODEL", "GIGACHAT_MODEL")
        default_api_mode = parse_api_mode(
            _env_first(
                "GPT2GIGA_HARNESS_DEFAULT_API_MODE",
                "GPT2GIGA_GIGACHAT_API_MODE",
            )
        )
        ui_host = _env_first("GPT2GIGA_HARNESS_UI_HOST") or DEFAULT_UI_HOST
        ui_port = _parse_int(
            _env_first("GPT2GIGA_HARNESS_UI_PORT"),
            DEFAULT_UI_PORT,
        )
        ui_bootstrap_token = _env_first("GPT2GIGA_HARNESS_UI_BOOTSTRAP_TOKEN")
        ui_allowed_hosts = _parse_csv(_env_first("GPT2GIGA_HARNESS_UI_ALLOWED_HOSTS"))
        ui_oidc_issuer = _env_first("GPT2GIGA_HARNESS_UI_OIDC_ISSUER")
        ui_oidc_client_id = _env_first("GPT2GIGA_HARNESS_UI_OIDC_CLIENT_ID")
        ui_oidc_client_secret = _env_first("GPT2GIGA_HARNESS_UI_OIDC_CLIENT_SECRET")
        ui_oidc_public_origin = _env_first("GPT2GIGA_HARNESS_UI_OIDC_PUBLIC_ORIGIN")
        ui_oidc_role_map = _parse_oidc_role_map(
            _env_first("GPT2GIGA_HARNESS_UI_OIDC_ROLE_MAP")
        )
        ui_trusted_proxies = _parse_csv(
            _env_first("GPT2GIGA_HARNESS_UI_TRUSTED_PROXIES")
        )
        ui_remote_absolute_ttl_seconds = _parse_int(
            _env_first("GPT2GIGA_HARNESS_UI_REMOTE_ABSOLUTE_TTL_SECONDS"),
            DEFAULT_UI_REMOTE_ABSOLUTE_TTL_SECONDS,
        )
        ui_remote_idle_ttl_seconds = _parse_int(
            _env_first("GPT2GIGA_HARNESS_UI_REMOTE_IDLE_TTL_SECONDS"),
            DEFAULT_UI_REMOTE_IDLE_TTL_SECONDS,
        )
        timeout = _parse_float(
            _env_first("GPT2GIGA_HARNESS_TIMEOUT_SECONDS"),
            DEFAULT_HARNESS_TIMEOUT_SECONDS,
        )
        auto_start_proxy = _parse_bool(
            _env_first("GPT2GIGA_HARNESS_AUTO_START_PROXY"),
            True,
        )
        proxy_start_timeout = _parse_float(
            _env_first("GPT2GIGA_HARNESS_PROXY_START_TIMEOUT_SECONDS"),
            DEFAULT_PROXY_START_TIMEOUT_SECONDS,
        )
        data_dir = _env_first("GPT2GIGA_HARNESS_DATA_DIR") or DEFAULT_HARNESS_DATA_DIR
        return cls(
            proxy_url=_normalize_proxy_url(proxy_url),
            api_key=api_key,
            harness_model_key=harness_model_key,
            default_model=default_model,
            default_api_mode=default_api_mode,
            ui_host=ui_host,
            ui_port=ui_port,
            ui_bootstrap_token=ui_bootstrap_token,
            ui_allowed_hosts=ui_allowed_hosts,
            ui_oidc_issuer=ui_oidc_issuer,
            ui_oidc_client_id=ui_oidc_client_id,
            ui_oidc_client_secret=ui_oidc_client_secret,
            ui_oidc_public_origin=ui_oidc_public_origin,
            ui_oidc_role_map=ui_oidc_role_map,
            ui_trusted_proxies=ui_trusted_proxies,
            ui_remote_absolute_ttl_seconds=ui_remote_absolute_ttl_seconds,
            ui_remote_idle_ttl_seconds=ui_remote_idle_ttl_seconds,
            timeout_seconds=timeout,
            auto_start_proxy=auto_start_proxy,
            proxy_start_timeout_seconds=proxy_start_timeout,
            data_dir=data_dir,
        )

    def with_overrides(
        self,
        *,
        proxy_url: str | None = None,
        ui_host: str | None = None,
        ui_port: int | None = None,
        auto_start_proxy: bool | None = None,
    ) -> "HarnessConfig":
        """Return a copy with CLI-provided overrides."""
        return HarnessConfig(
            proxy_url=_normalize_proxy_url(proxy_url or self.proxy_url),
            api_key=self.api_key,
            harness_model_key=self.harness_model_key,
            default_model=self.default_model,
            default_api_mode=self.default_api_mode,
            ui_host=ui_host or self.ui_host,
            ui_port=ui_port if ui_port is not None else self.ui_port,
            ui_bootstrap_token=self.ui_bootstrap_token,
            ui_allowed_hosts=self.ui_allowed_hosts,
            ui_oidc_issuer=self.ui_oidc_issuer,
            ui_oidc_client_id=self.ui_oidc_client_id,
            ui_oidc_client_secret=self.ui_oidc_client_secret,
            ui_oidc_public_origin=self.ui_oidc_public_origin,
            ui_oidc_role_map=self.ui_oidc_role_map,
            ui_trusted_proxies=self.ui_trusted_proxies,
            ui_remote_absolute_ttl_seconds=self.ui_remote_absolute_ttl_seconds,
            ui_remote_idle_ttl_seconds=self.ui_remote_idle_ttl_seconds,
            timeout_seconds=self.timeout_seconds,
            auto_start_proxy=(
                auto_start_proxy
                if auto_start_proxy is not None
                else self.auto_start_proxy
            ),
            proxy_start_timeout_seconds=self.proxy_start_timeout_seconds,
            data_dir=self.data_dir,
        )

    def to_context(self) -> HarnessContext:
        """Build a safe harness execution context."""
        return HarnessContext(
            proxy_url=self.proxy_url,
            api_key=self.api_key,
            harness_model_key=self.harness_model_key,
            default_model=self.default_model,
            timeout_seconds=self.timeout_seconds,
            auto_start_proxy=self.auto_start_proxy,
            proxy_start_timeout_seconds=self.proxy_start_timeout_seconds,
            data_dir=self.data_dir,
        )


def pass_model_env_note() -> str | None:
    """Return a note when PASS_MODEL indicates model override behavior."""
    value = _env_first("GPT2GIGA_PASS_MODEL")
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"false", "0", "no", "off"}:
        return (
            "GPT2GIGA_PASS_MODEL=False; requested model may be overridden "
            "by upstream GIGACHAT_MODEL."
        )
    return f"GPT2GIGA_PASS_MODEL={value}"


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return None


def _normalize_proxy_url(value: str) -> str:
    return value.strip().rstrip("/")


def _parse_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _parse_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_csv(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(item.strip().lower() for item in value.split(",") if item.strip())


def _parse_oidc_role_map(value: str | None) -> tuple[tuple[str, str], ...]:
    """Parse a default-deny JSON object mapping exact subjects to roles."""
    if value is None:
        return ()
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "GPT2GIGA_HARNESS_UI_OIDC_ROLE_MAP must be a JSON object"
        ) from exc
    if not isinstance(payload, dict) or not payload:
        raise ValueError(
            "GPT2GIGA_HARNESS_UI_OIDC_ROLE_MAP must be a non-empty JSON object"
        )
    normalized: list[tuple[str, str]] = []
    for subject, role in payload.items():
        if (
            not isinstance(subject, str)
            or not subject
            or len(subject) > 512
            or role not in {"viewer", "operator"}
        ):
            raise ValueError(
                "OIDC role map entries require an exact subject and viewer/operator role"
            )
        normalized.append((subject, role))
    return tuple(sorted(normalized))
