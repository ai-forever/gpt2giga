# How To Add A New Provider

Этот гайд описывает полный workflow добавления нового внешнего совместимого API provider-а в `gpt2giga` без обхода существующей архитектуры.

Под provider-ом в этом документе понимается не backend GigaChat, а внешний API surface, который должен выглядеть как другой продукт или SDK: OpenAI, Anthropic, Gemini или новый совместимый контракт.

Базовый scaffold лежит в [gpt2giga/providers/template_provider/README.md](../gpt2giga/providers/template_provider/README.md).

## Что в проекте считается provider-ом

Внутри `gpt2giga` есть два разных уровня интеграции:

1. Внешний provider surface.
   Это HTTP-совместимость с чьим-то API. Сейчас такими surface-ами являются:
   - `openai`
   - `anthropic`
   - `gemini`

2. Внутренний backend provider.
   Это реальный upstream, в который прокси в итоге ходит. В текущей архитектуре это `gpt2giga/providers/gigachat/`.

То есть при добавлении нового provider-а вы обычно не подключаете новый backend. Вы добавляете новый внешний контракт, который:

- принимает HTTP-запрос в формате нового API;
- нормализует его во внутренний canonical request;
- передает его в существующий feature-layer;
- получает ответ от GigaChat через уже существующие mapper/service слои;
- презентует результат обратно в формате нового API.

## Главный принцип архитектуры

Новый provider не должен пробивать shortcut напрямую из роутера в GigaChat.

Правильная цепочка выглядит так:

```text
HTTP request
-> gpt2giga/api/<provider>/*
-> provider request adapter / parser
-> gpt2giga/core/contracts/normalized.py
-> gpt2giga/features/<capability>/service.py
-> gpt2giga/providers/gigachat/*
-> GigaChat API
-> feature-layer result
-> provider response presenter / stream presenter
-> HTTP response
```

Если в новом коде router:

- сам выбирает backend `v1` или `v2`;
- сам собирает GigaChat payload;
- сам хранит метаданные files/batches/responses;
- сам решает auth/governance/mounting;

значит интеграция идет мимо архитектуры проекта.

## Где реально выбирается backend `v1`/`v2`

Для новых provider-ов важно держать в голове не только общую цепочку, но и конкретное место, где происходит backend split.

### Chat-like flow

```text
api/<provider>/*
-> build_normalized_request(...)
-> features/chat/service.py
-> providers/gigachat/chat_mapper.py
-> RequestTransformer.prepare_chat_completion(...) или prepare_chat_completion_v2(...)
-> GigaChat achat/astream или achat_v2/astream_v2
-> ResponseProcessor
-> provider response/stream presenter
```

- `features/chat/service.py` работает через `GigaChatChatMapper`, уже сконфигурированный в `gpt2giga/app/wiring.py`.
- `chat_mapper.py` получает `backend_mode` из runtime wiring и сам решает, какой prepare/process path использовать.
- `prepare_chat_completion_v2(...)` не должен вызываться из router напрямую. Он уже знает, как превратить chat-like payload в native `ChatV2` через structured helper-ы.

### Responses flow

```text
api/<provider>/*
-> build_normalized_request(...)
-> features/responses/service.py
-> RequestTransformer.prepare_response(...) или prepare_response_v2(...)
-> GigaChat achat или achat_v2
-> ResponseProcessor.process_response_api(...) или process_response_api_v2(...)
-> provider response/stream presenter
```

- `features/responses/service.py` получает `responses_backend_mode` тоже из `gpt2giga/app/wiring.py`.
- Именно service-layer, а не router, решает:
  - когда вызывать legacy Responses path;
  - когда собирать native `ChatV2`;
  - как использовать `previous_response_id` и response store для continuation flow.
- Internal source of truth для Responses v2 helper-ов теперь находится в `gpt2giga/providers/gigachat/responses/`.
- Плоские top-level модули вида `responses_request_mapper.py` и `responses_response_mapper.py` оставлены только как compatibility wrappers для старых import path-ов.

