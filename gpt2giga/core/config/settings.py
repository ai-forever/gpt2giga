"""Primary runtime settings models."""

import json
import warnings
from functools import cached_property
from typing import Annotated, Literal, Optional

from gigachat.settings import Settings as GigachatSettings
from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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

ProviderName = Literal["openai", "anthropic", "gemini"]
GigaChatAPIMode = Literal["v1", "v2"]
GovernanceLimitScope = Literal["api_key", "provider"]
_ALL_ENABLED_PROVIDERS: tuple[ProviderName, ...] = ("openai", "anthropic", "gemini")


def _normalize_provider_allowlist(value):
    """Normalize provider allowlists from ENV/CLI friendly forms."""
    if value is None or value == "":
        return None

    def _normalize_parts(parts: list[str]) -> list[str] | None:
        normalized = [part.strip().lower() for part in parts if part.strip()]
        if not normalized or "all" in normalized:
            return None
        return list(dict.fromkeys(normalized))

    if isinstance(value, str):
        return _normalize_parts(value.split(","))

    if isinstance(value, (list, tuple, set)):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.extend(item.split(","))
            else:
                return value
        return _normalize_parts(parts)

    return value


def _normalize_optional_string_list(value):
    """Normalize endpoint/model allowlists from ENV/CLI friendly forms."""
    if value is None or value == "":
        return None

    def _normalize_parts(parts: list[str]) -> list[str] | None:
        normalized = [part.strip() for part in parts if isinstance(part, str)]
        normalized = [part for part in normalized if part]
        if not normalized:
            return None
        return list(dict.fromkeys(normalized))

    if isinstance(value, str):
        return _normalize_parts(value.split(","))

    if isinstance(value, (list, tuple, set)):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.extend(item.split(","))
            else:
                return value
        return _normalize_parts(parts)

    return value


def _normalize_string_map(value):
    """Normalize string maps from ENV/CLI friendly forms."""
    if value is None or value == "":
        return {}

    if isinstance(value, dict):
        return {
            str(key).strip(): str(item).strip()
            for key, item in value.items()
            if str(key).strip() and item is not None and str(item).strip()
        }

    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return {}
        try:
            decoded = json.loads(normalized)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, dict):
            return _normalize_string_map(decoded)
        result: dict[str, str] = {}
        for item in normalized.split(","):
            part = item.strip()
            if not part or "=" not in part:
                continue
            key, raw_value = part.split("=", 1)
            key = key.strip()
            raw_value = raw_value.strip()
            if key and raw_value:
                result[key] = raw_value
        return result

    return value


class ScopedAPIKeySettings(BaseModel):
    """Optional API key with narrowed access scopes."""

    name: Optional[str] = Field(
        default=None,
        description="Человеко-читаемое имя scoped API key для admin/runtime surfaces.",
    )
    key: str = Field(
        min_length=1,
        description="Значение scoped API key.",
        repr=False,
    )
    providers: Annotated[list[ProviderName], NoDecode] | None = Field(
        default=None,
        description=(
            "Опциональный allowlist внешних provider-ов: openai, anthropic, gemini. "
            "Пусто = без ограничения по provider."
        ),
    )
    endpoints: Annotated[list[str], NoDecode] | None = Field(
        default=None,
        description=(
            "Опциональный allowlist normalized endpoint ids без /v1 или /v1beta "
            "(например chat/completions, responses, models/{model}:generateContent)."
        ),
    )
    models: Annotated[list[str], NoDecode] | None = Field(
        default=None,
        description=(
            "Опциональный allowlist model aliases/ids. Пусто = без ограничения по "
            "модели."
        ),
    )

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value):
        """Normalize blank names to ``None``."""
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("providers", mode="before")
    @classmethod
    def normalize_providers(cls, value):
        """Normalize provider allowlists from ENV/CLI friendly forms."""
        return _normalize_provider_allowlist(value)

    @field_validator("endpoints", "models", mode="before")
    @classmethod
    def normalize_optional_string_list(cls, value):
        """Normalize endpoint/model allowlists from ENV/CLI friendly forms."""
        return _normalize_optional_string_list(value)


