# Релиз

GigaLoom выпускает дистрибутив `gigaloom` по точным тегам
`gigaloom-vX.Y.Z`.

## Checklist maintainer

1. Убедитесь, что назначенные backup owners GitHub и PyPI приняли доступ с 2FA
   согласно
   [governance policy](https://github.com/krakenalt/gigaloom/blob/main/GOVERNANCE.md).
2. Обновите оба changelog и проверьте package version.
3. Соберите frontend assets и выполните полный non-live quality gate.
4. Соберите wheel и sdist без workspace sources.
5. Проверьте metadata, assets, checksums и isolated install.
6. Убедитесь, что release commit находится в `main`, а документированные
   main/tag rulesets активны.
7. Создавайте immutable tag только после авторизации и готовности внешних gates.

Release workflow проверяет repository identity, tag/version, history, commit
SHA и artifact set до публикации. Manual dispatch только строит и аттестует, но
не публикует.

Trusted Publisher, tags, GitHub releases и package publication — отдельные
внешние мутации. См.
[runbook восстановления](https://github.com/krakenalt/gigaloom/blob/main/.github/RELEASE_RECOVERY.md).
