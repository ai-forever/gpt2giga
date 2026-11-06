from types import SimpleNamespace
import ssl
import os
from unittest.mock import MagicMock

import pytest
import httpx2 as httpx
from functools import partial
from gigachat import GigaChat
from gigachat.settings import BASE_URL

from gpt2giga.providers.gigachat import client as client_module
from gpt2giga.providers.gigachat.client import (
    GigaChatClientConfigurationError,
    build_gigachat_client,
    create_gigachat_client,
)
from gpt2giga.models.config import GigaChatCLI
from gpt2giga.providers.gigachat.request_options import (
    GigaRequestOptions,
    gigachat_request_options,
)


@pytest.fixture(autouse=True)
def isolated_ca_environment(monkeypatch):
    """Keep default-CA tests independent of dotenv loaded by other tests."""
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)


async def test_configured_session_header_and_request_override(monkeypatch):
    monkeypatch.setenv("GIGACHAT_SESSION_ID", "configured-session")
    for key in ("CREDENTIALS", "USER", "PASSWORD"):
        monkeypatch.delenv(f"GIGACHAT_{key}", raising=False)
    settings = GigaChatCLI(
        base_url="https://gigachat.test/v1", model="test-model", access_token="test"
    )
    seen = []

    def handle(request):
        seen.append(request.headers.get("X-Session-ID"))
        return httpx.Response(
            200, json={"messages": [{"role": "assistant", "content": "ok"}]}
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), trust_env=False
    ) as http_client:
        monkeypatch.setattr(
            client_module, "GigaChat", partial(GigaChat, async_http_client=http_client)
        )
        async with build_gigachat_client(settings) as client:
            await client.achat.create("hello")
            options = GigaRequestOptions(
                headers={"x-session-id": "request-session"}, query=(), body={}
            )
            async with gigachat_request_options(client, options) as request_client:
                await request_client.achat.create("hello")
            await client.achat.create("hello")
        assert not http_client.is_closed
    assert seen == ["configured-session", "request-session", "configured-session"]


class FakeSettings:
    def __init__(self, values, *, fields_set=()):
        self.values = values
        self.model_fields_set = set(fields_set)
        self.exclude_none = None

    def model_dump(self, *, exclude_none=False):
        self.exclude_none = exclude_none
        if exclude_none:
            return {
                key: value for key, value in self.values.items() if value is not None
            }
        return dict(self.values)


def test_bundled_ca_is_loaded_for_verified_sdk_clients(monkeypatch):
    constructor = MagicMock()
    monkeypatch.setattr(client_module, "GigaChat", constructor)
    settings = FakeSettings({"verify_ssl_certs": True})
    build_gigachat_client(settings, request_auth={"access_token": "test"})
    context = constructor.call_args.kwargs["ssl_context"]
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    names = [str(cert["subject"]) for cert in context.get_ca_certs()]
    assert any("Russian Trusted Root CA" in name for name in names)
    assert len(names) > 1
    assert settings.values == {"verify_ssl_certs": True}


@pytest.mark.parametrize(
    "override",
    [
        {"verify_ssl_certs": False},
        {"ca_bundle_file": "/custom/ca.pem"},
        {"ssl_context": ssl.create_default_context()},
        {"use_bundled_ca": False},
    ],
)
def test_explicit_tls_configuration_takes_precedence(monkeypatch, override):
    constructor = MagicMock()
    monkeypatch.setattr(client_module, "GigaChat", constructor)
    values = {"verify_ssl_certs": True, "use_bundled_ca": True, **override}
    build_gigachat_client(FakeSettings(values))
    expected = {key: value for key, value in values.items() if key != "use_bundled_ca"}
    constructor.assert_called_once_with(**expected)


def test_bundled_ca_setting_from_environment(monkeypatch):
    monkeypatch.setenv("GIGACHAT_USE_BUNDLED_CA", "false")
    assert GigaChatCLI().use_bundled_ca is False


def test_create_gigachat_client_excludes_none_settings(monkeypatch):
    constructor = MagicMock()
    monkeypatch.setattr(client_module, "GigaChat", constructor)
    settings = FakeSettings(
        {
            "base_url": "https://api.example/v1",
            "credentials": "credential",
            "model": None,
        },
        fields_set={"base_url"},
    )

    create_gigachat_client(settings)

    assert settings.exclude_none is True
    constructor.assert_called_once_with(
        base_url="https://api.example/v1",
        credentials="credential",
    )
    assert settings.values["credentials"] == "credential"


