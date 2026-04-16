# PLANS.md — gpt2giga refactor ExecPlan for Codex / GPT-5.4

Дата: 2026-04-16
Статус: текущий рабочий план для следующей волны рефакторинга.

Этот файл должен использоваться как **живой execution plan**. Он заменяет старые широкие планы как основной источник правды для **оставшейся** работы по рефакторингу. Исторические документы можно читать для контекста, но выполнять нужно этот план.

## Как использовать этот файл

Перед началом работы прочитай:

1. `AGENTS.md`
2. этот `PLANS.md`
3. `docs/refactor-worklog.md`
4. `docs/architecture.md`
5. `docs/codex-gpt-5.4-progress.md` только как исторический журнал уже выполненных фаз

Рекомендуемый prompt для Codex:

> Read `AGENTS.md` and `PLANS.md`. Execute the next unchecked milestone in `PLANS.md`. Keep `PLANS.md` and `docs/refactor-worklog.md` updated as living documents. Run the listed verification commands. Commit after each green change slice and after each green milestone using a conventional commit. Do not ask for next steps unless blocked by missing credentials or a required product decision.

## Что уже сделано и что НЕ нужно переделывать

Считай эти задачи уже закрытыми и не открывай их заново без очень сильной причины:

- source-of-truth для shipped admin UI уже переведён на `packages/gpt2giga-ui/src/gpt2giga_ui/static/`;
- `api/admin/runtime.py` и `api/admin/settings.py` уже сведены к thin HTTP layer поверх app-level services;
- observability уже вынесена в отдельную control-plane settings section и UI flow;
- тяжёлые admin pages (`playground`, `logs`, `traffic`, `files-batches`) уже разрезаны на page slices;
- `providers/gigachat/responses/` уже стал внутренним source of truth для structured Responses pipeline;
- grouped internal config views для `security`, `observability` и `runtime_store` уже добавлены и частично внедрены.

Не трать новую итерацию на повторное «улучшение того же самого». Следующий refactor должен концентрироваться на оставшихся backend hot spots и release/guardrail проблемах.

## Цели этой волны рефакторинга

1. Снизить когнитивную нагрузку в самых тяжёлых backend-модулях.
2. Убрать архитектурную протечку, где feature-layer зависит от transport-layer formatting helpers.
3. Зафиксировать guardrails, чтобы проблема не вернулась.
4. Исправить release/CI мелочи, которые всё ещё могут ломать shipped результат.
5. Сохранить текущее поведение, совместимость и тестовое покрытие.

## Не-цели

- не добавлять новые продуктовые фичи;
- не менять внешние HTTP API, payload schema, env names или control-plane file format;
- не переписывать frontend ещё раз «с нуля»;
- не мигрировать стек на другой framework;
- не удалять vendored `gigachat-0.2.2a1-py3-none-any.whl` в рамках этой волны, если это не требуется для прохождения тестов;
- не делать big-bang rename imports по всему репозиторию.

## Жёсткие ограничения

- Совместимость Python: `3.10`–`3.14`.
- Следовать текущим Starlette/FastAPI conventions из `AGENTS.md`.
- Не добавлять тяжёлые новые зависимости. Для architecture guardrails предпочесть простой AST-based test вместо нового линтера.
- Если меняется внутренняя структура модуля, **сохранять текущие public import paths** через тонкие facade/re-export модули.
- Если меняется `gpt2giga/frontend/admin/**`, править исходники только там, затем запускать `npm run build:admin`, а generated JS в `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/` коммитить как build artifact.
- После каждого milestone обновлять этот файл: что сделано, что проверено, что дальше.
- После каждого заметного шага обновлять `docs/refactor-worklog.md`.
- После каждого завершённого change slice делать отдельный commit; нельзя переходить к следующему slice с незакоммиченным завершённым результатом.
- После каждого закрытого milestone делать отдельный commit.

## Текущее состояние hot spots

На момент подготовки этого плана основные крупные backend-модули выглядят так:

- `gpt2giga/app/telemetry.py` — ~1350 строк
- `gpt2giga/app/observability.py` — ~1145 строк
- `gpt2giga/app/runtime_backends.py` — ~871 строк
- `gpt2giga/app/admin_settings.py` — ~846 строк
- `gpt2giga/core/config/settings.py` — ~795 строк
- `gpt2giga/features/responses/stream.py` — ~791 строк
- `gpt2giga/core/config/control_plane.py` — ~735 строк
- `gpt2giga/app/admin_runtime.py` — ~684 строк

Самый явный точечный smell сейчас:

- `gpt2giga/features/chat/stream.py` и `gpt2giga/features/responses/stream.py` импортируют formatter functions из `gpt2giga.api.openai.streaming`, то есть feature-layer зависит от transport-layer.

Также остаются process issues:

- CI не проверяет `npm run build:admin`;
- `.github/workflows/docker_image.yaml` публикует одинаковые теги `latest` и `${version}` из **каждой** Python matrix job, что создаёт гонку тегов;
- `docker_image.yaml` не триггерится на изменения в `packages/gpt2giga-ui/**`, `package.json`, `package-lock.json`, `tsconfig.json`;
- в репозитории всё ещё лежат мусорные `.ipynb_checkpoints/*`, хотя `.gitignore` уже их игнорирует.

## Общая стратегия

Используй pattern **internal split + stable facade**:

- новая логика уходит во внутренний подпакет с ведущим underscore, например `gpt2giga/app/_telemetry/`;
- старый модуль (`gpt2giga/app/telemetry.py`) остаётся тонким фасадом и переэкспортирует публичные классы/функции;
- так мы уменьшаем размер implementation modules без массового import churn по репозиторию.

Не делай один огромный refactor. Работай узкими зелёными срезами.

---

# Milestones

## Milestone 0 — Guardrails, CI, release hygiene

### Зачем

Прежде чем резать тяжёлые модули, нужно зафиксировать базовые guardrails, иначе можно сделать красивый refactor и снова получить regressions в сборке или архитектуре.

### Что сделать

- [x] Удалить мусорные файлы из `.ipynb_checkpoints/`.
- [x] Добавить в CI отдельную проверку admin frontend build:
  - `npm ci`
  - `npm run build:admin`
- [x] Исправить `.github/workflows/docker_image.yaml`:
  - plain `${version}` и `latest` должны публиковаться только из **одной** canonical matrix job;
  - остальные jobs могут публиковать только versioned `pythonX.Y` теги.
- [x] Расширить `paths:` в `docker_image.yaml`, чтобы изменения в UI package и build-конфигах реально пересобирали image:
  - `packages/gpt2giga-ui/**`
  - `package.json`
  - `package-lock.json`
  - `tsconfig.json`
- [x] Добавить лёгкий architecture regression test, который запрещает импорт `gpt2giga.api.openai.streaming` из `gpt2giga/features/**` и `gpt2giga/providers/**`.

### Важно

Не добавляй новый tooling ради этого. Достаточно простого теста на `ast` или `pathlib + rg` style logic внутри `tests/unit/`.

### Проверка

Выполнить:

```bash
npm ci
npm run build:admin
uv run ruff check .github/workflows tests
uv run ruff format --check tests
uv run pytest tests/unit -q
```

Если workflow менялся существенно, дополнительно сделать хотя бы `git diff --check`.

### Commit

`ci: add frontend build and docker publish guardrails`

---

## Milestone 1 — Убрать transport leakage из feature streaming

### Зачем

Сейчас feature-layer зависит от `gpt2giga.api.openai.streaming`. Это неправильное направление зависимости. Formatter helpers должны жить в нейтральном слое, а transport/router код может их импортировать, но не наоборот.

### Что сделать

- [x] Создать нейтральный formatter module, например:
  - `gpt2giga/core/http/sse.py`

  или другой эквивалентный путь в `core/`, если он лучше ложится в текущую архитектуру.
- [x] Перенести туда и стабилизировать три helper-а:
  - `format_chat_stream_chunk`
  - `format_chat_stream_done`
  - `format_responses_stream_event`
- [x] Сделать `gpt2giga/api/openai/streaming.py` тонким compatibility facade, который просто реэкспортирует эти функции.
- [x] Перевести:
  - `gpt2giga/features/chat/stream.py`
  - `gpt2giga/features/responses/stream.py`
  на импорт из нового нейтрального модуля.
- [x] Обновить или добавить targeted tests так, чтобы запрет на старую зависимость был pinned.

### Проверка

```bash
uv run ruff check gpt2giga/core/http gpt2giga/api/openai/streaming.py gpt2giga/features/chat/stream.py gpt2giga/features/responses/stream.py tests
uv run ruff format --check gpt2giga/core/http gpt2giga/api/openai/streaming.py gpt2giga/features/chat/stream.py gpt2giga/features/responses/stream.py tests
uv run pytest tests/unit/api/openai/test_stream_generators.py tests/integration/openai/test_router_endpoints.py -q
```

### Commit

`refactor: move openai sse formatting out of transport layer`

---

