"""Domain mixins used to assemble ``ProxySettings``."""

import ipaddress
import warnings
from functools import cached_property
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import NoDecode

from gpt2giga.core.config._settings.access_control import (
    GovernanceLimitSettings,
    ScopedAPIKeySettings,
)
from gpt2giga.core.config._settings.common import (
    ALL_ENABLED_PROVIDERS,
    GigaChatAPIMode,
    ProviderName,
    normalize_api_mode,
    normalize_enabled_providers,
    normalize_json_array_setting,
    normalize_lowercase_string,
    normalize_observability_sinks,
    normalize_optional_string,
    normalize_optional_string_list,
    normalize_required_string,
    normalize_string_map,
    normalize_uppercase_string,
)
from gpt2giga.core.config.observability import ObservabilitySettings
from gpt2giga.core.config.runtime_store import RuntimeStoreSettings
from gpt2giga.core.config.security import SecuritySettings
from gpt2giga.core.constants import (
    DEFAULT_MAX_AUDIO_FILE_SIZE_BYTES,
    DEFAULT_MAX_AUDIO_IMAGE_TOTAL_SIZE_BYTES,
    DEFAULT_MAX_IMAGE_FILE_SIZE_BYTES,
    DEFAULT_MAX_REQUEST_BODY_BYTES,
    DEFAULT_MAX_TEXT_FILE_SIZE_BYTES,
)


class ServerProxySettingsMixin:
    """Server and transport-facing proxy settings."""

    mode: Literal["DEV", "PROD"] = Field(
        default="DEV",
        description="Режим запуска приложения: DEV или PROD",
    )
    host: str = Field(default="localhost", description="Хост для запуска сервера")
    port: int = Field(default=8090, description="Порт для запуска сервера")
    use_https: bool = Field(default=False, description="Использовать ли https")
    https_key_file: str | None = Field(
        default=None,
        description="Путь до key файла для https",
    )
    https_cert_file: str | None = Field(
        default=None,
        description="Путь до cert файла https",
    )
    disable_ui: bool = Field(
        default=False,
        description=(
            "Отключить HTML admin UI даже если установлен optional пакет gpt2giga-ui."
        ),
    )
    disable_persist: bool = Field(
        default=False,
        description=(
            "Отключить control-plane persistence. При True runtime-config читается "
            "только из .env/ENV, а admin save/rollback/key-rotation mutations недоступны."
        ),
    )
    cors_allow_origins: list[str] = Field(
        default_factory=lambda: ["*"],
        description="Разрешенные CORS origins",
    )
    cors_allow_methods: list[str] = Field(
        default_factory=lambda: ["*"],
        description="Разрешенные CORS методы",
    )
    cors_allow_headers: list[str] = Field(
        default_factory=lambda: ["*"],
        description="Разрешенные CORS заголовки",
    )

    @field_validator("mode", mode="before")
    @classmethod
    def normalize_mode(cls, value):
        """Normalize proxy mode names from ENV/CLI friendly forms."""
        return normalize_uppercase_string(value)


class ProviderProxySettingsMixin:
    """Provider selection and backend-routing settings."""

    pass_model: bool = Field(
        default=False,
        description="Передавать модель из запроса в API",
    )
    pass_token: bool = Field(
        default=False,
        description="Передавать токен из запроса в API",
    )
    enabled_providers: Annotated[list[ProviderName], NoDecode] = Field(
        default_factory=lambda: list(ALL_ENABLED_PROVIDERS),
        description=(
            "Список внешних провайдеров, роуты которых нужно включить. "
            "Поддерживаются: openai, anthropic, gemini. "
            "Значение 'all' в ENV/CLI включает все провайдеры."
        ),
    )
    gigachat_api_mode: GigaChatAPIMode = Field(
        default="v1",
        description=(
            "Базовый режим backend API GigaChat для chat-like endpoints. "
            "'v1' направляет OpenAI chat/completions, Anthropic messages, "
            "Gemini generateContent и batch chat requests через legacy API "
            "(achat/astream). "
            "'v2' направляет эти capability через native v2 API "
            "(achat_v2/astream_v2). Responses API может быть переопределен "
            "отдельно через `gigachat_responses_api_mode`."
        ),
    )
    gigachat_responses_api_mode: GigaChatAPIMode | None = Field(
        default=None,
        description=(
            "Опциональное переопределение backend API GigaChat только для "
            "OpenAI Responses API. Пусто = использовать `gigachat_api_mode`. "
            "'v1' направляет /responses через legacy API (achat/astream), "
            "'v2' через native v2 API (achat_v2/astream_v2)."
        ),
    )
    embeddings: str = Field(
        default="EmbeddingsGigaR",
        description="Модель для эмбеддингов",
    )
    enable_reasoning: bool = Field(
        default=False,
        description=(
            "Включить reasoning по умолчанию: добавляет reasoning_effort='high' "
            "в payload к GigaChat, если клиент не указал reasoning_effort явно"
        ),
    )

    @field_validator("enabled_providers", mode="before")
    @classmethod
    def normalize_enabled_providers(cls, value: Any) -> Any:
        """Normalize enabled providers from ENV/CLI friendly forms."""
        return normalize_enabled_providers(value)

    @field_validator(
        "gigachat_api_mode",
        "gigachat_responses_api_mode",
        mode="before",
    )
    @classmethod
    def normalize_gigachat_api_mode(cls, value: Any) -> Any:
        """Normalize backend mode names from ENV/CLI friendly forms."""
        return normalize_api_mode(value)

    @property
    def chat_backend_mode(self) -> Literal["v1", "v2"]:
        """Resolve the effective backend mode for chat-like capabilities."""
        return self.gigachat_api_mode

    @property
    def responses_backend_mode(self) -> Literal["v1", "v2"]:
        """Resolve the effective backend mode for the Responses capability."""
        return self.gigachat_responses_api_mode or self.gigachat_api_mode


