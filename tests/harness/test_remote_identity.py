from __future__ import annotations

import base64
from hashlib import sha256
import json
import time
from urllib.parse import parse_qs, urlsplit

from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
import jwt

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.ui.app import create_app
from gpt2giga_harness.ui.remote_identity import (
    RemoteActor,
    RemoteIdentityStore,
    RemoteOIDCClient,
    RemoteOIDCSettings,
)


class HermeticIssuer:
    def __init__(self) -> None:
        self.issuer = "https://issuer.example"
        self.client_id = "gigaloom"
        self.subject = "operator-sub"
        self.nonce = ""
        self.sid = "issuer-session-1"
        self.verifier = ""
        self.challenge = ""
        self.jwks_fetches = 0
        self._kid = "signing-key"
        self._private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

    def rotate_key(self) -> None:
        self._private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

    def fetch(self, method, url, headers, data):
        if url.endswith("/.well-known/openid-configuration"):
            return {
                "issuer": self.issuer,
                "authorization_endpoint": f"{self.issuer}/authorize",
                "token_endpoint": f"{self.issuer}/token",
                "jwks_uri": f"{self.issuer}/jwks",
                "end_session_endpoint": f"{self.issuer}/logout",
                "id_token_signing_alg_values_supported": ["RS256"],
                "response_types_supported": ["code"],
                "code_challenge_methods_supported": ["S256"],
            }
        if url.endswith("/jwks"):
            self.jwks_fetches += 1
            public = jwt.algorithms.RSAAlgorithm.to_jwk(
                self._private_key.public_key(),
                as_dict=True,
            )
            return {"keys": [{**public, "kid": self._kid, "use": "sig"}]}
        if url.endswith("/token"):
            assert method == "POST"
            assert headers["Authorization"].startswith("Basic ")
            values = parse_qs((data or b"").decode(), strict_parsing=True)
            self.verifier = values["code_verifier"][0]
            actual_challenge = (
                base64.urlsafe_b64encode(sha256(self.verifier.encode()).digest())
                .rstrip(b"=")
                .decode()
            )
            assert actual_challenge == self.challenge
            assert values["redirect_uri"] == [
                "https://harness.example/auth/oidc/callback"
            ]
            return {"id_token": self.id_token()}
        raise AssertionError(f"unexpected hermetic issuer request: {method} {url}")

    def id_token(self) -> str:
        now = int(time.time())
        return jwt.encode(
            {
                "iss": self.issuer,
                "sub": self.subject,
                "aud": self.client_id,
                "azp": self.client_id,
                "iat": now,
                "auth_time": now,
                "exp": now + 300,
                "nonce": self.nonce,
                "sid": self.sid,
            },
            self._private_key,
            algorithm="RS256",
            headers={"kid": self._kid},
        )

    def logout_token(self, *, jti: str = "logout-1") -> str:
        now = int(time.time())
        return jwt.encode(
            {
                "iss": self.issuer,
                "aud": self.client_id,
                "iat": now,
                "exp": now + 300,
                "jti": jti,
                "sid": self.sid,
                "events": {"http://schemas.openid.net/event/backchannel-logout": {}},
            },
            self._private_key,
            algorithm="RS256",
            headers={"kid": self._kid},
        )


def _config(tmp_path, **overrides) -> HarnessConfig:
    values = {
        "data_dir": str(tmp_path),
        "ui_host": "0.0.0.0",
        "ui_oidc_issuer": "https://issuer.example",
        "ui_oidc_client_id": "gigaloom",
        "ui_oidc_client_secret": "client-secret",
        "ui_oidc_public_origin": "https://harness.example",
        "ui_oidc_role_map": (
            ("operator-sub", "operator"),
            ("viewer-sub", "viewer"),
        ),
        "ui_remote_absolute_ttl_seconds": 3600,
        "ui_remote_idle_ttl_seconds": 600,
    }
    values.update(overrides)
    return HarnessConfig(**values)


def _app(tmp_path):
    issuer = HermeticIssuer()
    config = _config(tmp_path)
    oidc = RemoteOIDCClient(
        RemoteOIDCSettings.from_config(config),
        fetch_json=issuer.fetch,
    )
    app = create_app(
        config,
        registry=create_default_registry(include_entry_points=False),
        remote_oidc_client=oidc,
    )
    return app, issuer


def _client(app, *, address: str) -> TestClient:
    return TestClient(
        app,
        base_url="https://harness.example",
        client=(address, 50000),
    )


