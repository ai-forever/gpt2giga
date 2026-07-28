# Архитектура

GigaLoom — самостоятельный Python-дистрибутив с тремя локальными поверхностями:

1. команда `giga` запускает provider-native команды и административные операции;
2. терминальный UI на Textual показывает локальные runs и approvals;
3. FastAPI control plane раздаёт упакованный browser cockpit через loopback.

## Основные границы

- `gpt2giga_harness.harnesses` владеет встроенными adapters.
- `runtime` и `sessions` владеют jobs, leases, events, policy и persistence.
- `project`, `workspace` и `worktrees` ограничивают файловые изменения.
- `ui` проецирует redacted state и не становится вторым источником authority.
- Нативные provider CLI владеют аутентификацией и выполнением у провайдера.
- Gateway подключается через установленный дистрибутив, а не source dependency.

Approval связывается с проверенными scope и preview. Перед dispatch связь
проверяется снова; drift, cancellation, lease loss или отсутствие authority
приводят к fail-closed. Чувствительные значения редактируются до сохранения и
сериализации.

## Подробные решения

- [Архитектура компонентов](architecture/harness.md)
- [Схема authority и approval](architecture/authority-approval-schema-adr.md)
- [Ограниченный сетевой доступ](architecture/scoped-network-access-adr.md)
- [GitHub capability grants](architecture/github-capability-grants-adr.md)
- [Матрица аутентификации](architecture/provider-authentication-capability-matrix.md)
- [Сборка frontend assets](architecture/frontend-asset-build-architecture-adr.md)
- [Provider-native CLI facade](architecture/provider-native-cli-facade-adr.md)