## Где проходит граница ответственности

### `gpt2giga/api/<provider>/`

Transport layer. Этот слой:

- читает HTTP request;
- делает provider-specific валидацию;
- преобразует payload в canonical request или в аргументы feature service;
- форматирует HTTP response;
- форматирует SSE stream, если provider поддерживает streaming.

Этот слой не должен содержать бизнес-оркестрацию GigaChat.

### `gpt2giga/providers/<provider>/`

Provider package с capability adapter-ами и descriptor-ом. Этот слой:

- описывает, какие capabilities provider реально поддерживает;
- экспортирует `ProviderAdapterBundle`;
- экспортирует `ProviderDescriptor`;
- связывает внешний provider surface с transport/router layer.

### `gpt2giga/features/*`

Feature-layer. Это центр orchestration по capability:

- `gpt2giga/features/chat/service.py`
- `gpt2giga/features/responses/service.py`
- `gpt2giga/features/embeddings/service.py`
- `gpt2giga/features/models/service.py`
- `gpt2giga/features/files/service.py`
- `gpt2giga/features/batches/service.py`

Сюда надо ходить из transport layer вместо прямого вызова backend helper-ов.

### `gpt2giga/providers/gigachat/*`

Backend-specific mapping и upstream client layer. Новый внешний provider обычно переиспользует этот код, а не дублирует его.

## Как устроены текущие built-in provider-ы

Их полезно рассматривать как три разных шаблона.

| Provider | Основной паттерн | Что смотреть |
|---|---|---|
| `openai` | Максимально canonical flow: transport строит `Normalized*Request` и вызывает feature service почти без дополнительной презентации | `gpt2giga/api/openai/chat.py`, `gpt2giga/api/openai/request_adapter.py`, `gpt2giga/providers/openai/capabilities.py` |
| `anthropic` | Свой request adapter и свой response/stream presentation поверх chat feature | `gpt2giga/api/anthropic/messages.py`, `gpt2giga/api/anthropic/request_adapter.py`, `gpt2giga/providers/anthropic/capabilities.py` |
| `gemini` | Несколько mount groups, отдельная auth policy, mix chat/embeddings/files/batches/models | `gpt2giga/api/gemini/content.py`, `gpt2giga/providers/gemini/capabilities.py` |

Практически это значит:

- если новый provider близок к OpenAI-compatible surface, обычно хватит canonical normalization + feature service;
- если новый provider требует особый wire format ответа или stream events, берите pattern Anthropic/Gemini: transport все еще использует feature service, но ответ строит отдельный presenter.

## Перед началом: определите scope интеграции

Не начинайте с копирования всех файлов подряд. Сначала ответьте на четыре вопроса:

1. Какие capability нужны на самом деле?
   Возможные capability adapter-ы описаны в `gpt2giga/providers/contracts.py`:
   - `ChatProviderAdapter`
   - `ResponsesProviderAdapter`
   - `EmbeddingsProviderAdapter`
   - `ModelsProviderAdapter`
   - `FilesProviderAdapter`
   - `BatchesProviderAdapter`

2. Достаточно ли canonical contracts?
   Если provider можно свести к `NormalizedChatRequest`, `NormalizedResponsesRequest` или `NormalizedEmbeddingsRequest`, интеграция будет проще и устойчивее.

3. Нужен ли отдельный response presenter?
   Если ответ можно отдать прямо из existing feature service, дополнительный presenter не нужен. Если внешний API требует другой shape, как у Anthropic/Gemini, presenter обязателен.

4. Нужен ли особый auth policy?
   Сейчас `ProviderRouteAuthPolicy` в `gpt2giga/providers/descriptors.py` поддерживает:
   - `default`
   - `gemini`

   Если новому provider нужен нестандартный заголовок, query param или другой error style, придется расширить auth/governance wiring.

## Минимальный file layout

Обычно новый provider добавляет как минимум такие файлы:

