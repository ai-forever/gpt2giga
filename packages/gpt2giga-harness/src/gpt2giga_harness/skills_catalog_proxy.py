"""Read-only fixed-origin proxy for authenticated skills.sh metadata."""

from __future__ import annotations

from collections import OrderedDict, defaultdict, deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import hashlib
import json
import os
import re
from threading import Lock
import time
from typing import Any, Protocol
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

import anyio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


SKILLS_PROXY_UPSTREAM_ORIGIN = "https://skills.sh"
SKILLS_PROXY_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
SKILLS_PROXY_TIMEOUT_SECONDS = 20.0
SKILLS_PROXY_MAX_PAGE_SIZE = 500
SKILLS_PROXY_MAX_SEARCH_LIMIT = 200
SKILLS_PROXY_MAX_QUERY_LENGTH = 200
SKILLS_PROXY_MAX_CACHE_ENTRIES = 128
SKILLS_PROXY_STALE_IF_ERROR_SECONDS = 3_600
SKILLS_PROXY_MAX_FILE_PATHS = 512
SKILLS_PROXY_MAX_AUDITS = 32
_PATH_PART_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~-]{0,127}\Z")
_LIST_ITEM_FIELDS = {
    "id",
    "slug",
    "name",
    "source",
    "installs",
    "sourceType",
    "installUrl",
    "url",
    "isDuplicate",
    "installsYesterday",
    "change",
}


@dataclass(frozen=True)
class SkillsCatalogProxySettings:
    """Safe runtime settings; the upstream origin is intentionally not configurable."""

    listen_host: str = "127.0.0.1"
    listen_port: int = 8092
    rate_limit_per_minute: int = 120
    max_cache_entries: int = SKILLS_PROXY_MAX_CACHE_ENTRIES
    stale_if_error_seconds: int = SKILLS_PROXY_STALE_IF_ERROR_SECONDS

    def __post_init__(self) -> None:
        if self.listen_host not in {"127.0.0.1", "0.0.0.0", "::1"}:
            raise ValueError("skills proxy listen host is invalid")
        if (
            isinstance(self.listen_port, bool)
            or not isinstance(self.listen_port, int)
            or not 1 <= self.listen_port <= 65_535
        ):
            raise ValueError("skills proxy listen port is invalid")
        if (
            isinstance(self.rate_limit_per_minute, bool)
            or not isinstance(self.rate_limit_per_minute, int)
            or not 1 <= self.rate_limit_per_minute <= 600
        ):
            raise ValueError("skills proxy rate limit is invalid")
        if (
            isinstance(self.max_cache_entries, bool)
            or not isinstance(self.max_cache_entries, int)
            or not 1 <= self.max_cache_entries <= 1_024
        ):
            raise ValueError("skills proxy cache bound is invalid")
        if (
            isinstance(self.stale_if_error_seconds, bool)
            or not isinstance(self.stale_if_error_seconds, int)
            or not 60 <= self.stale_if_error_seconds <= 86_400
        ):
            raise ValueError("skills proxy stale window is invalid")

    @classmethod
    def from_env(cls) -> SkillsCatalogProxySettings:
        """Read only bounded listener settings from the process environment."""
        return cls(
            listen_host=os.environ.get("GIGA_SKILLS_PROXY_HOST", "127.0.0.1"),
            listen_port=_env_integer("GIGA_SKILLS_PROXY_PORT", 8092),
            rate_limit_per_minute=_env_integer("GIGA_SKILLS_PROXY_RATE_LIMIT", 120),
            max_cache_entries=_env_integer(
                "GIGA_SKILLS_PROXY_CACHE_ENTRIES",
                SKILLS_PROXY_MAX_CACHE_ENTRIES,
            ),
            stale_if_error_seconds=_env_integer(
                "GIGA_SKILLS_PROXY_STALE_IF_ERROR_SECONDS",
                SKILLS_PROXY_STALE_IF_ERROR_SECONDS,
            ),
        )


@dataclass(frozen=True)
class SkillsProxyUpstreamResponse:
    """Bounded response returned by an injected upstream transport."""

    status_code: int
    final_url: str
    headers: Mapping[str, str]
    body: bytes
    redirected: bool = False


