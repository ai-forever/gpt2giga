# Документация gpt2giga

Этот каталог теперь играет роль навигационного центра: корневой `README.md` объясняет, что делает проект, а `docs/` хранит подробные инструкции по запуску, эксплуатации, интеграциям и развитию.

## Canonical vs internal docs

Документы, перечисленные на этой странице, образуют canonical user-facing docs surface проекта.
Если в репозитории присутствуют internal working notes или planning/handoff материалы, они должны жить под `docs/internal/` и не считаются operator-facing source of truth.

## С чего начать

| Сценарий | Куда идти |
|---|---|
| Быстро понять проект и запустить локально | [../README.md](../README.md) |
| Настроить `.env`, CLI-флаги, auth и HTTPS | [configuration.md](./configuration.md) |
| Выбрать runtime switches и режим эксплуатации | [operator-guide.md](./operator-guide.md) |
| Обновиться с ветки `0.1.x` на релизную линию `1.0` | [upgrade-0.x-to-1.0.md](./upgrade-0.x-to-1.0.md) |
| Подготовить релизную сборку `1.0` | [release-checklist.md](./release-checklist.md) |
| Проверить поддержку route и API surface | [api-compatibility.md](./api-compatibility.md) |
| Подключить IDE, CLI-агента или reverse proxy | [integrations/README.md](./integrations/README.md) |
| Разобраться в архитектуре | [architecture.md](./architecture.md) |
| Понять спорные архитектурные trade-off-ы | [design-notes.md](./design-notes.md) |
| Добавить новый внешний provider | [how-to-add-provider.md](./how-to-add-provider.md) |
| Посмотреть runnable-примеры SDK | [../examples/README.md](../examples/README.md) |

## Карта документов

| Документ | О чем он |
|---|---|
| [configuration.md](./configuration.md) | Локальный запуск, Docker, `.env`, API-key auth, pass-token, HTTPS, режимы `DEV`/`PROD` |
| [operator-guide.md](./operator-guide.md) | Provider gating, backend `v1`/`v2`, `/admin`, `/metrics`, Compose-сценарии |
| [upgrade-0.x-to-1.0.md](./upgrade-0.x-to-1.0.md) | Пошаговый upgrade checklist для операторов, которые переходят с `0.1.x` на `1.0` |
| [release-checklist.md](./release-checklist.md) | Release gate для версии, changelog, build/test, admin assets и publish sanity-check |
| [architecture.md](./architecture.md) | Текущий request flow, provider mapping, runtime/control plane и lifecycle admin UI |
| [design-notes.md](./design-notes.md) | Почему проект держится за frameworkless admin UI, committed compiled assets и feature/provider boundary |
| [api-compatibility.md](./api-compatibility.md) | Полная матрица OpenAI-, Anthropic- и Gemini-совместимых route |
| [integrations/README.md](./integrations/README.md) | Индекс интеграций для IDE, coding agents, reverse proxy и совместимых клиентов |
| [how-to-add-provider.md](./how-to-add-provider.md) | Workflow добавления нового внешнего provider-а |

## Практический маршрут

Если вы настраиваете сервис впервые, обычно достаточно такого порядка:

1. Пройти [../README.md](../README.md) и поднять локальный instance.
2. Довести конфигурацию по [configuration.md](./configuration.md).
3. Для production или multi-instance режима открыть [operator-guide.md](./operator-guide.md).
4. Для конкретного клиента перейти в [integrations/README.md](./integrations/README.md).
