# Документация gpt2giga

Этот каталог теперь играет роль навигационного центра: корневой `README.md` объясняет, что делает проект, а `docs/` хранит подробные инструкции по запуску, эксплуатации, интеграциям и развитию.

## С чего начать

| Сценарий | Куда идти |
|---|---|
| Быстро понять проект и запустить локально | [../README.md](../README.md) |
| Настроить `.env`, CLI-флаги, auth и HTTPS | [configuration.md](./configuration.md) |
| Выбрать runtime switches и режим эксплуатации | [operator-guide.md](./operator-guide.md) |
| Проверить поддержку route и API surface | [api-compatibility.md](./api-compatibility.md) |
| Подключить IDE, CLI-агента или reverse proxy | [integrations/README.md](./integrations/README.md) |
| Разобраться в архитектуре | [../ARCHITECTURE_v2.md](../ARCHITECTURE_v2.md) |
| Добавить новый внешний provider | [how-to-add-provider.md](./how-to-add-provider.md) |
| Посмотреть runnable-примеры SDK | [../examples/README.md](../examples/README.md) |

## Карта документов

| Документ | О чем он |
|---|---|
| [configuration.md](./configuration.md) | Локальный запуск, Docker, `.env`, API-key auth, pass-token, HTTPS, режимы `DEV`/`PROD` |
| [operator-guide.md](./operator-guide.md) | Provider gating, backend `v1`/`v2`, `/admin`, `/metrics`, Compose-сценарии |
| [api-compatibility.md](./api-compatibility.md) | Полная матрица OpenAI-, Anthropic- и Gemini-совместимых route |
| [integrations/README.md](./integrations/README.md) | Индекс интеграций для IDE, coding agents, reverse proxy и совместимых клиентов |
| [how-to-add-provider.md](./how-to-add-provider.md) | Workflow добавления нового внешнего provider-а |

## Практический маршрут

Если вы настраиваете сервис впервые, обычно достаточно такого порядка:

1. Пройти [../README.md](../README.md) и поднять локальный instance.
2. Довести конфигурацию по [configuration.md](./configuration.md).
3. Для production или multi-instance режима открыть [operator-guide.md](./operator-guide.md).
4. Для конкретного клиента перейти в [integrations/README.md](./integrations/README.md).
