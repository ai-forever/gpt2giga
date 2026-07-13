# Changelog

Все значительные изменения в проекте gpt2giga-harness документированы в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.0.0/),
и проект придерживается [Семантического версионирования](https://semver.org/lang/ru/).

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

[0.0.1a1]: https://github.com/ai-forever/gpt2giga/releases/tag/gpt2giga-harness-v0.0.1a1