class GovernanceLimitSettings(BaseModel):
    """Fixed-window governance rule for request rate and token quotas."""

    name: Optional[str] = Field(
        default=None,
        description="Опциональное имя governance rule для admin/runtime surfaces.",
    )
    scope: GovernanceLimitScope = Field(
        description="Группа subject-ов, по которой считать окно: api_key или provider.",
    )
    providers: Annotated[list[ProviderName], NoDecode] | None = Field(
        default=None,
        description=(
            "Опциональный allowlist внешних provider-ов. "
            "Пусто = rule применяется ко всем provider-ам."
        ),
    )
    endpoints: Annotated[list[str], NoDecode] | None = Field(
        default=None,
        description=(
            "Опциональный allowlist normalized endpoint ids без /v1 или /v1beta."
        ),
    )
    models: Annotated[list[str], NoDecode] | None = Field(
        default=None,
        description="Опциональный allowlist model aliases/ids.",
    )
    window_seconds: int = Field(
        default=60,
        ge=1,
        le=86_400,
        description="Размер fixed window в секундах.",
    )
    max_requests: int | None = Field(
        default=None,
        ge=1,
        description="Максимум HTTP requests в одном окне.",
    )
    max_total_tokens: int | None = Field(
        default=None,
        ge=1,
        description="Максимум total_tokens в одном окне.",
    )

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value):
        """Normalize blank names to ``None``."""
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("scope", mode="before")
    @classmethod
    def normalize_scope(cls, value):
        """Normalize governance scope names from ENV/CLI friendly forms."""
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("providers", mode="before")
    @classmethod
    def normalize_providers(cls, value):
        """Normalize provider allowlists from ENV/CLI friendly forms."""
        return _normalize_provider_allowlist(value)

    @field_validator("endpoints", "models", mode="before")
    @classmethod
    def normalize_optional_string_list(cls, value):
        """Normalize endpoint/model allowlists from ENV/CLI friendly forms."""
        return _normalize_optional_string_list(value)

    @model_validator(mode="after")
    def validate_thresholds(self):
        """Require at least one request- or token-based threshold."""
        if self.max_requests is None and self.max_total_tokens is None:
            raise ValueError(
                "governance limit must define max_requests or max_total_tokens"
            )
        return self


