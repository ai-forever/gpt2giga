# GigaFusion

GigaFusion - локальный режим multi-model deliberation внутри `gpt2giga`.
Клиент отправляет обычный OpenAI-, Anthropic- или Gemini-compatible запрос, а
прокси выполняет несколько внутренних GigaChat-вызовов, сравнивает ответы и
возвращает один финальный ответ в исходном API-формате.

Это не прокси в OpenRouter Fusion и не точная копия OpenRouter behavior.
Внешний OpenRouter не вызывается: все direct, panel, judge/selector и
finalizer calls идут через настроенный GigaChat backend.

## Когда использовать

Fusion полезен для задач, где качество важнее latency:

- coding-agent запросы с неоднозначным планом;
- архитектурные решения и code review;
- задачи, где нужно сравнить несколько подходов;
- ответы, где полезно явно отловить противоречия, неполное покрытие и риски.

Не включайте Fusion по умолчанию для coding harnesses, дешевых коротких
completions, autocomplete и latency-sensitive UI без отдельной проверки. Один
Fusion-запрос делает несколько upstream model calls: `code-high` запускает три
panel calls и один judge/finalizer call, а selector presets могут добавлять
baseline-like direct candidate и optional finalizer. Panel и direct calls идут
параллельно, но расходуют больше upstream concurrency и tokens.

Перед включением Fusion как default для Codex/Claude Code/Qwen Code-style
клиентов проверьте отдельный tool-enabled agent preset и убедитесь, что
`direct_candidate + selector` близок к single Ultra baseline, p95 latency
понятен, judge parse errors почти отсутствуют, fallback/rewrite rates низкие, а
selected candidate distribution объяснима.

## Поддержанные API

Fusion включается на уже существующих публичных routes:

| API surface | Routes |
|---|---|
| OpenAI Chat Completions | `/chat/completions`, `/v1/chat/completions`, `/v2/chat/completions` |
| OpenAI Responses | `/responses`, `/v1/responses`, `/v2/responses` |
| Anthropic Messages | `/messages`, `/v1/messages`, `/v2/messages` |
| Gemini GenerateContent | `/models/{model}:generateContent`, `/models/{model}:streamGenerateContent` и versioned variants |
| Model discovery | `/models`, `/v1beta/models`, `/model/info` |

Streaming поддержан в buffered режиме: Fusion сначала завершает внутренний
deliberation, затем отдает финальный ответ как корректный SSE stream для
выбранного client protocol. Поэтому first byte будет позже, чем у обычного
single-model streaming. Для OpenAI Chat Completions можно включить opt-in
heartbeat через `GPT2GIGA_FUSION_STREAM_HEARTBEAT_SECONDS`: пока deliberation
выполняется, stream будет отдавать SSE comment frames
`: gpt2giga-fusion heartbeat`. Остальные protocol streams остаются строгим
buffered output до отдельной проверки client compatibility.

## Как включить

Минимальный `.env`:

```dotenv
GPT2GIGA_FUSION_ENABLED=True
GPT2GIGA_FUSION_DEFAULT_PRESET=code-high

GIGACHAT_CREDENTIALS="<your-gigachat-credentials>"
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max
```

Для agent/IDE клиентов с built-in tools обычно удобнее запускать public routes в
GigaChat v2 mode:

```dotenv
GPT2GIGA_GIGACHAT_API_MODE=v2
```

`GPT2GIGA_PASS_MODEL=False` можно продолжать использовать для обычных клиентов,
которые присылают не-GigaChat model ids. Fusion детектит virtual alias до
подмены модели и явно передает panel/judge model names во внутренние GigaChat
вызовы.

## Модельные aliases

По умолчанию Fusion срабатывает, когда request `model` совпадает с одним из
virtual aliases:

```text
gpt2giga/fusion
gpt2giga/fusion-general
gpt2giga/fusion-code
gpt2giga/fusion-code-budget
gpt2giga/fusion-code-high
gpt2giga/fusion-accuracy
gpt2giga/fusion-benchmark
gpt2giga/fusion-accuracy-verifier
gpt2giga/fusion-code-agent-safe
GigaChat-Fusion-Code
```

Aliases появляются в model discovery только когда
`GPT2GIGA_FUSION_ENABLED=True`.

