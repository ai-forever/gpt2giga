# Прогресс по плану Codex gpt-5.4

Дата старта: 2026-04-15
План: [codex-gpt-5.4-plan-2026-04-15.md](./codex-gpt-5.4-plan-2026-04-15.md)
Обязательно: после сделано нужно закоммитить изменения.

## Phase 0

### Сделано

- Проверил исходный drift admin UI: `npm run build:admin` писал в `gpt2giga/static/admin`, а runtime грузил shell и статику из optional package `gpt2giga_ui`.
- Подтвердил фактическое расхождение между двумя деревьями shipped asset-ов:
  - `gpt2giga/static/admin/forms.js`
  - `gpt2giga/static/admin/pages/control-plane-sections.js`
- Перевёл `tsconfig.json` на единый output path: `packages/gpt2giga-ui/src/gpt2giga_ui/static/`.
- Пересобрал admin UI и синхронизировал package assets; после сборки расхождение между деревьями исчезло.
- Удалил root-дубли `gpt2giga/static/admin/*` и `gpt2giga/templates/*`, которые не участвуют в runtime.
- Обновил ключевые docs под реальный packaging/runtime flow:
  - `README.md`
  - `AGENTS.md`
  - `gpt2giga/AGENTS.md`
  - `docs/architecture.md`
  - `COOL_UI.md`
  - `UI_PROGRESS.md`
  - `docs/refactor-tasks-2026-04-14.md`
- Убрал побочный эффект из `gpt2giga/app/cli.py`: `load_config()` больше не оставляет значения из `.env` в `os.environ` после построения `ProxyConfig`.
- Добавил regression test на отсутствие env-leak после `--env-path`, чтобы admin/integration тесты не зависели от локального `.env`.

### Проверка

- `npm run build:admin` проходит и пишет output в `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/`.
- Точечные admin UI тесты проходят при явном отключении telemetry в окружении:
  - `GPT2GIGA_ENABLE_TELEMETRY=false uv run pytest tests/integration/app/test_api_server.py::test_admin_static_assets_are_served tests/integration/app/test_admin_console_settings.py::test_console_routes_are_available tests/integration/app/test_system_router_extra.py::test_admin_ui_ok tests/integration/app/test_system_router_extra.py::test_admin_ui_warning_banner`
- Расширенный regression прогон теперь стабилен без ручного отключения telemetry:
  - `uv run pytest tests/unit/core/test_cli.py tests/integration/app/test_api_server.py tests/integration/app/test_admin_console_settings.py tests/integration/app/test_system_router_extra.py -q`
- Локализован и закрыт источник нестабильности:
  - `tests/integration/app/test_api_server.py::test_run_server` вызывал `load_config()`;
  - старое поведение `load_config()` подгружало корневой `.env` в процесс навсегда;
  - из-за этого последующие тесты неожиданно наследовали `GPT2GIGA_OBSERVABILITY_SINKS=phoenix`.

### Дальше

- Phase 0 можно считать закрытой: source-of-truth для shipped UI assets зафиксирован, docs синхронизированы, admin/integration verification не зависит от локального `.env`.
- Следующий шаг — Phase 1: выделение observability в отдельную control-plane settings section и API.

## Phase 1

### Сделано

- Добавлен отдельный backend slice для observability settings:
  - typed helper-модели в `gpt2giga/core/config/observability.py`;
  - новый admin endpoint `GET/PUT /admin/api/settings/observability`.
- Сгруппировал observability-конфиг поверх существующих flat `ProxySettings` полей, не ломая текущую совместимость:
  - `enable_telemetry`;
  - `observability_sinks`;
  - OTLP/Langfuse/Phoenix-specific поля.
- Новый endpoint возвращает safe UI-facing payload:
  - `active_sinks`;
  - `metrics_enabled`;
  - sink cards для `prometheus`, `otlp`, `langfuse`, `phoenix`;
  - `configured` / `missing_fields` / `live_apply` / `restart_required`;
  - masked/boolean presentation для secret-полей вместо raw secrets.
- Добавил persistence/update flow для grouped observability payload-ов через существующий control-plane config pipeline.
- Расширил admin settings integration coverage:
  - чтение grouped observability section;
  - запись OTLP/Phoenix настроек;
  - повторное чтение после persist/apply.
- Подключил observability backend slice к admin UI:
  - в `Settings` появился отдельный tab `Observability`;
  - telemetry toggle и sink-конфиг больше не живут внутри общего `application` form в day-2 settings flow.
- Добавил отдельный frontend payload/status flow для observability:
  - `buildObservabilityPayload(...)`;
  - pending diff/status summary для grouped sink payload-ов;
  - replace/clear UX для OTLP headers и Langfuse/Phoenix credential fields.
- UI теперь рендерит sink-specific cards для `prometheus`, `otlp`, `langfuse`, `phoenix` с:
  - enabled/configured статусом;
  - missing fields;
  - live-apply vs restart-safe подсказками;
  - sink-specific form controls.
- Расширил safe observability payload для UI:
  - top-level `otlp`, `langfuse`, `phoenix` sections;
  - masked previews для `langfuse_secret_key` и `phoenix_api_key`.
- Пересобрал shipped admin assets в `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/`.

### Проверка

- `npm run build:admin`
- `uv run pytest tests/integration/app/test_admin_console_settings.py -q`
- `uv run pytest tests/integration/app/test_system_router_extra.py::test_admin_ui_ok tests/integration/app/test_system_router_extra.py::test_admin_ui_warning_banner -q`
- `uv run pytest tests/unit/core/test_cli.py tests/integration/app/test_api_server.py tests/integration/app/test_admin_console_settings.py tests/integration/app/test_system_router_extra.py -q`
- `uv run ruff check gpt2giga/core/config/observability.py gpt2giga/api/admin/settings.py gpt2giga/app/cli.py tests/integration/app/test_admin_console_settings.py tests/unit/core/test_cli.py`
- `uv run ruff format --check gpt2giga/core/config/observability.py gpt2giga/api/admin/settings.py gpt2giga/app/cli.py tests/integration/app/test_admin_console_settings.py tests/unit/core/test_cli.py`

### Дальше

- Phase 1 по сути закрыта: observability стала first-class частью control plane и в backend, и в operator UI.
- Следующий шаг по плану — Phase 2: начать разрезать `gpt2giga/api/admin/settings.py` и `gpt2giga/api/admin/runtime.py` на domain-oriented services.
- Внутри observability ещё остаётся полезный follow-up, который можно делать уже как часть Phase 2/3:
  - label/description/category;
  - required settings;
  - live-apply vs restart semantics;
  - test/export actions.
