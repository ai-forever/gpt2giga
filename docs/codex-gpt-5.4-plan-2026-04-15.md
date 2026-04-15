# План для Codex gpt-5.4 + overview репозитория gpt2giga

Дата: 2026-04-15
База анализа: локальный архив репозитория, ветка `feature/extend_capabilities`

## Зачем этот документ

Это практический план под три цели:

1. сделать репозиторий заметно более модульным и проще для сопровождения;
2. упростить и облегчить operator UI;
3. сделать интеграции с observability-инструментами более явными, настраиваемыми и дружелюбными.

Документ не заменяет уже существующие `docs/repo-overview-2026-04-14.md` и `docs/refactor-tasks-2026-04-14.md`, а сужает их до более прикладного execution-плана для Codex gpt-5.4.

---

## 1. Executive summary

Репозиторий уже не выглядит как «тонкий FastAPI proxy». По факту здесь живут сразу несколько подсистем:

- protocol gateway: OpenAI / Anthropic / Gemini-compatible surfaces;
- provider adaptation layer для GigaChat;
- runtime/control-plane слой с конфигом, ключами, governance, runtime stores и admin API;
- встроенный operator UI.

Это не плохо. Проблема в другом: модульность уже есть на уровне файлов и папок, но не везде есть модульность на уровне **понятий**. Самая большая сложность сейчас не в том, что файлов много. Она в том, что человеку нужно держать в голове слишком много пересекающихся моделей одновременно.

### Мой короткий вывод

- **Backend в целом имеет хорошую форму**, особенно по слоям `api -> features -> providers -> runtime`.
- **Основной источник перегруза сейчас — admin/control-plane + UI**, а не core proxy-путь.
- **Observability слой уже неплохо абстрагирован в коде**, но плохо представлен как продуктовая функция: registry есть, а first-class UX/config story почти нет.
- **Самый срочный технический риск — UI packaging/build drift**: в репозитории есть дублированные compiled assets, и они уже не полностью синхронны.

---

## 2. Краткий снимок репозитория

### Что видно по структуре

- `gpt2giga/api/` — HTTP surfaces и transport layer.
- `gpt2giga/features/` — feature/use-case orchestration.
- `gpt2giga/providers/gigachat/` — маппинг запросов/ответов и streaming для GigaChat.
- `gpt2giga/app/` — composition root, runtime wiring, observability, state backends.
- `gpt2giga/frontend/admin/` — TypeScript-исходники admin UI.
- `packages/gpt2giga-ui/` — отдельный optional UI package.
- `tests/`, `docs/`, `examples/`, `deploy/` — хороший supporting layer.

### Что видно по масштабу

На текущем состоянии репозиторий уже ощутимо вырос:

- около `150` Python-файлов в `gpt2giga/`;
- `22` TypeScript-файла admin UI;
- `54` Python test-файла;
- около `25k` Python LOC в основном пакете;
- около `9.4k` TypeScript LOC в `gpt2giga/frontend/admin/`;
- две compiled admin asset tree:
  - `gpt2giga/static/admin/`
  - `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/`

Это уже не маленький сервис. Значит нужен не «cleanup по настроению», а управляемый refactor roadmap.

---

## 3. Что в репозитории уже хорошо

## 3.1. У backend есть реальная архитектурная форма

Слои распознаны и в целом разумно разделены:

- transport/compatibility routes в `api/`;
- orchestration в `features/`;
- provider-specific transforms в `providers/gigachat/`;
- wiring/runtime/config в `app/`.

Это намного лучше, чем типичный FastAPI-проект, где всё живёт прямо в handlers.

## 3.2. Feature decomposition выглядит осмысленно

`chat`, `responses`, `embeddings`, `files`, `batches`, `models` разделены по реальным продуктовым поверхностям. Это хорошая база для дальнейшей модульности.

## 3.3. Есть сильное operator-thinking

Проект уже ориентирован не только на «сделать запрос к модели», но и на day-2 operations:

- control plane;
- persisted config;
- bootstrap/setup;
- keys;
- logs/traffic/runtime diagnostics;
- observability sinks;
- compose/deploy сценарии.

Это важно и ценно. Именно поэтому refactor должен не ломать operator story, а усиливать её.