SkillsOIDCTokenProvider = Callable[[], Awaitable[str]]


class SkillsProxyUpstreamTransport(Protocol):
    """Injectable transport used by hermetic proxy tests."""

    async def __call__(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> SkillsProxyUpstreamResponse: ...


class _RateLimiter:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def admit(self, identity: str, now: float) -> bool:
        with self._lock:
            hits = self._hits[identity]
            cutoff = now - 60.0
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self._limit:
                return False
            hits.append(now)
            return True


@dataclass(frozen=True)
class _CacheEntry:
    payload: dict[str, Any]
    encoded: bytes
    stored_at: float
    max_age: int


class _LastGoodCache:
    def __init__(self, maximum: int) -> None:
        self._maximum = maximum
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = Lock()

    def get(self, key: str) -> _CacheEntry | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                self._entries.move_to_end(key)
            return entry

    def put(self, key: str, entry: _CacheEntry) -> None:
        with self._lock:
            self._entries[key] = entry
            self._entries.move_to_end(key)
            while len(self._entries) > self._maximum:
                self._entries.popitem(last=False)

    def count(self) -> int:
        with self._lock:
            return len(self._entries)


def create_skills_catalog_proxy_app(
    *,
    settings: SkillsCatalogProxySettings | None = None,
    token_provider: SkillsOIDCTokenProvider | None = None,
    upstream: SkillsProxyUpstreamTransport | None = None,
    monotonic: Callable[[], float] | None = None,
) -> FastAPI:
    """Create the independently deployable metadata-only proxy application."""
    config = settings or SkillsCatalogProxySettings.from_env()
    resolve_token = token_provider or _environment_oidc_token
    transport = upstream or fetch_skills_proxy_upstream
    limiter = _RateLimiter(config.rate_limit_per_minute)
    cache = _LastGoodCache(config.max_cache_entries)
    clock = monotonic or time.monotonic
    health_state: dict[str, str | None] = {
        "last_error_code": None,
        "last_success_path": None,
    }
    health_lock = Lock()
    application = FastAPI(
        title="Harness skills.sh metadata proxy",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @application.middleware("http")
    async def _rate_limit(request: Request, call_next):
        if request.url.path != "/healthz":
            identity = request.client.host if request.client is not None else "unknown"
            if not limiter.admit(identity, clock()):
                return _error_response(429, "proxy.rate_limited")
        return await call_next(request)

    @application.get("/healthz")
    async def _health() -> dict[str, Any]:
        with health_lock:
            last_error_code = health_state["last_error_code"]
            last_success_path = health_state["last_success_path"]
        oidc_configured = token_provider is not None or bool(
            os.environ.get("VERCEL_OIDC_TOKEN")
        )
        return {
            "status": "ready" if oidc_configured else "configuration_required",
            "upstream_origin": SKILLS_PROXY_UPSTREAM_ORIGIN,
            "read_only": True,
            "oidc_configured": oidc_configured,
            "cache_entries": cache.count(),
            "last_good_available": cache.count() > 0,
            "last_error_code": last_error_code,
            "last_success_path": last_success_path,
        }

    async def _proxy(
        url: str,
        *,
        sanitizer: Callable[[Any], dict[str, Any]],
        max_age: int,
    ) -> JSONResponse:
        try:
            token = await resolve_token()
            _validate_token(token)
            response = await transport(
                url=url,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                timeout_seconds=SKILLS_PROXY_TIMEOUT_SECONDS,
                max_response_bytes=SKILLS_PROXY_MAX_RESPONSE_BYTES,
            )
            payload = _validated_upstream_payload(response)
            sanitized = sanitizer(payload)
        except _ProxyFailure as exc:
            with health_lock:
                health_state["last_error_code"] = exc.code
            retained = cache.get(url)
            age = clock() - retained.stored_at if retained is not None else None
            if (
                retained is not None
                and age is not None
                and 0 <= age <= config.stale_if_error_seconds
            ):
                return _success_response(
                    retained.payload,
                    retained.encoded,
                    max_age=0,
                    cache_status="stale",
                    age_seconds=int(age),
                    source_error=exc.code,
                )
            return _error_response(exc.status_code, exc.code, headers=exc.headers)
        except Exception:
            with health_lock:
                health_state["last_error_code"] = "proxy.upstream_unavailable"
            retained = cache.get(url)
            age = clock() - retained.stored_at if retained is not None else None
            if (
                retained is not None
                and age is not None
                and 0 <= age <= config.stale_if_error_seconds
            ):
                return _success_response(
                    retained.payload,
                    retained.encoded,
                    max_age=0,
                    cache_status="stale",
                    age_seconds=int(age),
                    source_error="proxy.upstream_unavailable",
                )
            return _error_response(502, "proxy.upstream_unavailable")
        encoded = json.dumps(
            sanitized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        if len(encoded) > SKILLS_PROXY_MAX_RESPONSE_BYTES:
            return _error_response(502, "proxy.response_too_large")
        cache.put(
            url,
            _CacheEntry(
                payload=sanitized,
                encoded=encoded,
                stored_at=clock(),
                max_age=max_age,
            ),
        )
        with health_lock:
            health_state["last_error_code"] = None
            health_state["last_success_path"] = urllib_parse.urlsplit(url).path
        return _success_response(
            sanitized,
            encoded,
            max_age=max_age,
            cache_status="fresh",
            age_seconds=0,
        )

    @application.get("/api/v1/skills")
    async def _list_skills(
        view: str = "all-time",
        page: int = 0,
        per_page: int = 100,
    ) -> JSONResponse:
        if view not in {"all-time", "trending", "hot"}:
            return _error_response(400, "proxy.invalid_view")
        if page < 0 or not 1 <= per_page <= SKILLS_PROXY_MAX_PAGE_SIZE:
            return _error_response(400, "proxy.invalid_pagination")
        query = urllib_parse.urlencode(
            {"view": view, "page": page, "per_page": per_page}
        )
        return await _proxy(
            f"{SKILLS_PROXY_UPSTREAM_ORIGIN}/api/v1/skills?{query}",
            sanitizer=_sanitize_listing,
            max_age=60,
        )

    @application.get("/api/v1/skills/search")
    async def _search_skills(
        q: str,
        limit: int = 50,
        owner: str | None = None,
    ) -> JSONResponse:
        if not 2 <= len(q.strip()) <= SKILLS_PROXY_MAX_QUERY_LENGTH:
            return _error_response(400, "proxy.invalid_query")
        if not 1 <= limit <= SKILLS_PROXY_MAX_SEARCH_LIMIT:
            return _error_response(400, "proxy.invalid_limit")
        if owner is not None and _PATH_PART_RE.fullmatch(owner) is None:
            return _error_response(400, "proxy.invalid_owner")
        params: dict[str, str | int] = {"q": q.strip(), "limit": limit}
        if owner is not None:
            params["owner"] = owner
        query = urllib_parse.urlencode(params)
        return await _proxy(
            f"{SKILLS_PROXY_UPSTREAM_ORIGIN}/api/v1/skills/search?{query}",
            sanitizer=_sanitize_listing,
            max_age=60,
        )

    @application.get("/api/v1/skills/curated")
    async def _curated_skills() -> JSONResponse:
        return await _proxy(
            f"{SKILLS_PROXY_UPSTREAM_ORIGIN}/api/v1/skills/curated",
            sanitizer=_sanitize_curated,
            max_age=300,
        )

    @application.get("/api/v1/skills/audit/{owner}/{repository}/{skill}")
    async def _github_audit(
        owner: str,
        repository: str,
        skill: str,
    ) -> JSONResponse:
        if not all(
            _PATH_PART_RE.fullmatch(item) for item in (owner, repository, skill)
        ):
            return _error_response(400, "proxy.invalid_skill_id")
        path = "/".join(
            urllib_parse.quote(item, safe="") for item in (owner, repository, skill)
        )
        return await _proxy(
            f"{SKILLS_PROXY_UPSTREAM_ORIGIN}/api/v1/skills/audit/{path}",
            sanitizer=_sanitize_audit,
            max_age=300,
        )

    @application.get("/api/v1/skills/audit/{source}/{skill}")
    async def _well_known_audit(source: str, skill: str) -> JSONResponse:
        if not all(_PATH_PART_RE.fullmatch(item) for item in (source, skill)):
            return _error_response(400, "proxy.invalid_skill_id")
        path = "/".join(urllib_parse.quote(item, safe="") for item in (source, skill))
        return await _proxy(
            f"{SKILLS_PROXY_UPSTREAM_ORIGIN}/api/v1/skills/audit/{path}",
            sanitizer=_sanitize_audit,
            max_age=300,
        )

    @application.get("/api/v1/skills/{owner}/{repository}/{skill}")
    async def _github_detail(
        owner: str,
        repository: str,
        skill: str,
    ) -> JSONResponse:
        if not all(
            _PATH_PART_RE.fullmatch(item) for item in (owner, repository, skill)
        ):
            return _error_response(400, "proxy.invalid_skill_id")
        path = "/".join(
            urllib_parse.quote(item, safe="") for item in (owner, repository, skill)
        )
        return await _proxy(
            f"{SKILLS_PROXY_UPSTREAM_ORIGIN}/api/v1/skills/{path}",
            sanitizer=_sanitize_detail,
            max_age=300,
        )

    @application.get("/api/v1/skills/{source}/{skill}")
    async def _well_known_detail(source: str, skill: str) -> JSONResponse:
        if not all(_PATH_PART_RE.fullmatch(item) for item in (source, skill)):
            return _error_response(400, "proxy.invalid_skill_id")
        path = "/".join(urllib_parse.quote(item, safe="") for item in (source, skill))
        return await _proxy(
            f"{SKILLS_PROXY_UPSTREAM_ORIGIN}/api/v1/skills/{path}",
            sanitizer=_sanitize_detail,
            max_age=300,
        )

    return application


async def fetch_skills_proxy_upstream(
    *,
    url: str,
    headers: Mapping[str, str],
    timeout_seconds: float,
    max_response_bytes: int,
) -> SkillsProxyUpstreamResponse:
    """Fetch one fixed-origin upstream response without following redirects."""
    _validate_upstream_url(url)
    return await anyio.to_thread.run_sync(
        lambda: _read_upstream(
            url=url,
            headers=headers,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
        )
    )


def _read_upstream(
    *,
    url: str,
    headers: Mapping[str, str],
    timeout_seconds: float,
    max_response_bytes: int,
) -> SkillsProxyUpstreamResponse:
    request = urllib_request.Request(url, headers=dict(headers), method="GET")
    opener = urllib_request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            return SkillsProxyUpstreamResponse(
                status_code=response.status,
                final_url=response.geturl(),
                headers=dict(response.headers.items()),
                body=response.read(max_response_bytes + 1),
            )
    except urllib_error.HTTPError as exc:
        return SkillsProxyUpstreamResponse(
            status_code=exc.code,
            final_url=url,
            headers=dict(exc.headers.items()) if exc.headers is not None else {},
            body=exc.read(max_response_bytes + 1),
            redirected=300 <= exc.code < 400,
        )


class _NoRedirectHandler(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _ProxyFailure(RuntimeError):
    def __init__(
        self,
        status_code: int,
        code: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.headers = dict(headers or {})


def _validated_upstream_payload(response: SkillsProxyUpstreamResponse) -> Any:
    try:
        _validate_upstream_url(response.final_url)
    except ValueError as exc:
        raise _ProxyFailure(502, "proxy.redirect_rejected") from exc
    if response.redirected:
        raise _ProxyFailure(502, "proxy.redirect_rejected")
    if response.status_code in {401, 403}:
        raise _ProxyFailure(503, "proxy.upstream_auth_failed")
    if response.status_code == 429:
        retry_after = next(
            (
                value
                for key, value in response.headers.items()
                if key.casefold() == "retry-after" and value.isdigit()
            ),
            None,
        )
        raise _ProxyFailure(
            429,
            "proxy.upstream_rate_limited",
            headers={"Retry-After": retry_after} if retry_after is not None else None,
        )
    if response.status_code == 404:
        raise _ProxyFailure(404, "proxy.not_found")
    if not 200 <= response.status_code < 300:
        raise _ProxyFailure(502, "proxy.upstream_failed")
    if (
        not isinstance(response.body, bytes)
        or len(response.body) > SKILLS_PROXY_MAX_RESPONSE_BYTES
    ):
        raise _ProxyFailure(502, "proxy.response_too_large")
    try:
        return json.loads(
            response.body.decode("utf-8"), object_pairs_hook=_unique_object
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise _ProxyFailure(502, "proxy.invalid_payload") from exc


def _sanitize_listing(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise _ProxyFailure(502, "proxy.invalid_payload")
    if "pagination" in payload:
        if set(payload) != {"data", "pagination"}:
            raise _ProxyFailure(502, "proxy.schema_drift")
        pagination = payload["pagination"]
        if not isinstance(pagination, Mapping) or set(pagination) != {
            "page",
            "perPage",
            "total",
            "hasMore",
        }:
            raise _ProxyFailure(502, "proxy.schema_drift")
        return {
            "data": _sanitize_items(payload["data"]),
            "pagination": dict(pagination),
        }
    if set(payload) != {"data", "query", "searchType", "count", "durationMs"}:
        raise _ProxyFailure(502, "proxy.schema_drift")
    return {
        "data": _sanitize_items(payload["data"]),
        "query": payload["query"],
        "searchType": payload["searchType"],
        "count": payload["count"],
        "durationMs": payload["durationMs"],
    }


def _sanitize_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 10_000:
        raise _ProxyFailure(502, "proxy.invalid_payload")
    result = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) - _LIST_ITEM_FIELDS:
            raise _ProxyFailure(502, "proxy.schema_drift")
        result.append({key: item[key] for key in item if key in _LIST_ITEM_FIELDS})
    return result


def _sanitize_detail(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise _ProxyFailure(502, "proxy.invalid_payload")
    required = {"id", "source", "slug", "installs", "hash"}
    if not required <= set(payload) or set(payload) - (required | {"files"}):
        raise _ProxyFailure(502, "proxy.schema_drift")
    sanitized = {key: payload[key] for key in sorted(required)}
    if (
        not isinstance(sanitized["hash"], str)
        or re.fullmatch(r"[0-9a-f]{64}", sanitized["hash"]) is None
    ):
        raise _ProxyFailure(502, "proxy.invalid_payload")
    files = payload.get("files")
    if files is None:
        sanitized["files"] = None
        return sanitized
    if not isinstance(files, list) or len(files) > SKILLS_PROXY_MAX_FILE_PATHS:
        raise _ProxyFailure(502, "proxy.invalid_payload")
    sanitized["files"] = [_sanitize_file_path(item) for item in files]
    return sanitized


def _sanitize_file_path(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"path", "contents"}:
        raise _ProxyFailure(502, "proxy.schema_drift")
    path = value.get("path")
    if (
        not isinstance(path, str)
        or not 1 <= len(path) <= 512
        or path.startswith(("/", "\\"))
        or "\\" in path
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or any(ord(char) < 32 for char in path)
    ):
        raise _ProxyFailure(502, "proxy.invalid_payload")
    return {"path": path}


def _sanitize_curated(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != {
        "data",
        "totalOwners",
        "totalSkills",
        "generatedAt",
    }:
        raise _ProxyFailure(502, "proxy.schema_drift")
    owners = payload.get("data")
    if not isinstance(owners, list) or len(owners) > 1_000:
        raise _ProxyFailure(502, "proxy.invalid_payload")
    sanitized_owners = []
    allowed = {
        "owner",
        "totalInstalls",
        "featuredRepo",
        "featuredSkill",
        "skills",
    }
    for owner in owners:
        if not isinstance(owner, Mapping) or set(owner) != allowed:
            raise _ProxyFailure(502, "proxy.schema_drift")
        sanitized_owners.append(
            {
                "owner": owner["owner"],
                "totalInstalls": owner["totalInstalls"],
                "featuredRepo": owner["featuredRepo"],
                "featuredSkill": owner["featuredSkill"],
                "skills": _sanitize_items(owner["skills"]),
            }
        )
    return {
        "data": sanitized_owners,
        "totalOwners": payload["totalOwners"],
        "totalSkills": payload["totalSkills"],
        "generatedAt": payload["generatedAt"],
    }


def _sanitize_audit(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != {
        "id",
        "source",
        "slug",
        "audits",
    }:
        raise _ProxyFailure(502, "proxy.schema_drift")
    audits = payload.get("audits")
    if not isinstance(audits, list) or len(audits) > SKILLS_PROXY_MAX_AUDITS:
        raise _ProxyFailure(502, "proxy.invalid_payload")
    allowed = {
        "provider",
        "slug",
        "status",
        "summary",
        "auditedAt",
        "riskLevel",
        "categories",
    }
    sanitized_audits = []
    for audit in audits:
        if not isinstance(audit, Mapping) or set(audit) - allowed:
            raise _ProxyFailure(502, "proxy.schema_drift")
        if audit.get("status") not in {"pass", "warn", "fail"}:
            raise _ProxyFailure(502, "proxy.invalid_payload")
        sanitized_audits.append(
            {
                key: audit[key]
                for key in ("provider", "slug", "status", "auditedAt", "riskLevel")
                if key in audit
            }
        )
    return {
        "id": payload["id"],
        "source": payload["source"],
        "slug": payload["slug"],
        "audits": sanitized_audits,
    }


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


async def _environment_oidc_token() -> str:
    token = os.environ.get("VERCEL_OIDC_TOKEN")
    if token is None:
        raise _ProxyFailure(503, "proxy.oidc_unavailable")
    return token


def _validate_token(token: Any) -> None:
    if (
        not isinstance(token, str)
        or not 1 <= len(token) <= 8_192
        or any(ord(char) < 33 for char in token)
    ):
        raise _ProxyFailure(503, "proxy.oidc_unavailable")


def _validate_upstream_url(url: str) -> None:
    parsed = urllib_parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "skills.sh"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or not (
            parsed.path == "/api/v1/skills" or parsed.path.startswith("/api/v1/skills/")
        )
    ):
        raise ValueError("skills proxy upstream URL is invalid")


def _success_response(
    payload: dict[str, Any],
    encoded: bytes,
    *,
    max_age: int,
    cache_status: str,
    age_seconds: int,
    source_error: str | None = None,
) -> JSONResponse:
    headers = {
        "Cache-Control": f"public, max-age={max_age}",
        "ETag": '"' + hashlib.sha256(encoded).hexdigest() + '"',
        "X-Content-Type-Options": "nosniff",
        "X-Giga-Cache-Status": cache_status,
        "Age": str(age_seconds),
    }
    if source_error is not None:
        headers["X-Giga-Source-Error"] = source_error
        headers["Warning"] = '110 - "Response is stale"'
    return JSONResponse(content=payload, headers=headers)


def _error_response(
    status_code: int,
    code: str,
    *,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": code},
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            **dict(headers or {}),
        },
    )


def _env_integer(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def main() -> None:
    """Run the packaged proxy entry point."""
    import uvicorn

    settings = SkillsCatalogProxySettings.from_env()
    uvicorn.run(
        "gpt2giga_harness.skills_catalog_proxy:app",
        host=settings.listen_host,
        port=settings.listen_port,
        access_log=False,
    )


app = create_skills_catalog_proxy_app()


__all__ = [
    "SKILLS_PROXY_MAX_RESPONSE_BYTES",
    "SKILLS_PROXY_UPSTREAM_ORIGIN",
    "SkillsCatalogProxySettings",
    "SkillsProxyUpstreamResponse",
    "SkillsProxyUpstreamTransport",
    "app",
    "create_skills_catalog_proxy_app",
    "fetch_skills_proxy_upstream",
    "main",
]
