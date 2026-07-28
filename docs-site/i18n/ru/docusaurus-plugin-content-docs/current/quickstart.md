# Быстрый старт

Установите GigaLoom и проверьте локальное окружение:

```sh
giga doctor
giga --version
```

Аутентификация остаётся provider-owned. Войдите через нативный CLI Codex,
Claude или Gemini до запуска через GigaLoom.

## Префикс нативной команды

GigaLoom добавляет один префикс и сохраняет остальную команду:

```sh
giga codex exec --json "кратко опиши репозиторий"
giga claude -p "кратко опиши репозиторий"
giga gemini -p "кратко опиши репозиторий"
```

Help, version, stdin/stdout, JSON/JSONL и exit status остаются нативными. Если
CLI отсутствует или его контракт изменился, dispatch завершается fail-closed
до запуска provider session.

## Браузерный cockpit

```sh
giga ui
```

Откройте `http://127.0.0.1:8091/`. По умолчанию listener доступен только через
loopback. В cockpit:

1. выберите или зарегистрируйте локальный проект;
2. выберите provider adapter;
3. просмотрите execution preview и требуемый authority;
4. подтвердите только точное действие, которое хотите выполнить;
5. изучите события, diff и evidence.

Для терминального workflow используйте `giga tui`.

## Дальше

- [Справочник Harness](harness.md)
- [Agents и multi-agent поведение](agents-and-multi-agent.md)
- [Операции](operations.md)
- [Безопасность](security.md)
