# Compatibility Facades Policy

Этот документ фиксирует lifecycle policy для compatibility facades, wrappers и shim-слоёв в `gpt2giga`.

Цель: сохранить понятные публичные import/API точки после внутренних refactor-ов, но не накапливать бесконечный слой "старых путей на всякий случай".

## Классы facade-слоёв

В репозитории используются три разных класса совместимости. Они не равны по lifecycle и не должны поддерживаться по одним и тем же правилам.

| Класс | Что это | Статус |
|---|---|---|
| Stable public facade | Канонический import path, который остаётся внешней точкой входа, даже если реализация уехала во внутренний underscore-пакет или helper-модули | Долговременный контракт |
| Migration wrapper | Плоский или старый import path, сохранённый только для мягкого перехода на новый canonical path | Временный слой |
| Legacy HTTP/API shim | Устаревший route или alias, который сохраняется на переходный период и явно помечен deprecated/alternate | Временный слой с runtime-сигналом |

## 1. Stable public facades

Эти модули считаются поддерживаемыми import facade-слоями и не должны удаляться просто потому, что реализация стала внутренней:

| Public facade | Internal source of truth | Почему считается стабильным |
|---|---|---|
| `gpt2giga.app.observability` | `gpt2giga.app._observability.*` | Используется как общий runtime/import surface для middleware и admin runtime |
| `gpt2giga.app.telemetry` | `gpt2giga.app._telemetry.*` | Публичная точка подключения sink-ов и registry |
| `gpt2giga.app.runtime_backends` | `gpt2giga.app._runtime_backends.*` | Стабильный runtime backend facade, зафиксирован в docs и tests |
| `gpt2giga.core.config.control_plane` | `gpt2giga.core.config._control_plane.*` | Стабильный control-plane facade для bootstrap/persistence helpers |
| `gpt2giga.app.admin_settings` | `gpt2giga.app._admin_settings.*` | Публичная service boundary для admin settings/control-plane flow |
| `gpt2giga.app.admin_runtime` | `gpt2giga.app._admin_runtime.*` | Публичная service boundary для admin runtime snapshots/usage |
| `gpt2giga.features.batches.validation` | `gpt2giga.features.batches._validation.*` | Канонический feature-level validation entrypoint |
| `gpt2giga.features.responses.stream` | `gpt2giga.features.responses._streaming.*` | Канонический feature-level streaming facade |
| `gpt2giga.providers.gigachat.responses.input_normalizer` | split helpers inside `gpt2giga.providers.gigachat.responses.*` | Канонический structured Responses import path после split-а |
| `gpt2giga.core.config.settings` | `gpt2giga.core.config._settings.*` | Канонический config surface, включая env aliases и grouped views |

Правила для stable public facades:

1. Внешние и cross-package импорты должны идти через facade, а не через underscore-internal package.
2. Внутреннюю реализацию можно дробить и переносить, пока facade сохраняет имя и контракт.
3. Удаление или переименование такого facade допускается только как сознательное breaking change с:
   - обновлением docs и AGENTS guidance
   - release note/changelog записью
   - заменой всех first-party import-ов на новый канонический путь
4. Новые underscore-internal split-ы должны по умолчанию оставлять старый верхнеуровневый модуль как stable facade, если этот модуль уже фигурирует в docs, tests, examples или cross-package imports.

## 2. Migration-only wrappers

Эти wrapper-ы сохраняются не как долгосрочный API surface, а только чтобы не ломать старые import path-ы мгновенно.

Сейчас в дереве репозитория нет активных migration-only import wrapper-ов.

Исторический пример:

- плоские top-level structured Responses wrapper-ы вида `responses_request_mapper.py`
- были удалены после перевода first-party import-ов на `gpt2giga.providers.gigachat.responses.*`

Правила для migration wrappers:

1. Не добавлять новые first-party imports на wrapper-путь, если уже существует canonical path.
2. Docs, examples и новые тесты должны ссылаться на canonical path, а не на wrapper.
3. Wrapper должен оставаться thin re-export без новой логики.
4. Wrapper можно удалить только если выполнены все условия:
   - `rg` по репозиторию не показывает first-party usage вне compat/regression tests
   - docs/examples уже переведены на canonical path
   - в changelog или release notes был явно зафиксирован переход
   - удаление не ломает заявленные integration/extension scenarios, которые проект ещё обещает поддерживать

Практическое правило: если wrapper нужен только для старых локальных import-ов внутри самого репозитория, это не повод держать его бесконечно.

## 3. Legacy HTTP/API shims

Эта группа относится не к Python import path-ам, а к старым route/alias поверх текущего admin/API surface.

Сейчас в дереве репозитория нет активных legacy HTTP/API shim-ов.

Исторический пример:

- `/logs`, `/logs/stream`, `/logs/html`
- alias `gpt2giga.api.admin.logs.verify_logs_ip_allowlist()`

Правила для legacy HTTP/API shims:

1. Shim должен быть явно помечен deprecated, если это технически возможно.
2. Shim должен указывать replacement path или alternate target.
3. Новые клиенты и docs не должны строиться на legacy route/alias.
4. Удаление shim-а допустимо только после переходного периода минимум в один release cycle, когда:
   - replacement documented
   - deprecation signal уже публиковался
   - integration docs/examples больше не используют legacy path

## Как принимать решение при новом refactor-е

Если модуль разбивается на внутренние части, задайте три вопроса:

1. Этот путь уже выступает documented/public import boundary?
   Тогда оставляем stable public facade.
2. Это только старый путь после реорганизации структуры?
   Тогда оставляем migration wrapper и сразу фиксируем canonical replacement.
3. Это старый HTTP/API endpoint для мягкого перехода?
   Тогда делаем legacy shim с явным deprecation signal.

Если ни один из трёх пунктов не подходит, новый compatibility layer, скорее всего, не нужен.

## Contributor checklist

Перед добавлением или сохранением wrapper/facade проверьте:

1. Указан ли canonical source of truth.
2. Понятно ли, permanent это facade или migration-only wrapper.
3. Не начали ли новые модули импортировать временный wrapper вместо canonical path.
4. Нужно ли добавить или обновить compat/regression test на re-export.
5. Нужно ли обновить `docs/architecture.md`, `gpt2giga/AGENTS.md` или integration docs.
