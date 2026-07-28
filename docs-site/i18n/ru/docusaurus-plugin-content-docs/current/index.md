# Документация GigaLoom

GigaLoom — локальный, нейтральный к провайдеру управляющий слой для coding
agents. CLI, терминальный интерфейс и браузерный cockpit запускают нативных
агентов, а worktrees, approvals, evidence, schedules и сохранённое состояние
остаются под явной локальной политикой.

Линия `0.5.1a1` — alpha preview. Начните с [Установки](installation.md), затем
пройдите [Быстрый старт](quickstart.md).

## Выберите путь

| Задача | Руководство |
|---|---|
| Установить или обновить preview | [Установка](installation.md) |
| Запустить первую управляемую сессию | [Быстрый старт](quickstart.md) |
| Понять компоненты и trust boundaries | [Архитектура](architecture.md) |
| Сохранить состояние или устранить проблему | [Операции](operations.md) |
| Проверить privacy и authority boundaries | [Безопасность](security.md) |
| Подключить необязательный gateway gpt2giga | [Интеграция с gateway](gateway-integration.md) |
| Внести вклад или подготовить релиз | [Разработка](contributing.md) · [Релиз](release.md) |

Подробный [справочник Harness](harness.md), [agent workflows](agents-and-multi-agent.md)
и [матрица возможностей](agent-capability-matrix.md) описывают расширенную
поверхность продукта.

## Основная граница

Базовый дистрибутив самодостаточен и не требует checkout исходников
`gpt2giga`. Provider CLI сами владеют аутентификацией, а GigaLoom — локальной
оркестрацией, approvals, redaction и evidence.

Gateway совместимость подключается через необязательный установленный
дистрибутив. Нормализованный протокол и публичная API-совместимость gateway
остаются отдельными контрактами из
[руководства по интеграции](gateway-integration.md).

## Адреса проекта

- [Исходный код, issues и releases](https://github.com/krakenalt/gigaloom)
- [Опубликованная документация](https://krakenalt.github.io/gigaloom/)
- [Пакет](https://pypi.org/project/gpt2giga-harness/)
- Контекст извлечения: [История исходников](source-history.md)
