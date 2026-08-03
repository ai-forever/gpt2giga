# ADR: нормализованное исполнение OpenAI Responses

- Дата: 2026-08-03
- Статус: принято для gpt2giga 0.3
- Владельцы решения: направления Responses protocol и integration
- Ревизия контракта: `gpt2giga.responses-execution.v2`

## Контекст

Пользовательские model provider в Codex работают через OpenAI Responses wire
API. В шлюзе уже есть GigaChat-native путь Responses, сохраняющий hosted tools,
attachments, conversation state, v1/v2, non-streaming, SSE и provider-specific
адаптацию ответа. Первая реализация 0.3 сделала уменьшенный normalized subset
умолчанием и назвала native-владельца `legacy`, поэтому поддержанные GigaChat
семантики отклонялись до разрешения route, model и API mode.

## Решение

### Один выбранный владелец исполнения

Каждый запрос `/responses` до provider I/O проходит цепочку:

```text
decode известных public fields без потери распознанного intent
-> resolve immutable provider route
-> resolve effective model
-> resolve protocol/provider/model/API-mode/route capabilities
-> admit или reject запрошенных semantics
-> select ровно одного executor
```

Для GigaChat route выбирается `native_gigachat`, для настоящего cross-provider
route — `normalized_bridge`; выбор записывается в request context. После
dispatch нельзя менять executor, provider, account или model. После dispatch
или выдачи байтов fallback запрещён.

### Владелец совместимости

Native GigaChat Responses остаётся владельцем совместимости и умолчанием без
явной cross-provider конфигурации. Явный GigaChat bridge route также выбирает
native-владельца, пока normalized parity не доказана и отдельно не повышена.
Обычному GigaChat deployment не нужен compatibility flag.

Normalized bridge выбирается route-решением для cross-provider исполнения, а
не задаёт глобальный минимальный знаменатель. Responses compatibility
workaround не входит в исправленный public contract 0.3.

### Admission запроса

Decoder сохраняет распознанные поля и вложенные элементы до route/model
admission. Затем каждая semantic относится к одной категории:

- нормализуется и исполняется;
- принимается, но игнорируется с точным corpus evidence id и причиной manifest;
- отклоняется до разрешения credentials, network ticket и provider client с
  точной semantic и reason id.

Неизвестные поля отклоняются. `base_url`, селекторы провайдера, credentials,
TLS-настройки, произвольные headers и upstream model id всегда дают
`unsupported_semantic`; Pydantic extras не становятся расширениями провайдера.

Hosted tools, attachments, reasoning, previous-response/conversation state,
images и files не считаются глобально unsupported. Они допускаются, когда
выбранные route, model и API mode доказывают support. `unknown` не превращается
молча в supported или unsupported, а обрабатывается явной route policy.

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
- Существующим GigaChat-only deployments не нужен флаг или изменение config.
- Явные bridge profiles сохраняют exact immutable aliases и provider routes.
- Откат на 0.2.x оставляет profile files неактивными и не переписывает state.
- Executor selection не меняет alias и не выбирает другой provider/model молча.

## Ссылки

- [Справочник конфигурации Codex](https://developers.openai.com/codex/config-reference/)
- [Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create)
- [Responses streaming](https://developers.openai.com/api/docs/guides/streaming-responses)