class ProxySettings(BaseSettings):
    """Proxy runtime settings."""

    mode: Literal["DEV", "PROD"] = Field(
        default="DEV",
        description="Режим запуска приложения: DEV или PROD",
    )
    host: str = Field(default="localhost", description="Хост для запуска сервера")
    port: int = Field(default=8090, description="Порт для запуска сервера")
    use_https: bool = Field(default=False, description="Использовать ли https")
    https_key_file: Optional[str] = Field(
        default=None,
        description="Путь до key файла для https",
    )
    https_cert_file: Optional[str] = Field(
        default=None,
        description="Путь до cert файла https",
    )
    pass_model: bool = Field(
        default=False,
        description="Передавать модель из запроса в API",
    )
    pass_token: bool = Field(
        default=False,
        description="Передавать токен из запроса в API",
    )
    disable_ui: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "disable_ui", "GPT2GIGA_DISABLE_UI", "DISABLE_UI"
        ),
        description=(
            "Отключить HTML admin UI даже если установлен optional пакет gpt2giga-ui."
        ),
    )
    disable_persist: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "disable_persist",
            "GPT2GIGA_DISABLE_PERSIST",
            "DISABLE_PERSIST",
        ),
        description=(
            "Отключить control-plane persistence. При True runtime-config читается "
            "только из .env/ENV, а admin save/rollback/key-rotation mutations недоступны."
        ),
    )
    enabled_providers: Annotated[list[ProviderName], NoDecode] = Field(
        default_factory=lambda: list(_ALL_ENABLED_PROVIDERS),
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
    runtime_store_backend: str = Field(
        default="memory",
        description=(
            "Backend для stateful runtime-ресурсов: metadata stores, recent "
            "requests и recent errors. Встроенные backend-ы: memory, sqlite. "
            "Кастомные backend-ы можно регистрировать в app.runtime_backends."
        ),
    )
    runtime_store_dsn: Optional[str] = Field(
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
    embeddings: str = Field(
        default="EmbeddingsGigaR",
        description="Модель для эмбеддингов",
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
    enable_images: bool = Field(
        default=True,
        description="Включить загрузку изображений",
    )
    enable_reasoning: bool = Field(
        default=False,
        description=(
            "Включить reasoning по умолчанию: добавляет reasoning_effort='high' "
            "в payload к GigaChat, если клиент не указал reasoning_effort явно"
        ),
    )
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
        description="IP-адреса, которым разрешён доступ к /logs* (пусто = без ограничений)",
    )
    enable_api_key_auth: bool = Field(
        default=False,
        description="Нужно ли закрыть доступ к эндпоинтам (требовать API-ключ)",
    )
    api_key: Optional[str] = Field(
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

    @field_validator("mode", mode="before")
    @classmethod
    def normalize_mode(cls, value):
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("enabled_providers", mode="before")
    @classmethod
    def normalize_enabled_providers(cls, value):
        """Normalize enabled providers from ENV/CLI friendly forms."""
        if value is None or value == "":
            return list(_ALL_ENABLED_PROVIDERS)

        def _normalize_parts(parts: list[str]) -> list[str]:
            normalized = [part.strip().lower() for part in parts if part.strip()]
            if "all" in normalized:
                return list(_ALL_ENABLED_PROVIDERS)
            return list(dict.fromkeys(normalized))

        if isinstance(value, str):
            return _normalize_parts(value.split(","))

        if isinstance(value, (list, tuple, set)):
            parts: list[str] = []
            for item in value:
                if isinstance(item, str):
                    parts.extend(item.split(","))
                else:
                    return value
            return _normalize_parts(parts)

        return value

    @field_validator(
        "gigachat_api_mode",
        "gigachat_responses_api_mode",
        mode="before",
    )
    @classmethod
    def normalize_gigachat_api_mode(cls, value):
        """Normalize backend mode from ENV/CLI friendly forms."""
        if isinstance(value, str):
            normalized = value.strip().lower()
            return normalized or None
        return value

    @field_validator("runtime_store_backend", mode="before")
    @classmethod
    def normalize_runtime_store_backend(cls, value):
        """Normalize runtime store backend names from ENV/CLI friendly forms."""
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("runtime_store_namespace", mode="before")
    @classmethod
    def normalize_runtime_store_namespace(cls, value):
        """Normalize runtime store namespaces from ENV/CLI friendly forms."""
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("runtime_store_dsn", mode="before")
    @classmethod
    def normalize_runtime_store_dsn(cls, value):
        """Normalize runtime store DSN values from ENV/CLI friendly forms."""
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("observability_sinks", mode="before")
    @classmethod
    def normalize_observability_sinks(cls, value):
        """Normalize observability sink selection from ENV/CLI friendly forms."""
        if value is None:
            return ["prometheus"]

        def _normalize_parts(parts: list[str]) -> list[str]:
            normalized = [part.strip().lower() for part in parts if part.strip()]
            if not normalized:
                return []
            if any(part in {"off", "none", "disabled"} for part in normalized):
                return []
            return list(dict.fromkeys(normalized))

        if isinstance(value, str):
            return _normalize_parts(value.split(","))

        if isinstance(value, (list, tuple, set)):
            parts: list[str] = []
            for item in value:
                if isinstance(item, str):
                    parts.extend(item.split(","))
                else:
                    return value
            return _normalize_parts(parts)

        return value

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
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("otlp_headers", mode="before")
    @classmethod
    def normalize_otlp_headers(cls, value):
        """Normalize OTLP header maps from ENV/CLI friendly forms."""
        return _normalize_string_map(value)

    @field_validator("scoped_api_keys", mode="before")
    @classmethod
    def normalize_scoped_api_keys(cls, value):
        """Normalize scoped API keys from ENV/CLI friendly forms."""
        if value is None or value == "":
            return []
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                return []
            try:
                decoded = json.loads(normalized)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "scoped_api_keys must be a JSON array of key descriptors"
                ) from exc
            if decoded is None:
                return []
            return decoded
        return value

    @field_validator("governance_limits", mode="before")
    @classmethod
    def normalize_governance_limits(cls, value):
        """Normalize governance limits from ENV/CLI friendly forms."""
        if value is None or value == "":
            return []
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                return []
            try:
                decoded = json.loads(normalized)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "governance_limits must be a JSON array of rule descriptors"
                ) from exc
            if decoded is None:
                return []
            return decoded
        return value

    @model_validator(mode="after")
    def _validate_prod_security(self):
        """Emit warnings when PROD mode has insecure defaults."""
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
        """Build a consolidated SecuritySettings view for convenient access."""
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
            log_redact_sensitive=self.log_redact_sensitive,
            max_request_body_bytes=self.max_request_body_bytes,
            max_audio_file_size_bytes=self.max_audio_file_size_bytes,
            max_image_file_size_bytes=self.max_image_file_size_bytes,
            max_text_file_size_bytes=self.max_text_file_size_bytes,
            max_audio_image_total_size_bytes=self.max_audio_image_total_size_bytes,
        )

    @property
    def runtime_store(self) -> RuntimeStoreSettings:
        """Build a grouped runtime-store view for internal consumers."""
        return RuntimeStoreSettings.from_proxy_settings(self)

    @property
    def observability(self) -> ObservabilitySettings:
        """Build a grouped observability view for internal consumers."""
        return ObservabilitySettings.from_proxy_settings(self)

    @property
    def chat_backend_mode(self) -> Literal["v1", "v2"]:
        """Resolve the effective backend mode for chat-like capabilities."""
        return self.gigachat_api_mode

    @property
    def responses_backend_mode(self) -> Literal["v1", "v2"]:
        """Resolve the effective backend mode for the Responses capability."""
        return self.gigachat_responses_api_mode or self.gigachat_api_mode

    @property
    def metrics_enabled(self) -> bool:
        """Return whether Prometheus metrics are effectively enabled."""
        return self.observability.metrics_enabled

    model_config = SettingsConfigDict(env_prefix="gpt2giga_", case_sensitive=False)


class GigaChatCLI(GigachatSettings):
    """CLI-exposed GigaChat SDK settings."""

    model_config = SettingsConfigDict(env_prefix="gigachat_", case_sensitive=False)


class ProxyConfig(BaseSettings):
    """Конфигурация прокси-сервера gpt2giga."""

    proxy_settings: ProxySettings = Field(default_factory=ProxySettings, alias="proxy")
    gigachat_settings: GigaChatCLI = Field(
        default_factory=GigaChatCLI,
        alias="gigachat",
    )
    env_path: Optional[str] = Field(None, description="Path to .env file")

    model_config = SettingsConfigDict(
        cli_parse_args=True,
        cli_prog_name="gpt2giga",
        cli_kebab_case=True,
        cli_ignore_unknown_args=True,
    )