## 3.4. Документация, примеры и тестовая структура выше среднего

Есть:

- runnable examples;
- integration docs для реальных инструментов;
- deploy assets;
- unit/integration/smoke тестовая иерархия;
- contributor guidance через `AGENTS.md`.

Это очень хороший фундамент для безопасного поэтапного рефакторинга.

## 3.5. В observability уже есть полезное зерно

`gpt2giga/app/telemetry.py` уже содержит:

- понятие `ObservabilitySink`;
- `ObservabilityHub`;
- registry через `register_observability_sink(...)`;
- built-in sink-и для `prometheus`, `otlp`, `langfuse`, `phoenix`.

То есть здесь не нужно делать rewrite с нуля. Нужна продуктовая доводка и упрощение интерфейсов.

---

## 4. Что сейчас плохо или опасно

## 4.1. Admin/control-plane уже стал «вторым продуктом» внутри репозитория

Самые тяжёлые backend hotspots сейчас находятся не в proxy-роутах, а в операторском слое:

- `gpt2giga/app/telemetry.py` — 1200+ строк;
- `gpt2giga/app/observability.py` — 1100+ строк;
- `gpt2giga/api/admin/settings.py` — ~900 строк;
- `gpt2giga/api/admin/runtime.py` — ~800 строк;
- `gpt2giga/app/runtime_backends.py` — ~860 строк.

Это означает, что проблема не в отсутствии файлов. Проблема в том, что admin/control-plane код тянет на отдельную domain area, но пока остаётся размазанным между route-модулями, runtime helpers и config utilities.

## 4.2. Composition root становится слишком широким

`gpt2giga/app/factory.py`, `gpt2giga/app/wiring.py` и `gpt2giga/app/dependencies.py` в целом устроены логично, но вместе уже становятся точкой концентрации слишком многих решений:

- middleware order;
- route inclusion;
- auth/governance policy;
- runtime services;
- observability;
- stores;
- admin UI availability;
- bootstrap/posture behavior.

Это не авария, но это уже явный кандидат на дальнейшую декомпозицию.

## 4.3. Admin frontend модульный по файлам, но не по ответственности

Крупные page-модули всё ещё совмещают у себя слишком много обязанностей сразу:

- render;
- state;
- side effects;
- DOM lookup;
- event binding;
- API orchestration;
- UX flow;
- status messaging.

Самые заметные hotspots:

- `render-files-batches.ts` — ~1600 строк;
- `render-playground.ts` — ~1260 строк;
- `render-logs.ts` — ~1210 строк;
- `render-traffic.ts` — ~860 строк.

Текущий стек без фреймворка — это нормально. Проблема не в «vanilla TS». Проблема в том, что страницы стали инструментами, а не просто view-рендерами, но внутренняя организация всё ещё page-local и монолитная.

## 4.4. UI сейчас тяжёл не только кодом, но и информационной архитектурой

По смыслу admin console одновременно пытается быть:

- first-run setup wizard;
- config editor;
- runtime dashboard;
- logs/traffic observability surface;
- playground smoke client;
- files/batches workbench.

Это объясняет ощущение перегруженности даже без просмотра кода. Некоторые страницы уже больше похожи на «control room», чем на понятный последовательный workflow.

## 4.5. Самый важный технический red flag: UI asset duplication и drift

Сейчас есть минимум три параллельные реальности admin UI:

- TS source: `gpt2giga/frontend/admin/`
- compiled output в корне: `gpt2giga/static/admin/`
- compiled output в optional UI package: `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/`

И это уже привело к расхождению. Локальная проверка показала, что как минимум эти compiled файлы **не идентичны** между деревьями:

- `forms.js`
- `pages/control-plane-sections.js`

Это значит, что сейчас у проекта нет одного надёжного source-of-truth для shipped UI assets.

### Почему это критично

`gpt2giga/app/admin_ui.py` загружает UI из optional package `gpt2giga_ui`, а не из `gpt2giga/static/`. При этом `npm run build:admin` пишет output в `gpt2giga/static/`, а не в `packages/gpt2giga-ui/`.

Итог:

- разработчик может «собрать UI»;
- увидеть обновлённые root assets;
- но реально отгружаемый optional UI package останется на старых compiled файлах.

Это нужно чинить **до** больших UI-рефакторингов.