```text
gpt2giga/providers/<provider>/
├── __init__.py
└── capabilities.py

gpt2giga/api/<provider>/
├── __init__.py
├── request_adapter.py
├── openapi.py                  # если нужны provider-specific request/response schemas
├── <route_module>.py
├── response.py                 # если нужен custom response presenter
└── streaming.py                # если нужен custom SSE presenter
```

Иногда layout будет шире:

- несколько route modules для разных capabilities;
- отдельные helpers для provider-specific validation;
- отдельный upload router или special mount group, как у Gemini.

## Пошаговый workflow

### Шаг 1. Скопируйте scaffold

Возьмите за основу:

```text
gpt2giga/providers/template_provider/
```

и создайте новый пакет:

```text
gpt2giga/providers/<provider>/
```

Шаблон минимален специально. Он не пытается навязать лишние capabilities, а только задает ожидаемую форму:

- `capabilities.py`
- request/response/stream adapter ideas
- bundle registration

Важно: scaffold лежит в `providers`, а не в `api`, потому что он описывает capability bundle и descriptor, а не transport routes.

### Шаг 2. Создайте provider package

Минимальный `__init__.py` обычно просто реэкспортирует публичные точки входа:

```python
from gpt2giga.providers.<provider>.capabilities import (
    <PROVIDER>_PROVIDER_DESCRIPTOR,
    <provider>_provider_adapters,
)

__all__ = ["<PROVIDER>_PROVIDER_DESCRIPTOR", "<provider>_provider_adapters"]
```

В `capabilities.py` вы:

- объявляете adapter classes;
- собираете `ProviderAdapterBundle`;
- описываете mount specs;
- создаете `ProviderDescriptor`.

Смотрите референсы:

- `gpt2giga/providers/openai/capabilities.py`
- `gpt2giga/providers/anthropic/capabilities.py`
- `gpt2giga/providers/gemini/capabilities.py`

### Шаг 3. Реализуйте только реальные capabilities

Не публикуйте capability “на будущее”.

Хорошее правило:

- если provider поддерживает только chat и models, bundle должен содержать только `chat` и `models`;
- если files/batches/embeddings в контракте нет, не добавляйте stub handlers;
- отсутствие capability лучше, чем наполовину рабочий endpoint.

Пример структуры bundle:

```python
provider_adapters = ProviderAdapterBundle(
    chat=MyProviderChatAdapter(),
    models=MyProviderModelsAdapter(),
)
```

Если capability нет, оставьте поле `None`.

### Шаг 4. Создайте transport layer в `gpt2giga/api/<provider>/`

Это самый важный слой для нового внешнего API.

Обычно там нужны:

- `__init__.py` с lazy router export;
- один или несколько route modules;
- `request_adapter.py`;
- `openapi.py`, если нужен provider-specific schema fragment;
- `response.py` и/или `streaming.py`, если внешний контракт не совпадает с internal/OpenAI shape.

### Как выглядит `__init__.py`

У built-in provider-ов router package строится лениво. Например:

- `gpt2giga/api/openai/__init__.py`
- `gpt2giga/api/anthropic/__init__.py`
- `gpt2giga/api/gemini/__init__.py`

Паттерн один и тот же:

- `_build_router()` создает `APIRouter`;
- импортирует route modules локально;
- делает `include_router(...)`;
- экспортирует `router` через `__getattr__`.

Это полезно, чтобы избежать лишних импортных циклов и ранней инициализации.

### Чего transport layer делать не должен

В transport layer не нужно:

- вручную выбирать `achat` против `achat_v2`;
- вручную вызывать `prepare_chat_completion_v2(...)` или `prepare_response_v2(...)`;
- собирать GigaChat request body напрямую;
- создавать ad-hoc metadata storage;
- реализовывать auth policy вручную;
- монтировать роуты через `app.factory` напрямую.

Все это уже централизовано в других слоях.

### Шаг 5. Нормализуйте вход в canonical contracts

