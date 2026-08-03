# ADR: нормализованное исполнение OpenAI Responses

- Дата: 2026-08-03
- Статус: принято для gpt2giga 0.3
- Владельцы решения: направления Responses protocol и integration
- Ревизия контракта: `gpt2giga.responses-execution.v1`

## Контекст

Пользовательские model provider в Codex работают через OpenAI Responses wire
API. Сейчас `/responses` в шлюзе вызывает GigaChat-преобразования напрямую, а
нормализованные Responses-модели используются только для диагностики и
наблюдаемости. Версия 0.3 не может обещать совместимость с Codex, сохраняя двух
владельцев исполнения или молча теряя семантику. Поддержанный поднабор фиксирует
версионированный корпус `tests/corpora/bridge/`.

## Решение

### Один владелец исполнения

Каждый допущенный запрос `/responses` проходит одну цепочку:

```text
Responses request decoder
-> NormalizedChatRequest / normalized state contract
-> capability and loss admission
-> exact provider profile and public alias resolution
-> upstream provider adapter
-> NormalizedResponse / NormalizedStreamEvent
-> Responses response or SSE projection
```

После нормализованного admission маршрут не обращается к legacy-трансформеру
или второму провайдеру. После dispatch или выдачи байтов fallback запрещён.

### Режим совместимости

Нормализованное Responses-исполнение является умолчанием 0.3. Старый прямой
путь GigaChat разрешён только при `GPT2GIGA_LEGACY_RESPONSES=true`, без bridge
config и только для синтезированного legacy-профиля GigaChat. Совместное
использование флага с `--config` или `GPT2GIGA_CONFIG` даёт startup-ошибку
`invalid_profile`. Флаг deprecated в 0.3 и не является fallback провайдера.

### Admission запроса

Каждое поле и вложенный элемент относится к одной категории:

- нормализуется и исполняется;
- принимается, но игнорируется с точным corpus evidence id и причиной manifest;
- отклоняется до разрешения credentials, network ticket и provider client.

Неизвестные поля отклоняются. `base_url`, селекторы провайдера, credentials,
TLS-настройки, произвольные headers и upstream model id всегда дают
`unsupported_semantic`; Pydantic extras не становятся расширениями провайдера.

Стабильная цель Codex включает текст, instructions, function declarations,
function-call outputs, представимую JSON Schema, usage, stop reasons, HTTP SSE и
кооперативный disconnect. State, reasoning, multimodal и hosted-tool семантика
допускается лишь при явном доказательстве выбранной ревизией профиля/матрицы.

### Жизненный цикл ответа и stream

Обычный ответ содержит один Responses object с честными `status`, output,
известными usage-фактами и запрошенным публичным alias. Неизвестные token
категории не выдумываются.

SSE сохраняет порядок:

1. ровно один `response.created`;
2. start-события item/content до delta;
3. function argument delta до соответствующего done;
4. usage только когда он известен;
5. ровно один terminal: `response.completed`, `response.failed` или
   `response.incomplete`.

`error` завершает stream. Дубли terminal, данные после terminal, malformed или
незавершённый upstream stream становятся стабильной protocol-ошибкой. Disconnect
отменяет ровно текущую upstream-операцию и освобождает ресурсы без retry/fallback.

### Стабильные ошибки

Responses сохраняет OpenAI envelope и коды `invalid_request`,
`unknown_model_alias`, `unsupported_semantic`, `credential_unavailable`,
`destination_mismatch`, `provider_timeout`, `provider_protocol_error`,
`provider_failure`, `client_disconnected`. `param` указывает публичное поле,
когда оно известно. Сообщения не содержат контент, credential или сырой
upstream body.

## Миграция и откат

- Существующие маршруты и `/v1` aliases остаются.
- Явный legacy-режим можно временно включить без изменения данных.
- Откат на 0.2.x оставляет profile files неактивными и не переписывает state.
- Удаление legacy-флага возвращает normalized execution, не меняя alias/provider.

## Ссылки

- [Справочник конфигурации Codex](https://developers.openai.com/codex/config-reference/)
- [Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create)
- [Responses streaming](https://developers.openai.com/api/docs/guides/streaming-responses)