Specific aliases such as `gpt2giga/fusion-accuracy` and
`gpt2giga/fusion-code-agent-safe` select the matching built-in preset unless a
request-level `preset` override is provided. Generic aliases such as
`gpt2giga/fusion-code` continue to use `GPT2GIGA_FUSION_DEFAULT_PRESET`.

Для Gemini path можно использовать alias как model id:

```text
/v1beta/models/gpt2giga/fusion-code:generateContent
```

## Как работает pipeline

Текущая реализация поддерживает только `pipeline_mode=compact`. Внутри него
есть два decision modes:

- `decision_mode="synthesize"`: старый путь `panel -> judge/finalizer`, где
  judge возвращает structured `FusionAnalysis` с final answer или tool call.
- `decision_mode="selector"`: direct/panel candidates -> selector judge ->
  selected candidate as-is, если rewrite не нужен, или optional finalizer.

`final_model` используется только как optional selector finalizer model; если он
не задан, finalizer использует `judge_model`.

1. Router читает исходный request и ищет Fusion-настройку.
2. Request переводится во внутренний normalized chat contract.
3. Если `include_direct_candidate=true`, adapter параллельно запускает direct
   candidate: исходный normalized request без Fusion prompt envelope, через
   `direct_model` или `judge_model`.
4. `FusionProviderAdapter` запускает panel calls к моделям из preset. Каждая
   panel получает исходный запрос, служебный system prompt и optional role,
   например `architect`, `implementer`, `reviewer`.
5. Panel calls не выполняют tools. Если tools переданы и режим это разрешает,
   panel видит schemas только как reference и может предложить
   `tool_call_candidate`.
6. Перед judge prompt candidate outputs ограничиваются
   `max_panel_output_chars` и `max_total_panel_output_chars`; начало и конец
   ответа сохраняются, truncation явно помечается.
7. В `synthesize` judge/finalizer получает исходный запрос и candidate
   responses, сравнивает их и возвращает structured analysis: consensus,
   contradictions, partial coverage, unique insights, blind spots, risk flags,
   selected strategy, final answer или ровно один final tool call.
8. В `selector` judge возвращает `FusionSelection`: selected candidate id,
   confidence, `needs_rewrite`, correction и brief reason. Если
   `needs_rewrite=false` и `return_selected_candidate=true`, proxy возвращает
   выбранного кандидата без переписывания.
9. Финальный ответ маппится обратно в OpenAI, Anthropic или Gemini response
   shape. Usage агрегируется по direct, panel, judge и finalizer calls.

Если часть panel calls падает или истекает по timeout, Fusion продолжает работу,
пока выполнен `min_successful_panels`. Если judge response пустой или невалидный
JSON, adapter делает один repair-call. Если repair тоже не даёт валидный
`FusionAnalysis`, adapter пытается вернуть fallback в порядке: direct candidate,
выбранный candidate, solver panel, первый успешный panel. В selector mode
невалидный `FusionSelection` также попадает в observable fallback.

## Presets

Встроенные presets используются, если `GPT2GIGA_FUSION_PRESETS` не переопределил
их:

| Preset | Panel models | Judge model | Direct | Decision / prompt | Roles | Tools mode |
|---|---|---|---|---|---|---|
| `general` | `GigaChat-2-Max`, `GigaChat-2-Pro` | `GigaChat-2-Max` | no | `synthesize` / `full` | `planner`, `critic` | `off` |
| `code-budget` | `GigaChat-2-Pro`, `GigaChat-2-Max` | `GigaChat-2-Max` | no | `synthesize` / `full` | `implementer`, `reviewer` | `schema_only` |
| `code-high` | `GigaChat-3-Ultra`, `GigaChat-2-Max`, `GigaChat-2-Pro` | `GigaChat-3-Ultra` | no | `synthesize` / `full` | `architect`, `implementer`, `reviewer` | `schema_only` |
| `accuracy-ultra-selector` | `GigaChat-3-Ultra` | `GigaChat-3-Ultra` | yes | `selector` / `minimal` | `solver` | `off` |
| `accuracy-ultra-verifier` | `GigaChat-3-Ultra` | `GigaChat-3-Ultra` | yes | `selector` / `minimal` | `verifier` | `off` |
| `code-agent-safe` | `GigaChat-3-Ultra`, `GigaChat-2-Max` | `GigaChat-3-Ultra` | yes | `selector` / `full` | `solver`, `reviewer` | `schema_only` |