Если capability относится к chat/responses/embeddings, первым выбором должны быть canonical модели из `gpt2giga/core/contracts/normalized.py`:

- `NormalizedChatRequest`
- `NormalizedResponsesRequest`
- `NormalizedEmbeddingsRequest`
- `NormalizedMessage`
- `NormalizedTool`
- `NormalizedStreamEvent`

### Почему это важно

Эти модели задают стабильную границу между transport layer и feature layer.

Если новый provider приводит вход к canonical contract, то:

- feature service можно переиспользовать без provider-specific ветвления;
- backend mapping живет в одном месте;
- проще покрывать тестами request normalization отдельно от HTTP;
- меньше риск расхождения с `v1`/`v2` backend режимами.

### Как это выглядит на практике

Canonical flow:

```text
HTTP body
-> api/<provider>/request_adapter.py
-> Normalized*Request
-> features/<capability>/service.py
```

Хороший референс для этого паттерна:

- `gpt2giga/api/openai/request_adapter.py`

В нем видно полезные приемы:

- `deepcopy(...)`, чтобы не мутировать вход;
- явное вынимание canonical полей (`model`, `messages`, `input`, `stream`);
- сохранение остатка payload в `options`;
- преобразование tools/functions в `NormalizedTool`.

### Что класть в `options`

В `options` нужно сохранять provider-specific поля, которые:

- не являются canonical полями;
- все равно нужны downstream mapper-у или response shaper-у.

Не теряйте эти поля, если они нужны для backend transformation или response presentation.

### Шаг 6. Выберите один из двух execution patterns

В текущем проекте реально используются два шаблона исполнения.

### Паттерн A. Чистый canonical flow

Подходит, если внешний provider достаточно близок к internal/OpenAI shape.

Router делает примерно следующее:

1. читает JSON;
2. вызывает `<provider>_provider_adapters.<capability>.build_normalized_request(...)`;
3. вызывает feature service;
4. возвращает результат feature service напрямую или почти напрямую.

Пример:

- `gpt2giga/api/openai/chat.py`

Там маршрут:

- читает payload через `read_request_json`;
- строит `NormalizedChatRequest`;
- вызывает `chat_service.create_completion(...)` или `chat_service.stream_completion(...)`.

### Паттерн B. Canonical request + custom presentation

Подходит, если:

- внешний ответ сильно отличается от OpenAI-style result;
- stream event format у provider-а свой;
- нужны provider-specific envelope, delta events, token stats, stop reasons.

Тогда router:

1. строит normalized request;
2. использует feature service для prepare/execute;
3. преобразует normalized/raw result отдельным presenter-ом;
4. для streaming использует отдельный stream generator/presenter.

Примеры:

- `gpt2giga/api/anthropic/messages.py`
- `gpt2giga/api/gemini/content.py`

У Anthropic/Gemini transport layer не идет напрямую в `create_completion(...)`, потому что им нужен свой response wire format. Но они все равно переиспользуют `ChatService`.

### Шаг 7. Переиспользуйте feature services, а не backend helper-ы

Ниже краткая карта того, куда должен идти transport layer.

### Chat

Используйте:

- `gpt2giga/features/chat/service.py`

Основные методы:

- `prepare_request(...)`
- `execute_prepared_request(...)`
- `create_completion(...)`
- `stream_completion(...)`

Когда что использовать:

- если response shape совпадает с existing chat mapper output, берите `create_completion(...)` и `stream_completion(...)`;
- если provider хочет свой response envelope, используйте `prepare_request(...)` + `execute_prepared_request(...)` и строите provider response сами.

### Responses

Используйте:

- `gpt2giga/features/responses/service.py`

Основные методы:

- `create_response(...)`
- `stream_response(...)`
- `prepare_request(...)`

Особенности:

- service уже знает про `v1`/`v2` backend split;
- service уже знает про `response_store`;
- service уже валидирует request context для `model`, `conversation.id`, `previous_response_id`.

