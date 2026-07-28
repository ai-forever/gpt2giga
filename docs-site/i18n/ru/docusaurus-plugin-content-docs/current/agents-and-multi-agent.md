# Agents и multi-agent поведение в GigaLoom

В GigaLoom несколько разных сущностей называются «agent», но у них нет общего
runtime, identity или единой модели полномочий. Здесь описано, какой слой
владеет действием, что можно передавать между слоями и какие команды
поддерживает текущий продукт.

Кратко:

- **Direct Chat** — диалог с моделью GigaChat через gateway `gpt2giga`;
- **Coding Agent** — запуск Codex CLI, Claude Code или Gemini CLI через
  проверенный adapter;
- **Agent profile GigaLoom** — повторно используемая конфигурация одного
  coding-agent запуска, а не нативный subagent provider;
- **Arena** сравнивает независимые запуски;
- **Workflow** координирует durable child jobs и передаёт ограниченные видимые
  summaries или артефакты;
- **нативные subagents Codex** создаются и координируются внутри Codex.
  GigaLoom не превращает их в children Workflow и не переносит их приватное
  состояние.

## Как выбрать поверхность

| Поверхность | Для чего | Кто исполняет | Что сохраняет GigaLoom |
| --- | --- | --- | --- |
| Direct Chat | Вопросы, черновики, встроенные инструменты GigaChat | GigaChat через локальный gateway | Видимые сообщения, normalized events, записи допущенных tools и provider usage |
| Coding Agent | Исследование, review или изолированные изменения репозитория | Выбранный процесс Codex, Claude или Gemini CLI | Run/session identity, ограниченные events, артефакты, policy receipts и adapter evidence |
| Agent profile | Повторяемая роль, модель, инструкции, tools и policy | Указанный в profile coding-agent adapter | Неизменяемые redacted snapshots profile и execution plan |
| Arena | Сравнение одной задачи | Независимые обычные durable runs | Parent comparison и отдельные session/run каждого child |
| Workflow | Валидированный DAG с ограниченным fan-out, approvals, joins и handoffs | Durable coordinator и обычные child jobs | Hash definition, snapshots шагов, видимые handoffs, артефакты и ссылки на child runs |
| Нативные subagents Codex | Параллельная делегированная работа внутри turn Codex | Parent thread Codex и его agent threads | Только видимый output и артефакты внешнего Codex adapter |

Direct Chat не является repository tool loop. Coding Agent не является общим
provider-neutral механизмом login или permissions. Переключение между ними не
может молча менять task intent или workspace authority.

## Нативные subagents Codex