def _login(client: TestClient, issuer: HermeticIssuer, *, path="/cockpit-v2/work"):
    shell = client.get(path, follow_redirects=False)
    assert shell.status_code == 303
    assert shell.headers["location"].startswith("/auth/oidc/login?")

    login = client.get(shell.headers["location"], follow_redirects=False)
    assert login.status_code == 303
    authorization = urlsplit(login.headers["location"])
    query = parse_qs(authorization.query)
    assert authorization.scheme == "https"
    assert authorization.netloc == "issuer.example"
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == ["https://harness.example/auth/oidc/callback"]
    transaction_cookie = login.headers["set-cookie"]
    assert "gpt2giga_oidc_transaction=" in transaction_cookie
    assert "Path=/auth/oidc/callback" in transaction_cookie
    assert "Secure" in transaction_cookie
    assert "HttpOnly" in transaction_cookie
    assert "SameSite=lax" in transaction_cookie
    issuer.nonce = query["nonce"][0]
    issuer.challenge = query["code_challenge"][0]

    callback = client.get(
        "/auth/oidc/callback",
        params={"code": "one-use-code", "state": query["state"][0]},
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == path
    cookie = callback.headers["set-cookie"]
    assert "gpt2giga_harness_session=" in cookie
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    return query


def test_remote_oidc_login_enforces_pkce_nonce_roles_and_audit_identity(tmp_path):
    app, issuer = _app(tmp_path)
    client = _client(app, address="203.0.113.10")

    query = _login(client, issuer)
    status = client.get("/auth/status")
    defaults = client.get("/api/defaults")

    assert status.status_code == 200
    assert status.json()["authenticated"] is True
    assert status.json()["local"] is False
    assert status.json()["role"] == "operator"
    assert status.json()["actor_id"].startswith("oidc_")
    assert status.json()["session_id"].startswith("uis_")
    assert status.json()["authentication_time"]
    assert defaults.status_code == 200
    assert issuer.verifier
    assert query["code_challenge"][0] == issuer.challenge

    state_path = tmp_path / "ui_access" / "remote_state.json"
    state_text = state_path.read_text()
    assert client.cookies["gpt2giga_harness_session"] not in state_text
    assert "client-secret" not in state_text
    assert issuer.id_token() not in state_text
    assert json.loads(state_text)["transactions"] == []

    replay = client.get(
        "/auth/oidc/callback",
        params={"code": "replayed-code", "state": query["state"][0]},
        follow_redirects=False,
    )
    assert replay.status_code == 401


def test_remote_viewer_revocation_and_backchannel_logout_fail_closed(tmp_path):
    app, issuer = _app(tmp_path)
    operator = _client(app, address="203.0.113.11")
    _login(operator, issuer)

    issuer.subject = "viewer-sub"
    issuer.sid = "issuer-session-viewer"
    viewer = _client(app, address="203.0.113.12")
    _login(viewer, issuer)
    viewer_status = viewer.get("/auth/status").json()

    denied = viewer.post(
        "/api/sessions",
        headers={
            "Origin": "https://harness.example",
            "X-GigaLoom-CSRF": "1",
        },
        json={},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "Operator role required"
    assert viewer.get("/api/defaults").status_code == 200

    logout = viewer.post(
        "/auth/logout",
        headers={
            "Origin": "https://harness.example",
            "X-GigaLoom-CSRF": "1",
        },
    )
    assert logout.status_code == 200
    assert viewer.get("/api/defaults").status_code == 401
    _login(viewer, issuer)
    viewer_status = viewer.get("/auth/status").json()

    revoked = operator.post(
        "/auth/remote/revoke-actor",
        headers={
            "Origin": "https://harness.example",
            "X-GigaLoom-CSRF": "1",
        },
        json={"actor_id": viewer_status["actor_id"]},
    )
    assert revoked.json() == {"revoked": 1}
    assert viewer.get("/api/defaults").status_code == 401

    issuer.subject = "operator-sub"
    issuer.sid = "issuer-session-1"
    logout_token = issuer.logout_token()
    logout = operator.post(
        "/auth/oidc/backchannel-logout",
        content=f"logout_token={logout_token}",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert logout.status_code == 204
    assert operator.get("/api/defaults").status_code == 401
    replay = operator.post(
        "/auth/oidc/backchannel-logout",
        content=f"logout_token={logout_token}",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert replay.status_code == 400


def test_remote_oidc_refreshes_jwks_after_signing_key_rotation(tmp_path):
    app, issuer = _app(tmp_path)
    first = _client(app, address="203.0.113.13")
    _login(first, issuer)
    assert issuer.jwks_fetches == 1

    issuer.rotate_key()
    second = _client(app, address="203.0.113.14")
    _login(second, issuer)

    assert issuer.jwks_fetches == 2
    assert second.get("/api/defaults").status_code == 200


def test_remote_session_idle_expiry_and_role_change_revoke_access(tmp_path):
    now = [1_000.0]
    settings = RemoteOIDCSettings.from_config(
        _config(
            tmp_path,
            ui_remote_absolute_ttl_seconds=600,
            ui_remote_idle_ttl_seconds=60,
        )
    )
    store = RemoteIdentityStore(tmp_path, settings, clock=lambda: now[0])
    actor = RemoteActor(
        actor_id="oidc_" + "a" * 64,
        issuer=settings.issuer,
        subject="operator-sub",
        role="operator",
        issuer_session_id="issuer-session",
        authentication_time=now[0],
    )
    session = store.issue_session(actor)

    assert store.authenticate(session.token) is not None
    now[0] += 61
    assert store.authenticate(session.token) is None

    replacement = store.issue_session(actor)
    assert isinstance(settings.roles, dict)
    settings.roles["operator-sub"] = "viewer"
    assert store.authenticate(replacement.token) is None


def test_remote_proxy_headers_require_one_explicit_trusted_peer(tmp_path):
    trusted_config = _config(tmp_path, ui_trusted_proxies=("10.0.0.2",))
    trusted_oidc = RemoteOIDCClient(
        RemoteOIDCSettings.from_config(trusted_config),
        fetch_json=HermeticIssuer().fetch,
    )
    trusted_app = create_app(
        trusted_config,
        registry=create_default_registry(include_entry_points=False),
        remote_oidc_client=trusted_oidc,
    )
    headers = {
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Host": "harness.example",
    }
    trusted = TestClient(
        trusted_app,
        base_url="http://internal:8091",
        client=("10.0.0.2", 50000),
    )
    untrusted = TestClient(
        trusted_app,
        base_url="http://internal:8091",
        client=("10.0.0.3", 50000),
    )

    assert trusted.get("/healthz", headers=headers).status_code == 200
    assert untrusted.get("/healthz", headers=headers).status_code == 400
    assert (
        trusted.get(
            "/healthz",
            headers={**headers, "X-Forwarded-Host": "harness.example, attacker"},
        ).status_code
        == 400
    )
