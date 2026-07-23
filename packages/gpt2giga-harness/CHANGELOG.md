# Changelog

Все значительные изменения в проекте gpt2giga-harness документированы в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.0.0/),
и проект придерживается [Семантического версионирования](https://semver.org/lang/ru/).

## [0.4.1a1] - 2026-07-23

### Добавлено
- **Trace-to-Replay comparisons**: Runs Center может повторить сохранённую задачу в новой session, изменив ровно одну ось — model, provider, Harness или extensions — и показать content-addressed сравнение исходного и нового run без автоматического применения изменений.
- **Reviewed first-run bootstrap**: `giga bootstrap preview|apply|status|rollback` отделяет read-only discovery от явно выбранных обратимых шагов, связывает apply с точным plan hash и откатывает только неизменённые пути, созданные Harness.
- **Симуляция permissions**: preflight CLI и Workbench заранее показывают effective filesystem, command, network, secret, integration, provider и Git/GitHub permissions для точного route snapshot; deny блокирует запуск, а runtime-dependent и provider-owned действия не выдаются за гарантированное разрешение.
- **Compatibility guardian**: `giga compatibility check --json` и read-only API проверяют зафиксированные окна Codex, Claude и Gemini CLI, native protocols, Adapter/Integration SDK schemas и marketplace contracts до model-backed execution.
- **Truthful handoff capsules**: `giga handoff capsule` и Runs Center создают проверяемый content-free снимок задачи, evidence, environment, pending approvals и ограничений continuity для передачи между Harness без запуска target или заявления ложного resume.

## [0.4.0a1] - 2026-07-23

### Добавлено
- **Канонический терминальный Workbench**: bare `giga` запускает встроенный Textual TUI с навигацией по проектам и сессиям, созданием и продолжением диалогов, потоковыми событиями, evidence/resources, approvals, handoff и изолированным native terminal; attach mode подключается к уже запущенному Harness без неявного fallback.
- **Provider-native CLI facade**: буквальные пространства `giga codex|claude|gemini` сохраняют provider-owned argv, stdin/stdout/stderr, JSON/JSONL, сигналы и exit status на L0, используют явный terminal handoff на L1 и допускают L2 Workbench только по проверенным контрактам Codex, Claude и Gemini; `giga completion` и doctor показывают стабильную границу и локальное состояние transport.
- **Git и GitHub environments**: Workbench и TUI показывают bounded snapshot ветки, HEAD, worktree, staged/unstaged/untracked state, upstream и read-only GitHub checks/runs; commit, non-force push и создание pull request выполняются только через отдельные immutable preview и approval, связанные с точным локальным и remote state.
- **Portable Extension Packs**: один exact-version plan может собрать проверенный Skill и MCP package для всех совместимых Codex, Claude, Gemini и Harness-managed targets с матрицей совместимости, явными permissions и компенсируемыми apply/recovery/rollback.
- **Reviewed Arena verdicts**: завершённое сравнение принимает оценки всех кандидатов и одного выбранного победителя, связывает решение с точным hash набора evidence и показывает eligibility выбранного run для promotion; verdict неизменяем, а изменившиеся кандидаты требуют нового сравнения.

### Изменено
- **TUI входит в базовый пакет**: Textual теперь является проверенной прямой runtime dependency, `giga tui` остаётся compatibility alias, а интерактивные `chat`, `run --agent` и выбранные `session` actions переходят в единый TUI; JSON, dry-run, pipe/redirect, CI и административные команды остаются неинтерактивными.
- **Единый Workbench protocol**: TUI, Cockpit и native integration packs используют общие action events, resource projections, session state и terminal dispatch вместо параллельных transcript/runtime реализаций.

### Исправлено
- **Fail-closed native и GitHub paths**: неподдерживаемый structured transport деградирует без поломки opaque passthrough, а auth, repository mismatch, remote race, network-loss и permission failures GitHub классифицируются без утечки command output или credentials.
- **Terminal UX и lifecycle**: исправлены запуск канонического TUI, управление active session, bounded streaming, keyboard/mouse interactions, terminal resize/cancel и завершение процессов без потери machine-readable CLI контрактов.

## [0.3.0a1] - 2026-07-20

### Добавлено
- **Provider-neutral providers и routes**: добавлены пользовательские профили для OpenAI-, Anthropic- и Gemini-compatible API, отдельные route/model defaults, reference-only authentication, bounded health/model discovery и опциональный preset `gpt2giga` вместо обязательной связи Harness с gateway.
- **Безопасная миграция providers**: legacy defaults можно преобразовать только после deterministic dry-run и проверенного pre-upgrade backup; операция повторно проверяет исходное состояние под lock, сохраняет журнал и допускает rollback только восстановлением исходного архива.
- **Библиотека Skills, Plugins и MCP**: добавлены offline-first каталог, portable Skills, first-party starter pack, Codex/Claude/Gemini MCP targets, Codex/Claude Plugins, Gemini extensions и preview SDK для внешних adapter/integration packages.
- **Федеративное обнаружение интеграций**: metadata из `skills.sh` и NeuralDeep можно импортировать как immutable Skill или exact MCP plan; catalog presence, popularity и correlation никогда не дают install authority и не заменяют pin/integrity официального источника.
- **Target-scoped installation lifecycle**: single-target и all-Harness flows связывают preview и approval с точными package/artifact hashes, scope, permissions и target ownership, затем предоставляют verification, update, compensation, recovery и rollback с безопасным `managed_home` по умолчанию.
- **Generated documents в Cockpit**: сохранённые файлы можно скачать через bounded SDK endpoint, а self-contained HTML с scripts открыть в sandboxed preview без выдачи forms, external network или same-origin authority.

### Изменено
- **Integrations как Plugin Library**: Cockpit объединяет встроенные и внешние Skills/MCP с отдельными source filters, target-aware status и явными Add/preview/apply действиями; Settings управляет providers, routes и models через backend-authoritative read-back.
- **Provider-neutral base package**: базовый `gpt2giga-harness` больше не устанавливает gateway и GigaChat SDK неявно; интеграция с текущим gateway остаётся точным optional extra `gpt2giga==0.2.4a1`.

### Исправлено
- **Workbench и сообщения**: исправлены скачивание generated files, full-response Copy/Edit actions, document scrolling, изменяемый composer и layout shell на desktop/mobile.
- **Plugin lifecycle**: connection state сбрасывается после disconnect/reload, а загрузка большой библиотеки использует bounded projections без лишней повторной работы.

## [0.2.0a1] - 2026-07-18

### Добавлено
- **Provider-neutral execution contracts**: добавлены строгие content-free ссылки providers/routes, разрешение `SecretRef` только на границе исполнения, неизменяемые execution snapshots, versioned structured session links и ограниченный JSON-RPC supervisor с generation isolation, backpressure и approval bridge.
- **Нативные structured providers**: Codex app-server, Gemini ACP и Claude provider handoff получили проверяемые lifecycle-контракты; durable runs, workflows, schedules, Arena и Eval могут использовать структурированные native transports без смешивания provider-owned и Harness-owned state.
- **Adapter SDK conformance kit**: внешний adapter package может проверить entry points, metadata, capabilities, redaction и offline lifecycle до установки в Harness.
- **Действия с сообщениями**: кнопка Copy загружает и копирует полный сохранённый ответ assistant, даже если read model показывает bounded preview; карандаш загружает полный user prompt в composer для изменения и повторного запуска.
- **Версия CLI**: `giga --version` и `gpt2giga-harness --version` печатают версию установленного дистрибутива.

### Изменено
- **Structured Workbench по умолчанию**: поддерживаемые coding harness используют `native_structured` как основной execution transport, сохраняя явный выбор one-shot и native terminal там, где они доступны.
- **Чистый source distribution**: PyPI sdist больше не включает TypeScript sources, frontend-тесты, Vite/ESLint configs и npm lockfile; детерминированно собранные content-addressed Cockpit assets остаются в sdist и wheel.
- **Компактные Cockpit assets**: дублирующие `.br`/`.gz` больше не хранятся в репозитории и wheel; integrity-bound identity assets сжимаются gzip в памяти при локальной отдаче.

### Исправлено
- **Live-события Codex subagents**: fallback rollout теперь читается во время активного turn, поэтому вызовы и вложенная tool activity появляются сразу, а не только после завершения или отмены.
- **Быстрый вывод версии**: console entrypoint обрабатывает `giga --version` до импорта FastAPI, providers, UI и runtime.
- **Разметка Cockpit**: подпись «Рабочая область» центрирована в узком primary rail, а disclosure результата и длинные детали Codex subagents больше не смещаются и не обрезаются при focus/wrapping.
- **Read-model и UI lifecycle**: инициализация session read index сериализована, а cold-start timeout встроенного UI worker увеличен до реалистичного значения.

## [0.1.0b1] - 2026-07-17

### Изменено
- **Нативная Automation**: Cockpit теперь создаёт и редактирует agents, workflows и schedules через типизированные backend API, сохраняя optimistic revision checks и явные действия оператора вместо копирования YAML-команд вручную.
- **Одновременная Arena**: сравнение нескольких harness перестроено как набор независимых чатов с параллельным стартом, отдельной историей и follow-up для каждого участника.
- **Рендеринг сообщений**: Cockpit использует стандартный Markdown pipeline с безопасным HTML, подсветкой кода, таблицами, task lists и локально упакованным KaTeX.
- **Настройки моделей Cockpit**: модели по умолчанию для чатов и генерации заголовков теперь выбираются независимо из discovery-списка и сохраняются в backend-owned Harness Settings; Workbench и headless run используют сохранённый выбор без model-id, зашитого в клиент или session runner.
- **Rollout Cockpit V2**: пакетный React cockpit теперь открывается как локальный UI по умолчанию, прежние top-level deep links перенаправляются в канонические Workbench, Runs, Automation, Evaluation или Integrations, а `/legacy/**` остаётся release-level путём отката без миграции retained state. Новые Cockpit streams подключаются к durable live tail, а retained history остаётся в bounded snapshots, поэтому открытие большого завершённого run не прокручивает через браузер все сохранённые events. ETag read model получает новый process namespace, чтобы restart, смена data-dir или rollback не переиспользовали устаревший browser snapshot с тем же SQLite generation.

### Исправлено
- **Codex continuity**: app-server resume сохраняет историю разговора и активность subagents, включая `output_text` из предыдущих turns, а Workbench показывает связанные события без потери структуры.
- **Lifecycle UI**: readiness выбранного route не теряется при durable retry, UI worker pool настраивается явно, а graceful shutdown ограничен по времени.

### Добавлено
- **Политика зависимостей базовой установки**: clean wheel installs теперь запускают versioned audit для десяти проверенных прямых dependencies, лимита 64 resolved distributions и явных семейств исключений Office, remote channels, external clients и sandbox providers; optional providers остаются отдельно устанавливаемыми интеграциями, а не скрытыми базовыми зависимостями.
- **Контракт doctor для CI и support**: `giga doctor --json` теперь включает стабильную identity отчёта, версии packages/Python/platform и существующие evidence совместимости внешних CLI; `--fail-on blocked|degraded` задаёт явную CI exit policy, а `--output` атомарно записывает каноническое redaction-safe вложение для issue с mode `0600`.
- **Окна поддержки внешних CLI**: version-aware probes теперь требуют одновременно проверенные capabilities и объявленную minor-линию Codex CLI `0.144.x`, Claude Code `2.1.x` или Gemini CLI `0.46.x`; слишком старые и потерявшие обязательные флаги версии получают `unsupported`, а новые или неразбираемые версии — машинно-читаемый `degraded` и остаются fail-closed до обновления fixtures и окна поддержки.
- **Offline restore state и compatibility gate**: `giga state restore` теперь проверяет и переносит приватный backup в staging перед явной атомарной заменой, отклоняет активный или параллельно меняющийся destination, сохраняет file modes и SQLite integrity, принимает старые runtime schemas для forward migration при следующем открытии и fail-closed отклоняет schemas новее установленного Harness. Package rollback восстанавливает pre-upgrade архив вместо попытки reverse migration.
- **Детерминированный backup пользовательского state**: `giga state backup` теперь создаёт атомарный versioned content-addressed архив quiescent Harness data directory с согласованными SQLite snapshots, защитой от transient files и symbolic links и mode `0600`; `giga state verify` проверяет manifest hashes, безопасные пути, ZIP integrity и каждую сохранённую SQLite database перед обновлением или откатом.
- **Оставшиеся поверхности Cockpit V2**: Automation теперь объединяет Agents, Workflows и Schedules, Evaluation — Arena, Evals и Baselines, а Integrations — Harnesses, Models & routes, MCP и selected-plan Doctor; вторичная вкладка и выбранная запись сохраняются в deep link, React немедленно ограничивает ответы content-free projections, а run/eval/baseline/probe/doctor остаются отдельными действиями существующих API при сохранении legacy-маршрутов.
- **Вертикали Cockpit Workbench и Runs**: opt-in React-клиент теперь реализует канонический путь Work → Run → Evidence → Review → Reuse поверх bounded projections сессий/runs и durable live tail, показывает реальное состояние ownership, trace, artifacts, approvals, Attention, apply и promotion и сохраняет approval, apply и promotion отдельными явными операциями с responsive-управлением панелями Workbench.
- **Event-driven Cockpit streams**: run events теперь передаются через per-run уведомления, durable opaque cursor и `Last-Event-ID` вместо 250 мс full-state polling; heartbeat подхватывает межпроцессные записи, ограниченные client queues требуют явный resnapshot при backpressure, а React stream store пакетирует presentation deltas по animation frame, приоритизирует control events и предоставляет bounded virtualization, scroll-anchor и incremental Markdown primitives.
- **Ограниченная read model Cockpit**: additive индексированные lookup сессий/runs, ограниченные по байтам и cursor страницы messages/runs/events/artifacts, ETag-bound snapshots и ленивые projections raw/diff/report заменяют full-bundle чтение при запуске Cockpit V2; клиент отменяет устаревшие scopes, дедуплицирует параллельные запросы, изолирует ответы вне порядка и точечно обновляет cache entries.
- **Асинхронный UI data plane**: все FastAPI routes теперь имеют исчерпывающие контракты workload, storage/execution owner, deadline, cancellation, idempotency, payload, cursor и latency; filesystem, SQLite, network, subprocess, durable-job и SSE работа проходит через workload-bounded offload, а content-free диагностика показывает event-loop lag, queue/DB/storage/handler/serialization timing, response bytes и счётчики cancellation.
- **Пакетный shell Cockpit V2**: добавлен закреплённый React/TypeScript/Vite frontend с пятью route-split поверхностями, ленивыми inspector-модулями, детерминированным content-hashed manifest, integrity-bound Brotli/gzip assets, CSP-safe same-origin загрузкой и wheel smoke без Node; legacy cockpit остаётся явным recovery route.

- **Policy conformance для mutation-маршрутов**: все unsafe-method маршруты Harness API теперь входят в единый fail-closed semantic inventory с effect class, enforcement control и owner, стабильными permission actions там, где они применимы, и retained evidence для allow/ask/deny/stale/redaction; создание приложения и CI отклоняют неклассифицированные маршруты.
- **Бюджеты производительности Cockpit**: packaged shell публикует и проверяет machine-readable бюджеты для веса critical assets, времени first-ready, размера/rendering большого trace DOM, cursor reconnect и ограниченных diff/report preview; полный retained report и явные copy, open и apply остаются доступны отдельно.
- **Readiness выбранного запуска**: CLI/API/UI preflight до spawn показывает redaction-safe `ready`/`degraded`/`blocked` checks и remediation только для выбранных harness, invocation mode, route/model, workspace policy и durable/synchronous path; нерелевантные сбои не блокируют локальный Echo.

## [0.0.1a3] - 2026-07-15

### Добавлено
- **Переход от review к reuse**: rail в Work теперь ведёт подходящий успешный run к его точному provenance/promotion inspector, а preview/apply promotion и scheduling остаются отдельными явными действиями оператора.
- **Переход от evidence к review**: rail в Work теперь ведёт от terminal evidence к Diff точного сохранённого worktree при наличии изолированного patch, а apply и approval остаются отдельными явными действиями оператора.
- **Переход от запуска к evidence**: Work показывает компактный путь Run → Evidence после начала первого запуска и включает deep link на сохранённый trace именно этого run в Runs Center только после terminal completion.
- **Cross-harness review team**: reviewed-пример параллельно запускает read-only роли explorer, security, tests и maintainability через Codex, Claude и Gemini, сохраняет durable evidence каждого child при частичном сбое и синтезирует цитируемые artifacts без общего writable workspace.
- **Nightly compatibility guardian**: reviewed-пример содержит pinned Codex/Claude/Gemini eval, baseline с точными adapter dimensions, read-only triage регрессий и durable nightly schedule, работающий без UI.
- **Пример reviewed patch**: disposable issue fixture содержит reviewed-профили planner, изолированного implementer и read-only reviewer, durable workflow и post-apply eval; mutation исходного checkout, apply, commit, push и hosted writes остаются явными решениями оператора.
- **Офлайн-демо первого запуска**: disposable-репозиторий с вымышленными inventory-данными проверяет `giga init`, redaction-safe диагностику, локальный Echo read run и сгенерированный smoke eval, хранит runtime state внутри копии демо и не требует credentials, proxy, внешнего agent CLI или публичной сети.
- **Диагностика первого запуска**: `giga doctor [workspace] --json` теперь формирует redaction-safe отчёт о готовности proxy, routes, models, версий CLI-адаптеров, workspace и Git, durable worker, managed homes и MCP snapshots, добавляет исполнимые remediation-команды и читает runtime state без записи.
- **Capability matrix**: команда `giga harness capabilities` генерирует проверяемые Markdown и JSON представления непосредственно из runtime parity contracts встроенных CLI-адаптеров.
- **Доказательства идемпотентных side effects**: durable runtime умеет атомарно резервировать непрозрачные токены Harness-owned side effects и сохранять неизменяемые редактированные completion evidence, не разрешая автоматический retry произвольных edit-attempts.
- **Ограниченный side-effect executor**: Harness-owned runtime events теперь связывают резервирование токена, durable outbox delivery и неизменяемое completion evidence в одной транзакции; повторная доставка переиспользует готовое evidence, а неоднозначные reservations остаются заблокированными.
- **Durable recovery marker**: opt-in durable job хеширует перед сохранением переданный opaque side-effect token и записывает один фиксированный Harness-owned marker через атомарный executor; retry после потери owner переиспользует completed evidence, а неоднозначная reservation завершается безопасным отказом.
- **Policy audit evidence**: reviewed promotion теперь сохраняет append-only hash chain для policy resolution, решения пользователя, точного enforcement owner, approval grant и source/patch binding; audit rows запрещают изменение и удаление.
- **Lineage reviewed evidence**: успешно выполненные reviewed operations теперь публикуют проверенный content-addressed evidence manifest через runtime export, provenance запуска, replay requests и promotion запуска в agent/workflow/eval без раскрытия raw approval bindings или captured content.
- **Доказательства GigaChat-совместимости**: завершённые headless-запуски Codex, Claude и Gemini теперь публикуют content-addressed provenance для наблюдаемого маршрута `gpt2giga`, запрошенных model/API mode и нормализованных stream, tool, usage, error и cancellation semantics без сохранения prompt или response content.

### Исправлено
- **Attention для scheduled eval**: после успешного `test-now` точного schedule hash следующий failed eval приостанавливает schedule и создаёт один retained Attention item с кратким scorecard.
- **Durable scheduled evals**: повторная доставка одного schedule occurrence теперь использует исходный target run вместо создания второго eval/job, а scorecard, запущенный worker-ом, сохраняется в state directory разрешённого Harness-проекта.
- **Reviewed promotion**: подтверждение `git.apply` теперь одноразово связано с точными source commit, SHA-256 сохранённого patch и branch intent; устаревший source, изменённый patch и повторное связывание approval завершаются отказом до изменения checkout.

## [0.0.1a2] - 2026-07-14

### Добавлено
- **Безопасный запуск native CLI**: перед стартом или возобновлением Codex, Claude и Gemini выполняются проверки executable capabilities, workspace, proxy route и process-spawn policy; требующие доверия действия получают явное подтверждение.
- **Durable native terminals**: состояние и ownership PTY-процессов сохраняются в coordination store с crash reconciliation и контролируемым завершением process group; терминал поддерживает SSE с replay через `Last-Event-ID`, cursor polling fallback и изменение размера PTY из браузера.
- **Очередь интерактивных сообщений**: активный Harness-run можно прервать, а следующие turns — поставить в durable-очередь и видеть рядом с composer до последовательной отправки.
- **Attachment transports**: адаптеры объявляют поддержку конкретных типов вложений и способ доставки; Harness строит проверяемый render plan для prompt references, CLI flags, staged paths и metadata-only inputs.
- **Compatibility evidence**: добавлены version-aware probes Codex, Claude и Gemini CLI, adapter parity contracts, live compatibility telemetry и матрицы Eval Lab на основе структурированных capability-событий.

### Изменено
- **Headless adapter profiles**: model, reasoning effort, permission/workspace policy, бюджеты и разрешённые/запрещённые tools теперь применяются как capability-checked immutable snapshot; доверенные managed MCP profiles материализуются в изолированные CLI homes без изменения native-конфигурации пользователя.
- **Продолжение внешних CLI-сессий**: Codex использует supervised app-server threads для многоходового headless continuity с interrupt; Harness сохраняет opaque runtime links и явно сообщает ограничения continuation для адаптеров без безопасного resume-контракта.
- **Release contract**: Harness теперь точно зависит от `gpt2giga==0.2.3a2`, а публикация `gpt2giga-harness` использует PyPI Trusted Publishing.
- **Документация**: добавлено отдельное описание архитектуры, границ безопасности, потоков headless/native исполнения и полного control-plane API на русском и английском.

### Исправлено
- **Native session continuity**: resume snapshots теперь сохраняют модель, API route, permission mode и workspace; discovery и reconciliation восстанавливают историю Codex, Claude и Gemini без изменения vendor-owned homes и без дублирования turns.
- **Gemini CLI**: исправлены доставка initial prompt, закрепление выбранной модели, синхронизация live-ответов, отображение startup/runtime ошибок и стабильность многоходовых native-разговоров.
- **Claude Code**: исправлены запуск с managed MCP-конфигурацией и закрепление выбранной GigaChat-модели для headless/native запросов.
- **Tool activity**: native streams теперь показывают tool calls/results Claude и Gemini, включая активность Claude subagents, не смешивая её с обычным текстом ассистента.

## [0.0.1a1] - 2026-07-13

Первый отдельный alpha-релиз локального agentic control plane. API, форматы
хранимого состояния и automation-контракты линии `0.0.x` пока не считаются
стабильными.

### Добавлено
- **Отдельный дистрибутив и CLI**: добавлен пакет `gpt2giga-harness` с Python namespace `gpt2giga_harness`, командами `giga` и `gpt2giga-harness`, plugin entry-point group `gpt2giga.harnesses` и точной зависимостью от `gpt2giga==0.2.3a1`.
- **Project Cockpit**: добавлен локальный FastAPI UI с packaged no-build assets, project-aware навигацией, историей сессий, inspector, live-событиями, терминалом и автоматическим запуском durable worker.
- **Встроенные Harness-адаптеры**: добавлены Direct Chat, Codex CLI, Claude Code, Gemini CLI и Echo с общими contract metadata, проверкой доступности, выбором модели/API mode и безопасным запуском gateway sidecar.
- **Native sessions**: добавлены discovery, индексация и импорт существующих сессий Codex, Claude и Gemini, а также managed native processes, terminal streaming, attachments, project scoping и интерактивное подтверждение доверия к workspace.
- **Проекты и контекст**: добавлены `.giga/` project config, session scoping, workspace references, attachments, локальный preview файлов и изображений, project memory, run presets, reusable agent profiles и настраиваемые пути к исполняемым файлам в `~/.gpt2giga/harness/config.toml`.
- **Безопасные edit-flow**: добавлены изолированные worktrees, lease/policy checks, preview и approval перед применением изменений, editor/terminal bridges и PR-ready artifacts.
- **Durable runtime**: добавлены SQLite coordination store, worker leases, retries, cancellation, crash reconciliation, run provenance, replay и восстановление незавершённых jobs.
- **Оркестрация**: добавлены versioned workflows, reusable agents, команды и handoffs между агентами, promotion успешных runs, schedules и центр автоматизаций.
- **Выбор и сравнение Harness**: добавлены deterministic Smart Router, multi-Harness Arena с отдельными workspace и compatibility Eval Lab с локальными матрицами результатов.
- **Tools, MCP и policy**: добавлены общие tool/secret contracts, discovery и dry-run синхронизация MCP profiles, managed MCP configuration, preflight diagnostics и approval-gated действия.
- **Диагностика и документация**: добавлены `giga doctor`, inspect/config/session/native команды, alpha quickstart, migration guide и описание ограничений первого релиза.
---

[0.4.1a1]: https://github.com/ai-forever/gpt2giga/compare/gpt2giga-harness-v0.4.0a1...gpt2giga-harness-v0.4.1a1
[0.4.0a1]: https://github.com/ai-forever/gpt2giga/compare/gpt2giga-harness-v0.3.0a1...gpt2giga-harness-v0.4.0a1
[0.3.0a1]: https://github.com/ai-forever/gpt2giga/compare/gpt2giga-harness-v0.2.0a1...gpt2giga-harness-v0.3.0a1
[0.2.0a1]: https://github.com/ai-forever/gpt2giga/compare/gpt2giga-harness-v0.1.0b1...gpt2giga-harness-v0.2.0a1
[0.1.0b1]: https://github.com/ai-forever/gpt2giga/compare/gpt2giga-harness-v0.0.1a3...gpt2giga-harness-v0.1.0b1
[0.0.1a3]: https://github.com/ai-forever/gpt2giga/compare/gpt2giga-harness-v0.0.1a2...gpt2giga-harness-v0.0.1a3
[0.0.1a2]: https://github.com/ai-forever/gpt2giga/compare/gpt2giga-harness-v0.0.1a1...gpt2giga-harness-v0.0.1a2
[0.0.1a1]: https://github.com/ai-forever/gpt2giga/releases/tag/gpt2giga-harness-v0.0.1a1