Не дублируйте эту логику в transport layer.

### Embeddings

Используйте:

- `gpt2giga/features/embeddings/service.py`

Обычно flow простой:

1. собрать `NormalizedEmbeddingsRequest`;
2. вызвать `embeddings_service.create_embeddings(...)`;
3. отформатировать ответ в shape внешнего provider-а.

### Models

Используйте:

- `gpt2giga/features/models/service.py`

Типичный flow:

1. получить internal `ModelDescriptor` или список descriptor-ов;
2. сериализовать их через `provider_adapters.models.serialize_model(...)`.

Это хорошая граница ответственности:

- feature service знает, как получить внутренние дескрипторы;
- provider adapter знает, как представить их наружу.

### Files

Используйте:

- `gpt2giga/features/files/service.py`

Типичный flow:

1. transport читает multipart/form-data;
2. `provider_adapters.files.extract_create_file_args(...)` извлекает `purpose` и upload;
3. `FilesService.create_file(...)` делает upload и пишет metadata;
4. transport отдает provider-specific response.

Не храните file metadata самостоятельно.

### Batches

Используйте:

- `gpt2giga/features/batches/service.py`

Возможные варианты:

- провайдер уже дает OpenAI-style batch create payload: можно отдавать его в `create_batch(...)`;
- провайдер требует свой normalization step: делайте его в `provider_adapters.batches.build_create_payload(...)`, а дальше используйте `create_batch_from_rows(...)` или `create_batch(...)`.

Anthropic batch adapter в `gpt2giga/providers/anthropic/capabilities.py` полезен как пример более сложной нормализации.

### Шаг 8. Реализуйте provider adapters в `capabilities.py`

`gpt2giga/providers/contracts.py` задает протоколы adapter-ов.

Ниже их практический смысл.

### `ChatProviderAdapter`

Нужен, когда provider публикует chat-like endpoint.

Обычно должен уметь:

- `build_normalized_request(payload, logger=None) -> NormalizedChatRequest`

Иногда provider-specific adapter может содержать и вспомогательные методы, если route layer использует их напрямую. Например:

- Anthropic chat adapter умеет `build_token_count_texts(...)`;
- Gemini chat adapter умеет `build_count_tokens_texts(...)`.

Это допустимо, если метод относится к этому provider surface и не ломает базовую архитектуру.

### `ResponsesProviderAdapter`

Нужен для routes, совместимых с Responses API.

Минимально:

- `build_normalized_request(...) -> NormalizedResponsesRequest`

### `EmbeddingsProviderAdapter`

Нужен для embeddings-like routes.

Минимально:

- `build_normalized_request(...) -> NormalizedEmbeddingsRequest`

Provider может добавлять дополнительные helper-методы, если у него несколько embeddings surfaces. Gemini это делает через:

- `build_batch_request(...)`
- `build_single_request(...)`

### `ModelsProviderAdapter`

Нужен для model discovery.

Минимально:

- `serialize_model(model: ModelDescriptor) -> Any`

### `FilesProviderAdapter`

Нужен для multipart/file-specific transport parsing.

Минимально:

- `extract_create_file_args(multipart) -> tuple[str, Any]`

### `BatchesProviderAdapter`

Нужен для batch create normalization.

Минимально:

- `build_create_payload(payload, logger=None) -> Any`

Возвращаемый тип может быть:

- обычный `dict`;
- dataclass;
- provider-specific typed object.

Главное, чтобы route layer потом явно и прозрачно передавал эти данные в `BatchesService`.

### Шаг 9. Опишите `ProviderDescriptor`

`ProviderDescriptor` объявлен в `gpt2giga/providers/descriptors.py`.

Он содержит:

- `name`
- `display_name`
- `capabilities`
- `routes`
- `mounts`
- `adapters`

Это не просто декоративная метаинформация. Descriptor используется как источник правды для:

