# Архитектура Unified Harness

Unified Harness — локальный управляющий слой для работы с агентами. Он не
реализует модельный протокол и не заменяет `gpt2giga`, Codex CLI, Claude Code
или Gemini CLI. Harness выбирает адаптер выполнения, применяет локальные
политики, сохраняет нормализованную запись запуска и показывает это состояние
через CLI `giga` и браузерный cockpit.

UI API — альфа-версия локального control-plane API. Он не входит в публичный
OpenAI-, Anthropic- или Gemini-совместимый контракт шлюза. Описанные здесь
маршруты по умолчанию обслуживает `giga ui` на `127.0.0.1:8091`, а совместимые
с модельными API маршруты отдельно обслуживает `gpt2giga` на порту `8090`.

## Системный контекст

```mermaid
flowchart LR
    User["Пользователь"] --> CLI["giga CLI"]
    User --> Browser["Встроенный браузерный UI"]
    CLI --> Control["FastAPI control plane Harness :8091"]
    Browser --> Control

    Control --> Registry["Реестры harness-адаптеров и native-коннекторов"]
    Control --> Runtime["Durable runtime и policy engine"]
    Runtime --> Worker["Локальный durable worker"]
    Worker --> Runner["HarnessSessionRunner"]

    Runner --> Direct["Адаптер Direct Chat"]
    Runner --> AgentCLI["Headless-адаптеры Codex / Claude / Gemini"]
    Control --> Native["Управляемые native terminal-процессы"]

    Direct --> Gateway["Шлюз совместимости gpt2giga :8090"]
    AgentCLI --> Gateway
    Native --> Gateway
    Gateway --> GigaChat["GigaChat"]

    Runner --> SessionStore["Маскированные файлы сессий и артефактов"]
    Runtime --> SQLite["runtime.sqlite3"]
    Native --> NativeState["Native-индекс и managed homes"]
    Runner --> Worktrees["Изолированные Git worktrees"]
```

Главная граница проходит между оркестрацией и выполнением. Harness может
применять политики к операциям, которыми владеет: запуску процесса, подключению
к MCP-серверу или применению патча. Он не может восстановить скрытые вызовы
инструментов или решения о разрешениях внутри непрозрачного TUI стороннего CLI.

## Основные компоненты

| Компонент | Зона ответственности | Зачем нужен |
| --- | --- | --- |
| `ui/app.py` и `ui/routers/` | Композиция FastAPI, аутентификация, JSON/SSE API, встроенный статический UI | Дают CLI и браузеру единую локальную поверхность управления. |
| `registry.py`, `plugins.py`, `harnesses/` | Обнаружение встроенных адаптеров и адаптеров из entry points | Позволяют расширять набор исполнителей без хардкода каждого из них во frontend. |
| `session_runner.py` | Валидация запроса, сбор контекста, вызов адаптера, нормализованное сохранение | Даёт всем headless-адаптерам общий контракт session/run/event. |
| `sessions/` | Сессии, запуски, сообщения, события, raw records, маскирование | Сохраняет пригодную для проверки историю после перезапуска браузера или сервера. |
| `runtime/` | Durable jobs, attempts, leases, workers, retries, cancellation, approvals | Отделяет отправленную задачу от HTTP-запроса браузера, который её создал. |
| `native/` | Обнаружение native history и жизненный цикл принадлежащих Harness PTY-процессов | Сохраняет продолжение native CLI-сессий, не изменяя пользовательские vendor homes. |
| `attachments/`, `generated_files.py` | Загруженные файлы, ссылки на workspace и сгенерированные файлы | Передаёт адаптерам ограниченные типизированные файлы и безопасные preview. |
| `project.py`, `project_memory.py`, `workspace.py` | Идентичность проекта, конфигурация `.giga/`, memory, ограниченное чтение файлов | Отделяет переиспользуемые определения проекта от локальной runtime-истории машины. |
| `worktrees.py`, `pr_artifacts.py`, `promotions.py` | Изолированные изменения, patch/branch-артефакты, перенос результата в project YAML | Делает изменения проверяемыми и останавливает их при неполных проверках. |
| `tools/`, `mcp.py`, `managed_mcp.py` | Tool profiles, разрешение секретов, MCP discovery, managed CLI config | Подключает инструменты без записи секретов в публичные записи или vendor homes. |
| `agents.py`, `workflows.py`, `schedules.py`, `evals.py` | Переиспользуемые профили и высокоуровневая оркестрация | Строит повторяемую автоматизацию поверх того же durable run-примитива. |

