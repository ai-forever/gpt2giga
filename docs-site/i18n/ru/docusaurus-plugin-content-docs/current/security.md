# Безопасность

GigaLoom разделяет локальное выполнение, evidence, credentials, сетевой доступ
и внешние мутации на отдельные trust boundaries.

## Модель безопасности

- Provider credentials остаются в provider-owned homes или явных secret
  resolution boundaries.
- Секреты редактируются до persistence, logs, diagnostics, previews и UI.
- Content capture включается явно.
- Мутации требуют scoped authority, когда это задано policy.
- Approval связывает точные scope и preview; dispatch проверяет их снова.
- Внешние команды используют явные arguments, controlled cwd, bounded output и
  redacted records.
- Network и GitHub capabilities fail closed без точного grant.

Не коммитьте credentials, tokens, `.env`, certificates, raw traffic или
fixtures с секретами.

## Сообщение об уязвимостях

До появления repository security policy в следующем governance slice не
раскрывайте уязвимости в публичном issue. Свяжитесь с владельцем приватно через
его проверенный GitHub profile и передайте минимальный redacted reproduction.
S3-04 установит постоянную policy и поддерживаемый канал.

Страница описывает поведение продукта и не утверждает, что внешняя governance
или private reporting infrastructure уже настроена.