`GPT2GIGA_FUSION_DEFAULT_PRESET` выбирает preset для aliases и request-level
Fusion configs, где preset не указан.

Accuracy presets are for simple benchmark/QA validation and intentionally use
`tools_mode="off"`. `code-agent-safe` keeps a full harness envelope and
`return_selected_candidate=false`, so tool-enabled agent runs still pass through
the finalizer/tool arbitration path instead of blindly forwarding a selected
panel response.

## Env reference

| Переменная | Default | Что делает |
|---|---:|---|
| `GPT2GIGA_FUSION_ENABLED` | `False` | Включает детект Fusion aliases/plugin/tool/metadata и virtual model discovery. |
| `GPT2GIGA_FUSION_DEFAULT_PRESET` | `code-high` | Preset по умолчанию. |
| `GPT2GIGA_FUSION_ALIASES` | built-in list | JSON array или comma-separated list virtual model ids. |
| `GPT2GIGA_FUSION_PRESETS` | `{}` | JSON object с custom presets; ключи дополняют или переопределяют built-ins. |
| `GPT2GIGA_FUSION_MAX_PANEL_MODELS` | `4` | Верхний лимит `analysis_models` в одном запросе, допустимо `1..8`. |
| `GPT2GIGA_FUSION_MAX_PANEL_CONCURRENCY` | `4` | Сколько panel calls можно выполнять параллельно внутри одного Fusion-запроса. |
| `GPT2GIGA_FUSION_MAX_CONCURRENT_REQUESTS` | `4` | Глобальный для процесса лимит одновременно выполняющихся Fusion-запросов. |
| `GPT2GIGA_FUSION_MAX_TOTAL_UPSTREAM_CALLS_PER_REQUEST` | `5` | Максимум планируемых upstream calls на один Fusion-запрос: direct candidate, panel calls, judge call и обязательный selector finalizer. `0` отключает лимит. |
| `GPT2GIGA_FUSION_MAX_TOOL_CALLS` | `1` | Зарезервировано под будущие parallel tool calls; текущий compact pipeline поддерживает ровно один final tool call. |
| `GPT2GIGA_FUSION_MAX_CLIENT_TOOL_ROUNDS` | `8` | Сколько client-visible tool-result rounds можно продолжать с включенными tools перед forced finalization. |
| `GPT2GIGA_FUSION_POST_TOOL_MODE` | `direct_continuation` | Поведение после client tool result: `direct_continuation`, `fusion_continuation` или `finalize`. |
| `GPT2GIGA_FUSION_DIRECT_TOOL_CALL_POLICY` | `return_immediately` | Что делать с валидным native direct tool call до panel stage: вернуть сразу или отправить в `selector`. |
| `GPT2GIGA_FUSION_META_TOOL_NAMES` | `update_topic,update_plan,todo_write` | Comma-separated или JSON list tool names, которые считаются meta/state tools и не используются как final progress actions. |
| `GPT2GIGA_FUSION_STREAMING_MODE` | `buffered` | `buffered` отдает SSE после deliberation; `off` запрещает Fusion streaming requests. |
| `GPT2GIGA_FUSION_STREAM_HEARTBEAT_SECONDS` | `0` | Если больше `0`, OpenAI Chat Completions stream отдает SSE comment heartbeat frames, пока buffered Fusion deliberation еще выполняется. |
| `GPT2GIGA_FUSION_PIPELINE_MODE` | `compact` | Единственный поддержанный pipeline mode; decision behavior выбирается preset key `decision_mode`. |
| `GPT2GIGA_FUSION_EXPOSE_ANALYSIS_METADATA` | `False` | Добавляет structured judge analysis в provider metadata. Не включает raw prompts. |
| `GPT2GIGA_FUSION_EXPOSE_PANEL_RESPONSES` | `False` | Добавляет raw panel content в provider metadata. Оставляйте `False` вне локальной отладки. |
| `GPT2GIGA_FUSION_DEBUG_TRACE_ENABLED` | `False` | Зарезервировано для bounded debug trace support. |
| `GPT2GIGA_FUSION_FAIL_ON_ALL_PANELS_FAILED` | `True` | Зарезервировано под failure policy; текущий runtime возвращает ошибку, если не достигнут `min_successful_panels`. |