## Milestone 2 — Разрезать `features/responses/stream.py` без смены поведения

### Зачем

Это один из самых дорогих по чтению модулей во всём backend-е. Внутри смешаны:

- orchestration;
- SSE event sequencing;
- state mutation;
- v1/v2 divergence;
- tool progress handling;
- image hydration;
- failure mapping.

При этом existing test suite для stream behavior уже достаточно сильный, значит это хороший кандидат на безопасный split.

### Целевая форма

Сделать внутренний подпакет:

- `gpt2giga/features/responses/_streaming/events.py`
- `gpt2giga/features/responses/_streaming/state.py`
- `gpt2giga/features/responses/_streaming/v1.py`
- `gpt2giga/features/responses/_streaming/v2.py`
- `gpt2giga/features/responses/_streaming/failures.py`

Допустимы небольшие отклонения по именам, но смысл должен сохраниться:

- event formatting/sequencing отдельно;
- mutable stream state отдельно;
- v1 path отдельно;
- v2 path отдельно;
- error/failure emission отдельно.

### Что сделать

- [ ] Оставить `gpt2giga/features/responses/stream.py` как стабильный public entrypoint.
- [ ] Вынести `ResponsesStreamEventSequencer` и близкие helper-ы в отдельный internal module.
- [ ] Вынести legacy v1 flow в отдельный internal module.
- [ ] Вынести v2-specific state handling, tool state, function-call state и image hydration из giant function.
- [ ] Максимально заменить deep nested dict mutation на небольшие локальные helpers или typed state objects, но без переписывания semantics.
- [ ] Сохранить event order, status transitions, sequence numbers и error behavior **бит-в-бит по возможности**, потому что tests уже на это опираются.

### Важные правила

- Не менять публичное имя `stream_responses_generator`.
- Не менять фактический wire-format SSE событий.
- Не менять semantics `response.created`, `response.in_progress`, `response.completed`, `response.incomplete`, tool progress events и function_call delta events.
- Не объединять одновременно с этим milestone другие unrelated refactors.

### Проверка

Минимум:

```bash
uv run ruff check gpt2giga/features/responses tests/unit/api/openai/test_stream_generators.py
uv run ruff format --check gpt2giga/features/responses tests/unit/api/openai/test_stream_generators.py
uv run pytest tests/unit/api/openai/test_stream_generators.py -q
uv run pytest tests/integration/openai/test_router_endpoints.py -q
```

Если тесты зелёные, дополнительно полезно прогнать:

```bash
uv run pytest tests/unit/providers/gigachat/test_responses_v2.py -q
```

### Commit

`refactor: split responses streaming implementation`

---

## Milestone 3 — Разрезать `app/observability.py` и `app/telemetry.py` через internal packages

### Зачем

Это сейчас крупнейшая оставшаяся зона сложности в репозитории. При этом здесь уже есть реальная архитектура: feeds, audit events, usage accounting, sink registry, hub, Prometheus/OTLP/Langfuse/Phoenix. Значит нужен не rewrite, а аккуратный structural split.

### Целевая форма

Создать два внутренних подпакета:

- `gpt2giga/app/_observability/`
- `gpt2giga/app/_telemetry/`

Примерное разбиение:

`gpt2giga/app/_observability/`
- `models.py` — `RequestAuditUsage`, `RequestAuditMessage`, `RequestAuditEvent`
- `feeds.py` — accessors и feed-oriented helpers
- `usage.py` — usage accounting / aggregation helpers
- `messages.py` — message extraction / normalization / summarization
- `context.py` — request-local metadata helpers
- `recording.py` — `record_request_event`, setters и orchestration
- `filters.py` — `filter_request_events`, `query_request_events`

`gpt2giga/app/_telemetry/`
- `contracts.py` — `ObservabilitySink`, descriptors
- `hub.py` — `ObservabilityHub`
- `registry.py` — register/create helpers
- `prometheus.py` — Prometheus sink + exposition helpers
- `otlp.py` — OTLP encoding / headers / HTTP payload builders
- `langfuse.py` — Langfuse-specific OTLP wrapping
- `phoenix.py` — Phoenix/OpenInference-specific mapping
- `encoding.py` — shared OTLP attribute serialization helpers

Имена можно немного скорректировать, но публичные точки входа должны остаться прежними.

### Что сделать