## 4.6. Observability уже расширяемая в коде, но неудобная в конфиге и UI

Сейчас есть архитектурный парадокс:

- в коде есть pluggable sinks и registry;
- в UI и admin settings observability представлена почти как CSV-поле `observability_sinks` плюс toggle `enable_telemetry`.

При этом observability-specific поля существуют в `ProxySettings`:

- `otlp_traces_endpoint`
- `langfuse_base_url`
- `langfuse_public_key`
- `langfuse_secret_key`
- `phoenix_base_url`
- `phoenix_api_key`
- `phoenix_project_name`

Но они **не вынесены в first-class admin settings section** и не проходят через отдельный UI workflow.

То есть включить sink в принципе можно, а удобно и явно настроить его из operator UI — нет.

Именно здесь находится лучший шанс сделать observability-интеграции «легкими» для пользователя.

## 4.7. Config-модель слишком плоская

`gpt2giga/core/config/settings.py` содержит около `65` `Field(...)`. Это прямой сигнал, что один config object несёт слишком много разных предметных областей:

- transport/runtime;
- security;
- observability;
- logging;
- provider runtime;
- file/body limits;
- storage.

Для runtime это ещё терпимо, но для UI и mental model это тяжело. Нужна более явная группировка, хотя бы на уровне внутренних submodels.

## 4.8. Документация частично дрейфует относительно реального runtime

Есть два вида проблемы:

### A. Непереносимые абсолютные пути

`COOL_UI.md` и `UI_PROGRESS.md` содержат ссылки вида `/Users/...`, то есть привязаны к конкретной локальной машине.

### B. Частично устаревшая модель UI packaging

`docs/architecture.md` описывает `gpt2giga/static/admin/` и `gpt2giga/templates/console.html` как основную runtime-истину, но текущий runtime фактически поднимает UI через optional package `gpt2giga_ui`.

Это не катастрофа, но это уже мешает refactor-работе, потому что contributor сначала должен понять, какая из двух моделей «настоящая».

## 4.9. Фронтенд-проверки почти отсутствуют как отдельный слой

TypeScript-компиляция есть — это хорошо. Но нет отдельной лёгкой frontend verification story:

- нет page/controller-level tests;
- нет smoke-тестов user interactions;
- нет гарантии, что после рефакторинга сложные страницы не поломают event wiring.

---

## 5. Что я бы считал целевой архитектурой

## 5.1. Backend: сделать control-plane отдельной domain area

Не нужно переписывать весь проект. Нужно отделить HTTP слой от control-plane domain logic.

### Целевое направление

```text
gpt2giga/
  api/
    admin/              # только HTTP, auth, request/response shape
  control_plane/
    runtime_snapshot/
    settings/
    observability/
    keys/
    usage/
    logs/
  app/
    factory.py
    wiring.py
    dependencies.py
  providers/
  features/
```

### Идея

- `api/admin/*.py` должны стать thin routes;
- payload building и mutation-logic должны переехать в domain services;
- observability config/state должен стать отдельным доменом, а не частью общих «application settings».

## 5.2. Config: сохранить совместимость, но ввести внутренние submodels

Например:

- `ApplicationSettings`
- `SecuritySettings`
- `ObservabilitySettings`
- `RuntimeStoreSettings`
- `GigaChatSettings`

Даже если ENV-переменные останутся прежними, внутренняя модель должна стать группированной. Это уменьшит когнитивную нагрузку и упростит UI mapping.

## 5.3. Frontend: страница = slice, а не один большой renderer

Для тяжёлых admin-страниц целевой shape должен быть таким:

```text
frontend/admin/pages/playground/
  index.ts
  state.ts
  api.ts
  view.ts
  bindings.ts
  serializers.ts
```

То же самое для:

- `logs`
- `traffic`
- `files-batches`
- `settings`
- `setup`

Главное правило: у page slice должны быть отдельные модули для state, DOM bindings и API orchestration.

## 5.4. UI information architecture: меньше top-level cognitive load

Я бы вёл UI к такому виду:

- `Overview`
- `Setup`
- `Settings`
  - General
  - GigaChat
  - Security
  - Observability
- `Keys`
- `Requests`
  - Recent traffic
  - Errors
  - Live logs
