# Admin Frontend Review Worklog

Дата: 2026-04-17

Этот файл нужен как отдельный журнал работ по задачам из [admin-frontend-review-2026-04-17.md](./admin-frontend-review-2026-04-17.md).
Эти задачи нужно делать, потому что review уже зафиксировал конкретные проблемы по безопасности, UX и accessibility в `/admin`.

Обязательное правило по этой серии работ:
- законченные срезы нужно фиксировать отдельными коммитами;
- после каждого завершённого и проверенного среза нужен отдельный commit;
- нельзя оставлять готовые изменения только в рабочем дереве.

## Текущий срез

- [x] Завести отдельный файл-журнал по этой серии задач.
- [x] Закрыть P1 XSS в аварийном page fallback.
- [x] Закрыть P1 XSS в image preview `alt`.
- [x] Добавить защиту от потери несохранённых изменений для setup/settings.
- [x] Добавить `prefers-reduced-motion`.
- [x] Исправить misleading `cursor: wait` у disabled-кнопок.
- [x] Пересобрать admin frontend.
- [x] Прогнать адресные проверки.
- [x] Сделать отдельный commit завершённого среза.

## Что делаю сейчас

Сейчас в работе первый практический срез из review:
- P1 security fixes для string-based rendering;
- unsaved changes guard для setup/settings;
- быстрые accessibility/UX правки из списка `Сначала` / `Потом`.

## Результат текущего среза

- error fallback в `gpt2giga/frontend/admin/app.ts` теперь экранирует текст ошибки перед вставкой в HTML;
- image preview в `gpt2giga/frontend/admin/pages/files-batches/bindings.ts` больше не собирается через небезопасную HTML-строку для `alt`, а создаётся через DOM API;
- setup/settings формы публикуют dirty-state в `AdminApp`, и переходы внутри SPA плюс `beforeunload` теперь предупреждают о потере несохранённых изменений;
- в `console.css` добавлены `prefers-reduced-motion` и корректный `cursor: not-allowed` для disabled-кнопок.

## Проверка

- `npm run build:admin`
- `git diff --check -- gpt2giga/frontend/admin packages/gpt2giga-ui/src/gpt2giga_ui/static/admin docs/admin-frontend-review-2026-04-17-worklog.md`
- live-check через `curl -sfI http://localhost:8090/admin` не выполнен: локальный сервер в момент проверки не отвечал

## Следующий срез

- [x] Отфильтровать browser/admin noise из primary recent request/error summaries.
- [x] Убрать support/UI routes из OpenAI-family coverage в `Providers` и `System`.
- [x] Пересобрать admin frontend.
- [x] Прогнать адресные проверки.
- [x] Зафиксировать отдельным commit.

## Результат следующего среза

- `/admin/api/requests/recent` и `/admin/api/errors/recent` теперь по умолчанию скрывают operator-noise (`/`, `/favicon.ico`, `/robots.txt`, `/admin*`, docs/openapi/logs support routes) из primary summaries; для точечной диагностики шум можно вернуть через `include_noise=true`;
- `Providers` и `System` больше не относят `/`, `/favicon.ico` и `/robots.txt` к OpenAI-facing coverage, а трактуют их как operator support/admin surface;
- интеграционные тесты закрепляют оба поведения: filtered-by-default recent feeds и opt-in возврат шума.

## Проверка следующего среза

- `npm run build:admin`
- `uv run ruff check gpt2giga/app/_observability/feeds.py gpt2giga/app/observability.py gpt2giga/app/admin_runtime.py gpt2giga/api/admin/runtime.py tests/integration/app/test_system_router_extra.py`
- `uv run pytest tests/integration/app/test_system_router_extra.py -k 'recent_endpoints or operator_noise'`
