# Матрица возможностей agent surfaces GigaLoom

> Сгенерировано командой `giga harness capabilities --agents` из встроенных
> контрактов `HarnessSpec` и адаптеров. Ячейки матрицы нужно обновлять через
> генератор, а не вручную.

| Возможность | Direct Chat Completions | Codex CLI | Claude Code | Gemini CLI |
| --- | --- | --- | --- | --- |
| `execution_route` | supported | supported | supported | supported |
| `provider_authentication` | delegated | delegated | delegated | delegated |
| `session_continuity` | supported | partial | partial | partial |
| `cancellation` | supported | supported | supported | supported |
| `harness_and_provider_approvals` | partial | partial | partial | partial |
| `managed_mcp` | unsupported | supported | supported | supported |
| `skills_and_plugins` | partial | partial | partial | partial |
| `gigachat_builtin_tools` | supported | delegated | delegated | delegated |
| `isolated_edit_delivery` | unsupported | supported | supported | supported |
| `multi_agent_delivery` | partial | partial | partial | partial |
| `usage_and_monetary_cost` | partial | partial | partial | partial |
| `structured_evidence` | supported | partial | partial | partial |
| `cross_provider_session_transfer` | unsupported | unsupported | unsupported | unsupported |
| `hidden_reasoning_transfer` | unsupported | unsupported | unsupported | unsupported |

## Свидетельства контракта

### `execution_route`

Direct Chat вызывает GigaChat через локальный Chat Completions route.
CLI-поверхности запускают выбранный внешний coding-agent adapter, а поведение
внутри процесса остаётся ответственностью provider CLI.

### `provider_authentication`

Для Direct Chat границей credential остаётся gateway. В CLI-поверхностях
нативный provider CLI отвечает за login, refresh, хранение credentials, logout
и revocation; наличие executable не доказывает готовность аккаунта.

### `session_continuity`

Direct Chat воспроизводит нормализованную видимую историю. CLI-поверхности
поддерживают продолжение сессии частично: точный механизм зависит от
version-probed headless/app-server route и обнаруженного native session id.

### `cancellation`

Harness предоставляет cooperative cancellation для всех допущенных routes.
Уже завершившиеся provider side effects при этом не откатываются.

### `harness_and_provider_approvals`

Harness approvals покрывают принадлежащие Harness действия, например запуск
процесса или применение patch. Внутренние approval prompts провайдера остаются
provider-owned и не выводятся из внешнего receipt.

### `managed_mcp`

Direct Chat не проецирует managed MCP descriptors как встроенные инструменты
GigaChat. CLI-адаптеры фиксируют проверенные project MCP descriptors в
неизменяемом redaction-safe snapshot и разрешают secret references только при
создании subprocess.

### `skills_and_plugins`

GigaLoom может находить и управлять проверенными integrations на всех
поверхностях. Присутствие в каталоге само по себе не даёт execution authority
и не доказывает автоматическую prompt/tool injection.

### `gigachat_builtin_tools`

Для Direct Chat допускаются `web_search`, `url_content_extraction`,
`code_interpreter`, `image_generate` и `model_3d_generate`. Нативные
инструменты внешних CLI остаются provider-owned и не считаются эквивалентом
GigaChat built-ins.

### `isolated_edit_delivery`

В Direct Chat нет repository edit loop. CLI-адаптеры проводят запуск через
общую policy, а edit mode использует изолированный Git worktree согласно
политике `auto` или `worktree`.

### `multi_agent_delivery`

GigaLoom может координировать независимые Arena/workflow runs и передавать
ограниченные summaries или artifact references. Это не перенос нативного
subagent state или скрытых рассуждений.

### `usage_and_monetary_cost`

Provider-emitted usage сохраняется, когда доступен. Денежная стоимость остаётся
неизвестной, пока провайдер не вернёт явное подтверждение стоимости.

### `structured_evidence`

Direct Chat нормализует видимые response, tool, usage и completion events.
Для CLI-поверхностей нормализованные events доступны только через проверенные
headless/app-server routes; интерактивный TUI остаётся redacted raw-terminal
stream.

### `cross_provider_session_transfer`

Сохранённый Harness summary или handoff capsule не переносит нативную identity
сессии между провайдерами или адаптерами.

### `hidden_reasoning_transfer`

Через границы разрешено передавать только видимые summaries, messages, events
и сохранённые artifacts. Скрытые рассуждения не запрашиваются и не считаются
переносимыми.
