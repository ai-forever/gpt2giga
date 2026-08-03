# Перенос репозитория GigaLoom

GigaLoom — локальный agentic workbench, ранее описанный здесь как Unified
Harness, — теперь развивается в отдельном репозитории
[`krakenalt/gigaloom`](https://github.com/krakenalt/gigaloom).

## Что изменилось

- `ai-forever/gpt2giga` владеет compatibility gateway `gpt2giga`, его
  публичными OpenAI/Anthropic/Gemini-shaped API, bridge provider profiles 0.3,
  deployment manifests и этим сайтом.
- `krakenalt/gigaloom` владеет workbench GigaLoom, дистрибутивом
  `gpt2giga-harness`, оркестрацией native agents, Cockpit UI, approvals,
  workbench provider-launch presets и состоянием workbench.
- Установка `gpt2giga` не устанавливает GigaLoom. Установка и эксплуатация
  GigaLoom описываются в отдельном репозитории.

## Старые URL документации

Старые страницы Harness, agents, capabilities, approvals, provider auth,
network authority, UI identity и frontend assets сохранены здесь только как
migration tombstones. Они не являются актуальной документацией продукта.

Актуальные source, установка, документация, issues и releases находятся в
[отдельном репозитории GigaLoom](https://github.com/krakenalt/gigaloom). Этот
сайт остаётся каноническим для [совместимости API](api-compatibility.md),
[конфигурации](configuration.md), [интеграций](integrations.md) и
[эксплуатации](operations.md) gateway.

## Граница совместимости

В gpt2giga сохраняются публичные API и версионированный нормализованный слой
протоколов. В некоторых старых настройках и записях журнала изменений всё ещё
встречается слово `Harness` — оно оставлено для обратной совместимости. Сам
GigaLoom теперь развивается в отдельном репозитории.

Запуск gpt2giga из GigaLoom описан в разделе
[«Переход на gpt2giga 0.3»](migration-0-3.md). Интеграция использует только
установленную CLI-команду и публичный HTTP API. Общих внутренних Python-модулей
и миграции постоянных данных у проектов нет.