## Поток headless-выполнения

Обычная кнопка Run в браузере использует асинхронный маршрут `/start`.
Синхронные маршруты `/run` полезны для коротких CLI-подобных вызовов, но
связывают время жизни HTTP-запроса со временем выполнения и не являются
основным путём UI.

```mermaid
sequenceDiagram
    actor U as Пользователь
    participant API as FastAPI control plane
    participant P as Preflight и policy
    participant DB as runtime.sqlite3
    participant W as Durable worker
    participant R as Session runner
    participant A as Адаптер или внешний CLI
    participant S as Session store

    U->>API: POST /api/sessions/{id}/run/start
    API->>P: проверка проекта, route, capability и policy
    P->>S: queued HarnessRun и начальные события
    P->>DB: идемпотентный durable job
    API-->>U: run id, stream URL, cancel URL
    W->>DB: lease и новый attempt
    W->>R: выполнение сохранённого payload
    R->>A: direct chat или structured headless-команда
    A-->>R: нормализованные события и результат
    R->>S: маскированные сообщения, события и артефакты
    W->>DB: завершение attempt и job
    API-->>U: SSE до terminal run_finished
```

Job, attempt и run намеренно являются разными записями:

- **session** — видимый пользователю контейнер разговора или задачи;
- **run** — одно выполнение адаптера и сохранённые доказательства этого запуска;
- **job** — durable-запись планирования и отмены;
- **attempt** — одна worker lease этого job, сохраняющая историю retry.

## Поток native terminal

Native mode отделён от headless-выполнения. Harness владеет PTY-процессом и его
маскированным потоком байтов, но внутренним поведением TUI владеет CLI. Новая или
возобновляемая сессия проходит capability checks и route-aware preflight шлюза.
Вывод доступен через polling по cursor и SSE. `Last-Event-ID` или `after_seq`
позволяет ограниченно воспроизвести поток после reconnect. Resize и input
выделены в отдельные операции, потому что изменяют живой терминал.

```mermaid
flowchart TD
    Start["Запрос start или resume"] --> Probe["Проверка executable и capabilities"]
    Probe --> Route["Preflight шлюза для /v1 или /v2"]
    Route --> Policy{"Policy запуска процесса"}
    Policy -->|deny| Denied["403"]
    Policy -->|ask| Approval["202 approval required"]
    Policy -->|allow| PTY["PTY-процесс под управлением Harness"]
    PTY --> Events["Маскированные события raw-terminal-v1"]
    Events --> Poll["Fallback polling по cursor"]
    Events --> SSE["SSE с replay после reconnect"]
    PTY --> Record["Durable process и run metadata"]
```

## Границы состояния и безопасности

Принадлежащая проекту конфигурация, которую можно хранить вместе с кодом, лежит
в `.giga/`. Локальное runtime-состояние машины по умолчанию находится в
`~/.gpt2giga/harness` и не должно копироваться в репозиторий. Точная раскладка
может меняться в альфа-версии, но граница владения остаётся той же:

| Состояние | Типичное расположение | Контракт |
| --- | --- | --- |
| Agents, workflows, evals, schedules, prompts, project defaults | `<project>/.giga/` | Проверяемая конфигурация проекта без секретов. |
| Durable coordination | `~/.gpt2giga/harness/runtime.sqlite3` | Версионируемая SQLite-схема с WAL, миграциями, leases, approvals и audit history. |
| Sessions, events, raw records, attachments, arenas, eval results | `~/.gpt2giga/harness/...` | Маскирование до записи и ограниченная сериализация в API. |
| Native reference index и managed CLI homes | `~/.gpt2giga/harness/native/...` | Harness пишет только в свои managed homes, но не в пользовательский native vendor home. |
| Изолированные edit worktrees | `~/.gpt2giga/harness/worktrees/...` | Применение только после policy, approval, base-commit и dirty-tree checks. |

UI по умолчанию слушает только loopback. `/healthz` намеренно минимален и не
требует аутентификации. Remote bind требует явного opt-in, обмена bootstrap token
на сессию через `/auth/session`, разрешённого Host и внешнего TLS termination.
Секреты и скрытые reasoning-данные удаляются до сохранения и повторно перед
выбранными API-ответами.

## API управляющего слоя

Таблицы ниже описывают все смонтированные JSON- и SSE-маршруты. SPA-маршруты UI
и `/assets/*` только отдают встроенные frontend-файлы и не являются data API.
JSON-схема FastAPI доступна по `/openapi.json`; Swagger и ReDoc намеренно
отключены.

### Shell, discovery и preflight

| Маршруты | Зачем нужны |
| --- | --- |
| `GET /healthz` | Минимальная liveness-проверка без данных проекта или runtime. |
| `POST /auth/session` | Меняет настроенный remote bootstrap bearer token на cookie браузерной сессии в памяти. |
| `GET /api/health` | Возвращает аутентифицированному UI расширенную готовность cockpit, proxy, runtime и reconciliation. |
| `GET /api/defaults` | Передаёт UI безопасные начальные значения model, API mode, timeout и других настроек. |
| `GET /api/harnesses` | Перечисляет встроенные и plugin-адаптеры, их availability, capabilities, native support и compatibility evidence. |
| `GET /api/models` | Даёт model picker безопасный список моделей, не заставляя браузер обращаться к шлюзу напрямую. |
| `POST /api/preflight/run` | Проверяет prompt, workspace, attachments, route, executable и блокирующие условия до отправки. |
| `POST /api/route/recommendation` | Детерминированно рекомендует harness/mode; не вызывает LLM и не выдаёт edit-разрешение. |

### Project, workspace, memory и редактор

| Маршруты | Зачем нужны |
| --- | --- |
| `GET /api/project`<br />`GET /api/project/config` | Определяют идентичность проекта и отдельно возвращают безопасную конфигурацию `.giga/`. |
| `POST /api/project/init` | Создаёт стартовые определения без секретов и без молчаливой замены существующих файлов. |
| `GET /api/project/presets`<br />`POST /api/project/presets/{preset_name}/render` | Перечисляют prompt presets и рендерят выбранный preset после валидации входов. |
| `GET /api/project/state`<br />`PATCH /api/project/state` | Читают и обновляют небольшие UI-настройки вроде последней session; это не конфигурация исходного кода проекта. |
| `GET /api/project/memory`<br />`POST /api/project/memory`<br />`PATCH /api/project/memory/{memory_id}`<br />`DELETE /api/project/memory/{memory_id}` | Управляют явными project notes с валидацией и маскированием вместо скрытого извлечения памяти из истории. |
| `GET /api/workspace/tree`<br />`GET /api/workspace/file/metadata` | Дают ограниченное safe-path discovery для `@file` и preview без произвольного чтения файловой системы. |
| `POST /api/editor/open-workspace`<br />`POST /api/editor/open-file`<br />`POST /api/editor/open-diff`<br />`POST /api/editor/open-terminal` | Открывают разрешённый путь или команду в локальном редакторе после path/workspace checks. |

### Sessions, attachments и file preview

