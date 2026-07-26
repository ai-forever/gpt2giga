# ADR: граница идентификации удалённого UI

Статус: принято для slice G3-04 roadmap GigaLoom 2026-07-26.

Статус реализации: не реализовано. Удалённый UI остаётся fail-closed, пока
G3-05 не выполнит этот контракт.

## Контекст

GigaLoom может читать рабочие каталоги и запускать процессы с правами своей
учётной записи операционной системы. Поэтому локальный UI использует
одноразовый OS-local claim и серверные браузерные сессии. Такой bootstrap
доказывает близость к одной OS-учётной записи, но не удалённую идентичность
пользователя, tenant-границу, роль или проверяемого организационного
principal.

Прежний remote opt-in обменивал один общий environment bearer на одну
process-local cookie. Даже с TLS, проверкой Host, защитой CSRF и secure-cookie
он не позволял различить операторов, отозвать одного пользователя, связать
аудит с идентичностью или безопасно восстановить multi-user deployment.

## Решение

Удалённый multi-user UI остаётся в текущем roadmap, но требует отдельной
реализации G3-05 и deployment gate. Поддерживаемая граница — один статически
настроенный и принадлежащий deployment OpenID Connect issuer на один deployment
GigaLoom.

GigaLoom выступает confidential Backend for Frontend (BFF):

- OpenID Connect Authorization Code flow с PKCE `S256`;
- client credentials, коды, ID/access/refresh tokens не попадают в браузерный
  JavaScript или browser storage;
- браузер получает только opaque host-only cookie с `Secure`, `HttpOnly` и
  `SameSite=Strict`;
- сессии и их revocation хранятся на сервере;
- browser API ограничен тем же origin GigaLoom;
- issuer, client id, внешний HTTPS origin и callback URI задаются точно.

Допускаются только metadata и алгоритмы, явно проверенные в G3-05. Исключены
выбираемый пользователем issuer, dynamic client registration, implicit и
password flows, локальная база паролей, social-login aggregation и вставка
bearer-token через форму.

### Идентичность и роли

Стабильный remote actor — точная пара `(iss, sub)` из проверенного ID token.
Email, display name, domain и другие изменяемые claims не являются ключами
идентичности.

G3-05 реализует две роли:

- `viewer`: только чтение ограниченного product state без mutation, execution,
  approval, secret resolution или изменения интеграций;
- `operator`: то же чтение и доступ к mutation entry points, по-прежнему
  ограниченный независимой системой action authority и approvals.

Subject или группа без mapping получает отказ. Роли задаются deployment-owned
default-deny mapping по точным подписанным claims; роль нельзя выводить из
суффикса email. Изменение роли отзывает или вращает активные сессии. Ни одна
роль не меняет filesystem/process ceiling service account, поэтому tenant
isolation требует отдельных экземпляров GigaLoom и OS isolation.

Audit receipt содержит стабильный недисплейный actor id, производный от
проверенных issuer и subject, допущенную роль, session id и время
аутентификации. Display claims можно показать временно, но нельзя использовать
для авторизации.

### Login и сессии

Каждая login transaction получает одноразовые expiring `state`, `nonce` и PKCE
verifier, связанные с инициирующим браузером. Callback проверяет issuer,
signature, algorithm, audience, authorized party при необходимости, expiry,
issued-at, nonce и точный redirect URI до создания сессии. Неизвестный
алгоритм, metadata drift, ошибка получения ключа, replay и недопустимый clock
skew закрываются fail-closed.

Remote session имеет абсолютный и более короткий idle lifetime и вращается при
login, изменении привилегий и recovery. OAuth material не возвращается UI API
и не попадает в project state, logs, diagnostics, screenshots, traces или
audit receipts.

Каждый изменяющий запрос требует custom CSRF header и точной same-origin
проверки вместе с session cookie. Одного `SameSite` недостаточно.

### Logout, revocation и recovery

Локальный logout сначала отзывает серверную сессию GigaLoom и только затем при
наличии проверенной capability может перейти к RP-initiated logout провайдера.

G3-05 должен поддержать глобальный, actor-specific и session-specific revoke.
Проверенный OIDC back-channel logout token может отозвать сессии по issuer и
`sid` или `sub`; replay, неверная подпись, тип или audience закрываются
fail-closed. Issuer без допущенной logout capability получает только
ограниченный lifetime GigaLoom session и честный статус degraded.

