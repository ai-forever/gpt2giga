# Pull request GigaLoom

## Результат

<!-- Какое пользовательское или repository behavior изменяется? Добавьте target issues. -->

## Scope и совместимость

- Затронутый owner:
- Влияние на public CLI/UI/API/protocol/storage:
- Migration и rollback:
- Historical source link, если работа продолжает прежнюю:

## Проверка

<!-- Перечислите точные команды и ручные проверки с результатами. -->

```text

```

## Чеклист безопасности и release

- [ ] Изменение сфокусировано и проверено тестами owning layer.
- [ ] Нет credential, token, private user content, native-home data или raw traffic.
- [ ] English и Russian public documentation согласованы, если применимо.
- [ ] Изменения public compatibility имеют focused contract tests.
- [ ] Dependencies обоснованы; editable sibling, source override и root `uv.lock` не добавлены.
- [ ] Workflow permissions минимальны, untrusted PR code не получает secrets.
- [ ] Release/security/governance изменения получили требуемый owner review.
- [ ] Historical issues, reviews, authorship и timestamps связаны ссылками, а не представлены как перенесённые.

## Проверка maintainer

- [ ] Required stable checks совпадают с `.github/repository-policy.json`.
- [ ] Changelog/version/release notes рассмотрены.
- [ ] Emergency bypass имеет audit record и follow-up review.
