# Frontend Refactor Progress

Дата старта: 2026-04-16
Основной план: [codex-gpt-5.4-frontend-refactor-2026-04-16.md](/Users/riyakupov/code_projects/gpt2giga/docs/codex-gpt-5.4-frontend-refactor-2026-04-16.md)

## Правила ведения

- Этот файл обновляется после каждого законченного slice.
- Каждый законченный slice после релевантных проверок фиксируется отдельным commit.
- В журнале остаются только фактические изменения, проверки и следующий шаг.

## Slice Log

### Slice 1

Статус: `done`

Цель:

- подготовить инфраструктуру child pages и secondary nav;
- начать split `Setup` и `Settings` без смены frontend stack;
- обновить server-side console routes и route tests.

Планируемый объём:

- расширить `PageId` и route map;
- добавить shared helper для subpage navigation;
- перевести `Setup` в hub + step pages;
- перевести `Settings` в hub + section pages;
- завести совместимость для `settings?section=...`.

Фактически сделано:

- добавлены child pages и route metadata для `Setup`, `Settings`, `Files & Batches`;
- добавлен shared secondary nav helper и подключён в `Setup`, `Settings`, `Files & Batches`;
- `Setup` переведён в hub + отдельные страницы `claim/application/gigachat/security`;
- `Settings` переведён в hub + отдельные страницы `application/observability/gigachat/security/history`;
- добавлена compatibility-логика для `settings?section=...`;
- обновлены server-side console routes и integration test на доступность новых URL;
- runtime admin assets пересобраны через `npm run build:admin`.

Проверки:

- `npm run build:admin`
- `uv run pytest tests/integration/app/test_admin_console_settings.py tests/integration/app/test_system_router_extra.py -q`
- `uv run ruff check .`
- `uv run ruff format --check .`

Результат проверок:

- `npm run build:admin` — green
- `uv run pytest tests/integration/app/test_admin_console_settings.py tests/integration/app/test_system_router_extra.py -q` — 40 passed
- `uv run ruff check .` — green
- `uv run ruff format --check .` — green

Следующий шаг:

- выделить реальный focused split для `Files` / `Batches`, чтобы child pages перестали быть общим workbench с разными URL и получили отдельные surface-level layouts.