def test_build_gigachat_client_replaces_base_auth_without_mutating_settings(
    monkeypatch,
):
    constructor = MagicMock()
    monkeypatch.setattr(client_module, "GigaChat", constructor)
    settings = FakeSettings(
        {
            "base_url": BASE_URL,
            "credentials": "base-credential",
            "scope": "BASE_SCOPE",
            "access_token": None,
        }
    )

    build_gigachat_client(settings, request_auth={"access_token": "request-token"})

    constructor.assert_called_once_with(
        base_url=BASE_URL,
        access_token="request-token",
        credentials="",
        scope="",
        user="",
        password="",
    )
    assert settings.values["credentials"] == "base-credential"


@pytest.mark.parametrize(
    "auth",
    [
        {"credentials": "credential", "scope": "GIGACHAT_API_PERS"},
        {"access_token": "access-token"},
    ],
)
def test_sdk_default_base_url_remains_valid_for_non_password_auth(monkeypatch, auth):
    constructor = MagicMock()
    monkeypatch.setattr(client_module, "GigaChat", constructor)
    settings = FakeSettings({"base_url": BASE_URL})

    build_gigachat_client(settings, request_auth=auth)

    constructor.assert_called_once()


def test_username_password_auth_requires_explicit_base_url(monkeypatch):
    constructor = MagicMock()
    monkeypatch.setattr(client_module, "GigaChat", constructor)
    settings = FakeSettings(
        {
            "base_url": BASE_URL,
            "user": "user",
            "password": "super-secret-value",
        },
        fields_set={"user", "password"},
    )

    with pytest.raises(GigaChatClientConfigurationError) as exc_info:
        create_gigachat_client(settings)

    assert "GIGACHAT_BASE_URL" in str(exc_info.value)
    assert "super-secret-value" not in str(exc_info.value)
    constructor.assert_not_called()


def test_username_password_auth_accepts_explicit_base_url(monkeypatch):
    constructor = MagicMock(return_value=SimpleNamespace())
    monkeypatch.setattr(client_module, "GigaChat", constructor)
    settings = FakeSettings(
        {
            "base_url": "https://password-auth.example/v1",
            "user": "user",
            "password": "password",
        },
        fields_set={"base_url", "user", "password"},
    )

    result = create_gigachat_client(settings)

    assert result is constructor.return_value
    constructor.assert_called_once_with(
        base_url="https://password-auth.example/v1",
        user="user",
        password="password",
    )


@pytest.mark.parametrize("trust_env", [False, True])
def test_bundled_ca_obeys_environment_trust(monkeypatch, trust_env):
    monkeypatch.setenv("SSL_CERT_FILE", "/missing/synthetic-ca.pem")
    monkeypatch.setenv("SSL_CERT_DIR", "/missing/synthetic-ca-dir")
    settings = FakeSettings({"verify_ssl_certs": True, "trust_env": trust_env})
    if trust_env:
        with pytest.raises(FileNotFoundError):
            build_gigachat_client(settings)
    else:
        build_gigachat_client(settings)


@pytest.mark.parametrize("field", ["key_file", "key_file_password"])
def test_bundled_ca_rejects_orphan_key(field):
    with pytest.raises(GigaChatClientConfigurationError, match="require cert_file"):
        build_gigachat_client(FakeSettings({"verify_ssl_certs": True, field: "secret"}))


