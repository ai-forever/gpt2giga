# Миграция 0.3 и supervisor integration

Версия 0.3 добавляет universal provider bridge без обязательной миграции
постоянных данных. Исправленный релиз остаётся additive: GigaChat-only
deployments сохраняют native Responses и обновляются без файла провайдеров или
compatibility flag. Multi-provider deployment включается одним immutable,
startup-owned документом профилей.

Эта страница также задаёт process contract для внешнего supervisor, например
GigaLoom. Supervisor запускает установленный артефакт `gpt2giga`, использует
публичные CLI/HTTP contracts и никогда не импортирует приватные модули gateway.

## Выбор режима миграции

| Режим | Конфигурация | Поведение |
|---|---|---|
| Native GigaChat compatibility | Нет `--config` и `GPT2GIGA_CONFIG` | Built-in GigaChat route использует существующие `GIGACHAT_*` и proxy settings. Native Responses, hosted tools, attachments, v1/v2 и public routes сохраняются. Models приходят из provider discovery. |
| Universal provider bridge | `--config <path>` или `GPT2GIGA_CONFIG=<path>` | Profiles владеют destinations, credentials, immutable aliases и route policy. GigaChat inventory остаётся dynamic; requests не меняют routes. |

`GPT2GIGA_LEGACY_RESPONSES` не является migration input исправленного релиза.
Удалите его, если добавили при тестировании раннего 0.3 preview. Executor, route
и model выбираются до provider I/O. Ошибка после dispatch или начала response
bytes не переключает executor, provider, account или model.

Контракт пути точный:

```text
gpt2giga --config /etc/gpt2giga/providers.yaml
GPT2GIGA_CONFIG=/etc/gpt2giga/providers.yaml gpt2giga
```

Одинаковый путь из обоих источников допустим. Разные пути не проходят
валидацию; документы никогда не объединяются. Схема и безопасные примеры — в
[Профилях провайдеров и алиасах моделей](provider-profiles.md).

## Совместимость схемы provider profiles

Существующие `gpt2giga.provider-profiles.v1` остаются валидными. Каждый public
alias сохраняет exact provider route и upstream-model binding; correction не
переписывает и не угадывает aliases. Для `provider_kind: gigachat` элементы
`models` задают explicit alias/default policy, а не полный inventory. Общий
model catalog всё равно возвращает все credential-visible GigaChat models.

Текущая v1 schema требует непустой `models`. Сохраняйте этот список, если profile
должен работать и на старом 0.3 preview. Исправленный релиз вводит
`gpt2giga.provider-profiles.v2`, где `model_inventory: dynamic` разрешает
GigaChat route без перечисления aliases. Не выбирайте v2, пока
`--inspect-config` не сообщает поддержку этой revision: старые binaries
отклоняют unknown fields. Static aliases остаются authoritative для providers
без dynamic discovery.

Обычному GigaChat deployment не нужно перечислять все provider models, менять
existing alias или переписывать persistent state.

## Preflight до bind socket

Используйте тот же parser в inspect mode:

```sh
gpt2giga --config /etc/gpt2giga/providers.yaml --inspect-config
```

Успешный preflight пишет в stdout один JSON-документ `gpt2giga.inspect.v1` и
завершается с кодом `0`. Он проверяет schema, destination и policy references,
наличие credential, aliases, capability profiles и matrix revision. Socket не
открывается, запрос к провайдеру не выполняется. Документ может содержать имя
`credential_env`, но никогда не значение, его hash или authorization header.

Ошибка validation пишет bounded-документ `gpt2giga.error.v1`, направляет логи в
stderr и завершается с кодом `2`. Считайте preflight неуспешным при non-JSON в
stdout, content-bearing details или нулевом exit code при `valid != true`.

## Runtime machine contract

После успешного preflight запустите тот же установленный артефакт обычным
способом и используйте endpoints:

