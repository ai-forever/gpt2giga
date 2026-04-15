# Прогресс по плану Codex gpt-5.4

Дата старта: 2026-04-15
План: [codex-gpt-5.4-plan-2026-04-15.md](./codex-gpt-5.4-plan-2026-04-15.md)

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

### Проверка

- `npm run build:admin` проходит и пишет output в `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/`.
- Точечные admin UI тесты проходят при явном отключении telemetry в окружении:
  - `GPT2GIGA_ENABLE_TELEMETRY=false uv run pytest tests/integration/app/test_api_server.py::test_admin_static_assets_are_served tests/integration/app/test_admin_console_settings.py::test_console_routes_are_available tests/integration/app/test_system_router_extra.py::test_admin_ui_ok tests/integration/app/test_system_router_extra.py::test_admin_ui_warning_banner`
- Более широкий прогон тех же integration-файлов упирается в отдельную проблему локального observability-окружения:
  - без `GPT2GIGA_PHOENIX_BASE_URL` часть тестов падает на инициализации Phoenix sink;
  - при `GPT2GIGA_ENABLE_TELEMETRY=false` остаются telemetry-specific падения там, где тесты ожидают включённый Prometheus/runtime telemetry.

### Дальше

- Закрыть Phase 0 полностью коротким telemetry-stable verification story для admin/integration тестов.
- После этого переходить к Phase 1: выделение observability в отдельную control-plane settings section и API.
