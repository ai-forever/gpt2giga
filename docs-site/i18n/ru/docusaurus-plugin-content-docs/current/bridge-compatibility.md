# Совместимость bridge, потери и ошибки

Bridge 0.3 не утверждает, что каждый клиентский протокол эквивалентен каждому
upstream-провайдеру. Он публикует версионированное machine-readable решение для
каждого маршрута и отклоняет семантику, которую нельзя сохранить, до provider
I/O.

Схема матрицы — `gpt2giga.bridge-loss-matrix.v1`. Она содержит ровно 16 ячеек:
четыре публичных протокола, умноженные на четыре upstream provider kinds.

| Измерение | Значения |
|---|---|
| Public protocol | `openai_responses`, `openai_chat_completions`, `anthropic_messages`, `gemini_generate_content` |
| Upstream provider | `gigachat`, `openai_compatible`, `anthropic`, `gemini` |

Само наличие адаптера в пакете ещё не доказывает, что ячейку можно выполнять.
Используйте ревизию матрицы, которую публикует запущенный gateway.

## Статусы поддержки ячеек

У каждой ячейки ровно один статус. `unknown`, пропущенная ячейка или неявное
значение по умолчанию делают manifest невалидным.

| Статус | Значение |
|---|---|
| `stable` | Объявленный subset покрыт зафиксированными окнами версий клиента/провайдера, hermetic conformance и release E2E evidence. Это не заявление о полном vendor API parity. |
| `technical_preview` | Объявленный subset протестирован, но остаётся как минимум одна документированная семантическая потеря или повышенный риск upstream drift. Caller должен проверить semantic rows. |
| `blocked` | Безопасного проверенного маршрута нет. Admission отклоняет его до credentials, создания provider client или network dispatch. |

Ячейка также содержит bounded reason ids, evidence ids, окна версий клиента и
провайдера и полную таблицу семантик. Таблица покрывает roles, multimodal input,
tool definitions/call ids/choice/results, parallel calls, JSON Schema output,
stream lifecycle, input/output/cache/reasoning usage, stop reasons,
safety/refusal, reasoning controls, previous-response state, files/images,
hosted/provider-native tools, cancellation, timeout, malformed streams и
disconnect.

## Диспозиции семантик

У каждой semantic row одна диспозиция:

- `exact`: выбранный маршрут сохраняет объявленную семантику;
- `conditional`: семантика допускается только при наличии точного именованного
  capability predicate в разрешённом capability profile;
- `unsupported`: запрос, которому нужна эта семантика, отклоняется до dispatch.

`technical_preview` не превращает строки `unsupported` в best-effort behavior.
А строка `exact` не повышает всю ячейку до `stable`. Ячейку, semantic row,
зафиксированные окна версий и evidence ids нужно оценивать совместно.

Каноническая матрица без секретов имеет ревизию `sha256:<lowercase-hex>`.
Успешная admission record использует схему `gpt2giga.bridge-admission.v1` и
связывает public protocol и alias, точные provider/profile, config revision,
capability profile revision, matrix revision, запрошенные semantic paths и
evidence ids. В ней нет prompt, credential или response content.

## Admission выполняется до I/O

Для каждого bridge request gateway выполняет следующий порядок:

1. разрешает точный публичный алиас из immutable
   [реестра провайдеров](provider-profiles.md);
2. выбирает точную ячейку public-protocol/upstream-provider;
3. отклоняет ячейку `blocked`;
4. выводит запрошенные semantic rows из нормализованного запроса;
5. требует для каждой строки `exact` или выполнение её именованного capability
   predicate;
6. записывает content-free admission decision с привязкой к ревизиям;
7. вызывает ровно выбранный provider adapter.

Gateway не понижает семантику, не выбирает похожий алиас и не повторяет запрос
через другой provider/model/account. Переданные в request provider,
destination, upstream model, credential, TLS control или произвольный
authorization header не являются routing override.

OpenAI-shaped semantic rejection стабилен и указывает публичное поле:

```json
{
  "error": {
    "code": "unsupported_semantic",
    "message": "The selected bridge route cannot preserve this semantic.",
    "param": "web_search_options",
    "type": "invalid_request_error"
  }
}
```

Anthropic- и Gemini-shaped public routes сохраняют native error envelopes там,
где это требуется, и bounded machine code там, где он представим. Ошибка не
может повторять credentials, authorization headers, prompt content или
неочищенный upstream body.

## Стабильные коды ошибок bridge

| Код | Значение |
|---|---|
| `invalid_request` | Public request некорректен в рамках допустимого синтаксиса. |
| `unknown_model_alias` | Точный публичный алиас отсутствует, отключён или недоступен. |
| `unsupported_semantic` | Выбранная ячейка или semantic row не может сохранить запрос. |
| `credential_unavailable` | Startup credential reference выбранного профиля не разрешается. |
| `destination_mismatch` | Transport destination отличается от проверенного профиля. |
| `provider_timeout` | Операция точного провайдера превысила свой bound. |
| `provider_protocol_error` | Точный upstream вернул malformed response или stream. |
| `provider_failure` | Выбранный провайдер вернул другую отображённую ошибку. |
| `client_disconnected` | Клиент отключился до завершения, и точная upstream-операция была отменена. |

Startup/profile validation дополнительно использует `invalid_profile_schema`,
`duplicate_profile_id`, `duplicate_model_alias`, `invalid_destination` и
`invalid_policy_reference`. Ошибки machine endpoints используют
версионированный envelope `gpt2giga.error.v1` с bounded content-free reason ids
в `details`.

## Machine contract capabilities

`GET /bridge/capabilities` возвращает
`gpt2giga.bridge-capabilities.v1`. Документ связывает текущие
`config_revision` и `matrix_revision` и содержит все 16 ячеек в стабильном
лексикографическом порядке. Он не содержит пользовательский контент и не
обращается к провайдерам. Неполная, не совпадающая по ревизии, содержащая
`unknown`, дубли или секреты проекция отклоняется, а не публикуется.

Используйте этот endpoint для route planning и диагностики; не выводите
поддержку из наличия HTTP route, установленного SDK или класса provider adapter.
Детали protocol surface остаются в [Совместимости API](api-compatibility.md), а
нормативное решение матрицы записано в
[ADR статусов и потерь bridge](architecture/2026-08-03-bridge-status-loss-matrix-adr.md).
