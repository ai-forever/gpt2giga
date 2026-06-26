# Compatibility Doctor

Compatibility Doctor — это защищённый диагностический эндпоинт, который
объясняет, как `gpt2giga` интерпретирует клиентский запрос до его выполнения.

Он предназначен для поддержки, локальной отладки, будущих UI-панелей и
регрессионных фикстур. Он не вызывает GigaChat, не запускает инструменты и не
возвращает сырые prompts, responses, значения заголовков, query-параметров или
секреты.

## Включение эндпоинта

Эндпоинт входит в Admin API и по умолчанию отключён:

```dotenv
GPT2GIGA_ADMIN_API_ENABLED=True
GPT2GIGA_ADMIN_API_KEY="<strong-admin-secret>"
```

Запустите прокси обычным способом:

```bash
uv run gpt2giga
```

Диагностические запросы отправляются сюда:

```http
POST /_admin/compat/analyze
x-admin-api-key: <strong-admin-secret>
content-type: application/json
```

Для admin-доступа также принимается `Authorization: Bearer <strong-admin-secret>`.
Используйте отдельный admin key, а не публичный API key прокси.

## Envelope запроса

Анализатор получает envelope вокруг запроса, который нужно проверить:

```json
{
  "protocol": "openai",
  "route": "/v2/chat/completions",
  "headers": {},
  "query": {},
  "body": {}
}
```

Поля:

| Поле | Обязательно | Значение |
|---|---:|---|
| `route` | да | Публичный route, который вызвал бы настоящий клиент, включая `/v1`, `/v2` или `/v1beta`, если они важны. |
| `protocol` | нет | Одно из `openai`, `anthropic`, `gemini`, `litellm`, `system` или `unknown`. Если поле не задано, анализатор по возможности выводит протокол из route и клиентских headers. |
| `headers` | нет | Headers клиентского запроса. Чувствительные имена headers возвращаются как redacted; значения не возвращаются. |
| `query` | нет | Query-параметры клиентского запроса. Чувствительные ключи, например `key`, возвращаются как redacted; значения не возвращаются. |
| `body` | нет | JSON body запроса. Анализатор классифицирует имена полей и объявления tools; сырой prompt/response content не возвращается. |

## Пример OpenAI

```bash
ADMIN_HEADER_NAME=x-admin-api-key
curl -sS http://localhost:8090/_admin/compat/analyze \
  -H 'content-type: application/json' \
  -H "${ADMIN_HEADER_NAME}: ${GPT2GIGA_ADMIN_API_KEY:?set GPT2GIGA_ADMIN_API_KEY}" \
  -d '{
    "protocol": "openai",
    "route": "/v2/chat/completions",
    "headers": {
      "authorization": "Bearer client-key",
      "x-request-id": "req-1"
    },
    "query": {
      "key": "query-key"
    },
    "body": {
      "model": "gpt-4o",
      "messages": [{"role": "user", "content": "redacted by diagnostics"}],
      "temperature": 0.2,
      "seed": 123,
      "tools": [
        {
          "type": "function",
          "function": {
            "name": "search_docs",
            "parameters": {"type": "object"}
          }
        },
        {"type": "web_search_preview"},
        {"type": "file_search"}
      ]
    }
  }'
```

Сокращённая форма ответа:

```json
{
  "protocol": "openai",
  "route": "/v2/chat/completions",
  "operation": "chat_completions",
  "backend_mode": "gigachat_v2",
  "model": {
    "requested": "gpt-4o",
    "effective": "gpt-4o",
    "pass_model": true,
    "source": "request.model"
  },
  "fields": {
    "supported": ["messages", "model", "temperature", "tools"],
    "accepted_ignored": ["seed"],
    "accepted_diagnostic_only": [],
    "approximated": [],
    "rejected": []
  },
  "tools": {
    "user_functions": ["search_docs"],
    "mapped_builtin_tools": [
      {
        "from": "web_search_preview",
        "to": "web_search",
        "reason": "provider_alias"
      }
    ],
    "unsupported_tools": ["file_search"],
    "accepted_ignored": [],
    "rejected": [],
    "details": [
      {
        "source": "openai.tools",
        "category": "provider_builtin",
        "decision": "unsupported",
        "name": "file_search",
        "reason": "unsupported_tool_type",
        "field": "tools[2].type"
      }
    ]
  },
  "security": {
    "headers_redacted": ["authorization"],
    "query_redacted": ["key"],
    "body_fields_redacted": []
  },
  "warnings": [
    {
      "code": "accepted_ignored_field",
      "message": "`seed` is accepted for compatibility but ignored.",
      "severity": "warning",
      "field": "seed"
    },
    {
      "code": "unsupported_tool",
      "message": "`file_search` is accepted for diagnostics but is not executable by the current backend.",
      "severity": "warning",
      "field": "tools"
    }
  ]
}
```

Точный порядок полей и warnings может меняться по мере развития политик
совместимости, но значения, похожие на содержимое запроса или credentials, не
должны появляться в ответе.

## Пример Anthropic