| Endpoint | Ready response | Not-ready behavior | Назначение |
|---|---:|---:|---|
| `GET /health` | `200` | Процесс недоступен | Только liveness, не traffic readiness. |
| `GET /ready` | `200` `gpt2giga.readiness.v1` | `503` той же формы | Готовность route, clients и model catalog. |
| `GET /models` | `200` protocol response | Protocol error | Protocol projection общего model catalog. |
| `GET /bridge/models` | `200` `gpt2giga.bridge-models.v1` | `503` | Machine projection того же catalog snapshot и inventory revision. |
| `GET /bridge/capabilities` | `200` `gpt2giga.bridge-capabilities.v1` | `503` | Coarse content-free route manifest из 16 ячеек. |
| `GET /bridge/capabilities?model=...&protocol=...&api_mode=...` | `200` effective capability response | `400`/`404`/`503` | Model-aware tri-state decisions и revisions. |

Preflight, `/health` и coarse route matrix не обращаются к provider. Model
catalog projections могут выполнить bounded discovery refresh и честно сообщают
fresh/stale state. Кэшируйте документы с `config_revision`,
`inventory_revision`, `matrix_revision` и `capability_revision`, где применимо.
Смена revision инвалидирует прежний route planning. Coarse matrix описана в
[Совместимости bridge, потерях и ошибках](bridge-compatibility.md).

Readiness строже liveness. Типичные content-free reason ids:
`registry_not_loaded`, `provider_clients_not_ready` и `gateway_shutting_down`.
Supervisor может сохранить живой процесс для диагностики, пока `/health`
доступен, но `/ready` ложен, с учётом собственного bounded startup deadline.

## Последовательность запуска sidecar

Для GigaLoom-compatible или другого внешнего supervisor:

1. установите pinned wheel в окружение sidecar, без editable sibling checkout;
2. запишите profiles document в защищённый supervisor-owned path и передайте
   credentials через защищённое окружение процесса;
3. выполните `--inspect-config` и принимайте только exit `0` плюс валидный
   redacted JSON;
4. запустите `gpt2giga --config <same-path>` без shell interpolation секретов;
5. дождитесь `/health`, затем потребуйте `/ready.ready == true` за bounded
   deadline;
6. получите `/bridge/models` и effective `/bridge/capabilities` query выбранной
   model, проверьте schema и совпадение revisions, затем направьте трафик;
7. сохраняйте в supervisor evidence только content-free revisions/statuses,
   если отдельная policy явно не разрешает content capture.

GigaLoom владеет project/session/workbench state и process supervision.
`gpt2giga` владеет validation профилей, публичными protocol routes, admission
decisions и provider clients внутри gateway process. Продукты не импортируют
приватные Python-модули друг друга.

## Graceful shutdown

По SIGTERM или interrupt контракт 0.3 требует:

1. установить readiness false и отклонять новые model requests;
2. прекратить приём новых connections;
3. дренировать активные requests до configured shutdown deadline;
4. отменить оставшуюся upstream work;
5. закрыть каждый owned provider client, sink, store, iterator и network
   authorization;
6. завершиться non-zero только при нарушении cleanup bound.

Перед SIGKILL дождитесь graceful exit. Supervisor может послать SIGKILL только
после своего deadline. Shutdown не должен приводить к retry через другой alias,
provider, model, account или credential.

## Rollback

Миграция профилей не записывает application или conversation state. Поэтому
rollback выполняется конфигурацией или пакетом:

1. остановите новый трафик и graceful-завершите процесс 0.3;
2. удалите путь профилей и перезапустите 0.3 на built-in native GigaChat route
   либо переустановите pinned-артефакт 0.2.x;
3. восстановите прежние pinned client base URL и environment settings;
4. проверьте liveness и native public route до возврата трафика.

YAML/JSON-файлы профилей инертны, пока не выбраны. Версия 0.2.x их не
интерпретирует. Удаление или отключение alias должно после рестарта дать unknown
alias error, но никогда не скрытый remap. Неуспешный startup 0.3 не должен
открывать частично настроенный server, поэтому после исправления файла и
рестарта data repair не требуется.

Rollback на 0.2.x удаляет контракты 0.3 inspect, readiness, bridge-models и
bridge-capabilities. Supervisor должен вернуться к pinned 0.2.x процедуре
health/routing, а не считать отсутствие endpoints ошибкой провайдера.
