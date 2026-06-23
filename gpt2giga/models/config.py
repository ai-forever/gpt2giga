import json
import os
import warnings
from functools import cached_property
from typing import Annotated, Any, Literal, Optional

from gigachat.settings import Settings as GigachatSettings
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeFloat,
    PositiveInt,
    PositiveFloat,
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
FusionToolsMode = Literal["off", "schema_only", "final_arbitration"]
FusionStreamingMode = Literal["off", "buffered"]
FusionPipelineMode = Literal["compact", "strict"]
FusionInvocationMode = Literal["outer_auto", "classifier_auto", "force", "off"]
FusionDecisionMode = Literal["tool_result", "synthesize", "selector", "action"]
FusionPromptMode = Literal["full", "minimal"]
FusionPanelOutputTruncation = Literal["head_tail"]
FusionPostToolMode = Literal[
    "direct_continuation",
    "fusion_continuation",
    "verified_continuation",
    "finalize",
]
FusionDirectToolCallPolicy = Literal[
    "return_immediately",
    "selector",
    "verify_before_return",
]
FusionCandidateStageOrder = Literal[
    "parallel",
    "direct_then_verify",
    "direct_and_solver_then_verify",
]
FusionRequiredToolPolicy = Literal["model_inferred", "none"]


DEFAULT_FUSION_ALIASES = [
    "gpt2giga/fusion",
    "gpt2giga/fusion-general",
    "gpt2giga/fusion-code",
    "gpt2giga/fusion-code-budget",
    "gpt2giga/fusion-code-high",
    "gpt2giga/fusion-accuracy",
    "gpt2giga/fusion-benchmark",
    "gpt2giga/fusion-benchmark-text",
    "gpt2giga/fusion-benchmark-tools",
    "gpt2giga/fusion-accuracy-verifier",
    "gpt2giga/fusion-code-agent-safe",
    "gpt2giga/fusion-force-selector",
    "gpt2giga/fusion-force-synthesize",
    "GigaChat-Fusion-Code",
]

DEFAULT_FUSION_META_TOOL_NAMES = ["update_topic", "update_plan", "todo_write"]


def _parse_list_env(value: Any) -> Any:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            return json.loads(text)
        return [item.strip() for item in text.split(",") if item.strip()]
    if isinstance(value, list):
        return [item.strip() if isinstance(item, str) else item for item in value]
    return value


def _parse_dict_env(value: Any) -> Any:
    if value in (None, ""):
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return value


