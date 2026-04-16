# Архитектура gpt2giga

Этот документ заменяет устаревшую ссылку на `ARCHITECTURE_v2.md` и описывает текущую структуру проекта на уровне, достаточном для feature-работы и рефакторинга.

## Ключевая идея

`gpt2giga` принимает OpenAI-, Anthropic- и Gemini-совместимые HTTP-запросы, нормализует их через feature-слой и отправляет в GigaChat API. Runtime собирается в FastAPI-приложение, а операторский control plane живет в `/admin` и связанных `/admin/api/*` endpoint-ах.

## Request flow

1. `gpt2giga/app/factory.py` создает FastAPI-приложение, подключает middleware и монтирует provider/router surface.
2. Входящий запрос попадает в provider-specific router:
   - `gpt2giga/api/openai/`
   - `gpt2giga/api/anthropic/`
   - `gpt2giga/api/gemini/`
3. Router проверяет auth/governance через зависимости и передает payload в feature-сервис из `gpt2giga/features/`.
4. Feature-сервис вызывает provider helper-ы из `gpt2giga/providers/gigachat/` для маппинга запроса в GigaChat-совместимый payload.
5. GigaChat client выполняет upstream-вызов.
6. Response processor и streaming helper-ы нормализуют ответ обратно в OpenAI-, Anthropic- или Gemini-совместимый формат.

## Provider mapping flow

### Chat и Responses

- Общая request-нормализация сосредоточена в:
  - `gpt2giga/providers/gigachat/request_mapper.py`
  - `gpt2giga/providers/gigachat/request_mapping_base.py`
  - `gpt2giga/providers/gigachat/chat_request_mapper.py`
  - `gpt2giga/providers/gigachat/responses/`
  - `gpt2giga/providers/gigachat/responses_request_mapper.py` как compatibility entrypoint
- Общая response-нормализация сосредоточена в:
  - `gpt2giga/providers/gigachat/response_mapper.py`
  - `gpt2giga/providers/gigachat/response_mapping_common.py`
  - `gpt2giga/providers/gigachat/responses/`
  - `gpt2giga/providers/gigachat/responses_response_mapper.py` как compatibility entrypoint
- Streaming для GigaChat и OpenAI-compatible SSE разделен между:
  - `gpt2giga/providers/gigachat/streaming.py`
  - `gpt2giga/features/chat/stream.py`
  - `gpt2giga/features/responses/stream.py`
  - `gpt2giga/api/openai/streaming.py`

### Chat flow

```text
api/openai/chat.py
-> features/chat/service.py
-> providers/gigachat/chat_mapper.py
-> providers/gigachat/request_mapper.py
-> GigaChat achat/astream или achat_v2/astream_v2
-> providers/gigachat/response_mapper.py
-> OpenAI-compatible chat response / SSE
```

- `gpt2giga/app/wiring.py` передает `chat_backend_mode` в `GigaChatChatMapper`.
- `gpt2giga/providers/gigachat/chat_mapper.py` выбирает backend path один раз:
  - `prepare_chat_completion(...)` для `v1`;
  - `prepare_chat_completion_v2(...)` для `v2`.
- `prepare_chat_completion(...)` остается legacy chat path:
  - применяет `transform_chat_parameters(...)`;
  - нормализует сообщения через `chat_request_mapper.py`;
  - завершает payload через `_finalize_transformation(...)`;
  - дальше `ChatService`/provider client вызывают `achat` или `astream`.
- `prepare_chat_completion_v2(...)` не строит отдельный параллельный chat-pipeline:
  - сначала приводит chat-like payload к Responses-style `input/tools/text` shape;
  - затем делегирует в `prepare_response_v2(...)`;
  - итоговый `ChatV2` payload собирается helper-ами из `gpt2giga/providers/gigachat/responses/`.
- На ответе `GigaChatChatMapper` так же скрывает backend split:
  - `process_response(...)` / `process_stream_chunk(...)` для `v1`;
  - `process_response_v2(...)` / `process_stream_chunk_v2(...)` через `normalize_chat_v2_*` для `v2`.

### Responses flow

```text
api/openai/responses.py
-> features/responses/service.py
-> providers/gigachat/request_mapper.py
-> providers/gigachat/responses/
-> GigaChat achat или achat_v2
-> providers/gigachat/response_mapper.py
-> OpenAI-compatible Responses payload / SSE
```

- `gpt2giga/app/wiring.py` передает `responses_backend_mode` в `ResponsesService`.
- `gpt2giga/features/responses/service.py` держит backend choice внутри feature-layer:
  - валидирует request context;
  - при необходимости восстанавливает `model` из `previous_response_id`;
  - выбирает `prepare_response(...)` или `prepare_response_v2(...)`.
- `prepare_response(...)` — legacy Responses path:
  - `transform_responses_parameters(...)` переносит canonical поля в chat-like payload;
  - `transform_response_format(...)` разворачивает `input` в legacy `messages`;
  - `_finalize_transformation(...)` применяет общую message normalization.
- `prepare_response_v2(...)` живет в `gpt2giga/providers/gigachat/responses/backend_request.py` и собирает native `ChatV2` payload через узкие mixin-модули:
  - `input_normalizer.py`
  - `model_options.py`
  - `threading.py`
  - `tool_mapping.py`
  - `backend_request.py`
