import json
import os
import warnings
from functools import cached_property
from typing import Annotated, Literal, Optional

from gigachat.settings import Settings as GigachatSettings
from pydantic import (
    Field,
    NonNegativeFloat,
    PositiveInt,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from gpt2giga.constants import (
    DEFAULT_MAX_AUDIO_FILE_SIZE_BYTES,
    DEFAULT_MAX_AUDIO_IMAGE_TOTAL_SIZE_BYTES,
    DEFAULT_MAX_IMAGE_FILE_SIZE_BYTES,
    DEFAULT_MAX_TEXT_FILE_SIZE_BYTES,
    DEFAULT_MAX_TOKENS,
)
from gpt2giga.models.security import DEFAULT_MAX_REQUEST_BODY_BYTES

TrafficLogSinkName = Literal["noop", "jsonl", "postgres", "opensearch"]
ObservabilityBackendName = Literal["noop", "phoenix"]


class ProxySettings(BaseSettings):
    mode: Literal["DEV", "PROD"] = Field(
        default="DEV", description="Режим запуска приложения: DEV или PROD"
    )
    host: str = Field(default="localhost", description="Хост для запуска сервера")
    port: int = Field(default=8090, description="Порт для запуска сервера")
    use_https: bool = Field(default=False, description="Использовать ли https")
    https_key_file: Optional[str] = Field(
        default=None, description="Путь до key файла для https"
    )
    https_cert_file: Optional[str] = Field(
        default=None, description="Путь до cert файла https"
    )
    pass_model: bool = Field(
        default=True, description="Передавать модель из запроса в API"
    )
    pass_token: bool = Field(
        default=False, description="Передавать токен из запроса в API"
    )
    embeddings: str = Field(
        default="EmbeddingsGigaR", description="Модель для эмбеддингов"
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
        default=True, description="Включить загрузку изображений"
    )
    enable_reasoning: bool = Field(
        default=False,
        description=(
            "Включить reasoning по умолчанию: добавляет reasoning_effort='high' "
            "в payload к GigaChat, если клиент не указал reasoning_effort явно"
        ),
    )
    disable_reasoning: bool = Field(
        default=False,
        description=(
            "Отключить передачу reasoning в GigaChat: удаляет reasoning и "
            "reasoning_effort из upstream payload и подавляет enable_reasoning"
        ),
    )
    default_max_tokens: Optional[PositiveInt] = Field(
        default=DEFAULT_MAX_TOKENS,
        description=(
            "Опциональное значение max_tokens по умолчанию, отправляемое в GigaChat API, "
            "если клиент не указал max_tokens, max_completion_tokens или max_output_tokens; "
            "None означает не добавлять max_tokens"
        ),
    )
    model_max_connections: dict[str, PositiveInt] = Field(
        default_factory=dict,
        description="Maximum number of concurrent upstream GigaChat calls per model.",
    )
    model_max_connections_default: Optional[PositiveInt] = Field(
        default=None,
        description="Default per-model concurrency limit for models not listed in model_max_connections.",
    )
    model_max_connections_acquire_timeout: Optional[NonNegativeFloat] = Field(
        default=None,
        description="Seconds to wait for a free per-model slot; None means wait indefinitely.",
    )
    structured_output_mode: Literal["function_call", "native"] = Field(
        default="function_call",
        description=(
            "Режим structured output: function_call использует совместимый "
            "function-calling fallback, native передает response_format в GigaChat"
        ),
    )
    gigachat_api_mode: Literal["v1", "v2"] = Field(
        default="v1",
        description=(
            "Backend contract for GigaChat chat-like requests: v1 uses "
            "legacy chat methods, v2 uses chat completion resource methods"
        ),
    )
    experimental_normalized_layer: bool = Field(
        default=False,
        description="Enable experimental normalized protocol layer wiring.",
    )
    normalization_mode: Literal["off", "shadow", "on"] = Field(
        default="off",
        description=(
            "Normalized layer execution mode: off disables it, shadow records "
            "parallel translation only, on uses normalized execution."
        ),
    )
    legacy_chat_fallback: bool = Field(
        default=True,
        description="Allow legacy chat path fallback while modular migration is experimental.",
    )
    conversation_stitching_enabled: bool = Field(
        default=False,
        description=(
            "Enable opt-in local conversation stitching for stateless chat-like "
            "requests carrying a stable conversation identifier."
        ),
    )
    conversation_ttl_seconds: PositiveInt = Field(
        default=3_600,
        description="Seconds to retain idle in-memory stitched conversation state.",
    )
    conversation_max_messages: PositiveInt = Field(
        default=40,
        description="Maximum messages retained and sent for one stitched conversation.",
    )
    conversation_use_session_id: bool = Field(
        default=False,
        description=(
            "Allow x-session-id to act as a conversation key when no explicit "
            "conversation identifier is present."
        ),
    )
    conversation_on_divergence: Literal["client_wins", "fork"] = Field(
        default="client_wins",
        description=(
            "Conflict policy when incoming history does not overlap stored history: "
            "client_wins replaces state after success, fork stores under an internal "
            "revision-suffixed conversation id."
        ),
    )
    traffic_log_enabled: bool = Field(
        default=False,
        description="Enable future traffic log event emission.",
    )
    traffic_log_sink: TrafficLogSinkName = Field(
        default="noop",
        description=(
            "Traffic log sink backend: noop disables storage, jsonl writes local JSONL, "
            "postgres writes to optional Postgres storage, opensearch writes to optional search mirror."
        ),
    )
    traffic_log_sinks: Annotated[list[TrafficLogSinkName], NoDecode] = Field(
        default_factory=list,
        description=(
            "Optional ordered traffic log sink list for mirror setups, e.g. "
            "['postgres', 'opensearch']. Empty list preserves traffic_log_sink."
        ),
    )
    traffic_log_jsonl_path: str = Field(
        default="traffic_logs.jsonl",
        description="Path to local JSONL traffic log file when traffic_log_sink=jsonl.",
    )
    traffic_log_postgres_dsn: Optional[str] = Field(
        default=None,
        description="Postgres DSN for traffic log storage when traffic_log_sink=postgres.",
        repr=False,
    )
    traffic_log_capture_content: bool = Field(
        default=False,
        description="Capture redacted request/response bodies in traffic logs.",
    )
    traffic_log_queue_size: PositiveInt = Field(
        default=10_000,
        description="Maximum queued traffic log events before applying backpressure policy.",
    )
    traffic_log_batch_size: PositiveInt = Field(
        default=500,
        description="Maximum traffic log events written per storage batch.",
    )
    traffic_log_flush_interval_ms: PositiveInt = Field(
        default=2_000,
        description="Best-effort traffic log flush interval in milliseconds.",
    )
    traffic_log_drop_on_backpressure: bool = Field(
        default=True,
        description="Drop traffic log events instead of blocking when the queue is full.",
    )
    traffic_log_redact_sensitive: bool = Field(
        default=True,
        description="Redact sensitive keys and token-like strings before traffic log storage.",
    )
    traffic_log_redact_extra_keys: list[str] = Field(
        default_factory=list,
        description="Additional case-insensitive keys to redact before traffic log storage.",
    )
    traffic_log_retention_days: PositiveInt = Field(
        default=30,
        description="Number of days to retain Postgres traffic logs before purge.",
    )
    traffic_log_purge_interval_seconds: PositiveInt = Field(
        default=3_600,
        description="Seconds between best-effort traffic log retention purge runs.",
    )
    opensearch_url: str = Field(
        default="http://localhost:9200",
        description="OpenSearch URL for the optional traffic log search mirror.",
    )
    opensearch_username: Optional[str] = Field(
        default=None,
        description="OpenSearch username for the optional traffic log search mirror.",
        repr=False,
    )
    opensearch_password: Optional[str] = Field(
        default=None,
        description="OpenSearch password for the optional traffic log search mirror.",
        repr=False,
    )
    opensearch_index: str = Field(
        default="gpt2giga-traffic",
        description="OpenSearch index or data stream name for traffic log mirror events.",
    )
    opensearch_data_stream: bool = Field(
        default=True,
        description="Use OpenSearch data stream bulk create operations for traffic logs.",
    )
    opensearch_bulk_size: PositiveInt = Field(
        default=500,
        description="Maximum number of traffic log events per OpenSearch bulk request.",
    )
    opensearch_flush_interval_ms: PositiveInt = Field(
        default=2_000,
        description="Best-effort OpenSearch traffic log flush interval in milliseconds.",
    )
    observability_enabled: bool = Field(
        default=False,
        description="Enable OpenTelemetry/OpenInference observability hooks.",
    )
    observability_backend: ObservabilityBackendName = Field(
        default="phoenix",
        description="Observability backend: phoenix enables the optional Phoenix/OTel sink.",
    )
    phoenix_collector_endpoint: str = Field(
        default_factory=lambda: os.getenv(
            "PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:4317"
        ),
        description="Phoenix OTLP collector endpoint.",
    )
    phoenix_project_name: str = Field(
        default_factory=lambda: os.getenv("PHOENIX_PROJECT_NAME", "gpt2giga"),
        description="Phoenix project name for exported traces.",
    )
    phoenix_api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("PHOENIX_API_KEY") or None,
        description="Phoenix API key for hosted or protected collectors.",
        repr=False,
    )
    observability_sample_rate: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Fraction of requests to trace when observability is enabled.",
    )
    observability_capture_content: bool = Field(
        default=False,
        description="Capture prompt/response content in observability spans.",
    )
    observability_capture_messages: bool = Field(
        default=False,
        description="Capture normalized input messages in observability spans.",
    )
    observability_capture_tool_args: bool = Field(
        default=False,
        description="Capture tool schemas and tool call arguments in observability spans.",
    )
    observability_capture_responses: bool = Field(
        default=False,
        description="Capture normalized model response content in observability spans.",
    )
    observability_max_content_length: PositiveInt = Field(
        default=8_000,
        description="Maximum serialized content length for one observability attribute.",
    )
    observability_redaction_enabled: bool = Field(
        default=True,
        description="Redact sensitive content before adding observability attributes.",
    )
    metrics_enabled: bool = Field(
        default=False,
        description="Enable Prometheus-compatible runtime metrics endpoint.",
    )
    metrics_path: str = Field(
        default="/metrics",
        description="HTTP path for the Prometheus-compatible metrics endpoint.",
    )
    ui_enabled: bool = Field(
        default=False,
        description="Enable future built-in debugging and playground UI.",
    )
    ui_require_auth: bool = Field(
        default=True,
        description="Require the admin API key for built-in UI pages.",
    )
    debug_translate_enabled: bool = Field(
        default=False,
        description="Enable future debug translation endpoints.",
    )
    admin_api_enabled: bool = Field(
        default=False,
        description="Enable protected admin API endpoints.",
    )
    admin_api_key: Optional[str] = Field(
        default=None,
        description="Admin API key for protected debug/admin endpoints.",
        repr=False,
    )
    replay_enabled: bool = Field(
        default=False,
        description="Enable protected admin traffic-log request replay endpoint.",
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
        default="INFO", description="log verbosity level"
    )
    log_filename: str = Field(default="gpt2giga.log", description="Имя лог файла")
    log_max_size: int = Field(
        default=10 * 1024 * 1024, description="максимальный размер файла в байтах"
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

    @field_validator("mode", mode="before")
    @classmethod
    def normalize_mode(cls, value):
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("structured_output_mode", mode="before")
    @classmethod
    def normalize_structured_output_mode(cls, value):
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator(
        "gigachat_api_mode",
        "normalization_mode",
        "conversation_on_divergence",
        "traffic_log_sink",
        "observability_backend",
        mode="before",
    )
    @classmethod
    def normalize_api_modes(cls, value):
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("traffic_log_sinks", mode="before")
    @classmethod
    def normalize_traffic_log_sinks(cls, value):
        if value in (None, ""):
            return []
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            if text.startswith("["):
                return json.loads(text)
            return [item.strip().lower() for item in text.split(",") if item.strip()]
        if isinstance(value, list):
            return [
                item.strip().lower() if isinstance(item, str) else item
                for item in value
            ]
        return value

    @field_validator("metrics_path", mode="before")
    @classmethod
    def normalize_metrics_path(cls, value):
        if not isinstance(value, str):
            return value
        path = value.strip()
        if not path:
            return "/metrics"
        if not path.startswith("/"):
            path = f"/{path}"
        return path.rstrip("/") or "/metrics"

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
        from gpt2giga.models.security import SecuritySettings

        return SecuritySettings(
            mode=self.mode,
            enable_api_key_auth=self.enable_api_key_auth,
            api_key=self.api_key,
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

    model_config = SettingsConfigDict(env_prefix="gpt2giga_", case_sensitive=False)


class GigaChatCLI(GigachatSettings):
    model_config = SettingsConfigDict(env_prefix="gigachat_", case_sensitive=False)


class ProxyConfig(BaseSettings):
    """Конфигурация прокси-сервера gpt2giga"""

    proxy_settings: ProxySettings = Field(default_factory=ProxySettings, alias="proxy")
    gigachat_settings: GigaChatCLI = Field(
        default_factory=GigaChatCLI, alias="gigachat"
    )
    env_path: Optional[str] = Field(None, description="Path to .env file")

    model_config = SettingsConfigDict(
        cli_parse_args=True,
        cli_prog_name="gpt2giga",
        cli_kebab_case=True,
        cli_ignore_unknown_args=True,
    )
