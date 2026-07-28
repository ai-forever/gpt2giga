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

Не раскрывайте предполагаемые уязвимости в публичном issue, discussion или pull
request. Следуйте repository
[security policy](https://github.com/krakenalt/gigaloom/blob/main/SECURITY.md)
и используйте
[GitHub private vulnerability reporting](https://github.com/krakenalt/gigaloom/security/advisories/new).
Передавайте минимальный redacted reproduction и никогда не отправляйте
credentials, user content, native-home data или raw provider traffic.

Primary security owner —
[`@krakenalt`](https://github.com/krakenalt). Роль backup maintainer, response
targets, 2FA gate и восстановление compromised publisher определены в security
и
[governance](https://github.com/krakenalt/gigaloom/blob/main/GOVERNANCE.md)
policies. Public cutover заблокирован, пока отдельный backup owner не принял
доступ.
