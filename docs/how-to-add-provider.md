# How To Add A New Provider

Этот гайд описывает, как подключить новый внешний совместимый API provider к `gpt2giga` без обхода существующей архитектуры.

Базовый шаблон лежит в [gpt2giga/providers/template_provider/README.md](../gpt2giga/providers/template_provider/README.md).

## Что считать provider-ом

Provider в этом проекте — это внешний API surface, совместимый с каким-то клиентом или SDK.

Примеры текущих provider-ов:

- `openai`
- `anthropic`
- `gemini`

GigaChat provider-ом в этом смысле не считается. Это backend, живущий в `gpt2giga/providers/gigachat/`.

## Минимальная схема добавления

1. Создайте пакет `gpt2giga/providers/<provider>/`.
2. Создайте transport layer в `gpt2giga/api/<provider>/`.
3. Зарегистрируйте `ProviderDescriptor` в `gpt2giga/providers/registry.py`.
4. Добавьте tests и docs.

## Шаг 1. Скопируйте scaffold

Скопируйте шаблон:

```text
gpt2giga/providers/template_provider/
```

в новую директорию:

```text
gpt2giga/providers/<provider>/
```

Шаблон задает минимальный expected shape и checklist.

## Шаг 2. Определите supported capabilities

Не реализуйте все interfaces автоматически. Подключайте только те capabilities, которые реально поддерживает новый API:

- `ChatProviderAdapter`
- `ResponsesProviderAdapter`
- `EmbeddingsProviderAdapter`
- `ModelsProviderAdapter`
- `FilesProviderAdapter`
- `BatchesProviderAdapter`

Обычно это оформляется через provider bundle в `capabilities.py`.

Правило:

- если provider поддерживает только chat и models, bundle должен публиковать только их;
- отсутствие capability лучше, чем stub route с частично сломанным поведением.

## Шаг 3. Добавьте transport layer

Создайте `gpt2giga/api/<provider>/` и держите этот слой тонким.

Обычно там нужны:

- `__init__.py` с lazy router export;
- route modules;
- `request_adapter.py`;
- `response_presenter.py`;
- `stream_presenter.py`, если есть стриминг;
- `openapi.py`, если нужен provider-specific schema fragment.

Transport layer отвечает за:

- HTTP request parsing;
- provider-specific validation;
- response formatting в совместимом формате;
- stream event presentation.

Transport layer не должен выбирать backend `v1/v2` вручную и не должен собирать GigaChat payload прямо в роутере, если это можно отдать canonical adapter + feature service.

## Шаг 4. Нормализуйте вход в canonical contracts

Новый provider должен по возможности строить canonical request objects из `gpt2giga/core/contracts/`:

- `NormalizedChatRequest`
- `NormalizedResponsesRequest`
- `NormalizedEmbeddingsRequest`

Используйте их как границу между transport layer и feature layer.

Практически это выглядит так:

```text
HTTP body
-> request_adapter.py
-> Normalized*Request
-> features/<capability>/service.py
```

Если provider chat-like, его лучше направлять через уже существующий `ChatService`.

## Шаг 5. Используйте feature-layer, а не прямой backend вызов

Новый provider должен переиспользовать existing feature services:

- `features/chat/service.py`
- `features/responses/service.py`
- `features/embeddings/service.py`
- `features/models/service.py`
- `features/files/service.py`
- `features/batches/service.py`

Не дублируйте внутри роутера:

- выбор backend path;
- orchestration stream lifecycle;
- batch/file metadata handling;
- observability bookkeeping.

Это уже централизовано выше по стеку.

## Шаг 6. Зарегистрируйте descriptor

В `gpt2giga/providers/registry.py` добавьте новый `ProviderDescriptor`.

Descriptor должен описывать:

- `name`;
- capabilities;
- список `ProviderMountSpec`;
- router factory;
- auth policy;
- опубликованные route prefixes.

Именно registry является источником правды для:

- `app/factory.py`;
- `/admin/api/capabilities`;
- provider gating через `enabled_providers`.

Если новый provider должен публиковать несколько route groups, описывайте это несколькими mount specs, а не ручным кодом в app factory.

## Шаг 7. Учитывайте provider gating

После регистрации provider должен корректно участвовать в `GPT2GIGA_ENABLED_PROVIDERS`.

Ожидаемое поведение:

- включенный provider монтируется;
- выключенный provider не попадает в app routes;
- OpenAPI schema не показывает его endpoints;
- `/admin/api/capabilities` отражает его enabled state.

## Шаг 8. Тесты

Минимальный набор:

- unit tests для request adapter и response presenter;
- registry/mount tests, если у provider есть особая publish policy;
- integration tests на реальные transport routes;
- compatibility fixtures в `tests/compat/<provider>/`, если provider добавляет новый внешний контракт.

Если provider поддерживает стриминг, добавьте отдельные regression tests на stream formatting и error handling.

Если provider chat-like, проверьте оба backend режима, если новый API должен работать и с `v1`, и с `v2`.

## Шаг 9. Документация

После подключения обновите:

- `README.md`, если provider user-facing;
- examples;
- operator docs, если provider влияет на запуск;
- capability matrix, если она есть в admin/UI docs.

## Checklist перед PR

- thin routers без backend orchestration в transport layer;
- canonical request normalization добавлена;
- provider descriptor зарегистрирован;
- route gating работает;
- OpenAPI и admin capabilities отражают новый provider;
- tests покрывают happy path и stream path при необходимости;
- docs/examples обновлены.