- На execution path `ResponsesService` сам выбирает upstream method:
  - `giga_client.achat(...)` + `process_response_api(...)` для `v1`;
  - `giga_client.achat_v2(...)` + `process_response_api_v2(...)` для `v2`.
- Streaming path остается feature-owned:
  - orchestration и metadata-store handoff находятся в `gpt2giga/features/responses/stream.py`;
  - OpenAI-compatible SSE formatting остается в `gpt2giga/api/openai/streaming.py`.

### v1 и v2 backend path

- Режимы backend-а задаются конфигом:
  - `GPT2GIGA_GIGACHAT_API_MODE`
  - `chat_backend_mode`
  - `responses_backend_mode`
- `gpt2giga/app/wiring.py` связывает runtime с `RequestTransformer`, `ResponseProcessor`, `GigaChatChatMapper` и `ResponsesService`.
- Chat path и Responses path используют общие provider helper-ы, но развилки по v1/v2 скрыты внутри mapper/service слоя, а не в публичных router-ах.
- Практическое правило для contributors:
  - router и provider transport adapter не должны выбирать `achat` против `achat_v2`;
  - единственный internal source of truth для native Responses v2 helper-ов теперь находится в `gpt2giga/providers/gigachat/responses/`;
  - top-level модули `responses_*` сохранены как compatibility re-export layer для старых import path-ов.

### Models, embeddings, files, batches

- Более простые capability-level преобразования живут рядом:
  - `gpt2giga/providers/gigachat/embeddings_mapper.py`
  - `gpt2giga/providers/gigachat/models_mapper.py`
  - `gpt2giga/features/files/`
  - `gpt2giga/features/batches/`

## Runtime и control plane

### Runtime composition

- `gpt2giga/app/dependencies.py` создает typed container-ы в `app.state`:
  - `config`
  - `logger`
  - `services`
  - `stores`
  - `providers`
  - `observability`
- `gpt2giga/app/wiring.py` инициализирует GigaChat client, request/response mapper-ы и feature-сервисы.
- Runtime store backend и observability backend также провиженятся через typed container-ы, чтобы route-модули не собирали инфраструктуру вручную.

### Control plane

- Операторские HTML route-ы живут в `gpt2giga/api/admin/ui.py`.
- Операторские API и runtime snapshot endpoint-ы живут в `gpt2giga/api/admin/`, но сами route-модули теперь остаются thin HTTP layer.
- `gpt2giga/api/admin/settings.py` делегирует setup/settings/revisions/key-management flow в `gpt2giga/app/admin_settings.py`.
- `gpt2giga/api/admin/runtime.py` делегирует runtime/config/capabilities/usage payload building в `gpt2giga/app/admin_runtime.py`.
- Настройки и live mutation flow проходят через `gpt2giga/app/admin_settings.py` и `gpt2giga/core/config/control_plane.py`.
- Когда изменение безопасно для live-reload, `reload_runtime_services()` пересобирает runtime без полного рестарта процесса.
- Runtime snapshot service читает текущее состояние из `app.state.config`, runtime stores и observability state.

## Admin frontend

### Текущая структура

- Исходники operator UI находятся в `gpt2giga/frontend/admin/`.
- Runtime-ассеты и HTML shell лежат в optional package `packages/gpt2giga-ui/src/gpt2giga_ui/`.
- `gpt2giga/app/admin_ui.py` в source checkout предпочитает repo-local `packages/gpt2giga-ui/src/gpt2giga_ui/`, чтобы локальные template/CSS/admin asset правки не расходились с тем, что реально монтирует runtime.
- `gpt2giga/app/factory.py` монтирует `packages/gpt2giga-ui/src/gpt2giga_ui/static/` на `/admin/assets/*`.

### Как собирать

```bash
npm install
npm run build:admin
```

- TypeScript-конфиг в `tsconfig.json` использует:
  - `rootDir = gpt2giga/frontend`
  - `outDir = packages/gpt2giga-ui/src/gpt2giga_ui/static`
- Это означает, что `gpt2giga/frontend/admin/**/*.ts` компилируется в `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/**/*.js`.

### Нужно ли коммитить compiled admin assets

Да, в текущем release flow compiled admin assets внутри `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/*` должны оставаться в git.

Причина простая:

- `Dockerfile` копирует `gpt2giga/` и сразу вызывает `uv build`, без Node.js шага.
- `.github/workflows/publish-pypi.yml` отдельно собирает `packages/gpt2giga-ui`, тоже без `npm run build:admin`.
- `.github/workflows/docker_image.yaml` собирает образ напрямую из репозитория, без отдельной frontend-сборки.

Пока packaging/release pipeline не научится собирать admin frontend самостоятельно, каждое изменение в `gpt2giga/frontend/admin/` должно сопровождаться обновлением соответствующих файлов в `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/`.

Практическое правило для contributors:

1. Меняете `gpt2giga/frontend/admin/*`.
2. Запускаете `npm run build:admin`.
3. Коммитите и исходники, и обновленный output в `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/`.

## Куда смотреть дальше

- Общая документация: [README.md](../README.md)
- Навигация по docs: [README.md](./README.md)
- Runtime/config: [configuration.md](./configuration.md)
- Operator flow: [operator-guide.md](./operator-guide.md)
- API coverage: [api-compatibility.md](./api-compatibility.md)
