# Перенос репозитория GigaLoom

GigaLoom — локальный agentic workbench, ранее описанный здесь как Unified
Harness, — теперь развивается в отдельном репозитории
[`krakenalt/gigaloom`](https://github.com/krakenalt/gigaloom).

## Что изменилось

- `ai-forever/gpt2giga` владеет compatibility gateway `gpt2giga`, его
  публичными OpenAI/Anthropic/Gemini-shaped API, deployment manifests и этим
  сайтом.
- `krakenalt/gigaloom` владеет workbench GigaLoom, дистрибутивом
  `gpt2giga-harness`, оркестрацией native agents, Cockpit UI, approvals,
  provider profiles и состоянием workbench.
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

Gateway сохраняет публичные compatibility contracts и версионированный
normalized protocol bridge. Некоторые настройки gateway и исторические записи
changelog сохраняют слово `Harness` ради обратной совместимости. Это не делает
GigaLoom активно поддерживаемым продуктом этого репозитория.
