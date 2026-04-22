# Upgrade guide: `0.1.x` -> `1.0`

Этот гайд предназначен для операторов, которые уже запускали `gpt2giga` на ветке `0.1.x` и теперь переходят на релизную линию `1.0`.

Он описывает upgrade до major-release architecture и применим как к финальному `1.0.0`, так и к поздним `1.0.0rc*` сборкам, которые уже используют тот же runtime layout.

## Что поменялось концептуально

Ветка `0.1.x` была в первую очередь OpenAI-compatible proxy с набором совместимых маршрутов.

Ветка `1.0` стала шире:

- runtime теперь явно разделен на `api/`, `app/`, `core/`, `features/`, `providers/`;
- кроме OpenAI-compatible surface появились отдельные Anthropic- и Gemini-compatible surfaces;
- появились operator-facing runtime switches для provider gating, backend mode, telemetry и runtime store;
- admin console превратилась в отдельный optional UI package и control-plane поверхность, а не в побочный helper UI;
- deploy/layout документация переехала в `deploy/` и `docs/`.

Если у вас был только один локальный OpenAI-compatible endpoint, клиентский код часто продолжит работать почти без изменений. Основные upgrade-изменения касаются упаковки, конфигурации и operator workflows.

## Что обычно остается совместимым

- Базовый адрес по умолчанию по-прежнему `http://localhost:8090`.
- OpenAI-compatible клиенты по-прежнему могут работать через `http://localhost:8090` или `http://localhost:8090/v1`.
- GigaChat credentials по-прежнему задаются через переменные `GIGACHAT_*`.
- Глобальный gateway API key по-прежнему включается через `GPT2GIGA_ENABLE_API_KEY_AUTH=True` и `GPT2GIGA_API_KEY`.
- Health check `/health` остается удобной первой smoke-probe после старта.

## Что требует явного внимания при апгрейде

### 1. Обновите launch и packaging assumptions

Запускайте приложение через `uv run gpt2giga`.

Если вам нужен `/admin`, устанавливайте extra-пакет UI:

```bash
uv add "gpt2giga[ui]"
```

Без `ui` extra proxy продолжит работать, но operator-facing HTML admin shell не будет доступен как установленный package asset.

### 2. Обновите ссылки на layout репозитория

Если ваши runbook-ы, wiki или compose wrapper-скрипты ссылались на старые пути, их нужно перевести на новые:

- `compose/` -> `deploy/compose/`
- `traefik/` -> `deploy/traefik/`
- `integrations/` -> `docs/integrations/`

Для Docker/Compose стартовой точкой теперь является [../deploy/README.md](../deploy/README.md).

### 3. Зафиксируйте runtime posture явно, а не через старые implicit defaults

Для консервативного rollout-а лучше явно задать как минимум:

```dotenv
GPT2GIGA_MODE=DEV
GPT2GIGA_ENABLED_PROVIDERS=openai
GPT2GIGA_GIGACHAT_API_MODE=v1
GPT2GIGA_ENABLE_API_KEY_AUTH=True
GPT2GIGA_API_KEY="<strong_secret>"
GIGACHAT_CREDENTIALS="<your_gigachat_credentials>"
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max
```

Почему это важно:

- `GPT2GIGA_ENABLED_PROVIDERS` определяет, какие provider routes вообще монтируются;
- `GPT2GIGA_GIGACHAT_API_MODE` выбирает backend mode для chat-like flows;
- `GPT2GIGA_MODE` теперь напрямую влияет на доступность `/docs`, `/redoc`, `/openapi.json` и `/admin*`.

Если вы обновляетесь без functional-expansion цели, начните с `openai` + `v1`, а затем отдельно тестируйте `anthropic`, `gemini` и `v2`.

### 4. Не рассчитывайте на `/admin` и `/docs` в `PROD`

В `1.0` это operator policy, а не случайный побочный эффект:

- в `DEV` доступны `/docs`, `/redoc`, `/openapi.json`, `/admin`, `/admin/api/*`;
- в `PROD` эти surface-ы отключаются.

Если раньше вы использовали `/docs` или `/admin` как production debugging surface, это нужно заменить на нормальный staging workflow и `/metrics`/telemetry.

### 5. Если proxy стоит за reverse proxy, настройте trusted proxy policy явно

В `1.0` нельзя полагаться на присланный клиентом `X-Forwarded-For`.

Если нужен исходный client IP за Nginx/Traefik, перечислите доверенные proxy IP или CIDR:

```dotenv
GPT2GIGA_TRUSTED_PROXY_CIDRS=["10.0.0.0/24","127.0.0.1/32"]
```

Иначе admin allowlist и observability fields будут использовать прямой peer IP от ASGI-сервера.

### 6. Проверьте, нужен ли вам persistent runtime store

Ветка `1.0` активнее использует runtime metadata, files/batches inventory и control-plane payloads.

Если вам недостаточно памяти процесса между рестартами, явно задайте backend и DSN:

```dotenv
GPT2GIGA_RUNTIME_STORE_BACKEND=sqlite
GPT2GIGA_RUNTIME_STORE_DSN=.local/gpt2giga-runtime.sqlite3
```

Для multi-instance или внешних backend-ов используйте примеры в `deploy/compose/runtime-backends/`.

### 7. Учитывайте bootstrap/setup flow для operator console

Если вы поднимаете `PROD` впервые, control plane может войти в bootstrap mode до завершения setup/claim flow.

Практически это означает:

- не считайте `/admin` постоянной production-панелью;
- завершите bootstrap и сохраните gateway auth posture до ввода инстанса в эксплуатацию;
- проверьте, что security/bootstrap шаги закрыты до подачи пользовательского traffic.

## Рекомендуемый upgrade-порядок

1. Зафиксируйте текущую `0.1.x` конфигурацию.
   Сохраните старый `.env`, compose overrides, reverse-proxy конфиги и список реально используемых endpoint-ов.
2. Поднимите staging-инстанс на `1.0` с максимально консервативными настройками.
   Начните с `GPT2GIGA_ENABLED_PROVIDERS=openai` и `GPT2GIGA_GIGACHAT_API_MODE=v1`, даже если позже планируете больше surfaces.
3. Обновите packaging и deploy paths.
   Переведите локальные инструкции и automation на `deploy/compose/...`, `deploy/traefik/...` и новые docs paths.
4. Решите, нужен ли вам admin UI package.
   Если да, ставьте `gpt2giga[ui]`; если нет, не считайте отсутствие `/admin` packaging regression-ом.
5. Проверьте auth и trust boundary.
   Убедитесь, что заданы `GPT2GIGA_ENABLE_API_KEY_AUTH`, `GPT2GIGA_API_KEY`, а при reverse proxy еще и `GPT2GIGA_TRUSTED_PROXY_CIDRS`.
6. Прогоните smoke-трафик теми клиентами, которые уже используются в проде.
   Сначала OpenAI-compatible flows, затем Anthropic/Gemini only if you plan to expose them.
7. Только после этого включайте дополнительные surfaces.
   `anthropic`, `gemini`, `v2`, telemetry sinks и non-memory runtime backends лучше вводить отдельными шагами.

## Post-upgrade checklist

После старта `1.0` инстанса проверьте минимум:

- `GET /health` возвращает `200`;
- нужные provider routes реально смонтированы и отвечают на ту базу URL, которую используют клиенты;
- API-key auth работает так же, как ожидают ваши SDK и reverse proxy;
- в `DEV` доступны `/docs` и `/admin`, если вы их ожидаете;
- в `PROD` `/docs`, `/redoc`, `/openapi.json` и `/admin*` действительно закрыты;
- если стоит reverse proxy, client IP определяется корректно и не зависит от spoofed `X-Forwarded-For`;
- если используется observability, `/metrics` или выбранный telemetry sink действительно получает события;
- если нужны files/batches/runtime feeds между рестартами, выбран правильный `GPT2GIGA_RUNTIME_STORE_BACKEND`.

## Когда upgrade нельзя считать «безболезненным»

Планируйте дополнительное тестирование, если у вас есть хотя бы один из сценариев:

- старые runbook-ы жестко ссылаются на `compose/` или `traefik/` в корне;
- production-процессы depended on `/docs` или `/admin`;
- вы используете reverse proxy и раньше implicitly доверяли `X-Forwarded-For`;
- вы хотите сразу перейти на Anthropic/Gemini surfaces или на `GPT2GIGA_GIGACHAT_API_MODE=v2`;
- вам нужна persistence runtime metadata между рестартами или на нескольких инстансах.

## Куда смотреть дальше

- За operational semantics переключателей: [operator-guide.md](./operator-guide.md)
- За переменными окружения и production config: [configuration.md](./configuration.md)
- За полным route coverage и ограничениями: [api-compatibility.md](./api-compatibility.md)
- За deploy presets и compose сценариями: [../deploy/README.md](../deploy/README.md)