- [ ] Свести `gpt2giga/app/observability.py` к thin facade/re-export layer.
- [ ] Свести `gpt2giga/app/telemetry.py` к thin facade/re-export layer.
- [ ] Сохранить все текущие public class/function names и import paths.
- [ ] Не менять current sink registry contract.
- [ ] Не менять metrics exposition format и не ломать existing tests.
- [ ] По возможности сделать так, чтобы новый implementation file редко превышал ~400–500 строк; если одна тема всё равно остаётся больше, это должно быть осознанно и локально оправдано.

### Важные правила

- Не менять публичные env-driven semantics observability config.
- Не менять payload mapping для Langfuse/Phoenix/OTLP без тестов.
- Не смешивать этот milestone с большим UI refactor.

### Проверка

```bash
uv run ruff check gpt2giga/app tests/unit/core/test_telemetry.py tests/unit/api/test_middleware.py tests/unit/app/test_admin_runtime.py tests/unit/app/test_admin_settings.py
uv run ruff format --check gpt2giga/app tests/unit/core/test_telemetry.py tests/unit/api/test_middleware.py tests/unit/app/test_admin_runtime.py tests/unit/app/test_admin_settings.py
uv run pytest tests/unit/core/test_telemetry.py tests/unit/api/test_middleware.py tests/unit/app/test_admin_runtime.py tests/unit/app/test_admin_settings.py -q
uv run pytest tests/integration/app/test_admin_console_settings.py tests/integration/app/test_system_router_extra.py tests/integration/app/test_api_server.py -q
```

### Commit

`refactor: split observability and telemetry internals`

---

## Milestone 4 — Разрезать runtime/control-plane implementation hotspots

### Зачем

После stream и observability следующими по цене чтения остаются runtime/control-plane internals. Здесь приоритет не на новые возможности, а на повышение читаемости и локальности изменений.

### Области

Первая очередь:

- `gpt2giga/app/runtime_backends.py`
- `gpt2giga/core/config/control_plane.py`

Вторая очередь, только если остаётся бюджет и все проверки зелёные:

- `gpt2giga/app/admin_settings.py`
- `gpt2giga/app/admin_runtime.py`

### Целевая форма

Для runtime backends:

- `gpt2giga/app/_runtime_backends/contracts.py`
- `gpt2giga/app/_runtime_backends/memory.py`
- `gpt2giga/app/_runtime_backends/sqlite.py`
- `gpt2giga/app/_runtime_backends/registry.py`
- `gpt2giga/app/_runtime_backends/provisioning.py`

Для control plane:

- `gpt2giga/core/config/_control_plane/paths.py`
- `gpt2giga/core/config/_control_plane/bootstrap.py`
- `gpt2giga/core/config/_control_plane/crypto.py`
- `gpt2giga/core/config/_control_plane/payloads.py`
- `gpt2giga/core/config/_control_plane/revisions.py`
- `gpt2giga/core/config/_control_plane/status.py`

### Что сделать

- [ ] Оставить старые top-level files как stable facade/re-export layer.
- [ ] Сохранить file layout и persisted payload semantics control-plane storage.
- [ ] Сохранить registry API для runtime backends.
- [ ] Не менять JSON schema ревизий, bootstrap token flow, secret encryption flow.
- [ ] Добавить/обновить targeted tests, если split требует новых import-stability assertions.

### Проверка

```bash
uv run ruff check gpt2giga/app gpt2giga/core/config tests/unit/core/test_runtime_backends.py tests/unit/core/test_control_plane.py tests/unit/app/test_admin_runtime.py tests/unit/app/test_admin_settings.py
uv run ruff format --check gpt2giga/app gpt2giga/core/config tests/unit/core/test_runtime_backends.py tests/unit/core/test_control_plane.py tests/unit/app/test_admin_runtime.py tests/unit/app/test_admin_settings.py
uv run pytest tests/unit/core/test_runtime_backends.py tests/unit/core/test_control_plane.py tests/unit/app/test_admin_runtime.py tests/unit/app/test_admin_settings.py -q
```

Если milestone включает админские сервисы, дополнительно:

```bash
uv run pytest tests/integration/app/test_admin_console_settings.py tests/integration/app/test_system_router_extra.py -q
```

### Commit

`refactor: split runtime and control plane internals`

---

## Stop condition

Если после Milestone 3 всё зелёное, но Milestone 4 начинает раздуваться или тянуть за собой слишком много incidental complexity, остановись после зелёного Milestone 3 и зафиксируй это в этом файле как разумную границу итерации.

Лучше закончить волну на хорошем промежуточном состоянии, чем размыть её одним слишком широким diff.

---

# Definition of done for this refactor wave

Можно считать волну успешной, если выполнено следующее:

- [x] Milestone 0 закрыт и закоммичен
- [x] Milestone 1 закрыт и закоммичен
- [ ] Milestone 2 закрыт и закоммичен
- [ ] Milestone 3 закрыт и закоммичен
- [ ] Milestone 4 закрыт **или осознанно остановлен** после зелёного Milestone 3 с записью причины
- [ ] `uv run ruff check .` зелёный
- [ ] `uv run ruff format --check .` зелёный
- [ ] `uv run pytest tests/ --cov=. --cov-fail-under=80` зелёный
- [ ] если трогался frontend: `npm run build:admin` выполнен и generated assets обновлены
- [ ] `AGENTS.md` и `docs/architecture.md` обновлены, если изменилась реальная структура модулей

---

# Progress log

## Milestone 0

### TODO

- [x] completed

### Done

- Удалены локальные мусорные `.ipynb_checkpoints/` директории из корня репозитория и `local/`.
- В `.github/workflows/ci.yaml` добавлен отдельный job `admin-build` с `npm ci` и `npm run build:admin`.
- В `.github/workflows/docker_image.yaml` матрица переведена на canonical job для plain version / `latest`, остальные jobs публикуют только Python-versioned tags.
- В `docker_image.yaml` расширены `paths:` для UI package и frontend build-конфигов.
- Добавлен AST-based guardrail test `tests/unit/core/test_architecture_guardrails.py`, который запрещает transport-layer import в `features/**` и `providers/**`.
- В `AGENTS.md` зафиксировано обязательное правило коммитить каждый завершённый зелёный slice.
- Создан отдельный журнал `docs/refactor-worklog.md`.

### Verification

- `npm ci`
- `npm run build:admin`
- `uv run ruff check .github/workflows tests gpt2giga/core/http gpt2giga/api/openai/streaming.py gpt2giga/features/chat/stream.py gpt2giga/features/responses/stream.py`
- `uv run ruff format --check tests gpt2giga/core/http gpt2giga/api/openai/streaming.py gpt2giga/features/chat/stream.py gpt2giga/features/responses/stream.py`
- `uv run pytest tests/unit -q`
- `git diff --check`

### Next

- Canonical `latest`/plain version image tags для Docker Hub и GHCR должны оставаться привязанными к Python `3.13`.
- Начать `Milestone 2`: разрезать `gpt2giga/features/responses/stream.py` через internal split + stable facade без изменения wire-format SSE.

## Milestone 1

### TODO

- [x] completed

### Done

- Создан нейтральный модуль `gpt2giga/core/http/sse.py` для общих SSE formatter helpers.
- `gpt2giga/api/openai/streaming.py` сведён к compatibility facade/re-export.
- `gpt2giga/features/chat/stream.py` и `gpt2giga/features/responses/stream.py` переведены на импорт из `gpt2giga.core.http.sse`.
- В `tests/unit/api/openai/test_stream_generators.py` добавлен targeted test на сохранение старого import path через фасад.
- Guardrail test из `Milestone 0` теперь реально pin-ит отсутствие transport leakage.

### Verification

- `uv run ruff check .github/workflows tests gpt2giga/core/http gpt2giga/api/openai/streaming.py gpt2giga/features/chat/stream.py gpt2giga/features/responses/stream.py`
- `uv run ruff format --check tests gpt2giga/core/http gpt2giga/api/openai/streaming.py gpt2giga/features/chat/stream.py gpt2giga/features/responses/stream.py`
- `uv run pytest tests/unit/api/openai/test_stream_generators.py tests/integration/openai/test_router_endpoints.py -q`
- `uv run pytest tests/unit -q`

### Next

- Переходить к `Milestone 2`; транспортная зависимость убрана, можно безопасно резать внутренности `features/responses/stream.py`.

## Milestone 2

### TODO

- [ ] not started

### Done

- _empty_

### Verification

- _empty_

### Next

- _empty_

## Milestone 3

### TODO

- [ ] not started

### Done

- _empty_

### Verification

- _empty_

### Next

- _empty_

## Milestone 4

### TODO

- [ ] not started

### Done

- _empty_

### Verification

- _empty_

### Next

- _empty_

---

# Review checklist for Codex before finishing any milestone

- [ ] diff не меняет внешнее API поведение без необходимости
- [ ] не появилось новых циклических импортов
- [ ] старые import paths продолжают работать через facade/re-export
- [ ] tests покрывают refactor seam, а не только happy path
- [ ] нет случайных unrelated formatting-only churn changes
- [ ] docs отражают реальную структуру, если структура поменялась
- [ ] generated admin assets обновлены только если менялся frontend source