| Маршруты | Зачем нужны |
| --- | --- |
| `GET /api/sessions`<br />`POST /api/sessions` | Перечисляют контейнеры задач или создают пустую session до первого run. |
| `GET /api/sessions/{session_id}`<br />`PATCH /api/sessions/{session_id}`<br />`DELETE /api/sessions/{session_id}` | Загружают полный bundle, меняют title/archive state или удаляют принадлежащую Harness историю. |
| `POST /api/sessions/run`<br />`POST /api/sessions/{session_id}/run` | Синхронные create-and-run/run-in-session пути совместимости для коротких вызовов. |
| `POST /api/sessions/run/start`<br />`POST /api/sessions/{session_id}/run/start` | Основные асинхронные пути: сразу возвращают durable run, stream и cancel identifiers. |
| `GET /api/sessions/{session_id}/events` | Читает сохранённые маскированные события после refresh или без streaming. |
| `POST /api/sessions/{session_id}/attachments`<br />`POST /api/sessions/{session_id}/attachments/workspace` | Добавляют загруженные bytes или проверенную workspace-ссылку. |
| `GET /api/sessions/{session_id}/attachments` | Перечисляет attachment metadata для следующих запусков session. |
| `GET /api/attachments/{attachment_id}/metadata`<br />`GET /api/attachments/{attachment_id}`<br />`DELETE /api/attachments/{attachment_id}` | Разделяют дешёвое metadata-чтение, ограниченную выдачу blob и удаление данных Harness. |
| `GET /api/files/preview`<br />`GET /api/files/generated/{run_key}/{filename}` | Отдают разрешённые local previews и generated artifacts без раскрытия произвольных путей. |

### Runs, durable runtime, streaming и review artifacts

| Маршруты | Зачем нужны |
| --- | --- |
| `GET /api/runs` | Возвращает Runs Center с cursor pagination по durable jobs, attempts, status groups и workers. |
| `GET /api/runs/{run_id}`<br />`GET /api/runs/{run_id}/summary` | Разрешают run в полный persisted bundle или лёгкую durable summary. |
| `GET /api/runs/{run_id}/trace`<br />`GET /api/runs/{run_id}/events/{event_id}` | Держат trace list лёгким и загружают уже маскированный payload только при раскрытии события. |
| `GET /api/runs/{run_id}/events/stream` | Передаёт сохранённые события через SSE, поддерживает resume по cursor и завершается после `run_finished`. |
| `POST /api/runs/{run_id}/cancel` | Сохраняет намерение отмены, чтобы worker остановился и после отключения браузера. |
| `POST /api/runs/{run_id}/retry` | Повторно ставит в очередь только failed job с retry-safe idempotency class последнего attempt. |
| `GET /api/runs/{run_id}/provenance` | Возвращает adapter, route, binary/schema evidence, request hashes и безопасные metadata для воспроизводимости. |
| `POST /api/runs/{run_id}/replay`<br />`POST /api/runs/{run_id}/fork` | Повторяет безопасно сохранённый запрос в той же session или отделяет историю в новую session. |
| `GET /api/runs/{run_id}/diff`<br />`GET /api/runs/{run_id}/patch`<br />`GET /api/runs/{run_id}/pr` | Показывают isolated edit как structured diff, raw patch или PR-ready artifact. |
| `POST /api/runs/{run_id}/apply`<br />`POST /api/runs/{run_id}/branch` | Применяют reviewed patch или создают local branch только после approval и Git safety checks. |
| `POST /api/runs/{run_id}/discard`<br />`POST /api/runs/{run_id}/open-worktree` | Удаляют isolated worktree или открывают его в редакторе, не меняя source checkout. |
| `POST /api/runs/{run_id}/promotions/preview`<br />`POST /api/runs/{run_id}/promotions/apply` | Превращают run output в reviewed project YAML; apply требует review token и ETag/source-hash checks. |
| `POST /api/run` | Низкоуровневый синхронный вызов адаптера для простых probes и совместимости без durable UI lifecycle. |