- `Playground`
- `Files & Batches`
- `System`
  - Providers
  - Runtime
  - Routes
  - Diagnostics

### Что это даёт

- `Logs` и `Traffic` перестают быть двумя почти соседними diagnostic surfaces и становятся одним workflow;
- observability становится first-class частью `Settings`, а не прячется в generic application form;
- `Providers` перестают ощущаться как отдельная почти-диагностическая витрина и становятся частью system posture.

Важно: это не обязательно делать одной большой миграцией. Сначала можно реализовать grouped navigation и shared request context, а уже потом объединять маршруты.

## 5.5. Observability: перейти от «списка sink-ов» к «каталогу интеграций»

### Целевой смысл

Вместо абстрактного CSV-поля оператор должен видеть:

- Prometheus
- OTLP
- Langfuse
- Phoenix

как отдельные интеграции с:

- статусом;
- обязательными полями;
- кратким описанием;
- кнопкой проверки;
- понятным failure message;
- подсказкой по compose/endpoint.

### Целевая модель

В коде нужен не только `ObservabilitySinkDescriptor`, но и metadata/schema layer, например:

- `id`
- `label`
- `description`
- `category`
- `required_settings`
- `secret_fields`
- `test_connection()`
- `build_runtime_sink()`

Тогда один и тот же descriptor можно использовать:

- в runtime;
- в admin API;
- в UI form rendering;
- в docs generation.

---

## 6. Пошаговый план действий для Codex gpt-5.4

## Общие правила выполнения

1. Не делать big-bang rewrite.
2. Работать маленькими slices, каждый slice — отдельный commit.
3. Не менять совместимость клиентских API без необходимости.
4. Сначала чинить source-of-truth и границы модулей, потом UI polish.
5. Сначала уменьшать количество понятий, а не просто количество строк.
6. После завершения каждой задачи или законченного slice фиксировать результат отдельным commit, а потом переходить к следующей работе.
7. После завершения каждой задачи или заметного шага обновлять `docs/codex-gpt-5.4-progress.md`, чтобы там оставалась актуальная история выполненной работы, проверок и следующих шагов.
8. Commit обязателен: нельзя оставлять завершённый slice только в рабочем дереве и переходить к следующему шагу без фиксации результата в git.

## Phase 0 — зафиксировать и расчистить основу

### Цель

Убрать самые опасные источники дрейфа до начала крупного рефакторинга.

### Задачи

- Определить один source-of-truth для shipped admin assets.
- Синхронизировать или удалить дубли между:
  - `gpt2giga/static/admin/`
  - `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/`
- Проверить, нужны ли вообще root `gpt2giga/templates/*` как runtime source.
- Обновить docs так, чтобы они описывали **реальную** UI packaging flow.
- Удалить или исправить абсолютные `/Users/...` ссылки из UI docs.

### Предпочтительное решение

Лучший вариант: сделать `packages/gpt2giga-ui/src/gpt2giga_ui/static/` единственным shipped output для UI package и либо:

- собирать TypeScript сразу туда;
- либо добавить явный sync-step `build:admin && sync:admin-package`.

### Acceptance criteria

- UI package и runtime используют один и тот же набор compiled assets;
- нет расхождения между shipped asset trees;
- contributor может за 1 минуту понять, какие файлы редактируются руками, а какие генерируются.

## Phase 1 — сделать observability first-class частью control plane

### Цель

Упростить настройку observability-интеграций и сделать её видимой в UI и admin API.

### Задачи

- Вынести observability в отдельную settings section.
- Добавить отдельный admin endpoint, например:
  - `/admin/api/settings/observability`
- Разделить:
  - глобальный toggle telemetry;
  - список активных sink-ов;
  - sink-specific settings.
- Создать typed internal model:
  - `ObservabilitySettings`
  - `OtlpSettings`
  - `LangfuseSettings`
  - `PhoenixSettings`
- Сохранить backward compatibility для текущих env names через aliases/adapter layer.

### UI задачи

- Добавить в `Settings` отдельную секцию `Observability`.
- Для каждого sink-а сделать понятную карточку:
  - status
  - required fields
  - endpoint/base_url
  - auth fields
  - test/export sample button
- Показать, что реально применится live, а что потребует restart.

### Acceptance criteria

