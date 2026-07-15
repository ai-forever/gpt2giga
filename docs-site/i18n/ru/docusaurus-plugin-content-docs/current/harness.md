# Unified Harness

:::warning[Альфа-превью — активная разработка]

Линейка `gpt2giga-harness` 0.0.x — ранняя версия для тестирования и обратной
связи. UI, CLI, YAML-файлы проекта, схема runtime-хранилища и процесс обновления
могут меняться. Используйте Harness локально, для контролируемой работы под
наблюдением, а не как критичный production-сервис или удалённую multi-user
платформу.

:::

Unified Harness — локальный project cockpit поверх `gpt2giga`. В одном
интерфейсе можно запустить задачу через прямой GigaChat, Codex CLI, Claude Code,
Gemini CLI или plugin harness, сравнить результаты, разобрать ход выполнения и
решить, какие изменения разрешено вернуть в проект.

Это не ещё одна модель и не замена gateway или внешним CLI. Harness управляет
ими как control plane и хранит локальную нормализованную историю запусков,
approvals, артефактов и повторно используемой автоматизации.

## Зачем это нужно

У разных agent CLI разные команды, история, режимы разрешений и форматы
результатов. Unified Harness добавляет общий слой:

- **один cockpit проекта** — запуск из текущего репозитория через `giga ui`;
- **повторяемые сценарии** — agents, prompts, evals, workflows и schedules в
  `.giga/` вместо ручной настройки каждой задачи;
- **сравнение** — одна задача для нескольких доступных harness в Arena;
- **проверка до изменения** — edit-запуски в изолированных Git worktree, а
  apply и создание branch — только после явного approval;
- **прозрачность** — durable status, attempts, redacted events, артефакты,
  diff и provenance доступны после перезапуска браузера или UI;
- **локальный контроль** — конфигурация и runtime-история остаются на машине
  пользователя.

### Как связаны компоненты

| Слой | За что отвечает |
| --- | --- |
| Gateway `gpt2giga` | Даёт HTTP API в форматах OpenAI, Anthropic и Gemini с GigaChat в роли backend. |
| Unified Harness | Выбирает harness и модель, координирует запуски, хранит историю и предоставляет CLI/UI. |
| Direct Chat или agent CLI | Выполняет саму модельную или агентную работу. Внешний CLI отвечает за поведение внутри собственного процесса. |

Approval в Harness относится к действиям, которыми Harness действительно
владеет: например, запуску процесса или применению сохранённого patch. Harness
не обещает видеть каждое внутреннее действие непрозрачного Codex, Claude или
Gemini subprocess.

## Кому подходит альфа

Попробуйте preview, если хотите оценить локальный agent cockpit, сравнить
несколько harness, собрать проверяемый workflow или повлиять на интерфейсы
ранней обратной связью. Первые запуски делайте через `echo`, `--dry-run` и
режимы `plan`/`read` в тестовом репозитории.

Лучше дождаться следующей стадии, если вам уже сейчас нужны стабильный API
автоматизации, гарантированная обратная совместимость, high availability,
централизованное multi-user администрирование или полноценная security boundary
вокруг произвольных действий стороннего CLI.

Во время альфы:

- перед обновлением читайте release notes и делайте резервную копию
  `~/.gpt2giga/harness` и важных определений из `.giga/`;
- учитывайте, что интеграции зависят от конкретной версии Codex, Claude или
  Gemini CLI на машине;
- оставляйте UI на loopback-адресе по умолчанию, если намеренно не настроили
  remote authentication и TLS;
- проверяйте созданные `.giga/`-файлы перед commit и никогда не храните в них
  секреты;
