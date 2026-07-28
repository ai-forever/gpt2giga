# Релиз

GigaLoom выпускает дистрибутив `gpt2giga-harness` по точным тегам
`gpt2giga-harness-vX.Y.Z`.

## Checklist maintainer

1. Обновите оба changelog и проверьте package version.
2. Соберите frontend assets и выполните полный non-live quality gate.
3. Соберите wheel и sdist без workspace sources.
4. Проверьте metadata, assets, checksums и isolated install.
5. Убедитесь, что release commit находится в `main`.
6. Создавайте immutable tag только после авторизации и готовности внешних gates.

Release workflow проверяет repository identity, tag/version, history, commit
SHA и artifact set до публикации. Manual dispatch только строит и аттестует, но
не публикует.

Trusted Publisher, tags, GitHub releases и package publication — отдельные
внешние мутации. См.
[runbook восстановления](https://github.com/krakenalt/gigaloom/blob/main/.github/RELEASE_RECOVERY.md).
