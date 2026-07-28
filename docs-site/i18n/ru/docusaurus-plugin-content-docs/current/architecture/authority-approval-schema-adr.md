# ADR: Схема полномочий и подтверждений

Статус: принято для этапа G4-00 дорожной карты GigaLoom 2026-07-27.

## Контекст

Harness уже поддерживает запросы подтверждений, grants, профили разрешений,
симулятор без побочных эффектов и audit evidence, привязанный к хешу.
Существующая классификация действий является проекцией enforcement, а не полной
моделью полномочий: путь файловой системы не равен сетевому endpoint, GitHub
repository не равен локальному Git, а смена проверяющего не должна менять
sandbox.

Перед добавлением approval UX, сетевых и GitHub grants и диагностики первого
запуска этапу G4 нужен единый versioned source.

## Решение

Схемой версии 1 владеет `gpt2giga_harness.runtime.authority`. Она раздельно
моделирует восемь типов target:

- пути файловой системы относительно workspace;
- конкретный executable дочернего процесса вместе с content-addressed `argv` и
  `cwd`;
- сетевой host, port, protocol и redirect policy;
- точный GitHub `owner/repository`;
- точный browser origin;
- managed MCP server и необязательный tool;
- определение integration вместе с immutable revision;
- дочерний агент вместе с digest верхней границы полномочий родителя.

Каждый scope содержит конкретный target и непустой набор классов операций.
Semantic payload адресуется по содержимому. Approval preview привязан по
SHA-256, поэтому secrets, содержимое файлов, аргументы команд и другие исходные
значения не должны попадать в grants или receipts.

`operation`, `session` и `persisted_policy` являются разными lifetime.
Persisted policy grants всегда имеют срок действия. Каждый grant показывает
источник policy, тип и identity проверяющего, enforcement boundary, preview
digest, время создания и окончания, отзыв и необязательный parent grant.

Пользовательские presets компилируются в явные правила для каждого scope:

| Preset | Результат schema v1 |
| --- | --- |
| `always_ask` | Каждый конкретный scope получает решение `ask`. |
| `ask_on_writes` | Только зафиксированный набор read-only операций может получить `allow`; каждая другая операция получает `ask`. |
| `allow_reviewed` | Только точная пара scope и preview digest из проверенного набора получает `allow`; все остальные получают `ask`. |

Human review и auto review являются identities проверяющего. Они не меняют
boundary `enforced_by_harness`, `delegated_to_cli_sandbox` или
`advisory_or_unobservable`.

Полномочия дочернего агента действительны только тогда, когда его target
совпадает с target в верхней границе родителя, а операции являются подмножеством
родительских. G4-00 намеренно выбирает это строгое правило; будущий код может
добавить отдельно проверенное более узкое отношение target, но не должен
выводить его из строк.

Отозванный или истёкший grant, устаревший preview digest, изменившийся target,
redirect или retry требуют повторной проверки. Предыдущее подтверждение нельзя
привязать к изменившейся операции.

## Совместимость

`gpt2giga_harness.runtime.policy.PermissionAction` остаётся текущей проекцией
enforcement и persistence. G4-01 может отображать authority scopes версии 1 в
эти действия при создании approval UX и симулятора разрешений. G4-00 не
мигрирует существующие строки подтверждений и grants.

Неизвестные версии схемы, resource targets, presets, lifetime, операции и
некорректные digest отклоняются fail closed. Полученный из исходного кода
manifest является источником vocabulary для документации и UI.

## Последствия

G4-00 не выдаёт полномочия на filesystem, process, network, GitHub, browser,
MCP, integration или дочерних агентов. Этап не меняет sandbox settings, не
сохраняет новую policy, не отзывает существующие grants, не обращается к
credentials и не выполняет live mutations. G4-01 и последующие этапы должны
использовать эту схему вместо создания локальных словарей target или lifetime.
