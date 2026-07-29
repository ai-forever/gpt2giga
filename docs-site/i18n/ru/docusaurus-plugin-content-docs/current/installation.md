# Установка

GigaLoom поддерживает Python 3.10–3.14. Отдельно установите хотя бы один
provider-native CLI и завершите собственный flow аутентификации провайдера.

## Установка preview

Через `uv`:

```sh
uv tool install --prerelease allow 'gigaloom==0.5.1a1'
```

Или в изолированном Python-окружении:

```sh
python -m pip install --pre 'gigaloom==0.5.1a1'
```

Проверьте установленный артефакт:

```sh
giga --version
giga doctor
```

`doctor` сообщает состояние возможностей и конфигурации, не читая содержимое
prompts и не обращаясь к провайдерам.

## Миграция с `gpt2giga-harness`

Имя PyPI-проекта изменилось до первого самостоятельного target release.
Удалите исторический дистрибутив и установите `gigaloom`, не удаляя
существующие каталоги состояния:

```sh
uv tool uninstall gpt2giga-harness
uv tool install --prerelease allow 'gigaloom==0.5.1a1'
```

Python namespace `gpt2giga_harness`, команды `giga` и
`gpt2giga-harness`, `~/.gpt2giga/harness` и `.giga/` остаются совместимыми.
Dual-published shim не требуется.

## Необязательный gateway preset

Базовый пакет не требует gpt2giga. Установите extra только для Direct Chat или
legacy preset локального gateway:

```sh
uv tool install --prerelease allow 'gigaloom[gpt2giga]==0.5.1a1'
```

Устанавливается закреплённый публичный дистрибутив gateway. Репозиторий gateway,
sibling checkout, editable dependency или submodule не нужны. См.
[Интеграцию с gateway](gateway-integration.md).

## Обновление и удаление

```sh
uv tool upgrade --prerelease allow gigaloom
uv tool uninstall gigaloom
```

Удаление пакета не удаляет пользовательское состояние в
`~/.gpt2giga/harness`. Сначала прочитайте [Операции](operations.md).