### Native history и terminal processes

| Маршруты | Зачем нужны |
| --- | --- |
| `GET /api/native/sessions`<br />`POST /api/native/sessions/sync` | Читают cached native refs или обнаруживают vendor CLI history с явной project scope. |
| `GET /api/native/sessions/{native_ref_id}/preview`<br />`POST /api/native/sessions/{native_ref_id}/import` | Показывают маскированный transcript перед импортом в нормализованную историю. |
| `POST /api/sessions/{session_id}/native/link` | Явно связывает Harness session с проверенным native ref, если автоматической корреляции недостаточно. |
| `POST /api/native/processes/start` | Запускает новый или resumed CLI в принадлежащем Harness PTY после capability, route, policy и managed-home checks. |
| `GET /api/native/processes/{process_id}`<br />`DELETE /api/native/processes/{process_id}` | Читают durable process state или запрашивают ограниченную остановку принадлежащей Harness process group. |
| `POST /api/native/processes/{process_id}/input` | Пишет ограниченный input в PTY как отдельную валидируемую и аудируемую мутацию. |
| `GET /api/native/processes/{process_id}/output` | Читает маскированный terminal output по cursor и остаётся fallback при недоступном EventSource. |
| `GET /api/native/processes/{process_id}/output/stream` | Передаёт terminal events, keepalives и replay после reconnect через SSE. |
| `POST /api/native/processes/{process_id}/resize` | Валидирует rows/columns и синхронизирует размер TUI с viewport браузера. |

### Arena, policies, approvals и attention

| Маршруты | Зачем нужны |
| --- | --- |
| `GET /api/arena/runs`<br />`POST /api/arena/runs`<br />`GET /api/arena/runs/{arena_id}` | Перечисляют, создают и читают comparison parent, чьи children являются обычными независимыми durable runs. |
| `GET /api/arena/runs/{arena_id}/events/stream` | Объединяет события child runs в один SSE comparison stream. |
| `GET /api/policy/profiles` | Показывает неизменяемые встроенные решения для interactive, review-every-action и unattended contexts. |
| `GET /api/approvals`<br />`POST /api/approvals/{approval_id}/decision` | Перечисляют durable approval requests и сохраняют allow/deny, после чего job requeue или cancel. |
| `GET /api/attention`<br />`POST /api/attention/read` | Собирают approvals, failed schedules и другие actionable items, сохраняя исходный audit record. |

### Tools и MCP configuration

| Маршруты | Зачем нужны |
| --- | --- |
| `GET /api/tools`<br />`POST /api/tools/sync` | Перечисляют нормализованные tool profiles и обновляют project-derived inventory. |
| `GET /api/tool-servers`<br />`GET /api/tool-servers/{server_id}` | Возвращают маскированные MCP descriptors, adapter compatibility и ограниченную probe history. |
| `POST /api/tool-servers/{server_id}/probe` | Выполняет initialize/capability discovery без tool call; недоверенный process/network access требует approval. |
| `POST /api/tool-config/preview` | Показывает точное маскированное изменение managed CLI home. |
| `POST /api/tool-config/apply` | Применяет только trusted servers с optimistic locking и ownership checks. |
| `POST /api/tool-config/rollback` | Восстанавливает последнюю managed config backup, не меняя native CLI home пользователя. |

### Agents и workflows