class RuntimeStoreProxySettingsMixin:
    """Runtime-store configuration for stateful runtime resources."""

    runtime_store_backend: str = Field(
        default="memory",
        description=(
            "Backend для stateful runtime-ресурсов: metadata stores, recent "
            "requests и recent errors. Встроенные backend-ы: memory, sqlite. "
            "Кастомные backend-ы можно регистрировать в app.runtime_backends."
        ),
    )
    runtime_store_dsn: str | None = Field(
        default=None,
        description=(
            "Опциональный DSN/URL для внешнего runtime store backend "
            "(например sqlite:///tmp/gpt2giga-runtime.db, Redis/Postgres) "
            "при использовании built-in sqlite или кастомной реализации."
        ),
    )
    runtime_store_namespace: str = Field(
        default="gpt2giga",
        description=(
            "Логический namespace для stateful runtime backend-а. "
            "Полезен для Redis/Postgres и кастомных backend-ов."
        ),
    )

    @field_validator("runtime_store_backend", mode="before")
    @classmethod
    def normalize_runtime_store_backend(cls, value: Any) -> Any:
        """Normalize runtime store backend names from ENV/CLI friendly forms."""
        return normalize_lowercase_string(value)

    @field_validator("runtime_store_namespace", mode="before")
    @classmethod
    def normalize_runtime_store_namespace(cls, value: Any) -> Any:
        """Normalize runtime store namespaces from ENV/CLI friendly forms."""
        return normalize_required_string(value)

    @field_validator("runtime_store_dsn", mode="before")
    @classmethod
    def normalize_runtime_store_dsn(cls, value: Any) -> Any:
        """Normalize runtime store DSN values from ENV/CLI friendly forms."""
        return normalize_optional_string(value)

    @property
    def runtime_store(self) -> RuntimeStoreSettings:
        """Build a grouped runtime-store view for internal consumers."""
        return RuntimeStoreSettings.from_proxy_settings(self)


