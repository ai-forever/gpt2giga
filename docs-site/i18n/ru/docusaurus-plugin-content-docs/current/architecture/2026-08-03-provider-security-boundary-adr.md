# ADR: граница credentials, destination, TLS и запрет fallback

- Дата: 2026-08-03
- Статус: принято для gpt2giga 0.3
- Владельцы решения: provider-profiles, provider adapters и integration
- Ревизия: `gpt2giga.provider-security.v1`

## Контекст

Universal bridge расширяет набор destinations и credentials процесса. Без
единой startup-owned границы поле совместимости, header, redirect, DNS result
или retry может стать незапланированным provider switch либо SSRF-путём.

## Решение

### Authority и request boundary

Только immutable provider profile выбирает provider kind, scheme, host, port,
base path, TLS policy, credential reference и upstream model. Bodies/headers не
могут их переопределить. `base_url`, `url`, `provider`, `api_key`, `token`,
`authorization`, TLS/proxy controls, arbitrary headers и upstream model ids
отклоняются до I/O, а не копируются в extensions. Adapters сами создают
provider-required headers и allowlist bounded trace ids; generic header map в
schema v1 отсутствует.

### Destination и DNS

- Production profiles требуют `https`.
- `http` разрешён только explicitly marked loopback development profile и не
  может разрешиться вне loopback.
- Userinfo, fragments, ambiguous ports, unsupported schemes и non-canonical
  hosts недопустимы.
- Private, link-local, multicast, unspecified, loopback и cloud metadata
  addresses запрещены, кроме точного loopback development rule.
- DNS resolution создаёт request-scoped network authorization, связанную со
  scheme/host/port/address set/method/body digest-size/purpose/response ceiling/
  expiry; connected peer сверяется с ней.
- SDK без этой границы не получает публичную конфигурацию до перехода на
  controlled transport.
- HTTP redirects отключены; redirect даёт `destination_mismatch`.

### TLS и credentials

TLS verification всегда включена. Profile ссылается на reviewed TLS policy id;
request не отключает verification и не поставляет certificates. Profile хранит
только имя environment/SecretRef. Enabled profiles разрешают credential при
preflight/startup; отсутствие даёт `credential_unavailable`. Values доступны
только точной границе adapter client и исключены из repr, errors, logs, traces,
metrics, inspect, manifests, fixtures и persistence. Per-request provider
credentials запрещены; legacy pass-token остаётся вне bridge-profile mode.

### Retry, cancellation и fallback

Provider/profile/alias/model/account/credential fallback запрещён. Bounded retry
может повторить только ту же idempotent operation, exact profile/model, по
reviewed policy и до первого response event. Streaming interruption, disconnect,
cancellation, destination mismatch, protocol error и semantic rejection не
являются cross-route retry signals. Все limits, network authorizations, bodies,
iterators и owned clients закрываются при любом исходе.

Content-free evidence может хранить ids/revisions, bounded error code, timings,
byte counts и network-attempt count. Credential values/hashes, raw auth headers,
content по умолчанию и unrestricted provider errors запрещены.

## Миграция и откат

- Existing GigaChat env settings используются только synthesized legacy profile.
- Request-carried transport/provider fields теперь fail closed в bridge mode.
- Удаление config после restart возвращает legacy boundary; 0.2.x оставляет
  profile files и policy references неактивными.