- оператор может включить и настроить OTLP/Langfuse/Phoenix не через `.env`, а через UI/control-plane API;
- observability перестаёт быть CSV-полем в общей application форме;
- backend и UI используют одну и ту же schema/metadata model для sink-ов.

## Phase 2 — разрезать admin backend по доменам

### Цель

Сделать `api/admin/*` тонким HTTP слоем.

### Задачи

Извлечь сервисы/модули из:

- `gpt2giga/api/admin/runtime.py`
- `gpt2giga/api/admin/settings.py`

### Предлагаемые домены

- `runtime_snapshot`
- `capability_matrix`
- `usage_reporting`
- `key_management`
- `control_plane_updates`
- `observability_config`
- `logs_query`

### Практическое правило

Route handler должен в основном:

- валидировать вход;
- проверить доступ;
- вызвать domain service;
- вернуть JSON response.

А не строить большие payload-ы inline.

### Acceptance criteria

- route modules заметно уменьшаются;
- большие helper-функции переезжают в domain services;
- admin payload building покрыт focused tests.

## Phase 3 — упростить Setup / Settings как единый control-plane workflow

### Цель

Убрать дублирование и сделать first-run + day-2 configuration более понятными.

### Задачи

- Продолжить вынесение shared sections из `render-setup.ts` и `render-settings.ts`.
- Отделить shared control-plane form primitives от page-specific flow.
- Сделать единый reusable pattern для:
  - validation;
  - busy state;
  - inline status;
  - secret field updates;
  - pending diff;
  - live-apply vs restart-required messaging.

### UX-цель

`Setup` должен быть коротким guided flow, а `Settings` — полноценным редактором конфигурации, но не второй копией setup.

### Acceptance criteria

- меньше повторяющихся form sections;
- observability входит в единый config story;
- страницы читаются как разные workflow, а не как вариации одного giant form renderer.

## Phase 4 — разрезать тяжёлые admin pages на slice-архитектуру

### Цель

Сделать UI реально модульным, не меняя стек.

### Приоритет страниц

1. `playground`
2. `logs`
3. `traffic`
4. `files-batches`

### На каждой странице

Вынести отдельно:

- `state.ts`
- `api.ts`
- `view.ts`
- `bindings.ts`
- `serializers.ts`

### Что особенно важно

- убрать scattered mutable locals;
- минимизировать page-local ad hoc state;
- сократить количество прямых `querySelector(...)` и случайных cross-element связей;
- сократить `innerHTML` для highly-interactive участков;
- сделать cleanup/unsubscribe pattern единообразным.

### Acceptance criteria

- ни одна тяжёлая страница не остаётся giant renderer-файлом;
- page logic читается по модулям;
- state model виден отдельно от rendering.

## Phase 5 — облегчить сам UX, а не только код

### Цель

Сделать UI проще для оператора.

### Практические шаги

- Сгруппировать навигацию по сценариям:
  - Start
  - Configure
  - Observe
  - Diagnose
- Объединить `Logs` + `Traffic` в единый request workflow хотя бы на уровне navigation/state handoff.
- Показать summary-first view на верхних экранах.
- Убрать «слишком много панелей на одном экране» там, где можно сделать staged workflow.
- Для observability добавить понятные интеграционные пресеты:
  - Local Prometheus
  - Local OTLP collector
  - Local Langfuse
  - Local Phoenix

### Acceptance criteria

- новые пользователи могут пройти: setup -> key -> playground -> traffic без ощущения, что на них вывалили всю внутреннюю телеметрию сразу;
- observability настроить проще, чем сейчас;
- страницы перестают быть одновременно dashboard и workbench без приоритетов.

## Phase 6 — упростить provider-layer только после control-plane/UI

### Цель

Снизить когнитивную сложность provider mapping graph, но не лезть туда раньше времени.

### Задачи

- Сгруппировать `responses_*` helper-модули в более явную внутреннюю структуру.
- Привести naming к более понятной модели pipeline.
- Отдельно задокументировать:
  - chat flow
  - responses flow
  - v1/v2 backend path
- Удалить transitional compatibility shims, если тесты подтверждают, что они мёртвые.

### Почему это не Phase 1

Потому что основной pain сейчас не там. Самые заметные product-facing выигрыши лежат в UI, control plane и observability UX.