class ObservabilityProxySettingsMixin:
    """Telemetry and sink settings that back the observability grouped view."""

    enable_telemetry: bool = Field(
        default=True,
        description=(
            "Включить telemetry sink layer поверх request audit events. "
            "False отключает fan-out в Prometheus/OTLP/Langfuse/Phoenix и оставляет "
            "только recent request/error feeds для admin."
        ),
    )
    observability_sinks: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["prometheus"],
        description=(
            "Список observability sink-ов для нормализованных request events. "
            "Встроенные sink-и: prometheus, otlp, langfuse, phoenix. Кастомные sink-и "
            "можно регистрировать через app.telemetry registry."
        ),
    )
    otlp_traces_endpoint: str | None = Field(
        default=None,
        description=(
            "Полный OTLP/HTTP endpoint для trace export-а, например "
            "http://otel-collector:4318/v1/traces."
        ),
    )
    otlp_headers: Annotated[dict[str, str], NoDecode] = Field(
        default_factory=dict,
        description=(
            "Дополнительные HTTP headers для OTLP export-а. Поддерживает JSON "
            "object или CSV вида `Header=Value,Another=Value`."
        ),
    )
    otlp_timeout_seconds: float = Field(
        default=5.0,
        ge=0.1,
        le=60.0,
        description="Таймаут одного OTLP export HTTP request в секундах.",
    )
    otlp_max_pending_requests: int = Field(
        default=256,
        ge=1,
        le=10_000,
        description="Максимум in-flight OTLP export requests перед drop-ом новых событий.",
    )
    otlp_service_name: str = Field(
        default="gpt2giga",
        description="service.name resource attribute для OTLP/Langfuse/Phoenix exporters.",
    )
    langfuse_base_url: str | None = Field(
        default=None,
        description=(
            "Base URL Langfuse instance-а без суффикса endpoint-а, например "
            "http://langfuse-web:3000."
        ),
    )
    langfuse_public_key: str | None = Field(
        default=None,
        description="Langfuse public key для OTLP ingest auth.",
    )
    langfuse_secret_key: str | None = Field(
        default=None,
        description="Langfuse secret key для OTLP ingest auth.",
        repr=False,
    )
    phoenix_base_url: str | None = Field(
        default=None,
        description=(
            "Base URL Phoenix instance-а без суффикса /v1/traces, например "
            "http://phoenix:6006."
        ),
    )
    phoenix_api_key: str | None = Field(
        default=None,
        description="Phoenix API key для Authorization: Bearer ingest auth.",
        repr=False,
    )
    phoenix_project_name: str | None = Field(
        default=None,
        description=(
            "Опциональный Phoenix/OpenInference project name "
            "(`openinference.project.name`)."
        ),
    )
    recent_requests_max_items: int = Field(
        default=200,
        description="Максимальное число recent request events в admin ring buffer.",
    )
    recent_errors_max_items: int = Field(
        default=100,
        description="Максимальное число recent error events в admin ring buffer.",
    )

    @field_validator("observability_sinks", mode="before")
    @classmethod
    def normalize_observability_sinks(cls, value: Any) -> Any:
        """Normalize observability sink selection from ENV/CLI friendly forms."""
        return normalize_observability_sinks(value)

    @field_validator(
        "otlp_traces_endpoint",
        "langfuse_base_url",
        "langfuse_public_key",
        "langfuse_secret_key",
        "phoenix_base_url",
        "phoenix_api_key",
        "phoenix_project_name",
        mode="before",
    )
    @classmethod
    def normalize_optional_strings(cls, value):
        """Normalize blank string settings to ``None``."""
        return normalize_optional_string(value)

    @field_validator("otlp_headers", mode="before")
    @classmethod
    def normalize_otlp_headers(cls, value):
        """Normalize OTLP header maps from ENV/CLI friendly forms."""
        return normalize_string_map(value)

    @property
    def observability(self) -> ObservabilitySettings:
        """Build a grouped observability view for internal consumers."""
        return ObservabilitySettings.from_proxy_settings(self)

    @property
    def metrics_enabled(self) -> bool:
        """Return whether Prometheus metrics are effectively enabled."""
        return self.observability.metrics_enabled