[Актуальное руководство OpenAI по subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
описывает их как отдельные agent threads для ограниченных задач, результаты
которых сводятся в parent thread. Текущие клиенты Codex показывают эти threads;
в CLI команда `/agent` позволяет просматривать их и переключаться между ними.

Граница полномочий остаётся в Codex:

- subagent наследует текущие sandbox и permission mode parent turn;
- при запуске child повторно применяются live runtime overrides;
- custom agent может сузить полномочия, например до read-only;
- другая модель или конфигурация custom agent не расширяет sandbox;
- если non-interactive запуск не может запросить новое approval, действие
  завершается ошибкой, которая возвращается parent.

GigaLoom не читает private reasoning Codex, не копирует native Codex thread в
другой provider и не превращает native subagents в Agent profiles Harness. Для
GigaLoom они остаются поведением внутри допущенного процесса Codex или
app-server session.

## Agents, Arena и Workflows GigaLoom

Project Agent profile в `.giga/agents/*.yaml` — versioned-рецепт поверх
существующего harness. Он может выбирать instructions, model, reasoning effort,
workspace/permission policy, ids управляемых MCP, budgets и ожидаемый artifact.
Неподдерживаемые options отклоняются до постановки в очередь. Profile не может
содержать literal secrets или произвольные provider flags.

Arena создаёт независимые child sessions и durable runs. Follow-up адресуется
конкретному child. Parent view объединяет только видимые events: он не сливает
provider-native history и не передаёт полномочия одного child другому.

Workflow — валидированный DAG. Шаги agent, arena и eval создают обычные durable
jobs. Каждый child получает неизменяемый snapshot profile и execution plan.
Editing children принудительно работают в отдельных detached Git worktrees;
patch остаётся доступным для review, пока оператор явно не выберет, не отбросит
или не применит его. Handoff содержит только ограниченный summary и выбранные
ссылки на артефакты, но не hidden reasoning.

Само членство в Workflow не является универсальным child-agent grant. Каждый
child отдельно проходит admission по явной policy. Будущая работа над scoped
authority может унифицировать ceilings, но здесь не заявляется ещё не
реализованный контракт.

Авторитетные исходники:

- [`agents.py`](https://github.com/krakenalt/gigaloom/blob/main/packages/gpt2giga-harness/src/gpt2giga_harness/agents.py)
  — Agent profiles, snapshots и execution plans;
- [`arena.py`](https://github.com/krakenalt/gigaloom/blob/main/packages/gpt2giga-harness/src/gpt2giga_harness/arena.py)
  — независимые comparison children и evidence;
- [`workflows.py`](https://github.com/krakenalt/gigaloom/blob/main/packages/gpt2giga-harness/src/gpt2giga_harness/workflows.py)
  — валидированный DAG и ограниченные handoffs;
- [`runtime/policy.py`](https://github.com/krakenalt/gigaloom/blob/main/packages/gpt2giga-harness/src/gpt2giga_harness/runtime/policy.py)
  — policy Harness и approval receipts;
- [`worktrees.py`](https://github.com/krakenalt/gigaloom/blob/main/packages/gpt2giga-harness/src/gpt2giga_harness/worktrees.py)
  — изолированная доставка изменений.

## Authentication, approvals и tools

Текущие пути authentication:

- Direct Chat использует credential boundary gateway и `SecretRef`;
- нативные CLI Codex, Claude и Gemini сами владеют login, refresh, credential
  storage, logout и revocation.

Native login broker GigaLoom может запускать provider-owned операции login,
status, logout и revocation, а также привязывать подтверждённый account к
допущенной session. Credentials и refresh по-прежнему принадлежат provider CLI.
Само наличие binary никогда не доказывает готовность account.

Approvals тоже разделены. Harness approvals покрывают действия, которыми
владеет Harness: например, process admission, integration mutation или apply
сохранённого patch. Интерактивные prompts внутри внешнего CLI остаются
provider-owned. Внешний Harness receipt не доказывает, что Harness видел или
одобрил каждое внутреннее действие provider.

Имена tools не переносятся между границами автоматически:

- Direct Chat поддерживает допущенные built-ins GigaChat: `web_search`,
  `url_content_extraction`, `code_interpreter`, `image_generate` и
  `model_3d_generate`;
- выбранные для coding-agent запуска MCP descriptors фиксируются в immutable
  redacted snapshot и материализуются только на execution boundary;
- Skills и Plugins можно найти, проверить, установить, включить или отключить,
  но наличие в catalog не выдаёт runtime authority и не доказывает
  автоматическую инъекцию prompt/tool;
- неизвестные и недоступные capabilities отклоняются до provider execution.

Независимые intent и authority определены в
[`product_capabilities.py`](https://github.com/krakenalt/gigaloom/blob/main/packages/gpt2giga-harness/src/gpt2giga_harness/product_capabilities.py):
`Ask`, `Review` и `Change` никогда не расширяют `Read only` или
`Workspace write`.

## Continuity, cancellation, cost и evidence

Continuity зависит от route. Direct Chat повторяет видимую нормализованную
history. Codex может использовать supervised app-server thread, если его
подтвердил version probe. Headless-маршруты Claude и Gemini — one-shot; их
native resume — отдельные контракты, ограниченные adapter evidence.

Cancellation кооперативна. GigaLoom сохраняет intent остановки и просит
допущенный route завершиться, но не может откатить уже выполненное provider
action.

Usage и cost — разные вещи. GigaLoom сохраняет token/usage evidence, если его
вернул provider. Денежная стоимость остаётся `unknown`, пока provider не вернул
явное cost evidence; продукт не оценивает стоимость подписки и не выводит её с
уверенностью из token count.

Через boundary Harness могут проходить только видимые messages, summaries,
normalized events, redacted terminal output и сохранённые artifacts. GigaLoom
не заявляет:

- перенос hidden reasoning или private chain-of-thought;
- перенос provider-native session между Codex, Claude, Gemini и Direct Chat;
- полную видимость black-box provider process;
- автоматическую делегацию без допущенной операции Arena, Workflow или
  native-provider.

## Точные поддерживаемые команды

Запуск поверхностей:

```bash
giga ui
giga chat "Кратко сравни варианты"
giga run --agent codex --mode read "Проверь этот репозиторий"
```

Создание и продолжение retained session:

```bash
giga session create --harness codex-cli --workspace . --json
giga session turn <session_id> --prompt "Проверь текущий diff" --json
giga session events <run_id> --json
giga session approve <approval_id> --decision allow_once --json
```

Agent profiles:

```bash
giga agent list --workspace .
giga agent show reviewer --workspace . --json
giga agent validate .giga/agents/reviewer.yaml
giga agent run reviewer --workspace . --prompt "Проверь этот patch" --dry-run
```

Workflows:

```bash
giga workflow list --workspace .
giga workflow show review-team --workspace . --json
giga workflow validate .giga/workflows/review-team.yaml
giga workflow run review-team --workspace . --prompt "Проверь изменение" --json
giga workflow status <workflow_run_id> --json
giga workflow cancel <workflow_run_id>
```

Текущие source-derived contracts:

```bash
giga harness list --json
giga harness inspect codex-cli --json
giga harness capabilities
giga harness capabilities --agents
giga harness capabilities --agents --json
giga harness capabilities --inventory --json
```

Arena сейчас доступна через Web/API, отдельной команды `giga arena` нет.
Откройте **Evaluation → Arena** в `giga ui` или используйте authenticated
`/api/arena/runs`, описанные в
[архитектуре Harness](architecture/harness.md).

## Генерируемая capability matrix

Versioned product inventory строится из product schemas, встроенных registries,
установленных entry points, provider compatibility profiles, CLI parser,
registry команд TUI, API routes и contract tests. First-run doctor включает
его schema, version, digest, provider contracts и documentation ids:

```bash
giga harness capabilities --inventory --json
```

[Матрица agent surfaces](agent-capability-matrix.md) — проекция того же
inventory. Её точный Markdown генерирует:

```bash
giga harness capabilities --agents
```

CI запускает `giga harness capabilities --inventory --check` и проверяет
inventory digest, CLI/TUI/API surfaces, protocol, transport, mode и deprecation
records, локальные documentation targets, contract-test evidence и
сгенерированные ячейки английской и русской матриц.