Bootstrap recovery остаётся OS-local и не создаёт удалённую browser session. Он
может проверить identity config, повернуть session keys GigaLoom и отозвать все
remote sessions. При недоступности issuer или trusted proxy remote login
недоступен; local bootstrap не становится remote break-glass credential.

### Proxy и origin

Public origin — одна точная комбинация HTTPS scheme, host и port. Прямой
удалённый HTTP не поддерживается. Forwarded host, scheme и client address
игнорируются, если immediate peer не совпадает с явной trusted-proxy
конфигурацией. Конфликтующие или недопустимые multi-hop значения отвергаются.

Allowed Hosts, callback URL, post-logout redirect и CORS — точные allowlists.
Wildcard и redirect target из request запрещены. TLS termination, HSTS, лимиты
размера и частоты запросов и trusted-proxy config остаются обязанностью
deployment и проверяются doctor до remote startup.

## Threat model

| Угроза | Обязательный контроль |
| --- | --- |
| Утечка или replay общего bootstrap | Удалить его из remote auth; отвергать non-loopback startup до G3-05. |
| Перехват или injection authorization code | Exact redirect URI, одноразовая transaction state, Authorization Code, PKCE `S256` и nonce. |
| Issuer mix-up или token substitution | Один точный issuer; проверка `iss`, signature, algorithm, `aud`, `azp`, nonce и key provenance. |
| CSRF или login CSRF | Browser-bound одноразовый state, PKCE/nonce, exact Origin, strict cookie и custom mutation header. |
| Session fixation или кража cookie | Ротация opaque server-side session; host-only secure HttpOnly strict cookie; idle и absolute expiry. |
| Подмена proxy headers или Host | Forwarded fields доверяются только явным proxy peers; exact public origin и Host allowlist. |
| Role escalation через mutable claims | Default-deny exact mapping; никакого email inference; revoke при изменении mapping. |
| Доступ после logout или инцидента | Local, actor и global revoke; back-channel logout; bounded lifetime. |
| XSS или скомпрометированный asset | Нет OAuth tokens в browser, нет runtime third-party assets, CSP, encoding и server authorization каждого request. |
| Доступ одного пользователя к OS-ресурсам другого tenant | Вне scope одного instance; отдельные service accounts и deployments. |
| Недоступность IdP или потеря config | Fail-closed; только OS-local doctor и recovery ключей/revocation. |

## Операционное решение

Стоимость приемлема только для этого ограниченного single-issuer BFF profile.
Он переиспользует серверную границу GigaLoom и не отдаёт provider tokens
браузеру. При этом необходимы durable session/revocation storage, проверенная
OIDC validation, rotation, proxy policy, role enforcement, audit identity,
hermetic fixtures и deployment documentation.

Стоимость не принята для multiple issuers, tenant isolation внутри одного OS
process, собственного IdP, SCIM, dynamic registration, local password recovery
или live provider onboarding.

## Переход и gates

До реализации G3-05 GigaLoom принимает только loopback UI binding.
`--allow-remote`, legacy environment bootstrap token и remote Host allowlists
не авторизуют listener. Non-loopback host завершается ошибкой до запуска
FastAPI application или worker pool и сообщает, что OIDC contract ещё не
реализован.

G3-05 разрешено реализовать один этот profile с hermetic issuer fixtures. Оно
не разрешает регистрировать live client, настраивать secrets, создавать users
или groups, публиковать callback, развёртывать reverse proxy или запускать
remote listener с реальным identity provider. Для каждого действия нужен
отдельный внешний gate.

## Основные стандарты

- [OAuth 2.0 Security Best Current Practice (RFC 9700)](https://www.rfc-editor.org/rfc/rfc9700.html)
- [OAuth 2.0 for Browser-Based Applications (RFC 10017)](https://www.rfc-editor.org/rfc/rfc10017.html)
- [Proof Key for Code Exchange (RFC 7636)](https://www.rfc-editor.org/rfc/rfc7636.html)
- [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html)
- [OpenID Connect Back-Channel Logout 1.0](https://openid.net/specs/openid-connect-backchannel-1_0-final.html)
- [OpenID Connect RP-Initiated Logout 1.0](https://openid.net/specs/openid-connect-rpinitiated-1_0-final.html)

## Последствия

Обмен общего remote bearer больше не является продуктным режимом. Существующие
remote experiments должны вернуться на loopback до завершения G3-05 и
отдельного разрешения deployment. Локальные first-run, logout, rotation и
recovery не меняются.

Этот ADR разрешает только G3-05. Он не предоставляет remote identity, role,
action authority, network/GitHub access, deployment или live OIDC config.
