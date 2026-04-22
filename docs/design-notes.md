# Design Notes

Этот документ фиксирует спорные, но текущие осознанные решения в `gpt2giga`.

Это не обещание, что решение будет вечным. Это объяснение, почему проект устроен так сейчас, какие правила из этого следуют для contributor-ов и по каким сигналам решение стоит пересматривать.

## 1. Frameworkless admin UI

### Статус

Принято и сохраняется как базовое направление.

### Решение

Admin console продолжает развиваться как frameworkless TypeScript UI, который отдается самим Python runtime как статический asset bundle.

Исходники живут в `gpt2giga/frontend/admin/`, а runtime/package потребляют собранный output из `packages/gpt2giga-ui/src/gpt2giga_ui/`.

### Почему так

- Проект в первую очередь Python-first и packaging-first, а не отдельный frontend product.
- Для operator UI здесь важнее низкая инфраструктурная стоимость, чем полноценный SPA stack.
- Текущий подход держит JavaScript dependency surface маленьким и не добавляет отдельный React/Vite lifecycle в release-процесс.
- UI уже показывает, что frameworkless подход жизнеспособен при дисциплине вокруг `api`, `state`, `serializers`, `view`, `bindings`.

### Что это означает для contributor-ов

- Не тащить React/Vue/Svelte как "локальное удобство" для одной страницы.
- Новые страницы и крупные правки должны следовать page-folder pattern вместо возвращения к giant single-file bindings.
- Pure helpers, URL/state serializers и DOM-independent logic нужно выносить в тестируемые модули раньше, чем добавлять новую imperative DOM orchestration.

### Когда пересматривать

Решение стоит пересмотреть, если одновременно выполняется хотя бы часть следующих условий:

- runtime package начнет собирать frontend как отдельный build artifact без committed output;
- появится потребность в сложной client-side компонентной модели, которую уже нельзя поддерживать discipline-only модульностью;
- frontend начнет требовать тяжелого state/runtime composition, который заметно дороже поддерживать вручную, чем через минимальный framework.

## 2. Committed compiled admin assets

### Статус

Временно обязательное решение, продиктованное текущим packaging/release flow.

### Решение

Скомпилированные admin assets под `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/` должны оставаться в git вместе с изменениями исходников в `gpt2giga/frontend/admin/`.

### Почему так

- `Dockerfile` собирает Python wheel-ы без Node.js build step.
- publish/release flow для `gpt2giga-ui` и Docker image использует repository state как source of truth.
- Runtime монтирует именно файлы из optional UI package, а не пересобирает frontend при старте.

Иными словами: пока pipeline не умеет сам собирать frontend на publish path, некоммиченный generated output означает риск shipping stale assets.

### Что это означает для contributor-ов

1. Меняете `gpt2giga/frontend/admin/*`.
2. Запускаете `npm run sync:admin`.
3. Коммитите и TS source, и обновленный generated output.

`npm run check:admin` и `CI` дополнительно проверяют, что после rebuild под `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/` не остается diff-а.

### Когда пересматривать

Это решение нужно упростить или снять, если:

- Docker/publish pipeline начнет гарантированно собирать frontend сам;
- runtime package перестанет зависеть от committed JS/CSS output в репозитории;
- появится reproducible release path, где source-to-artifact sync проверяется без хранения generated assets в git.

## 3. Граница feature vs provider mapping

### Статус

Ключевое архитектурное правило. Его нужно сохранять даже при рефакторинге внутренних модулей.

### Решение

Внешние provider surfaces и HTTP transport не должны напрямую собирать GigaChat transport payload или выбирать backend execution path. Оркестрация capability идет через feature layer, а backend-specific mapping живет в `gpt2giga/providers/gigachat/`.

### Разделение ответственности

- `gpt2giga/api/*`: HTTP transport, auth/governance dependencies, request parsing, provider-specific response formatting.
- `gpt2giga/features/*`: capability orchestration, metadata-store interaction, continuation flow, execution policy.
- `gpt2giga/providers/<external-provider>/*`: provider descriptors и thin capability adapters для внешнего surface.
- `gpt2giga/providers/gigachat/*`: backend-specific request/response mapping и upstream transport details.

### Почему так

- Один и тот же capability flow должен переиспользоваться разными external provider surfaces без дублирования GigaChat-specific transport logic.
- Router-ы остаются thin и не накапливают branching по backend `v1`/`v2`.
- Feature layer может централизованно управлять stores, runtime policy и compatibility behavior, не размазывая эту логику по каждому provider surface.

### Красные флаги

Нарушением границы обычно являются такие изменения:

- router сам выбирает `achat` против `achat_v2`;
- router или provider presenter напрямую строит native GigaChat payload;
- provider package начинает зависеть от transport-format helpers чужого surface;
- metadata stores для files, batches или responses начинают обслуживаться из transport layer вместо feature service.

### Что это означает для contributor-ов

- Новый provider surface добавляется как transport + provider descriptor поверх существующих feature services.
- Новые backend-specific helper-ы для GigaChat должны жить под `gpt2giga/providers/gigachat/`, а не в `api/<provider>/` и не в `features/*`.
- Если логика нужна нескольким provider surfaces, сначала проверяйте, не относится ли она к canonical feature orchestration, а не к конкретному wire format.

### Когда пересматривать

Пересмотр уместен только если изменится сам продуктовый контур, например:

- proxy перестанет быть GigaChat-centric и появятся несколько равноправных backend engines;
- capability orchestration перестанет быть общей для разных external surfaces;
- текущая feature/provider boundary начнет систематически мешать расширению, а не защищать от дублирования.

## Связанные документы

- [architecture.md](./architecture.md) — текущий request/runtime flow и правила по admin asset lifecycle.
- [how-to-add-provider.md](./how-to-add-provider.md) — практический workflow добавления нового external provider-а поверх этой границы.
- [../README.md](../README.md) — быстрый старт, release surface и contributor команды.
