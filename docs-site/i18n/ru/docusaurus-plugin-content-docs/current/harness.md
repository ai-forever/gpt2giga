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
git clone --branch feature/unified_harness \
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
uv tool install gpt2giga-harness
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
giga doctor
giga init
```

`giga init` создаёт в `.giga/` non-secret конфигурацию, стартовые agent profiles,
prompts, smoke eval и review workflow. Существующие файлы не заменяются без
флага `--overwrite`.

Сначала проверьте локальный execution path через `echo` без credentials и сети:

```bash
giga harness run echo \
  --workspace . \
  --prompt "Кратко опиши выбранную задачу"
```

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

Для встроенных внешних CLI поле `protocol_capability_scope` имеет значение
`harness_surface`: capability-описание фиксирует то, что Harness действительно
наблюдает и гарантирует, а не все внутренние wire-протоколы CLI. В
`adapter_capabilities` используются состояния `supported`, `partial`,
`delegated` и `unsupported`, поэтому `giga harness inspect --json` и
`/api/harnesses` явно показывают ограничения continuity, native policy, доставки
первого prompt и managed tools.

Для новых управляемых native-запусков Harness сохраняет неизменяемый безопасный
execution snapshot: route `v1|v2`, model, managed home, workspace, project id,
permission mode и hash управляемой tool-конфигурации. Этот snapshot переносится
через sync, import, link и resume. Старые refs без snapshot помечаются
`route_unknown`: перед resume нужно явно подтвердить `api_mode`, и неизвестный
исходный route больше не подменяется молча на `/v2`. Противоречащие snapshot
route, model, home, workspace, project или harness блокируются до запуска CLI.

Перед новым Gemini native-запуском Harness проверяет поддержку
`--prompt-interactive` установленной версией CLI. Если flag доступен, составной
prompt вместе с отрендеренными ссылками на attachments передаётся ровно в одном
interactive invocation, без обрезания и повторной отправки через stdin. Run и
native link сохраняют безопасные idempotency key, hash prompt, число байт,
механизм и состояние `pending|delivered|failed`; сам prompt не копируется в
command или plan metadata. Повторный browser submit с тем же key отклоняется и
после перезагрузки UI. Старая версия Gemini без подтверждённого flag завершается
явной ошибкой до spawn, а не открывает пустой terminal.

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
