# Встроенные инструменты

Этот документ фиксирует маппинг встроенных инструментов провайдеров в `tools`
GigaChat Chat Completions v2. Источник истины для GigaChat здесь -
установленный `gigachat` SDK, а не сайт или внешняя документация.

## Источник истины

В `pyproject.toml` пакет ограничен диапазоном `gigachat>=0.2.2a1,<0.3.0`.
Для этого диапазона канонический список встроенных инструментов берётся из
SDK-моделей:

- `gigachat.models.chat_completions.ChatTool`;
- SDK-нормализатор короткой записи `_normalize_tool`;
- локальный вспомогательный объект `gpt2giga.common.tools.GIGACHAT_BUILTIN_TOOL_TYPES`.

SDK принимает ровно такие поля встроенных инструментов:

| Инструмент GigaChat | Поле SDK | Форма конфигурации |
|---|---|---|
| Поиск в интернете | `web_search` | `ChatWebSearchTool`: `type`, `indexes`, `flags` плюс совместимые с SDK дополнительные поля |
| Извлечение содержимого URL | `url_content_extraction` | `dict[str, Any]` |
| Интерпретатор кода | `code_interpreter` | `dict[str, Any]` |
| Генерация изображений | `image_generate` | `dict[str, Any]` |
| Генерация 3D-моделей | `model_3d_generate` | `dict[str, Any]` |

`functions` в `ChatTool` - это обёртка для пользовательских function tools.
Это не встроенный инструмент GigaChat: он маппится отдельно из
OpenAI/Anthropic/Gemini function declarations.

## Где исполняются инструменты

Встроенные инструменты отправляются upstream только через контракт GigaChat
Chat Completions v2. На публичных маршрутах это означает:

- `/v2/...` всегда использует v2 backend contract;
- корневые routes используют v2 только при `GPT2GIGA_GIGACHAT_API_MODE=v2`;
- `/v1/...` использует legacy-контракт GigaChat chat, где встроенные
  инструменты не передаются как исполняемые tools.

Если в одном запросе один и тот же встроенный инструмент передан несколько раз
через разные aliases, в GigaChat payload попадает первое каноническое поле.
Принудительный `tool_choice` для поддержанных встроенных инструментов превращается в
GigaChat `ChatToolConfig(mode="tool", tool_name="<canonical tool>")`.

Чтобы временно отключить этот маппинг без отключения пользовательских function
tools, задайте `GPT2GIGA_DISABLE_BUILTIN_TOOL_MAPPING=True`. Тогда известные
provider built-in tools принимаются для совместимости, но не отправляются
upstream как исполняемые GigaChat tools; соответствующий `tool_choice`
игнорируется.

## Маппинг OpenAI

OpenAI Chat Completions и Responses tools нормализуются по `type`.

| Тип OpenAI tool | Инструмент GigaChat | Примечания |
|---|---|---|
| `web_search` | `web_search` | Прямой канонический маппинг |
| `web_search_*` | `web_search` | Покрывает датированные типы OpenAI, например `web_search_2025_08_26` |
| `web_search_preview` | `web_search` | Предварительный alias |
| `web_search_preview_*` | `web_search` | Датированные предварительные aliases |
| `code_interpreter` | `code_interpreter` | Прямой канонический маппинг |
| `image_generation` | `image_generate` | Alias для генерации изображений OpenAI Responses |
| `image_generate` | `image_generate` | Каноническая передача GigaChat без переименования |
| `url_content_extraction` | `url_content_extraction` | Каноническая передача GigaChat без переименования |
| `model_3d_generate` | `model_3d_generate` | Нативная передача GigaChat без переименования |
| `function` | обёртка `functions` | Пользовательская function, не встроенный инструмент |
| `namespace` | обёртка `functions` | Responses namespace tools разворачиваются в плоские имена функций GigaChat |

Конфигурация читается из канонического поля, alias-поля и неструктурных
верхнеуровневых ключей. Например:

```json
{
  "type": "web_search_preview",
  "indexes": ["web"],
  "flags": ["trusted"]
}
```

превращается в:

```json
{"web_search": {"indexes": ["web"], "flags": ["trusted"]}}
```