class SecurityProxySettingsMixin:
    """Security, logging, and request-limit settings."""

    max_request_body_bytes: int = Field(
        default=DEFAULT_MAX_REQUEST_BODY_BYTES,
        description="Глобальный лимит размера HTTP-тела запроса в байтах (до парсинга JSON)",
    )
    max_audio_file_size_bytes: int = Field(
        default=DEFAULT_MAX_AUDIO_FILE_SIZE_BYTES,
        description="Максимальный размер одного аудиофайла в байтах",
    )
    max_image_file_size_bytes: int = Field(
        default=DEFAULT_MAX_IMAGE_FILE_SIZE_BYTES,
        description="Максимальный размер одного изображения в байтах",
    )
    max_text_file_size_bytes: int = Field(
        default=DEFAULT_MAX_TEXT_FILE_SIZE_BYTES,
        description="Максимальный размер одного текстового файла в байтах",
    )
    max_audio_image_total_size_bytes: int = Field(
        default=DEFAULT_MAX_AUDIO_IMAGE_TOTAL_SIZE_BYTES,
        description="Максимальный суммарный размер аудио и изображений в одном запросе, в байтах",
    )
    log_level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = Field(
        default="INFO",
        description="log verbosity level",
    )
    log_filename: str = Field(default="gpt2giga.log", description="Имя лог файла")
    log_max_size: int = Field(
        default=10 * 1024 * 1024,
        description="максимальный размер файла в байтах",
    )
    log_redact_sensitive: bool = Field(
        default=True,
        description="Маскировать чувствительные поля (api_key, token, password и др.) в логах",
    )
    logs_ip_allowlist: list[str] = Field(
        default_factory=list,
        description="IP-адреса, которым разрешён доступ к admin surface в DEV (пусто = без ограничений)",
    )
    trusted_proxy_cidrs: list[str] = Field(
        default_factory=list,
        description=(
            "Список доверенных reverse-proxy IP/CIDR, от которых разрешено "
            "учитывать X-Forwarded-For. Пусто = forwarded headers игнорируются."
        ),
    )
    enable_api_key_auth: bool = Field(
        default=False,
        description="Нужно ли закрыть доступ к эндпоинтам (требовать API-ключ)",
    )
    api_key: str | None = Field(
        default=None,
        description="API ключ для защиты эндпоинтов (если enable_api_key_auth=True)",
        repr=False,
    )
    scoped_api_keys: list[ScopedAPIKeySettings] = Field(
        default_factory=list,
        description=(
            "Опциональные scoped API keys в JSON-массиве. Global GPT2GIGA_API_KEY "
            "сохраняет полный доступ, а scoped keys можно ограничить по provider, "
            "endpoint и model."
        ),
    )
    governance_limits: list[GovernanceLimitSettings] = Field(
        default_factory=list,
        description=(
            "Опциональные governance rules в JSON-массиве. Поддерживают fixed-window "
            "rate limits и token quotas по api_key/provider с optional filters по "
            "provider, endpoint и model."
        ),
    )

    @field_validator("scoped_api_keys", mode="before")
    @classmethod
    def normalize_scoped_api_keys(cls, value):
        """Normalize scoped API keys from ENV/CLI friendly forms."""
        return normalize_json_array_setting(
            value,
            error_message="scoped_api_keys must be a JSON array of key descriptors",
        )

    @field_validator("governance_limits", mode="before")
    @classmethod
    def normalize_governance_limits(cls, value):
        """Normalize governance limits from ENV/CLI friendly forms."""
        return normalize_json_array_setting(
            value,
            error_message="governance_limits must be a JSON array of rule descriptors",
        )

    @field_validator("trusted_proxy_cidrs", mode="before")
    @classmethod
    def normalize_trusted_proxy_cidrs(cls, value):
        """Normalize trusted proxy CIDRs from ENV/CLI friendly forms."""
        return normalize_optional_string_list(value) or []

    @field_validator("trusted_proxy_cidrs")
    @classmethod
    def validate_trusted_proxy_cidrs(cls, value: list[str]) -> list[str]:
        """Validate trusted proxy CIDR entries eagerly."""
        normalized: list[str] = []
        for entry in value:
            ipaddress.ip_network(entry, strict=False)
            normalized.append(entry)
        return normalized

    @model_validator(mode="after")
    def validate_prod_security(self):
        """Emit warnings when PROD mode keeps insecure defaults."""
        if self.mode != "PROD":
            return self
        if "*" in self.cors_allow_origins:
            warnings.warn(
                "PROD mode with wildcard CORS origins ('*') is insecure. "
                "Set GPT2GIGA_CORS_ALLOW_ORIGINS to a list of trusted origins.",
                UserWarning,
                stacklevel=2,
            )
        if not self.enable_api_key_auth and not self.api_key:
            warnings.warn(
                "PROD mode without API-key auth is insecure. "
                "Set GPT2GIGA_ENABLE_API_KEY_AUTH=True and GPT2GIGA_API_KEY.",
                UserWarning,
                stacklevel=2,
            )
        if not self.log_redact_sensitive:
            warnings.warn(
                "PROD mode with log_redact_sensitive=False may leak secrets to logs.",
                UserWarning,
                stacklevel=2,
            )
        return self

    @cached_property
    def security(self):
        """Build a consolidated security view for convenient internal access."""
        return SecuritySettings(
            mode=self.mode,
            enable_api_key_auth=self.enable_api_key_auth,
            api_key=self.api_key,
            scoped_api_keys_configured=len(self.scoped_api_keys),
            governance_limits_configured=len(self.governance_limits),
            cors_allow_origins=self.cors_allow_origins,
            cors_allow_methods=self.cors_allow_methods,
            cors_allow_headers=self.cors_allow_headers,
            logs_ip_allowlist=self.logs_ip_allowlist,
            trusted_proxy_cidrs=self.trusted_proxy_cidrs,
            log_redact_sensitive=self.log_redact_sensitive,
            max_request_body_bytes=self.max_request_body_bytes,
            max_audio_file_size_bytes=self.max_audio_file_size_bytes,
            max_image_file_size_bytes=self.max_image_file_size_bytes,
            max_text_file_size_bytes=self.max_text_file_size_bytes,
            max_audio_image_total_size_bytes=self.max_audio_image_total_size_bytes,
        )