- сообщайте об ошибках в [GitHub Issues](https://github.com/ai-forever/gpt2giga/issues),
  прикладывая вывод `giga doctor`, версию Harness, шаги воспроизведения и
  диагностику без секретов.

## Быстрый старт

### 1. Получите preview

Требуются Python 3.10–3.14 и `uv`. Текущий и всегда доступный путь для alpha —
запуск из source checkout:

```bash
git clone --branch feature/harness_enrichment \
  https://github.com/ai-forever/gpt2giga.git
cd gpt2giga
uv sync --all-packages --all-extras --dev
source .venv/bin/activate
giga doctor
giga harness list
```

Оставляйте virtual environment checkout активным в каждом терминале, где
работаете с preview. После этого можно перейти через `cd` в пользовательский
проект: команды `giga` и `gpt2giga` продолжат запускаться из checkout. В Windows
используйте `.venv\Scripts\Activate.ps1`.

После появления отдельного preview-пакета в вашем package index будет доступен
короткий вариант:

```bash
uv tool install --prerelease allow gpt2giga-harness
giga doctor
```

Для Direct Chat понадобятся credentials из [быстрого старта gpt2giga](quickstart.md).
Codex, Claude Code и Gemini — опциональные интеграции: соответствующий CLI
executable должен быть в `PATH` или задан явным override, а локальный gateway —
настроен и доступен. Для описанного Harness route отдельный vendor login не
нужен. Отсутствующий CLI будет недоступен, но не сломает остальной cockpit.

### 2. Инициализируйте тестовый проект

Начните с репозитория, где безопасно просмотреть созданные файлы и пробные
изменения:

```bash
cd /path/to/project
giga doctor .
giga doctor . --json
giga init
```

`giga doctor [workspace]` показывает готовность первого запуска до старта
агента. Структурированный вариант `--json` проверяет proxy и routes, model
discovery, версии внешних CLI, готовность workspace и Git, durable worker,
Harness-managed homes и managed MCP snapshots. Проверки получают статус
`ready`, `degraded` или `blocked`; для degraded и blocked prerequisites отчёт
предлагает remediation-команду. Secret values редактируются, абсолютный путь
workspace не публикуется, а существующий runtime worker state читается без
перезаписи.

`giga init` создаёт в `.giga/` non-secret конфигурацию, стартовые agent profiles,
prompts, smoke eval и review workflow. Существующие файлы не заменяются без
флага `--overwrite`.

Сначала проверьте локальный execution path через `echo` без credentials и сети:

```bash
giga harness run echo \
  --workspace . \
  --prompt "Кратко опиши выбранную задачу"
```

Для полностью локального знакомства используйте
[демо-репозиторий первого запуска](https://github.com/ai-forever/gpt2giga/tree/main/examples/harness/first-run-demo).
Он содержит только вымышленные inventory-данные. Инструкция копирует их во
временный Git-репозиторий, изолирует Harness runtime state внутри этой копии,
запускает `giga init` и `giga doctor .`, затем проверяет read-only Echo run и
два сгенерированных smoke-eval cases. Credentials, proxy, внешний agent CLI и
доступ в публичную сеть не требуются.

Model-backed
[пример issue-to-reviewed-patch](https://github.com/ai-forever/gpt2giga/tree/main/examples/harness/issue-to-reviewed-patch)
содержит три reviewed agent profiles, durable workflow с сохранением изменений
в Harness-owned worktree и post-apply eval. До approval source checkout остаётся
неизменным, а apply, commit, push и hosted writes выполняются только по явному
решению оператора.

Model-backed
[nightly compatibility guardian](https://github.com/ai-forever/gpt2giga/tree/main/examples/harness/nightly-compatibility-guardian)
содержит pinned Codex/Claude/Gemini eval, точные baseline dimensions,
read-only triage workflow и durable nightly schedule. Он работает при закрытом
UI и отправляет в Attention только failed-контракт, ранее прошедший test-now,
для классификации product/adapter/model/environment.

Model-backed
[cross-harness review team](https://github.com/ai-forever/gpt2giga/tree/main/examples/harness/cross-harness-review-team)
параллельно запускает read-only роли explorer, security, tests и maintainability
через Codex, Claude и Gemini. Единственный synthesis-шаг цитирует сохранённые
child artifacts; сбой одного child остаётся видимым, а частичные evidence не
могут быть молча представлены как успешный review.

Затем посмотрите план внешнего агента, не запуская его:

```bash
giga run \
  --agent codex \
  --mode read \
  --workspace . \
  --dry-run \
  "Кратко опиши этот репозиторий"
```

### 3. Подключите GigaChat

Настройте credentials и локальный API key по [основному quickstart](quickstart.md).
Для browser и durable-worker запусков держите gateway в отдельном терминале.
Активируйте в нём environment того же source checkout и запустите:

```bash
source /path/to/gpt2giga/.venv/bin/activate
gpt2giga
```

При установке tools отдельно установите gateway по основному quickstart, чтобы
команда `gpt2giga` была доступна в `PATH`, и запустите её без `uv run`.

Проверьте Direct Chat:

```bash
giga chat --api-mode v2 --model GigaChat-2-Max "Привет"
giga harness list
```

Одиночные CLI-запуски могут временно поднять loopback sidecar, если gateway
недоступен и реальные GigaChat credentials уже есть в окружении. Durable worker
намеренно не поднимает proxy автоматически: для browser workflows gateway
нужно держать запущенным отдельно.

### 4. Откройте cockpit

Из корня нужного проекта запустите:

```bash
giga ui
```

Команда запускает локальный UI и durable worker, но не открывает браузер сама.
Перейдите на `http://127.0.0.1:8091/`.

Рекомендуемый первый маршрут:

1. В **Work** проверьте название проекта и текущую Git branch.
2. Выберите `echo` и отправьте безопасный prompt.
3. В **Runs** откройте attempt, trace и сохранённые redacted payloads.
4. В **Arena** сравните два доступных harness на одной задаче.
5. Изучите **Approvals**, **Agents**, **Workflows**, **Evaluate**, **Tools** и
   **Scheduled**, прежде чем включать edits или unattended execution.

Если worker уже запущен отдельно или UI нужен только для просмотра состояния:

```bash
giga ui --no-start-worker
```

## Что уже можно попробовать

| Раздел | Пользовательский сценарий |
| --- | --- |
| Work | Direct Chat, Codex, Claude, Gemini, plugin harness, attachments и project context. |
| Arena | Сравнение нескольких harness на одной задаче. |
| Runs | Durable queue, attempts, retries, cancellation, trace, events, artifacts и diffs. |
| Approvals | Явные решения перед действиями, которыми владеет Harness. |
| Agents | Повторно используемые project profiles в `.giga/agents/`. |
| Workflows | Версионированные многошаговые и multi-agent DAG в `.giga/workflows/`. |
| Evaluate | Повторяемые eval cases, матрицы harness/model и baselines. |
| Tools | Discovery и проверка MCP, preview/apply/rollback управляемой конфигурации. |
| Scheduled | Проверяемые расписания, история occurrences и Attention Inbox. |

## Эффективные параметры Agent Profiles

Перед постановкой `Run as Agent` в durable queue Agent Studio раскладывает
каждое исполняемое поле профиля на `effective`, `delegated` или `unsupported` и
показывает источник enforcement. В run сохраняются неизменяемые redacted
`agent_profile_snapshot` и `agent_execution_plan` с requested/effective
значениями. Неподдерживаемые safety- и budget-параметры блокируют queueing, а
provenance-only selectors дают явное предупреждение.

| Параметр профиля | Codex CLI | Claude Code | Gemini CLI |
| --- | --- | --- | --- |
| model, route, mode, workspace/permission policy | effective | effective | effective |
| timeout и retry attempts | enforced by Harness | enforced by Harness | enforced by Harness |
| `reasoning_effort` | capability-proven config | capability-proven `--effort` | unsupported |
| `allowed_tools` / `disallowed_tools` | unsupported | capability-proven fixed flags | unsupported |
| `tool_ids` | immutable managed-MCP snapshot | immutable managed-MCP snapshot | immutable managed-MCP snapshot |
| `max_tokens` | unsupported | unsupported | unsupported |

`max_concurrency` больше 1 относится к coordinator уровня Workflow или
Schedule. `tool_ids` должны ссылаться на enabled, trusted и совместимые с
адаптером project MCP profiles. До queueing они замораживаются в неизменяемый
snapshot и materialize только в активный временный headless home. Prompt files,
skills и context/memory selectors пока сохраняются как явно unsupported
provenance. Профиль не принимает произвольные CLI flags или secret literals.

Для headless run публичные metadata содержат только descriptor-free identity;
полный безопасный snapshot проверяется по content hash внутри Harness data dir.
Replay повторно использует тот же snapshot даже после изменения project TOML.
Secret refs разрешаются только на границе создания subprocess config, а точная
конфигурация записывается во временный Codex/Claude/Gemini home и удаляется после
процесса. Пользовательские native homes при этом не меняются.

## Конфигурация

CLI flags имеют приоритет над environment variables. Основные переменные:

```bash
GPT2GIGA_HARNESS_PROXY_URL=http://127.0.0.1:8090
GPT2GIGA_HARNESS_API_KEY=<local-proxy-api-key>
GPT2GIGA_HARNESS_DEFAULT_MODEL=GigaChat-2-Max
GPT2GIGA_HARNESS_DEFAULT_API_MODE=v2
GPT2GIGA_HARNESS_UI_HOST=127.0.0.1
GPT2GIGA_HARNESS_UI_PORT=8091
GPT2GIGA_HARNESS_UI_BOOTSTRAP_TOKEN=<strong-random-secret-for-remote-ui>
GPT2GIGA_HARNESS_UI_ALLOWED_HOSTS=harness.example.internal
GPT2GIGA_HARNESS_AUTO_START_PROXY=True
GPT2GIGA_HARNESS_PROXY_START_TIMEOUT_SECONDS=15
GPT2GIGA_HARNESS_TIMEOUT_SECONDS=3600
GPT2GIGA_HARNESS_DATA_DIR=~/.gpt2giga/harness
```

Если `GPT2GIGA_HARNESS_API_KEY` не задан, Harness использует
`GPT2GIGA_API_KEY` для локального proxy. GigaChat credentials, OAuth tokens,
certificates и содержимое `.env` не передаются внешнему agent CLI.

Пути к нестандартно установленным CLI храните в пользовательском
`~/.gpt2giga/harness/config.toml`, а не в проекте:

```toml
[executables]
"codex-cli" = "/opt/tools/codex"
"claude-code" = "/opt/tools/claude"
"gemini-cli" = "/opt/tools/gemini"
```

```bash
giga config path
giga config set executables.codex-cli /opt/tools/codex
giga config unset executables.codex-cli
```

Configured path должен быть абсолютным, имеет приоритет над `PATH` и проходит
version/capability probe до запуска.

### Конфигурация проекта

`giga init` создаёт `.giga/harness.toml` и стартовые определения. Посмотреть
effective project config и его источник можно так:

```bash
giga project info --json
giga project init --name my-project --json
```

Project config хранит только переносимые несекретные ссылки: default harness,
model/API mode, пути к prompts, agents, workflows, evals, tools и schedules.
Absolute executable paths, credentials и runtime ownership остаются на уровне
пользователя. Не редактируйте `.giga/` из UI без просмотра diff.

### Повторно используемые Agent Profiles

Agent profile — version-controlled TOML-описание harness, модели, режима
`plan|read|edit`, workspace policy, timeout/retry и допустимых tools. Профиль не
может подмешивать произвольные shell flags или literals секретов.

```bash
giga agent list --workspace .
giga agent show reviewer --workspace . --json
giga run --agent reviewer --workspace . "Проверь изменение"
```

Перед queueing Harness строит immutable execution plan. Неподдерживаемый
safety-critical параметр блокирует запуск; delegated параметр остаётся явно
отмеченным, чтобы UI не выдавал его за enforcement со стороны Harness.

### Версионированные Workflows

Workflow — YAML DAG под `.giga/workflows/` с шагами agent, prompt, eval или
handoff. Определение получает content hash; durable run сохраняет snapshot,
поэтому последующее редактирование YAML не меняет уже поставленную задачу.

```bash
giga workflow list --workspace .
giga workflow validate .giga/workflows/review.yaml
giga workflow run review --workspace . --prompt "Проверь изменение" --json
```

Условия, зависимости и retry описываются декларативно. Multi-agent fan-out
ограничивается coordinator policy; workspace mutation всё равно требует
worktree isolation и approvals.

### Project Memory

Project memory хранит короткие, проверяемые факты и решения, а не скрытую копию
всего репозитория:

```bash
giga memory add "Использовать Alembic migrations" --workspace . --tag decision
giga memory list --workspace . --json
giga memory disable <memory_id> --workspace .
giga memory enable <memory_id> --workspace .
```

Перед сохранением удалите credentials, personal data и приватный code content.
Memory selectors в profile пока могут быть provenance-only; смотрите effective
plan до запуска.

### Preflight запуска

Preflight проверяет доступность executable, совместимость версии, route/model,
proxy authentication, workspace trust, permission mapping, managed tools,
attachments и нужные approvals до создания процесса:

```bash
giga run --agent codex --mode read --workspace . --dry-run "Проверь проект"
giga harness inspect codex-cli --json
giga doctor
```

Ошибка preflight не должна оставлять process, worktree или временный managed
home. Existing external proxy никогда не останавливается Harness; созданный им
loopback sidecar имеет явный ownership и очищается при failed startup.

### Tool Profiles и MCP

Tool profile содержит descriptor MCP server, trust state, transport, secret
refs и policy labels. Раздел **Tools** показывает discovery и совместимость, но
не выполняет tool автоматически.

Управление доступно в top-level разделе **Tools** и через аутентифицированные
`/api/tools`, `/api/mcp` endpoints cockpit. Сначала используйте preview/dry-run.
Apply/rollback managed configuration проходит
через approval. Secret ref разрешается только у owning subprocess и не попадает
в durable metadata, project YAML или browser response.

### Eval Lab и матрицы совместимости

Eval case фиксирует input, проверяемые критерии и ожидаемые artifacts. Матрица
запускает независимую пару case/harness/model и сравнивает только совместимые
dimensions: Git SHA, config hash, CLI version, event schema и route.

```bash
giga eval list --workspace .
giga eval run smoke --workspace . --harness echo --json
giga eval run smoke --harness codex-cli,claude-code,gemini-cli --dry-run
```

Baseline — локальный versioned reference, а не гарантия качества модели. Не
сравнивайте результаты после изменения CLI/model/route как одну и ту же серию:
UI пометит такой baseline несовместимым.

### PR artifacts, provenance и replay

Run может собрать diff, patch, summary, test evidence и PR-ready metadata, но
не выполняет скрытый push/merge. Provenance связывает immutable execution
snapshot, attempt, workspace, model, adapter evidence, approvals и artifacts.

```bash
giga runtime inspect --json
giga runtime export --output harness-runtime.json
```

Replay использует сохранённый snapshot и не подменяет его текущей project
configuration. Export по умолчанию не содержит raw task payloads; всё равно
просмотрите файл перед передачей третьей стороне.

### Promotion и Editor Bridge

Успешный run можно превратить в proposal для agent/prompt/workflow/eval. Promotion
сначала показывает diff и требует approval; она не изменяет source checkout
неявно. Editor Bridge открывает поддерживаемый local artifact или diff в
настроенном editor и не превращает browser input в произвольную shell-команду.

## Встроенные Harness-адаптеры

| Адаптер | Назначение | Continuation |
| --- | --- | --- |
| `direct-chat` | Прямой Chat Completions через gateway | structured replay |
| `codex-cli` | Headless Codex или managed native terminal | app-server thread при доказанном контракте; иначе degraded replay |
| `claude-code` | Headless Claude Code или managed native terminal | one-shot headless; native resume зависит от CLI evidence |
| `gemini-cli` | Headless Gemini CLI или managed native terminal | one-shot headless; native resume зависит от CLI evidence |
| `echo` | Deterministic smoke без credentials и сети | stateless |

`giga harness list` показывает только реально доступные adapters, а
`giga harness inspect <id> --json` — capability evidence, transport
attachments, policy ownership и причины degraded/disabled state.

### Codex CLI

Harness предпочитает reviewed `codex app-server` JSON-RPC для headless
multi-turn continuity. Если contract не доказан, используется
`codex exec --ephemeral --json` с явным `degraded_replay`. Native mode запускает
TUI в managed PTY; это другой transport и другой уровень наблюдаемости.

### Claude Code

Headless run использует capability-probed flags для model, permission mode,
effort и allowed/disallowed tools. Managed MCP config материализуется только во
временном home. Native output может содержать структурированную tool activity,
но внутренние prompts и approvals CLI остаются delegated.

### Gemini CLI

Перед native start проверяется `--prompt-interactive`, чтобы initial prompt был
доставлен ровно один раз. Wrapper argv задаётся TOML-массивом без `shell=True`.
Неизвестный или несовместимый event stream завершается явной ошибкой вместо
догадок по terminal text.

## CLI истории и native sessions

```bash
giga session list --workspace .
giga session show <session-id> --json
giga native sync --harness codex-cli --workspace . --json
giga native list --harness codex-cli --workspace . --json
giga native import <native_ref_id> --json
```

`session` работает с Harness-owned history. `native` обнаруживает и связывает
vendor sessions через adapter-specific read-only contract. Sync не импортирует
transcript автоматически и не переписывает homes Codex, Claude или Gemini.

## Browser UI, Smart Router и Arena

UI состоит из **Work**, **Runs**, **Native**, **Arena**, **Approvals**,
**Agents**, **Workflows**, **Evaluate**, **Tools** и **Scheduled**. Runs Center
читает durable queue, trace и artifacts; reasoning model не отображается в
timeline. Smart Router объясняет выбор adapter/model и не скрывает unavailable
capabilities. Arena создаёт независимые child jobs и workspaces, чтобы один
участник не менял контекст другого.

После начала первого run Work постепенно показывает компактный путь Run →
Evidence → Approval/worktree → Reuse/automation. Пока run активен, evidence остаётся pending.
После success, failure или cancellation кнопка **Open evidence** открывает
trace именно этого run в Runs Center и показывает только сохранённые counts
событий/tools и duration, не повторяя prompt, response или workspace content.
Если run сохранил изолированный patch, **Review worktree** открывает его точный
Diff inspector; apply patch и выдача approval остаются отдельными явными
действиями оператора. Для успешного run без ожидающего review кнопка **Reuse
run** открывает существующий provenance/promotion inspector именно этого run;
preview/apply кандидата agent/workflow/eval и его последующее добавление в
schedule остаются отдельными явными действиями оператора.

Attachments сначала копируются или связываются по безопасному project policy,
затем преобразуются в adapter-specific render plan. UI различает rich
transport, CLI flag, staged path, prompt reference и metadata-only delivery;
`supports_attachments=True` сам по себе не доказывает multimodal delivery.

## Durable worker, schedules и очередь

Worker владеет leases, heartbeats, retries, timeout/cancel и crash
reconciliation. Browser можно закрыть после queueing. Interactive composer
умеет interrupt текущего turn и durable queue следующих сообщений; они
отправляются последовательно и остаются видимыми рядом с composer.

```bash
giga worker start
giga worker status
giga worker stop-on-idle --idle-seconds 30
giga schedule list --workspace . --json
giga schedule preview schedule.yaml --workspace . --json
giga schedule test-now daily-review --workspace . --json
giga schedule enable daily-review --workspace . --json
```

Schedule нельзя включить без live worker и успешного `Test now` для точного
content hash. Изменение material field ставит schedule на pause. Occurrence
history не удаляется при archive, а unattended edit fail-closed без worktree и
нужных approvals.

## Безопасный edit-сценарий

1. Сначала выполните задачу в `plan` или `read` либо используйте `--dry-run`.
2. Для `edit` оставьте workspace policy в `auto` или явно выберите изолированный
   worktree.
3. После запуска откройте diff и artifacts в **Runs**.
4. Не применяйте patch, если он обрезан, конфликтует с исходным checkout или
   содержит неожиданные файлы.
5. Разрешайте apply или создание branch только через понятный approval.

Harness не включает скрытый auto-apply, push или merge. Сторонний CLI может
иметь собственную sandbox/permission-модель, поэтому проверяйте одновременно
его настройки и то, что сообщает Harness.

## Где хранятся данные

| Путь | Содержимое |
| --- | --- |
| `~/.gpt2giga/harness` | Runtime SQLite, sessions, attempts, redacted logs, managed native homes, worktrees и локальное UI state. |
| `.giga/` в проекте | Non-secret project config, prompts, agents, workflows, evals и schedules. |

При uninstall/reinstall не удаляйте эти каталоги автоматически. Сначала
остановите UI и worker, сделайте backup и проверьте release notes.

Секреты храните в environment variables или разрешённом локальном secret
backend. Не записывайте credentials, API keys, OAuth tokens, cookies,
сертификаты, private keys или содержимое `.env` в `.giga/harness.toml`, YAML,
issue или диагностический архив.

## Удалённый доступ

Безопасный режим по умолчанию — `127.0.0.1:8091`. Для non-loopback bind нужны
явный `--allow-remote`, сильный bootstrap token, список разрешённых hosts и TLS:

```bash
export GPT2GIGA_HARNESS_UI_BOOTSTRAP_TOKEN="$(openssl rand -hex 32)"
export GPT2GIGA_HARNESS_UI_ALLOWED_HOSTS=harness.example.internal
giga ui --host 0.0.0.0 --allow-remote
```

Не передавайте token через URL. Размещайте TLS reverse proxy перед UI. Alpha не
позиционируется как публичный Internet-facing или multi-tenant сервис.

Bootstrap token даёт доступ доверенного оператора с правами того же OS account,
а не изолированного tenant или read-only пользователя. Аутентифицированный
оператор может выбрать любой доступный этому account workspace, открыть
поддерживаемые файлы и запускать там разрешённые policy процессы. Передавайте
token только операторам, которым допустимы эти filesystem и process privileges.

## Ограничения preview

- Поведение Codex, Claude и Gemini зависит от поддержки custom endpoints,
  headless mode, native resume и формата local history в установленной версии
  CLI.
- Часть действий внутри внешнего CLI непрозрачна; policy enforcement может быть
  delegated или advisory.
- MCP-раздел ориентирован на discovery и управляемую конфигурацию; это не
  обещание автоматической установки, OAuth или выполнения любого MCP tool.
- Scheduled jobs требуют живого worker, успешного `Test now` для текущего hash
  и необходимых approvals.
- Generated artifacts и patches всегда нужно проверять вручную. Preview не
  даёт production SLA и гарантии полной обратной совместимости.

## Если что-то не работает

Начните с:

```bash
giga doctor
giga harness list
giga harness inspect codex-cli --json
```

### Диагностика совместимости адаптера

Для встроенных внешних CLI поле `protocol_capability_scope` имеет значение
`harness_surface`: capability-описание фиксирует то, что Harness действительно
наблюдает и гарантирует, а не все внутренние wire-протоколы CLI. В
`adapter_capabilities` используются состояния `supported`, `partial`,
`delegated` и `unsupported`, поэтому `giga harness inspect --json` и
`/api/harnesses` явно показывают ограничения continuity, native policy, доставки
первого prompt и managed tools.
Отдельное поле `headless_continuation` сообщает фактическую стратегию:
`structured_thread`, `structured_replay`, `native_cli_resume`,
`degraded_replay`, `one_shot` или `unsupported`.

Единую проверяемую матрицу для всех встроенных внешних CLI можно сгенерировать
непосредственно из этих runtime-контрактов:

```bash
giga harness capabilities
giga harness capabilities --json
```

Markdown и версионированный JSON детерминированы, не запускают probes
установленных бинарных файлов и не читают native CLI homes. Необъявленная
ячейка остаётся `null`/`undeclared`: генератор не превращает отсутствие claim в
поддержку. Evidence для установленной версии по-прежнему доступно отдельно
через `giga harness inspect <id> --json`.

Перед тем как считать Codex CLI, Claude Code или Gemini CLI доступным, Harness
выполняет ограниченные `--version` и `--help` probes во временном изолированном
home. Они не читают пользовательские history/config и не сохраняют environment
или секреты. Результат кэшируется по безопасному argv и версии; поэтому
найденный, но несовместимый binary получает явный compatibility warning в
doctor, worker fingerprint, `giga harness inspect --json`, `/api/harnesses` и
cockpit. Для Gemini wrapper можно задать безопасный TOML-массив argv в
`~/.gpt2giga/harness/config.toml`; элементы передаются напрямую без `shell=True`.
Парсеры допускают неизвестные добавочные поля из versioned fixtures, но поток
без единого распознанного обязательного event contract завершается ошибкой.

Headless-потоки и Codex app-server публикуют стабильные tool, command, file,
usage, failure и lifecycle events только из capability-probed structured schema.
Usage сохраняет доступные cached-input, reasoning-output и tool token details.
Нативные TUI Codex, Claude и Gemini остаются редактированным потоком
`raw-terminal-v1` с явными ограничениями `tool_lifecycle_opaque`,
`usage_unavailable` и `artifacts_unclassified`: Harness не угадывает структуру
по тексту терминала.

### Baseline eval и live compatibility matrix

Baseline eval фиксирует не только Git SHA и config hash, но и точную версию CLI,
event schema и маршрут `/v1|/v2`. Без совпадения этих dimensions сравнение явно
помечается несовместимым. Без запуска model task установленную матрицу можно
проверить opt-in командой:

```bash
GPT2GIGA_RUN_CLI_COMPAT_MATRIX=1 GPT2GIGA_COMPAT_API_MODE=v2 \
  uv run pytest -q tests/live/test_adapter_compatibility_matrix.py
```

### Headless continuity Codex

Для Codex main chat Harness дополнительно проверяет контракт
`codex app-server --help`. Если доступен reviewed stdio JSON-RPC v2, первая
реплика создаёт `thread/start` и `turn/start`, а следующие реплики используют
тот же `thread_id` без нового TUI или `codex exec --ephemeral`. Один supervised
app-server процесс может держать несколько совместимых Harness sessions как
разные Codex threads. Явный Harness fork отображается в `thread/fork`, cancel —
в `turn/interrupt`, а после смены owner Harness выполняет `thread/read` и
`thread/resume` и сохраняет recovery outcome.

Durable link содержит только opaque runtime id, `thread_id`, последний
`turn_id`, protocol/version evidence, status и неизменяемый execution snapshot.
Route, model, managed home identity, source/effective workspace, permission mode
и hash managed-MCP snapshot должны совпадать при продолжении; изменить их можно
только через явный fork. Стабильный внутренний message id передаётся как
`clientUserMessageId`, поэтому повторная доставка prompt блокируется. Raw stdio
и PID app-server не попадают в browser. `turn/*`, `item/*`, tool, file-change и
assistant delta преобразуются в обычные normalized Run events.

App-server запускает headless turns с reviewed sandbox и
`approvalPolicy=never`. Неожиданный server-side approval или elicitation
отклоняется fail-closed и фиксируется warning. MCP secret refs разрешаются
только на границе запуска owning process, после initialize удаляются из
Harness-owned config, а durable metadata хранит только snapshot id/hash.

Если app-server contract не доказан, Codex сохраняет совместимый
`codex exec --ephemeral --json`, но full-history replay явно помечается
`degraded_replay`, а не resume того же Codex thread. Direct Chat использует
`structured_replay`. Headless continuation Claude Code и Gemini CLI пока
`unsupported`: ограничение публикуется до их one-shot процесса. Plugins по
умолчанию остаются `one_shot`, пока не объявят отдельный проверенный contract.

### Native session continuity

Для новых управляемых native-запусков Harness сохраняет неизменяемый безопасный
execution snapshot: route `v1|v2`, model, managed home, workspace, project id,
permission mode и hash управляемой tool-конфигурации. Этот snapshot переносится
через sync, import, link и resume. Старые refs без snapshot помечаются
`route_unknown`: перед resume нужно явно подтвердить `api_mode`, и неизвестный
исходный route больше не подменяется молча на `/v2`. Противоречащие snapshot
route, model, home, workspace, project или harness блокируются до запуска CLI.

Native discovery теперь берёт workspace/project identity из самой истории CLI,
а не приписывает каждому внешнему ref проект, из которого запустили sync. Если
такого evidence нет, ref явно остаётся unscoped и не попадает в project-filtered
списки по умолчанию. CLI-list и file-backed записи с одинаковым native session
id сводятся к одному стабильному metadata ref без автоматического импорта
transcript. Большие выборки sync можно обходить через `--limit` и возвращённый
`--cursor`. Когда управляемые Codex или Gemini записывают новую history, Harness
автоматически связывает ref с owning run только при однозначном совпадении
execution snapshot.

### Native preflight и policy

Управляемые native start и resume для Codex, Claude Code и Gemini выполняют
route-aware proxy preflight до spawn CLI. Harness сначала проверяет health, затем
требует, чтобы точный выбранный route `GET /v1/models` или `GET /v2/models`
принял настроенный локальный proxy key. Недоступный route, auth-enabled внешний
proxy без `GPT2GIGA_HARNESS_API_KEY` и запрещённый remote auto-start завершаются
явной ошибкой до spawn. Новый loopback sidecar помечается как Harness-owned в
безопасном plan evidence и останавливается при ошибке native startup до handoff;
существующий proxy помечается external и никогда не останавливается. Созданный
sidecar key передаётся напрямую в startup context CLI, а не восстанавливается из
временного key cache UI-процесса.

Spawn native-процесса также проходит через общее действие Approval Center
`process.spawn` до создания worktree, запуска proxy или spawn CLI. Профиль
`review_every_action` возвращает approval, после которого исходный запрос можно
повторить; deny не запускает процесс и не создаёт worktree. Для безопасной
политики `auto` и явной `worktree` native-режим `edit` создаёт отдельный detached
Git worktree и передаёт CLI только его effective path. Ошибка изоляции блокирует
запуск без fallback в source checkout. Run, native link и безопасный plan
сохраняют source/effective workspace и результат Harness policy.

После spawn permission enforcement остаётся делегированным конкретному CLI:
Codex отображает `plan|read` в `--sandbox read-only`, а `edit` в
`workspace-write`; Claude Code использует `--permission-mode plan` для
`plan|read` и `default` для `edit`; Gemini использует `--approval-mode plan` и
`default` соответственно. Интерактивные approval prompts внутри CLI явно
помечаются delegated: Approval Center не заявляет, что видит или подтверждает
их.

### Durable native process и terminal transport

Для каждого управляемого native-процесса Harness теперь сохраняет в
`runtime.sqlite3` публичную запись ownership: owner и process id, lease,
heartbeat, timeout/cancel state, terminal cursor и ограниченные redacted-ссылки
на output. Сырые PTY и process handles остаются только у процесса-владельца.
Другой UI/API-клиент может читать durable state и запросить cooperative cancel,
но не может писать в неподтверждённый PTY или «усыновить» его. После истечения
lease reconciliation явно фиксирует `interrupted`, `exited` или `unknown`,
оставляет managed home и изолированный worktree для review, а живой orphan
помечает `process_alive_not_adopted` без ложного reconnect.

Панель Native по умолчанию читает terminal output через аутентифицированный
cursor-based SSE endpoint
`GET /api/native/processes/{process_id}/output/stream`. Ограниченные batches
несут монотонный cursor; reconnect принимает и query `cursor`, и браузерный
`Last-Event-ID`, поэтому уже показанный output не дублируется. Ограниченный
`/output` polling сохранён как compatibility fallback. Для PTY локального owner
endpoint `POST /api/native/processes/{process_id}/resize` валидирует и применяет
rows/columns; pipe transport и чужой owner завершаются явной ошибкой. При
навигации и завершении terminal UI закрывает EventSource, polling timers и
resize observer.

### Доставка первого prompt в Gemini

Перед новым Gemini native-запуском Harness проверяет поддержку
`--prompt-interactive` установленной версией CLI. Если flag доступен, составной
prompt вместе с отрендеренными ссылками на attachments передаётся ровно в одном
interactive invocation, без обрезания и повторной отправки через stdin. Run и
native link сохраняют безопасные idempotency key, hash prompt, число байт,
механизм и состояние `pending|delivered|failed`; сам prompt не копируется в
command или plan metadata. Повторный browser submit с тем же key отклоняется и
после перезагрузки UI. Старая версия Gemini без подтверждённого flag завершается
явной ошибкой до spawn, а не открывает пустой terminal.

### Транспорт вложений

Attachment capability теперь описывается по типу файла и transport отдельно для
headless и native. У Codex изображение передаётся через `--image` только после
успешной version-aware проверки этого флага; обычные файлы остаются безопасными
path references, а rich image transport через app-server не заявляется. Claude
Code и Gemini CLI получают изображения и документы только как ограниченные
ссылки на путь, пока установленная версия CLI не докажет более богатый transport.
UI, Smart Router и render-plan показывают это как `reference-only`, а не как
полноценную multimodal-доставку. Legacy-поля `supports_attachments` и
`accepted_attachment_kinds` сохранены для совместимости плагинов, но больше не
используются как доказательство rich transport.

### Checklist диагностики

Проверьте:

- доступен ли proxy по `GPT2GIGA_HARNESS_PROXY_URL`;
- совпадает ли `GPT2GIGA_HARNESS_API_KEY` с ключом gateway;
- есть ли GigaChat credentials для реального запроса;
- находится ли нужный внешний CLI в `PATH`;
- выбран ли ожидаемый backend route `v1` или `v2`;
- запущен ли worker для durable и scheduled runs.

Перед публикацией diagnostics удалите секреты и приватный код. Runtime summary
без raw payloads можно получить командами `giga runtime inspect --json` и
`giga runtime export`.

## CLI-справочник по задачам

Показать путь к пользовательской конфигурации и изменить executable override:

```bash
giga config path
giga config set executables.codex-cli /opt/tools/codex
giga config unset executables.codex-cli
```

Создать или проверить project cockpit:

```bash
giga project info --json
giga project init --name my-project --json
```

Посмотреть и запустить preset:

```bash
giga preset list --workspace .
giga preset run review --workspace . --dry-run
```

Проверить и запустить agent profile:

```bash
giga agent list --workspace .
giga agent show reviewer --workspace . --json
giga agent validate .giga/agents/reviewer.yaml
giga agent run reviewer --workspace . --prompt "Проверь patch" --dry-run
```

Управлять durable workflow:

```bash
giga workflow list --workspace .
giga workflow run review-team --workspace . --prompt "Проверь change" --json
giga workflow status <workflow_run_id> --json
giga workflow cancel <workflow_run_id>
```

Управлять project memory:

```bash
giga memory list --workspace . --json
giga memory add "Решение проекта" --workspace . --tag decision
giga memory disable <memory_id> --workspace .
giga memory enable <memory_id> --workspace .
```

Запустить eval или dry-run matrix:

```bash
giga eval list --workspace . --json
giga eval run smoke --workspace . --harness echo --json
giga eval run smoke --harness codex-cli,claude-code --dry-run
```

Проверить worker:

```bash
giga worker status
giga worker stop-on-idle --idle-seconds 30
```

Управлять schedule:

```bash
giga schedule list --workspace . --json
giga schedule show daily-review --workspace . --json
giga schedule run-now daily-review --workspace . --json
giga schedule pause daily-review --workspace . --json
```

Просмотреть Harness-owned session:

```bash
giga session list --workspace .
giga session show <session_id> --json
```

Обнаружить native sessions:

```bash
giga native sync --harness codex-cli --workspace . --json
giga native list --harness codex-cli --include-external --json
giga native import <native_ref_id> --json
```

Открыть session, run, diff, terminal или файл в настроенном editor:

```bash
giga open session <session_id>
giga open run <run_id> --diff
giga open run <run_id> --terminal
giga open file src/foo.py --workspace . --line 42
```

Проверить или экспортировать coordination state:

```bash
giga runtime inspect --json
giga runtime export --output /tmp/harness-runtime.json
```

## Добавление собственного Harness

Plugin использует entry-point group `gpt2giga.harnesses`, но его import target
не должен находиться в gateway namespace:

```toml
[project.entry-points."gpt2giga.harnesses"]
my-harness = "my_package.my_harness:MyHarness"
```

Начните со scaffold, затем проверьте metadata/capabilities и dry-run:

```bash
giga harness scaffold my-harness
giga harness validate my-harness --json
giga harness inspect my-harness --json
```

Adapter обязан явно описать execution modes, continuation, event schema,
attachments transport, tool/policy ownership, required executable и redaction
boundaries. Не объявляйте capability, которую не подтверждает probe или test.

## Миграция со старого combined prerelease

Gateway и Harness теперь два самостоятельных дистрибутива и namespace. Перед
переустановкой удалите обе старые tool installations, но не удаляйте runtime и
project state:

```bash
uv tool uninstall gpt2giga
uv tool uninstall gpt2giga-harness
uv tool install --prerelease allow gpt2giga-harness
giga doctor
```

Текущая metadata `gpt2giga-harness==0.0.1a2` требует ровно
`gpt2giga==0.2.3a2`. Старый import `gpt2giga.harness` больше не является
публичным; используйте `gpt2giga_harness`. Миграция package не переносит и не
перезаписывает `~/.gpt2giga/harness`, `.giga/` или vendor-owned CLI homes.

## Ручной QA checklist

- `giga doctor . --json` не показывает неожиданных secret values, абсолютного
  workspace path или user-home content;
- `giga harness run echo` завершается без сети и credentials;
- `giga ui` слушает loopback, а remote bind без opt-in и token блокируется;
- run переживает reload UI, а SSE reconnect не дублирует события;
- cancel/interrupt оставляет понятный final state и не бросает orphan ownership;
- `plan|read` не пишет в source workspace;
- `edit` использует isolated worktree и требует approval для apply/branch;
- native terminal восстанавливает cursor, принимает resize только от owner и
  закрывает EventSource при завершении;
- attachment UI показывает реальный transport, а не общий optimistic флаг;
- schedule нельзя включить без exact-hash `Test now` и live worker;
- export и browser API не содержат raw reasoning, credentials или secret refs.

## Выбор модели и текущие ограничения

`model` в profile/request — клиентская модель. При `GPT2GIGA_PASS_MODEL=True`
она передаётся gateway; при `False` gateway использует свою configured GigaChat
model. Для Claude/Gemini через Harness выбранная upstream model закрепляется во
внутреннем trusted context, но публичная форма ответа остаётся совместимой с
исходным protocol.

Alpha не обещает stable API/SQLite/YAML contracts, high availability,
multi-tenant isolation, полный контроль действий black-box CLI или rich
attachments для любого adapter. Headless continuation Claude/Gemini остаётся
ограниченным до появления проверенного resume contract. Всегда ориентируйтесь
на `giga harness inspect --json`, а не на название установленного CLI.