```bash
ADMIN_HEADER_NAME=x-admin-api-key
curl -sS http://localhost:8090/_admin/compat/analyze \
  -H 'content-type: application/json' \
  -H "${ADMIN_HEADER_NAME}: ${GPT2GIGA_ADMIN_API_KEY:?set GPT2GIGA_ADMIN_API_KEY}" \
  -d '{
    "protocol": "anthropic",
    "route": "/v2/messages",
    "headers": {
      "anthropic-version": "2023-06-01"
    },
    "body": {
      "model": "claude-3-5-sonnet-latest",
      "max_tokens": 256,
      "messages": [{"role": "user", "content": "redacted by diagnostics"}],
      "tools": [
        {"type": "custom", "name": "lookup"},
        {"type": "web_search_20250305", "name": "web_search"}
      ],
      "tool_choice": {"type": "tool", "name": "web_search"}
    }
  }'
```

Ответ объясняет поддержанные поля Messages, provider tool aliases, поддержку
forced tool-choice для выбранного backend mode и игнорируемые поля совместимости
Anthropic.

## Пример Gemini

```bash
ADMIN_HEADER_NAME=x-admin-api-key
curl -sS http://localhost:8090/_admin/compat/analyze \
  -H 'content-type: application/json' \
  -H "${ADMIN_HEADER_NAME}: ${GPT2GIGA_ADMIN_API_KEY:?set GPT2GIGA_ADMIN_API_KEY}" \
  -d '{
    "route": "/v1beta/models/gemini-pro:streamGenerateContent?key=client-key",
    "query": {
      "key": "client-key"
    },
    "body": {
      "contents": [{"parts": [{"text": "redacted by diagnostics"}]}],
      "generationConfig": {"temperature": 0},
      "safetySettings": [{"category": "HARM_CATEGORY_DANGEROUS_CONTENT"}],
      "tools": [
        {"googleSearch": {}},
        {
          "functionDeclarations": [
            {
              "name": "search_docs",
              "parametersJsonSchema": {"type": "object"}
            }
          ]
        },
        {"fileSearch": {}}
      ],
      "toolConfig": {
        "functionCallingConfig": {
          "mode": "ANY",
          "allowedFunctionNames": ["search_docs"]
        }
      }
    }
  }'
```

Анализатор определяет протокол Gemini по route, сообщает effective model из
`models/{model}:operation`, редактирует `key` и отделяет function declarations
от provider tools Gemini, например `googleSearch`, и неподдерживаемых
diagnostic-only tools, например `fileSearch`.

## Поля ответа

| Поле | Значение |
|---|---|
| `protocol` | Обнаруженное или переданное семейство протокола. |
| `route` | Route после базовой проверки request envelope. |
| `operation` | Внутреннее имя операции, например `chat_completions`, `responses`, `messages`, `generate_content`, `stream_generate_content`, `embed_content` или `model_info`. |
| `backend_mode` | `gigachat_v1`, `gigachat_v2` или `unknown`, на основе route prefix и `GPT2GIGA_GIGACHAT_API_MODE`. |
| `model` | Requested/effective model и активность passthrough request model. |
| `fields.supported` | Поля, влияющие на выполнение или поведение ответа. |
| `fields.accepted_ignored` | Известные поля совместимости, которые gateway принимает, но не отправляет upstream как исполняемые настройки GigaChat. |
| `fields.accepted_diagnostic_only` | Поля, сохранённые только для диагностики, summaries наблюдаемости или будущего UI-объяснения. |
| `fields.approximated` | Поля, реализованные приближением, а не точной provider-семантикой. |
| `fields.rejected` | Поля или формы, которые текущий анализатор классифицирует как неисполняемые. |
| `tools.user_functions` | Имена пользовательских functions/tools. |
| `tools.mapped_builtin_tools` | Provider built-in aliases, сопоставленные с именами встроенных инструментов GigaChat v2. |
| `tools.unsupported_tools` | Tools, принятые только как diagnostics совместимости и не отправленные как executable built-ins. |
| `tools.details` | Решения по каждому tool: source, category, decision, target, reason и field path, если доступно. |
| `tools.mapping_disabled` | Повлияло ли `GPT2GIGA_DISABLE_BUILTIN_TOOL_MAPPING=True` на built-in tool mapping. |
| `tools.forced_tool_choice_supported` | Можно ли выразить запрошенный forced tool choice для текущего backend и формы tools. |
| `security` | Имена headers, query keys и body field paths, отредактированные в diagnostics. |
| `warnings` | Машиночитаемые warnings совместимости с `code`, `message`, `severity` и необязательным `field`. |

## Покрытые операции

Текущий анализатор покрывает:

- OpenAI Chat Completions, Responses, Embeddings, Models и LiteLLM
  `/model/info`;
- Anthropic Messages, Count Tokens и model discovery;
- Gemini GenerateContent, StreamGenerateContent, CountTokens, EmbedContent,
  BatchEmbedContents и model discovery;
- классификацию system routes, где применимо.

OpenAI Files/Batches, Anthropic Message Batches и Gemini Files/Batches остаются
вне поддерживаемой release surface. Они могут выглядеть как unrecognized или
diagnostic-only shapes, пока не появится сквозное выполнение.

## Security notes

- Эндпоинт отключён, если не задано `GPT2GIGA_ADMIN_API_ENABLED=True`.
- Эндпоинт требует admin key, а не публичный proxy key.
- Анализатор не вызывает upstream GigaChat client.
- Чувствительные headers и query keys возвращаются только по имени.
- Secret-like body paths возвращаются только как paths.
- Prompt и response content не echo'ятся.
- Эндпоинт предназначен для diagnostics; он не доказывает, что live upstream
  request успешно выполнится.

Более широкая матрица routes описана в [Совместимости API](api-compatibility.md).
Политика на уровне параметров описана в
[Совместимости параметров клиентов](client-parameter-compatibility.md).