- router mounting в `gpt2giga/app/factory.py`;
- `/admin/api/capabilities` в `gpt2giga/api/admin/runtime.py`;
- provider gating через `GPT2GIGA_ENABLED_PROVIDERS`;
- отображения surface area в operator/admin tooling.

### Как проектирует mounts

Каждый `ProviderMountSpec` описывает:

- `router_factory`
- `prefix`
- `tags`
- `auth_policy`

Используйте несколько mounts, если provider публикуется в нескольких route groups.

Примеры:

- OpenAI публикуется и без префикса, и под `/v1`, плюс отдельный LiteLLM router;
- Gemini публикуется под `/v1beta` и отдельно под `/upload/v1beta`.

Не добавляйте special-case код в `app/factory.py`, если задачу можно решить несколькими `ProviderMountSpec`.

### Как заполнять `capabilities`

Поле `capabilities` должно отражать user-facing capability names, которые вы хотите показывать в admin/runtime surfaces.

Это не обязано быть именем Python interface. Примеры из текущих provider-ов:

- OpenAI: `chat_completions`, `responses`, `embeddings`, `files`
- Anthropic: `messages`, `count_tokens`, `message_batches`
- Gemini: `generate_content`, `stream_generate_content`, `batch_embed_contents`

То есть это operator-facing vocabulary, а не strict internal enum.

### Как заполнять `routes`

Указывайте фактически публикуемые path patterns.

Это влияет на:

- `/admin/api/capabilities`;
- диагностику активного surface area;
- операторское понимание того, что реально включено.

Если есть префиксированная и непрефиксированная версии, перечисляйте обе.

### Шаг 10. Зарегистрируйте provider в registry

В `gpt2giga/providers/registry.py` новый descriptor должен попасть в bootstrap:

```python
from gpt2giga.providers.<provider> import <PROVIDER>_PROVIDER_DESCRIPTOR
```

и затем в список built-in provider-ов.

Но этого недостаточно.

Если provider должен быть полноценной частью конфигурации и governance surface, обычно нужно обновить еще несколько мест.

### Шаг 11. Добавьте provider в конфигурационные enum-ы и surface metadata

### `gpt2giga/core/config/settings.py`

Здесь придется обновить:

- `ProviderName`
- `_ALL_ENABLED_PROVIDERS`
- описания, где перечислены поддерживаемые provider-ы

Это важно для:

- `GPT2GIGA_ENABLED_PROVIDERS`
- scoped API keys
- governance rules
- Pydantic validation

Если этого не сделать, новый provider не сможет корректно участвовать в config validation.

### `gpt2giga/api/tags.py`

Если provider должен красиво отображаться в OpenAPI, обычно нужно обновить:

- `PROVIDER_<NAME>`
- `_PROVIDER_ORDER`
- `_PROVIDER_KEYS`
- `_PROVIDER_CAPABILITY_DESCRIPTIONS`
- `_TAG_PROVIDER_ALIASES`, если нужно

Иначе OpenAPI tags либо не появятся, либо будут неполными.

### `gpt2giga/api/admin/runtime.py`

Обычно отдельной ручной регистрации не нужно, потому что admin берет данные из registry. Но после добавления descriptor-а нужно проверить, что:

- provider виден в `/admin/api/capabilities`;
- `display_name`, `capabilities` и `routes` выглядят корректно.

### Шаг 12. Проверьте provider gating

Provider должен корректно участвовать в `GPT2GIGA_ENABLED_PROVIDERS`.

Ожидаемое поведение:

- включенный provider монтируется;
- выключенный provider не попадает в app routes;
- OpenAPI schema не показывает его теги и endpoints;
- `/admin/api/capabilities` отражает `enabled=false`;
- scoped API keys и governance rules могут ссылаться на него по имени.

Текущее монтирование делается через `iter_enabled_provider_descriptors(...)` в `gpt2giga/app/factory.py`.

Если новый provider требует обхода этого механизма, это почти наверняка архитектурный smell.

### Шаг 13. Если нужен новый top-level path root, обновите path normalization