| Маршруты | Зачем нужны |
| --- | --- |
| `GET /api/agents`<br />`GET /api/agents/{agent_id}` | Перечисляют валидные profiles и возвращают profile с source и execution-plan evidence. |
| `POST /api/agents/validate` | Валидирует недоверенный profile YAML без записи. |
| `POST /api/agents/{agent_id}/draft`<br />`POST /api/agents/{agent_id}/apply` | Отделяют просмотр маскированного diff от atomic ETag-checked записи. |
| `POST /api/agents/{agent_id}/duplicate` | Показывает независимую копию с новым safe id; применение остаётся явным. |
| `POST /api/agents/{agent_id}/run` | Ставит durable run в очередь с immutable snapshot выбранного profile. |
| `GET /api/workflows`<br />`GET /api/workflows/{workflow_id}` | Перечисляют definitions/runs или возвращают workflow и deterministic plan. |
| `POST /api/workflows/validate`<br />`POST /api/workflows/import` | Валидируют YAML без записи или явно импортируют YAML/built-in template. |
| `PUT /api/workflows/{workflow_id}`<br />`POST /api/workflows/{workflow_id}/duplicate`<br />`GET /api/workflows/{workflow_id}/export` | Обновляют с optimistic locking, создают отдельную копию или экспортируют точный portable YAML. |
| `POST /api/workflows/{workflow_id}/run`<br />`GET /api/workflow-runs/{run_id}`<br />`POST /api/workflow-runs/{run_id}/cancel` | Стартуют с immutable definition snapshot, продвигают/читают durable state или отменяют active children. |
| `GET /api/workflow-runs/{run_id}/handoffs`<br />`POST /api/workflow-runs/{run_id}/handoffs/{step_id}/choose`<br />`POST /api/workflow-runs/{run_id}/handoffs/{step_id}/discard` | Проверяют isolated child patches и явно выбирают или удаляют кандидатов. |
| `POST /api/workflow-runs/{run_id}/merge-queue`<br />`POST /api/workflow-runs/{run_id}/merge-queue/apply` | Готовят объединённый patch без пересечений и применяют его только через auditable `git.apply` approval. |

### Schedules, automation и evaluations

| Маршруты | Зачем нужны |
| --- | --- |
| `GET /api/schedules`<br />`GET /api/schedules/{schedule_id}` | Перечисляют project schedules или возвращают definition, state, будущие UTC instants и occurrence history. |
| `POST /api/schedules/preview`<br />`POST /api/schedules`<br />`PUT /api/schedules/{schedule_id}`<br />`DELETE /api/schedules/{schedule_id}` | Валидируют без записи, создают disabled definition, ставят изменённое расписание на pause и удаляют YAML с сохранением audit history. |
| `POST /api/schedules/{schedule_id}/test-now`<br />`POST /api/schedules/{schedule_id}/enable`<br />`POST /api/schedules/{schedule_id}/pause`<br />`POST /api/schedules/{schedule_id}/resume`<br />`POST /api/schedules/{schedule_id}/run-now` | Требуют safe test точного definition hash перед enable; pause/resume и ручной run используют общий worker/policy path. |
| `GET /api/automation` | Возвращает Automation Center: calendar, recent occurrences, worker health и attention state. |
| `GET /api/evals`<br />`POST /api/evals/{eval_name}/runs`<br />`GET /api/evals/runs/{eval_run_id}` | Перечисляют specs/results, ставят case-by-harness matrix в очередь и читают scorecard. |
| `GET /api/evaluate`<br />`GET /api/evaluate/{eval_name}/matrix` | Строят protocol/quality lab projection и фильтруют несовместимые cells до постановки в очередь. |
| `POST /api/evaluate/runs/{eval_run_id}/cancel`<br />`POST /api/evaluate/runs/{eval_run_id}/baseline` | Отменяют незавершённые matrix jobs или фиксируют завершённый dimensioned baseline. |

## Расширение архитектуры

Новый backend выполнения добавляется как адаптер в `harnesses/` и регистрируется
через entry-point group `gpt2giga.harnesses`. Native continuity следует добавлять
только когда connector способен честно реализовать discovery/resume semantics.
Новые семейства API должны жить в `ui/routers/`; `ui/app.py` следует оставлять
композицией и ядром session/run flow. Любой новый путь сохранения обязан
маскировать данные до записи, а любая мутация — явно указывать policy boundary.

Пользовательская настройка и поведение функций описаны в
[руководстве Unified Harness](../harness.md).