Custom presets задаются JSON-строкой:

```dotenv
GPT2GIGA_FUSION_PRESETS='{
  "code-review": {
    "analysis_models": ["GigaChat-3-Ultra", "GigaChat-2-Max"],
    "judge_model": "GigaChat-3-Ultra",
    "direct_model": null,
    "final_model": null,
    "panel_roles": ["reviewer", "risk-checker"],
    "temperature": 0.2,
    "max_completion_tokens": 4096,
    "include_direct_candidate": true,
    "return_selected_candidate": true,
    "decision_mode": "selector",
    "prompt_mode": "full",
    "max_panel_output_chars": 6000,
    "max_total_panel_output_chars": 16000,
    "min_successful_panels": 1,
    "timeout_seconds": 180,
    "tools_mode": "schema_only"
  }
}'
```

В `.env` обычно удобнее держать JSON в одну строку. `analysis_models`,
`judge_model`, `direct_model` и `final_model` не могут ссылаться на Fusion
aliases, чтобы не создать рекурсивный Fusion-вызов. `temperature=null` и
`max_completion_tokens=null` означают preserve client generation settings.

## Tools behavior

FusionProviderAdapter никогда не выполняет tools сам.

`schema_only`:

- Panels видят tool schemas как текстовую справку и могут предложить действие
  только как plain-text/JSON `tool_call_candidate`.
- Только judge/finalizer получает реальные tools и может вернуть один
  validated final tool call.

`final_arbitration`:

- Panels могут включить structured tool-call candidates в свой текстовый output.
- Эти candidates advisory only и никогда не пересылаются клиенту напрямую.
- Только judge/finalizer получает реальные tools и может вернуть один
  validated final tool call.

Final tool-call arguments разбираются как JSON, ограничиваются по размеру и
валидируются по исходной JSON Schema tool parameters. Если final tool call
невалиден, но есть text `final_answer`, клиент получает text answer без tool
call. Если клиент требовал tool call через `tool_choice`, Fusion возвращает
ошибку.

Judge output has one final action: either `final_answer` or `final_tool_call`.
If legacy judge JSON includes both, Fusion deterministically normalizes it.
`final_answer` wins unless `task_status="needs_tool"` or `tool_choice` forces a
valid non-meta progress tool. Meta/state tools from
`GPT2GIGA_FUSION_META_TOOL_NAMES` are dropped as final actions. If the same tool
name and canonical arguments already appeared in recent assistant tool calls
after the latest user message, Fusion returns text fallback or a typed error
instead of emitting the repeated call again.

For tool-enabled agent presets prefer `return_selected_candidate=false`, so the
selector decision still goes through finalizer/tool arbitration. Returning a
selected candidate as-is is intended for tool-free accuracy presets until the
tool-enabled preset has separate validation.

## Failure semantics

Fusion infrastructure failures и upstream failures возвращаются как protocol
compatible error body. Для OpenAI Chat Completions и OpenAI Responses
non-stream и buffered-stream routes такие ошибки возвращаются с HTTP 502.
Model-level successful responses остаются HTTP 200.

## Request-level включение

Самый простой способ - выбрать virtual model:

```json
{
  "model": "gpt2giga/fusion-code",
  "messages": [{"role": "user", "content": "Review this migration plan"}]
}
```

Также поддержаны OpenRouter-style shapes для клиентов, которые умеют передавать
custom request body:

```json
{
  "model": "GigaChat-3-Ultra",
  "plugins": [
    {"id": "fusion", "preset": "code-budget"}
  ],
  "messages": [{"role": "user", "content": "Find edge cases"}]
}
```

```json
{
  "model": "GigaChat-3-Ultra",
  "tools": [
    {
      "type": "openrouter:fusion",
      "parameters": {
        "preset": "code-high",
        "analysis_models": ["GigaChat-3-Ultra", "GigaChat-2-Max"],
        "model": "GigaChat-3-Ultra"
      }
    }
  ],
  "messages": [{"role": "user", "content": "Compare two designs"}]
}
```

Native gpt2giga metadata config:

```json
{
  "model": "GigaChat-3-Ultra",
  "metadata": {
    "gpt2giga_fusion": {
      "preset": "code-budget",
      "enabled": true
    }
  },
  "messages": [{"role": "user", "content": "Suggest a safe rollout plan"}]
}
```

Detection priority is: `tools` `openrouter:fusion`, then `plugins`, then
`metadata` / `extra_body` `gpt2giga_fusion`, then model alias. For
plugin/tool/metadata configs, `"enabled": false` disables Fusion for that
request.

## Client examples

OpenAI Chat Completions:

```sh
curl http://localhost:8090/v1/chat/completions \
  -H "Authorization: Bearer $GPT2GIGA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt2giga/fusion-code",
    "messages": [{"role": "user", "content": "Review this API design"}]
  }'
```

OpenAI Responses, useful for Codex-style clients:

```sh
curl http://localhost:8090/v2/responses \
  -H "Authorization: Bearer $GPT2GIGA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt2giga/fusion-code",
    "input": "Inspect the repo and propose the next implementation step."
  }'
```

Anthropic Messages:

```sh
curl http://localhost:8090/v1/messages \
  -H "Authorization: Bearer $GPT2GIGA_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt2giga/fusion-code",
    "max_tokens": 2048,
    "messages": [{"role": "user", "content": "Compare these implementation options"}]
  }'
```

Gemini GenerateContent:

```sh
curl http://localhost:8090/v1beta/models/gpt2giga/fusion-code:generateContent \
  -H "x-goog-api-key: $GPT2GIGA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "contents": [
      {"role": "user", "parts": [{"text": "Find risks in this release checklist"}]}
    ]
  }'
```

Codex config override:

```toml
model = "gpt2giga/fusion-code"
model_provider = "gpt2giga"
model_reasoning_effort = "none"

[model_providers.gpt2giga]
name = "gpt2giga"
base_url = "http://localhost:8090/v2"
env_key = "GPT2GIGA_API_KEY"
wire_api = "responses"
supports_websockets = false
```

Claude Code can use the same alias as `--model gpt2giga/fusion-code` when
`ANTHROPIC_BASE_URL` points at `gpt2giga`. Qwen Code and Gemini CLI can use the
alias through their configured model id.

## What to show in a demo or smoke

1. `GET /models` includes Fusion aliases after `GPT2GIGA_FUSION_ENABLED=True`.
2. A non-stream `/responses` request with `model="gpt2giga/fusion-code"` returns
   normal Responses API output.
3. Response protocols that expose gateway metadata show safe markers such as
   `gpt2giga_fusion=true`, preset, analysis models, judge model and panel counts.
4. A `stream=true` request returns valid SSE only after the internal deliberation
   finishes.
5. `/metrics` includes `gpt2giga_fusion_*` series when metrics are enabled.
6. Phoenix/OpenTelemetry shows an extra `GigaFusion` span when observability is
   enabled.

Manual smoke script:

```sh
uv run python scripts/run_fusion_smoke.py --routes models,responses
```

For full route coverage:

```sh
uv run python scripts/run_fusion_smoke.py \
  --routes models,responses,chat,anthropic,gemini
```

## Observability and safety

Fusion metadata is intentionally bounded. Where the response protocol exposes
gateway metadata, it includes only safe operational markers by default:

- requested Fusion alias;
- preset;
- panel model ids;
- judge/final model ids;
- successful and failed panel counts;
- decision mode and prompt mode;
- selected candidate id/source;
- rewrite, judge parse error and panel truncation flags;
- fallback reason, if fallback happened.

Metrics and Phoenix span events do not include prompts, raw panel responses,
tool arguments, API keys or GigaChat credentials. Raw panel content is exposed
only when `GPT2GIGA_FUSION_EXPOSE_PANEL_RESPONSES=True`; keep it disabled in
shared and production environments.

Fusion metrics include request and stage latency, panel calls, token usage,
selected candidate distribution, rewrite count, judge parse errors, repair
calls, fallback reasons and panel/candidate truncation counters. These are the
primary signals for checking p95 latency, fallback rate, rewrite rate and
selector distribution before using Fusion as a default coding-harness preset.

More operational details: [Операции](operations.md#metrics) and
[Phoenix / OpenTelemetry](operations.md#phoenix-opentelemetry).

Internal module boundaries and extension rules are described in
[Fusion provider architecture](architecture/fusion-provider.md).