## Маппинг Anthropic

Anthropic Messages tools используют версионированные имена provider tools.
Прокси убирает suffixes провайдера/версии там, где смысл чисто маппится на
встроенный инструмент GigaChat SDK.

| Тип Anthropic tool | Инструмент GigaChat | Примечания |
|---|---|---|
| `web_search` | `web_search` | Прямой alias провайдера |
| `web_search_*` | `web_search` | Покрывает датированные SDK-имена, например `web_search_20250305` |
| `web_fetch` | `url_content_extraction` | URL fetch маппится на извлечение URL |
| `web_fetch_*` | `url_content_extraction` | Покрывает датированные SDK-имена, например `web_fetch_20250910` |
| `code_execution` | `code_interpreter` | Code execution маппится на интерпретатор |
| `code_execution_*` | `code_interpreter` | Покрывает датированные SDK-имена, например `code_execution_20250825` |
| Custom tools с `input_schema` | обёртка `functions` | Пользовательская function, не встроенный инструмент |

## Маппинг Gemini

Записи Gemini `tools` не содержат поле `type`. Adapter маппит известные ключи
объекта tool во встроенные инструменты GigaChat, а неподдержанные ключи сохраняет в
`raw_extensions["unsupportedTools"]` для диагностики.

| Ключ Gemini tool | Инструмент GigaChat | Примечания |
|---|---|---|
| `googleSearch` / `google_search` | `web_search` | Поиск Google маппится на web search |
| `googleSearchRetrieval` / `google_search_retrieval` | `web_search` | Устаревшая/retrieval форма поиска best-effort маппится на web search |
| `urlContext` / `url_context` | `url_content_extraction` | URL context маппится на извлечение URL |
| `codeExecution` / `code_execution` | `code_interpreter` | Code execution маппится на интерпретатор |
| `functionDeclarations` / `function_declarations` | обёртка `functions` | Пользовательские functions, не встроенные инструменты |

Для Gemini requests в каноническое поле GigaChat передаётся только объект
конфигурации из поддержанного ключа Gemini tool:

```json
{"googleSearch": {"indexes": ["web"]}}
```

превращается в:

```json
{"type": "web_search", "web_search": {"indexes": ["web"]}}
```

`toolConfig.functionCallingConfig` применяется только к Gemini function
declarations. Он не форсирует, не фильтрует и не удаляет встроенные
инструменты провайдера.

## Не маппится

Встроенные provider tools остаются unsupported, если GigaChat SDK не предоставляет
семантически эквивалентное поле `ChatTool`.

| Провайдер | Примеры без маппинга | Поведение |
|---|---|---|
| OpenAI | `file_search`, `computer`, `computer_use_preview`, `mcp`, `tool_search`, `shell`, `local_shell`, `apply_patch`, freeform `custom` | Игнорируются или сохраняются только в compatibility diagnostics в зависимости от route |
| Anthropic | `tool_search*`, `memory*`, `bash*`, `text_editor*`, `advisor`, MCP tools, computer-use tools | Принимаются там, где это разрешено compatibility policy, но не отправляются в GigaChat как исполняемые встроенные инструменты |
| Gemini | `fileSearch`, `googleMaps`, `computerUse`, `mcpServers`, `enterpriseWebSearch`, `parallelAiSearch`, Vertex/RAG/retrieval tools | Сохраняются в diagnostics `unsupportedTools` и не применяются GigaChat |

Такой подход намеренно консервативный: похожих названий недостаточно для
маппинга. Маппинг появляется только тогда, когда в GigaChat SDK есть
исполняемое поле с тем же операционным смыслом.

## Чеклист обновления

Когда SDK провайдера добавляет или переименовывает встроенные инструменты:

1. Проверить установленные SDK провайдера и модели GigaChat SDK.
2. Обновить `gpt2giga.common.tools.normalize_gigachat_builtin_tool_type`.
3. Для Gemini object-key tools обновить `gpt2giga.protocols.gemini.adapter`.
4. Добавить тесты request-builder и adapter.
5. Обновить этот документ, а также `api-compatibility.md` и
   `client-parameter-compatibility.md`, если меняется публичное поведение.
