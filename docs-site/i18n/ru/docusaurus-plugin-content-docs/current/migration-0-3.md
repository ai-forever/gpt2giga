# Миграция 0.3 и supervisor integration

Версия 0.3 добавляет universal provider bridge без обязательной миграции
постоянных данных. Существующие GigaChat-only deployments могут обновиться без
файла провайдеров. Multi-provider deployment включается одним immutable,
startup-owned документом профилей.

Эта страница также задаёт process contract для внешнего supervisor, например
GigaLoom. Supervisor запускает установленный артефакт `gpt2giga`, использует
публичные CLI/HTTP contracts и никогда не импортирует приватные модули gateway.

## Выбор режима миграции

| Режим | Конфигурация | Поведение |
|---|---|---|
| Существующая GigaChat-совместимость | Нет `--config` и `GPT2GIGA_CONFIG` | Gateway синтезирует один GigaChat-профиль из существующих `GIGACHAT_*` и proxy settings. Существующие публичные маршруты сохраняются. |
| Universal provider bridge | `--config <path>` или `GPT2GIGA_CONFIG=<path>` | Файл профилей авторитетен для destinations, credentials, aliases, models и capabilities. Requests не могут добавлять или менять маршруты. |
| Временный legacy Responses | `GPT2GIGA_LEGACY_RESPONSES=true`, без файла провайдеров | Старый прямой GigaChat Responses path выбирается явно. В 0.3 режим deprecated и никогда не является автоматическим fallback. |

Legacy Responses нельзя совмещать с `--config` или `GPT2GIGA_CONFIG`: такая
комбинация завершает startup ошибкой. Ошибка после normalized admission или
после начала response bytes никогда не переключает запрос на legacy path или
другого провайдера.

Контракт пути точный:

```text
gpt2giga --config /etc/gpt2giga/providers.yaml
GPT2GIGA_CONFIG=/etc/gpt2giga/providers.yaml gpt2giga
```

Одинаковый путь из обоих источников допустим. Разные пути не проходят
валидацию; документы никогда не объединяются. Схема и безопасные примеры — в
[Профилях провайдеров и алиасах моделей](provider-profiles.md).

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
| `GET /ready` | `200` `gpt2giga.readiness.v1` | `503` той же версионированной формы | Registry загружен, routes mounted, все enabled provider clients инициализированы. |
| `GET /bridge/models` | `200` `gpt2giga.bridge-models.v1` | `503` | Лексикографически упорядоченные public aliases и безопасные provider/capability/profile metadata. |
| `GET /bridge/capabilities` | `200` `gpt2giga.bridge-capabilities.v1` | `503` | Полный content-free manifest из 16 protocol/provider ячеек. |

Endpoints никогда не обращаются к провайдеру. Кэшируйте документ только вместе
с `config_revision` и `matrix_revision`; смена ревизии после рестарта
инвалидирует прежний route planning. 16-cell manifest описан в
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
6. получите `/bridge/models` и `/bridge/capabilities`, проверьте их schema и
   совпадение ревизий, затем направьте клиентский трафик;
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
2. удалите путь профилей и перезапустите 0.3 в synthesized GigaChat mode либо
   переустановите pinned-артефакт 0.2.x;
3. восстановите прежние pinned client base URL и environment settings;
4. проверьте liveness и legacy public route до возврата трафика.

YAML/JSON-файлы профилей инертны, пока не выбраны. Версия 0.2.x их не
интерпретирует. Удаление или отключение alias должно после рестарта дать unknown
alias error, но никогда не скрытый remap. Неуспешный startup 0.3 не должен
открывать частично настроенный server, поэтому после исправления файла и
рестарта data repair не требуется.

Rollback на 0.2.x удаляет контракты 0.3 inspect, readiness, bridge-models и
bridge-capabilities. Supervisor должен вернуться к pinned 0.2.x процедуре
health/routing, а не считать отсутствие endpoints ошибкой провайдера.
