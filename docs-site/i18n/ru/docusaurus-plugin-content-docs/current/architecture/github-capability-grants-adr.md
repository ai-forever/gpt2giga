# ADR: Ограниченные GitHub capabilities

Статус: принят для slice G4-03 roadmap GigaLoom 2026-07-27.

## Контекст

В GigaLoom уже есть два намеренно разных GitHub-пути:

- `GitHubEnvironmentService` выполняет ограниченную read-only ориентацию по
  repository через reviewed-команды `gh`;
- `GovernedEnvironmentPullRequestService` создаёт один точный pull request
  только после approval, связанного с неизменным локальным и hosted state.

Ни один путь не приравнивает локальный `git` к hosted GitHub authority.
Локальный commit или branch имеет другие credentials, targets, enforcement и
side effects, чем authenticated GitHub API или CLI request.

GitHub CLI также разделяет active account/host и каждый API request. Команда
`gh api` может неявно изменить HTTP method при добавлении fields, поэтому
GigaLoom связывает grant с operation class и reviewed payload, а не доверяет
названию команды. GitHub REST permissions зависят от endpoint и иногда требуют
нескольких repository permissions.

## Решение

`gpt2giga_harness.runtime.github_access` владеет schema version 1 для
семантической GitHub authority boundary. Она классифицирует:

- `local_git` как отдельную, не-GitHub authority;
- `github_api` и `github_cli` как hosted GitHub authority;
- read-only orientation отдельно от issue, comment, pull-request и release
  writes.

Каждый request связывает один канонический `owner/repository`, один operation
class, одну API/CLI surface и один opaque credential binding. Credential binding
содержит только класс владельца, host, hash principal, hash permission set и
expiry, если владелец credential его раскрывает. Tokens, account labels и пути
credential storage не попадают в requests, approvals или receipts.

Контракт не настраивает, не обновляет, не переключает, не печатает и никак
иначе не разрешает GitHub credentials. В частности, GigaLoom никогда не
вызывает token-revealing опции `gh auth`.

## Read-only orientation

`orientation.read` не принимает и не расходует mutation authority. Поэтому
repository identity, pull-request state, counts issues/checks и recent Actions
доступны для ориентации без hosted write grant.

Для реального transport по-прежнему отдельно нужны admitted network/CLI
execution. Контракт G4-03 — только semantic authorization; он не обращается к
GitHub и не ослабляет network controls G4-02.

## Hosted writes

Issue, comment, pull-request и release writes требуют:

1. точный Harness-enforced `AuthorityGrant`;
2. operation lifetime вместо session или persisted write grant;
3. неотозванный grant с явным expiry;
4. те же repository, operation class, credential binding, content-free
   resource identity, payload byte count и payload SHA-256, что в reviewed
   preview;
5. preview window не более пяти минут;
6. повторную validation непосредственно перед dispatch.

Automatic retry не покрывается прежним grant. Retry, изменённый target,
payload, credential identity или permission set, просроченный preview либо
просроченный/отозванный grant требуют нового preview и решения.

Существующее создание pull request остаётся во владении immutable-state
service. G4-03 даёт общий semantic seam, но не переавторизует и не исполняет
этот старый flow автоматически.

## Audit и privacy

Receipts показывают repository, operation class, API/CLI surface, класс
credential source, hashes, byte counts, policy source, reviewer class, expiry
и outcome. Resource и reviewer identities хешируются.

Receipts не содержат credential material, raw principals, write bodies и
direct personal, contact или payment data. Consumer обязан применить то же
правило до передачи preview в общий Approval Center.

## Последствия

GigaLoom может рассуждать о GitHub orientation и mutation без blanket-
переключателя «GitHub enabled». Само использование `gh` или создание approval
request не защищает mutation consumer: он обязан применить exact ticket при
dispatch и сохранить отдельную network boundary.

Slice не выполняет live GitHub read/write, login, credential setup, push,
issue/comment/PR mutation, release publication или network request.

## Ссылки

- [GitHub CLI `gh auth status`](https://cli.github.com/manual/gh_auth_status)
- [GitHub CLI `gh api`](https://cli.github.com/manual/gh_api)
- [GitHub REST API permission troubleshooting](https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api)
- Authority and approval schema:
  `docs/architecture/authority-approval-schema-adr.md`.
- Scoped network access: `docs/architecture/scoped-network-access-adr.md`.