def _normalize_string(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    return value


def _normalize_lower_string(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().lower()
    return value


class FusionPresetSettings(BaseModel):
    """Describe one Fusion deliberation preset."""

    analysis_models: list[str] = Field(min_length=1, max_length=8)
    judge_model: str
    final_model: Optional[str] = None
    direct_model: Optional[str] = None
    panel_roles: list[str] = Field(default_factory=list)
    temperature: Optional[float] = None
    max_completion_tokens: Optional[PositiveInt] = None
    reasoning: Optional[dict[str, Any]] = None
    include_direct_candidate: bool = False
    return_selected_candidate: bool = True
    invocation_mode: FusionInvocationMode = "outer_auto"
    decision_mode: FusionDecisionMode = "tool_result"
    prompt_mode: FusionPromptMode = "minimal"
    max_panel_output_chars: int = Field(default=6000, ge=0)
    max_total_panel_output_chars: int = Field(default=16000, ge=0)
    panel_output_truncation: FusionPanelOutputTruncation = "head_tail"
    min_successful_panels: PositiveInt = 1
    timeout_seconds: PositiveFloat = 120.0
    tools_mode: FusionToolsMode = "schema_only"
    candidate_stage_order: FusionCandidateStageOrder = "parallel"
    required_tool_policy: FusionRequiredToolPolicy = "model_inferred"
    max_client_tool_rounds: Optional[int] = Field(default=None, ge=0, le=64)
    post_tool_mode: Optional[FusionPostToolMode] = None
    direct_tool_call_policy: Optional[FusionDirectToolCallPolicy] = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("analysis_models", "panel_roles", mode="before")
    @classmethod
    def normalize_string_lists(cls, value):
        return _parse_list_env(value)

    @field_validator(
        "tools_mode",
        "invocation_mode",
        "decision_mode",
        "prompt_mode",
        "panel_output_truncation",
        "post_tool_mode",
        "direct_tool_call_policy",
        "candidate_stage_order",
        "required_tool_policy",
        mode="before",
    )
    @classmethod
    def normalize_string_modes(cls, value):
        return _normalize_lower_string(value)

    @field_validator("judge_model", "final_model", "direct_model", mode="before")
    @classmethod
    def normalize_model_names(cls, value):
        return _normalize_string(value)

    @model_validator(mode="after")
    def validate_success_threshold(self):
        """Ensure the preset can satisfy its own quorum."""
        if self.min_successful_panels > len(self.analysis_models):
            raise ValueError(
                "min_successful_panels cannot exceed analysis_models length"
            )
        return self


class FusionSettings(BaseModel):
    """Feature-flagged Fusion settings view."""

    enabled: bool = False
    default_preset: str = "code-high"
    aliases: list[str] = Field(default_factory=lambda: list(DEFAULT_FUSION_ALIASES))
    presets: dict[str, FusionPresetSettings] = Field(default_factory=dict)
    max_panel_models: int = Field(default=4, ge=1, le=8)
    max_panel_concurrency: int = Field(default=4, ge=1)
    max_concurrent_requests: int = Field(default=4, ge=1)
    max_total_upstream_calls_per_request: int = Field(default=5, ge=0)
    max_fusion_invocations_per_turn: int = Field(default=1, ge=0, le=1)
    max_server_tool_calls: int = Field(default=16, ge=0, le=16)
    max_client_final_tool_calls: int = Field(default=1, ge=0, le=1)
    max_tool_calls: int = Field(default=1, ge=0, le=16)
    max_client_tool_rounds: int = Field(default=8, ge=0, le=64)
    post_tool_mode: FusionPostToolMode = "direct_continuation"
    direct_tool_call_policy: FusionDirectToolCallPolicy = "return_immediately"
    streaming_mode: FusionStreamingMode = "buffered"
    stream_heartbeat_seconds: float = Field(default=0.0, ge=0.0)
    pipeline_mode: FusionPipelineMode = "compact"
    expose_analysis_metadata: bool = False
    expose_panel_responses: bool = False
    debug_trace_enabled: bool = False
    fail_on_all_panels_failed: bool = True
    meta_tool_names: list[str] = Field(
        default_factory=lambda: list(DEFAULT_FUSION_META_TOOL_NAMES)
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("aliases", "meta_tool_names", mode="before")
    @classmethod
    def normalize_string_lists(cls, value):
        return _parse_list_env(value)

    @field_validator("presets", mode="before")
    @classmethod
    def normalize_presets(cls, value):
        return _parse_dict_env(value)

    @field_validator("default_preset", mode="before")
    @classmethod
    def normalize_default_preset(cls, value):
        return _normalize_string(value)

    @field_validator(
        "streaming_mode",
        "pipeline_mode",
        "post_tool_mode",
        "direct_tool_call_policy",
        mode="before",
    )
    @classmethod
    def normalize_modes(cls, value):
        return _normalize_lower_string(value)

    @model_validator(mode="after")
    def validate_aliases_and_presets(self):
        """Reject recursive Fusion aliases inside concrete model slots."""
        if self.max_tool_calls != 1 and self.max_server_tool_calls == 16:
            self.max_server_tool_calls = self.max_tool_calls
        aliases = {alias.removeprefix("models/") for alias in self.aliases}
        for preset_name, preset in self.presets.items():
            concrete_models = [
                *preset.analysis_models,
                preset.judge_model,
                *(
                    model
                    for model in [preset.final_model, preset.direct_model]
                    if model
                ),
            ]
            for model in concrete_models:
                if model.removeprefix("models/") in aliases:
                    raise ValueError(
                        f"Fusion preset {preset_name!r} references Fusion alias "
                        f"{model!r}; recursive Fusion is not allowed"
                    )
        return self


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
    fusion_enabled: bool = Field(
        default=False,
        description="Enable local GigaFusion multi-model deliberation provider.",
    )
    fusion_default_preset: str = Field(
        default="code-high",
        description="Default Fusion preset used when a request does not name one.",
    )
    fusion_aliases: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_FUSION_ALIASES),
        description="Virtual model aliases that trigger Fusion when enabled.",
    )
    fusion_presets: Annotated[dict[str, Any], NoDecode] = Field(
        default_factory=dict,
        description="Fusion preset map encoded as JSON object in env.",
    )
    fusion_max_panel_models: int = Field(
        default=4,
        ge=1,
        le=8,
        description="Maximum number of parallel analysis models per Fusion request.",
    )
    fusion_max_panel_concurrency: int = Field(
        default=4,
        ge=1,
        description="Maximum concurrent analysis calls inside one Fusion request.",
    )
    fusion_max_concurrent_requests: int = Field(
        default=4,
        ge=1,
        description="Maximum concurrently running Fusion requests per process.",
    )
    fusion_max_total_upstream_calls_per_request: int = Field(
        default=5,
        ge=0,
        description=(
            "Maximum planned upstream calls in one Fusion request. "
            "Use 0 to disable the per-request call budget."
        ),
    )
    fusion_max_tool_calls: int = Field(
        default=1,
        ge=0,
        le=16,
        description=(
            "Maximum tool calls Fusion may return when tool arbitration is enabled. "
            "Current compact pipeline supports exactly one final tool call."
        ),
    )
    fusion_max_client_tool_rounds: int = Field(
        default=8,
        ge=0,
        le=64,
        description=(
            "Maximum client-visible tool result rounds Fusion may continue before "
            "forcing a final post-tool answer."
        ),
    )
    fusion_post_tool_mode: FusionPostToolMode = Field(
        default="direct_continuation",
        description=(
            "Post-tool Fusion behavior: direct_continuation, fusion_continuation, "
            "or finalize."
        ),
    )
    fusion_direct_tool_call_policy: FusionDirectToolCallPolicy = Field(
        default="return_immediately",
        description=(
            "How Fusion handles a valid native direct tool call before panels: "
            "return_immediately or selector."
        ),
    )
    fusion_streaming_mode: FusionStreamingMode = Field(
        default="buffered",
        description="Fusion streaming behavior: off or buffered SSE after deliberation.",
    )
    fusion_stream_heartbeat_seconds: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Seconds between opt-in OpenAI Chat SSE heartbeat comment frames "
            "while buffered Fusion deliberation is running. 0 disables heartbeats."
        ),
    )
    fusion_pipeline_mode: FusionPipelineMode = Field(
        default="compact",
        description=(
            "Fusion pipeline mode. Current implementation supports only compact, "
            "where judge and finalizer are one call."
        ),
    )
    fusion_expose_analysis_metadata: bool = Field(
        default=False,
        description="Expose safe structured Fusion analysis metadata in responses.",
    )
    fusion_expose_panel_responses: bool = Field(
        default=False,
        description="Expose raw panel responses in Fusion metadata; unsafe unless debug-only.",
    )
    fusion_debug_trace_enabled: bool = Field(
        default=False,
        description="Enable bounded Fusion debug trace support.",
    )
    fusion_fail_on_all_panels_failed: bool = Field(
        default=True,
        description="Return an error when no Fusion analysis panel succeeds.",
    )
    fusion_meta_tool_names: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_FUSION_META_TOOL_NAMES),
        description=(
            "Tool names treated as Fusion meta/state tools and not as final "
            "progress actions."
        ),
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
        "fusion_streaming_mode",
        "fusion_pipeline_mode",
        "fusion_post_tool_mode",
        "fusion_direct_tool_call_policy",
        mode="before",
    )
    @classmethod
    def normalize_api_modes(cls, value):
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("fusion_aliases", mode="before")
    @classmethod
    def normalize_fusion_aliases(cls, value):
        return _parse_list_env(value)

    @field_validator("fusion_meta_tool_names", mode="before")
    @classmethod
    def normalize_fusion_meta_tool_names(cls, value):
        return _parse_list_env(value)

    @field_validator("fusion_presets", mode="before")
    @classmethod
    def normalize_fusion_presets(cls, value):
        return _parse_dict_env(value)

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
    def _validate_fusion_settings(self):
        """Validate the nested Fusion settings view built from flat env fields."""
        if self.fusion_enabled:
            _ = self.fusion
        return self

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
    def fusion(self) -> FusionSettings:
        """Build a nested Fusion settings view from flat GPT2GIGA_FUSION_* envs."""
        if not self.fusion_enabled:
            return FusionSettings(enabled=False)
        return FusionSettings(
            enabled=self.fusion_enabled,
            default_preset=self.fusion_default_preset,
            aliases=self.fusion_aliases,
            presets=self.fusion_presets,
            max_panel_models=self.fusion_max_panel_models,
            max_panel_concurrency=self.fusion_max_panel_concurrency,
            max_concurrent_requests=self.fusion_max_concurrent_requests,
            max_total_upstream_calls_per_request=(
                self.fusion_max_total_upstream_calls_per_request
            ),
            max_server_tool_calls=self.fusion_max_tool_calls,
            max_tool_calls=self.fusion_max_tool_calls,
            max_client_tool_rounds=self.fusion_max_client_tool_rounds,
            post_tool_mode=self.fusion_post_tool_mode,
            direct_tool_call_policy=self.fusion_direct_tool_call_policy,
            streaming_mode=self.fusion_streaming_mode,
            stream_heartbeat_seconds=self.fusion_stream_heartbeat_seconds,
            pipeline_mode=self.fusion_pipeline_mode,
            expose_analysis_metadata=self.fusion_expose_analysis_metadata,
            expose_panel_responses=self.fusion_expose_panel_responses,
            debug_trace_enabled=self.fusion_debug_trace_enabled,
            fail_on_all_panels_failed=self.fusion_fail_on_all_panels_failed,
            meta_tool_names=self.fusion_meta_tool_names,
        )

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