## Phase 7 — верификация и CI

### Цель

Сделать рефакторинг безопасным.

### Минимум

После каждого slice:

```bash
npm run build:admin
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/
```

### Дополнительно

Добавить lightweight frontend verification:

- минимум smoke на critical operator flows;
- unit-level проверки shared render/helpers;
- при возможности — 1-2 browser smoke сценария на setup/settings/playground.

---

## 7. Рекомендуемый порядок PR / commit slices

### PR 1

`refactor(ui-build): establish single source of truth for shipped admin assets`

### PR 2

`refactor(observability): introduce dedicated control-plane observability settings section`

### PR 3

`refactor(admin-ui): deduplicate setup and settings control-plane sections`

### PR 4

`refactor(admin-ui): split playground into state/api/view/bindings modules`

### PR 5

`refactor(admin-ui): split logs and traffic into request-workflow slices`

### PR 6

`refactor(admin-ui): split files-batches into workflow modules`

### PR 7

`refactor(admin-api): extract runtime snapshot and usage reporting services`

### PR 8

`refactor(admin-api): extract control-plane update and key management services`

### PR 9

`refactor(config): group observability/runtime settings into internal submodels`

### PR 10

`docs: align architecture, packaging, and observability operator guides with real runtime`

---

## 8. Что Codex делать не должен

- Не делать полный rewrite frontend на React/Vue «потому что так проще». Это сейчас не обязательно.
- Не смешивать visual redesign и structural refactor в одном большом проходе.
- Не трогать provider-layer раньше, чем будет понятный выигрыш по operator UX и control-plane modularity.
- Не плодить новые альтернативные UI entrypoints.
- Не оставлять несколько «почти одинаковых» compiled asset trees без явного source-of-truth.
- Не превращать admin API route modules в место, где заново собирается вся доменная логика.

---

## 9. Сигналы успеха

Рефакторинг можно считать успешным, если после него одновременно выполняются следующие условия:

- новый contributor понимает build/runtime story admin UI без археологии по репозиторию;
- observability-интеграции настраиваются как first-class feature, а не как набор скрытых env-полей;
- `api/admin/*` читается как transport layer, а не как место, где живёт вся бизнес-логика;
- тяжёлые UI pages разрезаны на понятные page slices;
- navigation и UX стали проще даже без редизайна на новый фреймворк;
- provider compatibility и operator capabilities сохранились;
- docs описывают реальную систему, а не прошлую версию её packaging flow.

---

## 10. Готовый briefing для Codex gpt-5.4

Ниже текст, который можно дать Codex как рабочую рамку.

```text
Ты работаешь в репозитории gpt2giga на ветке feature/extend_capabilities.

Цель:
1) сделать репозиторий более модульным и проще для сопровождения;
2) упростить admin/operator UI без смены стека;
3) сделать observability integrations first-class частью control plane и UI.

Ограничения:
- не делать big-bang rewrite;
- не переходить на тяжёлый frontend framework без жёсткой необходимости;
- сохранять совместимость существующих OpenAI/Anthropic/Gemini-compatible API surfaces;
- работать малыми PR-sized slices;
- после каждого slice обновлять docs и прогонять quality gate.

Приоритет работ:
1. Исправить UI packaging/build drift и определить single source of truth для shipped admin assets.
2. Вынести observability в отдельную control-plane/settings область с dedicated admin API и UI section.
3. Продолжить дедупликацию setup/settings shared sections.
4. Разрезать тяжёлые admin pages (playground, logs, traffic, files-batches) на page slices: state/api/view/bindings/serializers.
5. Извлечь admin domain services из api/admin/runtime.py и api/admin/settings.py.
6. Только после этого упрощать provider-layer naming/grouping.

Правила реализации:
- route modules должны становиться тоньше;
- observability config должен быть schema-driven и пригодным и для runtime, и для admin UI;
- UI должен стать summary-first и workflow-oriented;
- не допускать параллельных невалидируемых compiled asset trees;
- каждый шаг должен быть тестируемым и обратимым.

Definition of done для каждого slice:
- npm run build:admin
- uv run ruff check .
- uv run ruff format --check .
- uv run pytest tests/
- docs обновлены под реальное поведение системы
```