`PathNormalizationMiddleware` в `gpt2giga/app/factory.py` получает фиксированный список `valid_roots`.

Сейчас там перечислены, например:

- `v1`
- `v1beta`
- `chat`
- `models`
- `responses`
- `messages`
- `files`
- `batches`
- `upload`

Если новый provider публикует route group с новым top-level сегментом, которого нет в этом списке, придется обновить `valid_roots`, иначе path rewrite middleware может не распознавать этот root.

Пример вопроса, который нужно себе задать:

- provider использует уже существующие корни вроде `/v1/...` или `/models/...`?
- или он требует новый root вроде `/fooapi/...`?

Во втором случае path normalization нужно расширить.

### Шаг 14. Если нужен новый auth style, расширьте auth/governance wiring

Сейчас `ProviderRouteAuthPolicy` поддерживает два режима:

- `default`
- `gemini`

Они используются в `gpt2giga/app/factory.py`, который строит:

- `build_api_key_verifier(...)`
- `build_governance_verifier(...)`

Если у нового provider-а:

- другой заголовок API key;
- другой query param;
- другой error format для auth/governance;

придется обновить как минимум:

- `gpt2giga/providers/descriptors.py`
- `gpt2giga/api/dependencies/auth.py`
- `gpt2giga/api/dependencies/governance.py`
- возможно, exception handling / response helpers

Не пишите кастомную auth-проверку прямо в route handler, если проблему можно решить расширением общего wiring.

### Шаг 15. Решите, нужен ли provider-specific OpenAPI

Если новый provider имитирует внешнее API достаточно близко и вы хотите, чтобы `/docs` выглядел убедительно, добавьте `openapi.py` рядом с transport routes.

Референсы:

- `gpt2giga/api/openai/openapi.py`
- `gpt2giga/api/anthropic/openapi.py`
- `gpt2giga/api/gemini/openapi.py`

Обычно это нужно, когда:

- тело запроса не совпадает с internal schema;
- response schema у provider-а сильно специфична;
- route использует `openapi_extra=...`.

### Шаг 16. Добавьте тесты

Минимальный набор тестов для нового provider-а:

- unit tests для request adapter-а;
- unit tests для response presenter-а, если он есть;
- unit tests для stream formatter-а, если есть streaming;
- route/integration tests на реальные FastAPI endpoints;
- registry/mount tests, если есть несколько prefixes или special auth policy;
- compatibility fixtures в `tests/compat/<provider>/`, если provider приносит новый внешний wire contract.

### Что особенно важно тестировать

#### Request normalization

Проверяйте:

- обязательные поля;
- дефолты;
- перенос provider-specific полей в `options`;
- преобразование tools/messages/input;
- validation errors на плохом payload.

#### Streaming

Проверяйте:

- порядок SSE events;
- формат `data:` lines;
- завершение stream;
- обработку upstream exceptions;
- различия между пустыми delta и финальными event-ами.

#### Backend mode

Если новый provider chat-like или responses-like, проверьте поведение с backend режимами, когда это применимо:

- `gigachat_api_mode=v1`
- `gigachat_api_mode=v2`

Важно не дублировать выбор режима в transport layer, а проверить, что provider корректно работает через feature service.

#### Gating

Проверяйте:

- provider присутствует при включении;
- provider отсутствует при отключении;
- OpenAPI/admin surfaces не показывают его как включенный, когда он выключен.

### Шаг 17. Обновите документацию и examples

После добавления provider-а обычно нужно обновить:

- `README.md`, если provider user-facing;
- `docs/api-compatibility.md`;
- `docs/configuration.md`, если появились новые switches или новый provider name;
- `docs/operator-guide.md`, если provider влияет на mounting/auth/governance;
- `examples/`, если у provider есть пользовательский сценарий;
- `docs/README.md`, если появился новый заметный документ.

Если provider пока internal-only и не готов для публичного surface, это нужно явно отразить в docs, а не оставлять полудокументированным.