@pytest.mark.parametrize("mode", ["token", "credentials", "user"])
async def test_request_auth_isolated_from_all_server_environment(monkeypatch, mode):
    import base64
    from gpt2giga.providers.gigachat.auth import create_gigachat_client_for_request

    for field in ("ACCESS_TOKEN", "CREDENTIALS", "SCOPE", "USER", "PASSWORD"):
        monkeypatch.setenv(f"GIGACHAT_{field}", f"server-{field}")
    settings = GigaChatCLI(
        base_url="https://api.test/v1",
        model="test-model",
        auth_url="https://auth.test/oauth",
        verify_ssl_certs=False,
        trust_env=False,
        max_retries=0,
    )
    original = settings.model_dump()
    seen = []
    tenant = "A"

    def handle(request):
        seen.append(request)
        if request.url.path.endswith("/oauth"):
            assert (
                request.headers["authorization"]
                == "Basic " + base64.b64encode(f"{tenant}:secret".encode()).decode()
            )
            assert request.content == b"scope=TENANT_SCOPE"
            return httpx.Response(
                200,
                json={"access_token": f"tenant-{tenant}", "expires_at": 9999999999999},
            )
        if request.url.path.endswith("/token"):
            assert (
                request.headers["authorization"]
                == "Basic " + base64.b64encode(f"{tenant}:secret".encode()).decode()
            )
            assert request.content == b""
            return httpx.Response(
                200, json={"tok": f"tenant-{tenant}", "exp": 9999999999}
            )
        assert "server-" not in request.headers.get("authorization", "")
        return httpx.Response(
            200, json={"messages": [{"role": "assistant", "content": "ok"}]}
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), trust_env=False
    ) as http_client:
        monkeypatch.setattr(
            client_module,
            "GigaChat",
            partial(
                GigaChat,
                async_http_client=http_client,
                auth_async_http_client=http_client,
            ),
        )
        for tenant in ("A", "B"):
            token = {
                "token": f"giga-auth-tenant-{tenant}",
                "credentials": "giga-cred-"
                + base64.b64encode(f"{tenant}:secret".encode()).decode()
                + ":TENANT_SCOPE",
                "user": f"giga-user-{tenant}:secret",
            }[mode]
            async with create_gigachat_client_for_request(settings, token) as client:
                await client.achat.create("hello")
            assert not http_client.is_closed
    assert len(seen) == (2 if mode == "token" else 4)
    assert settings.model_dump() == original
    for field in ("ACCESS_TOKEN", "CREDENTIALS", "SCOPE", "USER", "PASSWORD"):
        assert os.environ[f"GIGACHAT_{field}"] == f"server-{field}"


async def test_tenant_token_401_never_uses_server_oauth(monkeypatch):
    from gigachat.exceptions import AuthenticationError

    for field in ("ACCESS_TOKEN", "CREDENTIALS", "SCOPE", "USER", "PASSWORD"):
        monkeypatch.setenv(f"GIGACHAT_{field}", f"server-{field}")
    seen = []

    def handle(request):
        seen.append(request)
        assert request.url.path == "/v2/chat/completions"
        assert request.headers["authorization"] == "Bearer tenant-token"
        return httpx.Response(401, json={"message": "expired"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), trust_env=False
    ) as http_client:
        monkeypatch.setattr(
            client_module,
            "GigaChat",
            partial(
                GigaChat,
                async_http_client=http_client,
                auth_async_http_client=http_client,
            ),
        )
        async with build_gigachat_client(
            GigaChatCLI(
                base_url="https://api.test/v1",
                model="test-model",
                max_retries=0,
                trust_env=False,
            ),
            request_auth={"access_token": "tenant-token"},
        ) as client:
            with pytest.raises(AuthenticationError):
                await client.achat.create("hello")
    assert len(seen) == 1


@pytest.fixture
def local_tls_certificate(tmp_path):
    """Generate a temporary CA and encrypted localhost identity, never credentials."""
    import shutil
    import subprocess

    if not shutil.which("openssl"):
        pytest.skip("openssl is required for the local TLS handshake test")

    def openssl(*args):
        subprocess.run(
            ["openssl", *args], cwd=tmp_path, check=True, capture_output=True
        )

    (tmp_path / "ca.cnf").write_text(
        "[req]\ndistinguished_name=dn\nx509_extensions=ca\n[dn]\n"
        "[ca]\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\n"
        "subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid:always\n"
    )
    openssl(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        "ca.key",
        "-out",
        "ca.pem",
        "-days",
        "1",
        "-subj",
        "/CN=Temporary test CA",
        "-config",
        "ca.cnf",
    )
    openssl(
        "req",
        "-newkey",
        "rsa:2048",
        "-passout",
        "pass:synthetic-password",
        "-keyout",
        "client.key",
        "-out",
        "client.csr",
        "-subj",
        "/CN=localhost",
    )
    (tmp_path / "extensions.cnf").write_text(
        "subjectAltName=IP:127.0.0.1\nextendedKeyUsage=serverAuth,clientAuth\n"
        "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
        "subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n"
    )
    openssl(
        "x509",
        "-req",
        "-in",
        "client.csr",
        "-CA",
        "ca.pem",
        "-CAkey",
        "ca.key",
        "-CAcreateserial",
        "-out",
        "client.pem",
        "-days",
        "1",
        "-extfile",
        "extensions.cnf",
    )
    return tmp_path


