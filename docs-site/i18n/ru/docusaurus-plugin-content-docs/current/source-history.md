# История исходников и миграция

GigaLoom извлечён с отфильтрованной историей из общего репозитория
[`ai-forever/gpt2giga`](https://github.com/ai-forever/gpt2giga). Это
**историческая ссылка на исходники**. Текущая разработка, документация, issues
и releases находятся в
[`krakenalt/gigaloom`](https://github.com/krakenalt/gigaloom).

Имя дистрибутива `gpt2giga-harness`, namespace `gpt2giga_harness`, команды
`giga` и `gpt2giga-harness`, а также пути локального состояния сохраняются.

Старые compare links в changelog намеренно ведут в исторический репозиторий,
чтобы pre-split tags оставались доступны. Они не означают текущего владения или
зависимости от source checkout.

Для миграции удалите старый combined prerelease artifact, установите standalone
`gpt2giga-harness` и сохраните backup `~/.gpt2giga/harness`. См.
[справочник Harness](harness.md), раздел «Миграция со старого combined
prerelease».