## Практический decision guide

### Когда достаточно только `request_adapter.py` и route module

Если provider:

- принимает почти OpenAI-like body;
- может быть сведен к `Normalized*Request`;
- возвращает shape, который можно получить из feature service без глубокой переработки;

то обычно достаточно:

- `request_adapter.py`
- route module
- `capabilities.py`
- descriptor registration

### Когда обязательно нужен `response.py`

Если provider:

- использует другой envelope;
- хочет другие поля usage/finish_reason/stop_reason;
- требует другую сериализацию model ids;
- требует другой shape для tool calls или content blocks;

тогда добавляйте отдельный presenter.

### Когда обязательно нужен `streaming.py`

Если provider:

- не использует OpenAI-style chat SSE;
- требует provider-specific event types;
- требует provider-specific heartbeat/final chunk structure;

тогда выносите стриминг в отдельный модуль.

### Когда нужен отдельный upload router или extra mount

Если provider:

- публикует upload routes в отдельном namespace;
- использует несколько base prefixes;
- требует отдельную auth policy на subset маршрутов;

используйте несколько `ProviderMountSpec`, как это сделано у Gemini.

## Частые ошибки

### Ошибка 1. Прямой вызов GigaChat из transport route

Плохо, потому что:

- теряется единая оркестрация;
- сложнее поддерживать `v1`/`v2`;
- ломается единый путь observability и metadata handling;
- логика дублируется между provider-ами.

### Ошибка 2. Роутер сам решает backend mode

Выбор `achat`/`achat_v2` уже инкапсулирован в feature-layer и mapper-ах. Роутер не должен знать эту деталь, кроме случаев, когда он передает `api_mode` в provider-specific stream presenter для форматирования потока.

### Ошибка 3. Смешивание request normalization и response presentation

Хорошее правило:

- `request_adapter.py` переводит вход в canonical/internal representation;
- `response.py` или `streaming.py` переводит выход наружу.

Если оба направления смешаны в одной функции route handler-а, код быстро становится нерасширяемым.

### Ошибка 4. Stub capability “на будущее”

Если endpoint не готов, не публикуйте его descriptor-ом и не добавляйте в OpenAPI/routes list.

### Ошибка 5. Обновлен registry, но не обновлены config enum-ы

Это одна из самых частых ловушек. Provider может казаться “подключенным”, но:

- не проходить validation в `enabled_providers`;
- не работать в scoped API keys;
- не отображаться как допустимый provider в governance rules.

### Ошибка 6. Добавлен новый root path, но не обновлен path normalization

Результат обычно выглядит как “route вроде есть, но некоторые клиенты с префиксами попадают мимо нужного path”.

## Рекомендуемый checklist перед PR

- создан `gpt2giga/providers/<provider>/` с `capabilities.py` и публичным `__init__.py`;
- создан `gpt2giga/api/<provider>/` с lazy router export;
- transport layer остается thin;
- request normalization сведена к canonical contracts везде, где это возможно;
- feature services переиспользуются вместо прямых backend вызовов;
- `ProviderDescriptor` зарегистрирован;
- `ProviderName` и `_ALL_ENABLED_PROVIDERS` обновлены;
- OpenAPI tags metadata обновлена;
- provider корректно участвует в `GPT2GIGA_ENABLED_PROVIDERS`;
- `/admin/api/capabilities` показывает provider корректно;
- streaming покрыт отдельными тестами, если он есть;
- `v1`/`v2` режимы проверены там, где это применимо;
- docs и examples обновлены.

## Сверхкраткий шаблон мышления

Если нужно запомнить только одно правило, запоминайте это:

1. Новый provider принимает свой HTTP формат.
2. Как можно раньше превращает его во внутренний canonical contract.
3. Как можно дольше переиспользует existing feature services.
4. Только на границах делает provider-specific request parsing и response presentation.

Именно так новый surface добавляется в `gpt2giga` без архитектурного долга.