@pytest.mark.parametrize("backend", ["httpx2", "aiohttp"])
async def test_factory_mtls_api_only_with_real_local_transport(
    monkeypatch, local_tls_certificate, backend
):
    import socket
    from aiohttp import web

    certs = local_tls_certificate
    for field in ("ACCESS_TOKEN", "CREDENTIALS", "SCOPE", "USER", "PASSWORD"):
        monkeypatch.delenv(f"GIGACHAT_{field}", raising=False)
    monkeypatch.setenv("GIGACHAT_ASYNC_BACKEND", backend)
    monkeypatch.setenv("GIGACHAT_CERT_FILE", str(certs / "client.pem"))
    monkeypatch.setenv("GIGACHAT_KEY_FILE", str(certs / "client.key"))
    monkeypatch.setenv("GIGACHAT_KEY_FILE_PASSWORD", "synthetic-password")
    monkeypatch.setenv("SSL_CERT_FILE", str(certs / "ca.pem"))
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    observed = []

    async def handle(request):
        observed.append(
            (request.path, bool(request.transport.get_extra_info("peercert")))
        )
        if request.path == "/oauth":
            return web.json_response(
                {"access_token": "tenant-token", "expires_at": 9999999999999}
            )
        return web.json_response({"messages": [{"role": "assistant", "content": "ok"}]})

    app = web.Application()
    app.router.add_post("/oauth", handle)
    app.router.add_post("/v2/chat/completions", handle)
    server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server_context.load_cert_chain(
        certs / "client.pem", certs / "client.key", "synthetic-password"
    )
    server_context.load_verify_locations(cafile=certs / "ca.pem")
    server_context.verify_mode = ssl.CERT_OPTIONAL
    runner = web.AppRunner(app)
    await runner.setup()
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 0))
        sock.listen(16)
        port = sock.getsockname()[1]
        await web.SockSite(runner, sock, ssl_context=server_context).start()
        settings = GigaChatCLI(
            base_url=f"https://127.0.0.1:{port}/v1",
            auth_url=f"https://127.0.0.1:{port}/oauth",
            model="test-model",
            credentials="dGVuYW50OnNlY3JldA==",
            verify_ssl_certs=True,
            timeout=10,
            max_retries=0,
        )
        assert settings.async_backend == backend
        async with build_gigachat_client(settings) as client:
            result = await client.achat.create("hello")
            assert result.messages[0].content[0].text == "ok"
        assert observed == [("/oauth", False), ("/v2/chat/completions", True)]
    finally:
        await runner.cleanup()
        sock.close()


def test_backend_cli_and_default(monkeypatch):
    from gpt2giga.models.config import ProxyConfig

    monkeypatch.delenv("GIGACHAT_ASYNC_BACKEND", raising=False)
    assert GigaChatCLI().async_backend == "httpx2"
    config = ProxyConfig(_cli_parse_args=["--gigachat.async-backend", "aiohttp"])
    assert config.gigachat_settings.async_backend == "aiohttp"
    assert isinstance(config.gigachat_settings.timeout, (int, float))


@pytest.mark.parametrize("trust_env", [False, True])
async def test_invalid_explicit_ca_is_not_ignored(trust_env):
    async with build_gigachat_client(
        GigaChatCLI(
            base_url="https://api.test/v1",
            model="test-model",
            access_token="test",
            trust_env=trust_env,
            ca_bundle_file="/missing/explicit-test-ca.pem",
        )
    ) as client:
        with pytest.raises(FileNotFoundError):
            await client.achat.create("hello")


def test_factory_preserves_explicit_oauth_context(monkeypatch, local_tls_certificate):
    certs = local_tls_certificate
    context = ssl.create_default_context()
    original = context.cert_store_stats()
    constructor = MagicMock()
    monkeypatch.setattr(client_module, "GigaChat", constructor)
    build_gigachat_client(
        FakeSettings(
            {
                "verify_ssl_certs": True,
                "trust_env": False,
                "cert_file": str(certs / "client.pem"),
                "key_file": str(certs / "client.key"),
                "key_file_password": "synthetic-password",
                "auth_ssl_context": context,
            }
        )
    )
    kwargs = constructor.call_args.kwargs
    assert kwargs["auth_ssl_context"] is context
    assert kwargs["ssl_context"] is not context
    assert all(
        kwargs[field] == "" for field in ("cert_file", "key_file", "key_file_password")
    )
    assert context.cert_store_stats() == original
