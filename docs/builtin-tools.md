# Встроенные инструменты

Этот документ фиксирует сопоставление встроенных инструментов провайдеров с `tools`
GigaChat Chat Completions v2. Источник истины для GigaChat здесь —
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

`functions` в `ChatTool` — это обёртка для пользовательских функциональных инструментов.
Это не встроенный инструмент GigaChat: он сопоставляется отдельно из
объявлений функций OpenAI/Anthropic/Gemini.

## Где исполняются инструменты

Встроенные инструменты отправляются в вышестоящий сервис только через контракт GigaChat
Chat Completions v2. На публичных маршрутах это означает:

- `/v2/...` всегда использует контракт бэкенда v2;
- корневые маршруты используют v2 только при `GPT2GIGA_GIGACHAT_API_MODE=v2`;
- `/v1/...` использует прежний контракт чата GigaChat, где встроенные
  инструменты не передаются как исполняемые инструменты.

Если в одном запросе один и тот же встроенный инструмент передан несколько раз
через разные псевдонимы, в полезную нагрузку GigaChat попадает первое каноническое поле.
Принудительный `tool_choice` для поддерживаемых встроенных инструментов превращается в
GigaChat `ChatToolConfig(mode="tool", tool_name="<canonical tool>")`.

## Сопоставление OpenAI

Инструменты OpenAI Chat Completions и Responses нормализуются по `type`.

| Тип инструмента OpenAI | Инструмент GigaChat | Примечания |
|---|---|---|
| `web_search` | `web_search` | Прямое каноническое сопоставление |
| `web_search_*` | `web_search` | Покрывает датированные типы OpenAI, например `web_search_2025_08_26` |
| `web_search_preview` | `web_search` | Предварительный псевдоним |
| `web_search_preview_*` | `web_search` | Датированные предварительные псевдонимы |
| `code_interpreter` | `code_interpreter` | Прямое каноническое сопоставление |
| `image_generation` | `image_generate` | Псевдоним для генерации изображений OpenAI Responses |
| `image_generate` | `image_generate` | Каноническая передача GigaChat без переименования |
| `url_content_extraction` | `url_content_extraction` | Каноническая передача GigaChat без переименования |
| `model_3d_generate` | `model_3d_generate` | Нативная передача GigaChat без переименования |
| `function` | обёртка `functions` | Пользовательская функция, не встроенный инструмент |
| `namespace` | обёртка `functions` | Инструменты пространства имён Responses разворачиваются в плоские имена функций GigaChat |

Конфигурация читается из канонического поля, поля-псевдонима и неструктурированных
ключей верхнего уровня. Например:

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

## Сопоставление Anthropic

Инструменты Anthropic Messages используют версионированные имена провайдерских инструментов.
Прокси убирает суффиксы провайдера/версии там, где смысл чисто сопоставляется со
встроенным инструментом GigaChat SDK.

| Тип инструмента Anthropic | Инструмент GigaChat | Примечания |
|---|---|---|
| `web_search` | `web_search` | Прямой провайдерский псевдоним |
| `web_search_*` | `web_search` | Покрывает датированные SDK-имена, например `web_search_20250305` |
| `web_fetch` | `url_content_extraction` | Извлечение по URL сопоставляется с извлечением содержимого URL |
| `web_fetch_*` | `url_content_extraction` | Покрывает датированные SDK-имена, например `web_fetch_20250910` |
| `code_execution` | `code_interpreter` | Выполнение кода сопоставляется с интерпретатором |
| `code_execution_*` | `code_interpreter` | Покрывает датированные SDK-имена, например `code_execution_20250825` |
| Пользовательские инструменты с `input_schema` | обёртка `functions` | Пользовательская функция, не встроенный инструмент |

## Сопоставление Gemini

Записи Gemini `tools` не содержат поле `type`. Адаптер сопоставляет известные ключи
объекта инструмента со встроенными инструментами GigaChat, а неподдерживаемые ключи сохраняет в
`raw_extensions["unsupportedTools"]` для диагностики.

| Ключ инструмента Gemini | Инструмент GigaChat | Примечания |
|---|---|---|
| `googleSearch` / `google_search` | `web_search` | Поиск Google сопоставляется с веб-поиском |
| `googleSearchRetrieval` / `google_search_retrieval` | `web_search` | Устаревшая/retrieval-форма поиска по возможности сопоставляется с веб-поиском |
| `urlContext` / `url_context` | `url_content_extraction` | URL context сопоставляется с извлечением содержимого URL |
| `codeExecution` / `code_execution` | `code_interpreter` | Выполнение кода сопоставляется с интерпретатором |
| `functionDeclarations` / `function_declarations` | обёртка `functions` | Пользовательские функции, не встроенные инструменты |

Для запросов Gemini в каноническое поле GigaChat передаётся только объект
конфигурации из поддерживаемого ключа инструмента Gemini:

```json
{"googleSearch": {"indexes": ["web"]}}
```

превращается в:

```json
{"type": "web_search", "web_search": {"indexes": ["web"]}}
```

`toolConfig.functionCallingConfig` применяется только к объявлениям функций Gemini.
Он не форсирует, не фильтрует и не удаляет встроенные провайдерские инструменты.

## Не сопоставляется

Встроенные провайдерские инструменты остаются неподдерживаемыми, если GigaChat SDK не предоставляет
семантически эквивалентное поле `ChatTool`.

| Провайдер | Примеры без сопоставления | Поведение |
|---|---|---|
| OpenAI | `file_search`, `computer`, `computer_use_preview`, `mcp`, `tool_search`, `shell`, `local_shell`, `apply_patch`, freeform `custom` | Игнорируются или сохраняются только в диагностике совместимости в зависимости от маршрута |
| Anthropic | `tool_search*`, `memory*`, `bash*`, `text_editor*`, `advisor`, MCP tools, computer-use tools | Принимаются там, где это разрешено политикой совместимости, но не отправляются в GigaChat как исполняемые встроенные инструменты |
| Gemini | `fileSearch`, `googleMaps`, `computerUse`, `mcpServers`, `enterpriseWebSearch`, `parallelAiSearch`, Vertex/RAG/retrieval tools | Сохраняются в диагностике `unsupportedTools` и не применяются GigaChat |

Такой подход намеренно консервативный: похожих названий недостаточно для
сопоставления. Сопоставление появляется только тогда, когда в GigaChat SDK есть
исполняемое поле с тем же операционным смыслом.

## Чек-лист обновления

Когда SDK провайдера добавляет или переименовывает встроенные инструменты:

1. Проверить установленные SDK провайдера и модели GigaChat SDK.
2. Обновить `gpt2giga.common.tools.normalize_gigachat_builtin_tool_type`.
3. Для инструментов Gemini с ключами-объектами обновить `gpt2giga.protocols.gemini.adapter`.
4. Добавить тесты сборщика запросов и адаптера.
5. Обновить этот документ, а также `api-compatibility.md` и
   `client-parameter-compatibility.md`, если меняется публичное поведение.
