from types import SimpleNamespace
from unittest.mock import MagicMock

from gpt2giga.common.gigachat_auth import (
    create_gigachat_client_for_request,
    pass_token_to_gigachat,
)
from gpt2giga.common.tools import convert_tool_to_giga_functions
from gigachat.models import Function


def test_pass_token_giga_user():
    giga = SimpleNamespace(
        _settings=SimpleNamespace(
            user=None, password=None, credentials=None, access_token=None
        )
    )
    token = "giga-user-u1:p1"
    res = pass_token_to_gigachat(giga, token)
    assert res._settings.user == "u1"
    assert res._settings.password == "p1"
    assert res._settings.credentials is None


def test_pass_token_giga_cred():
    giga = SimpleNamespace(
        _settings=SimpleNamespace(
            user=None,
            password=None,
            credentials=None,
            access_token=None,
            scope="GIGACHAT_API_PERS",
        )
    )
    token = "giga-cred-abcd-efgh"
    res = pass_token_to_gigachat(giga, token)
    assert res._settings.credentials == "abcd-efgh"
    assert res._settings.scope == "GIGACHAT_API_PERS"


def test_pass_token_giga_cred_with_scope():
    giga = SimpleNamespace(
        _settings=SimpleNamespace(
            user=None, password=None, credentials=None, access_token=None
        )
    )
    token = "giga-cred-abcd-efgh:MY_SCOPE"
    res = pass_token_to_gigachat(giga, token)
    assert res._settings.credentials == "abcd-efgh"
    assert res._settings.scope == "MY_SCOPE"


def test_pass_token_giga_auth_ignored():
    """pass_token_to_gigachat does not handle giga-auth-; use create_gigachat_client_for_request (issue #74)."""
    giga = SimpleNamespace(
        _settings=SimpleNamespace(
            user=None, password=None, credentials=None, access_token=None
        )
    )
    token = "giga-auth-sometoken"
    res = pass_token_to_gigachat(giga, token)
    assert res._settings.access_token is None


def test_create_gigachat_client_for_request_giga_auth_uses_constructor():
    """giga-auth- must create GigaChat with access_token in constructor (issue #74)."""
    settings = SimpleNamespace(
        model_dump=lambda: {
            "base_url": "https://api.example/v1",
            "verify_ssl_certs": True,
            "credentials": "secret",
            "access_token": None,
        }
    )
    with MagicMock() as mock_giga_class:
        from gpt2giga.common import gigachat_auth

        orig = gigachat_auth.GigaChat
        gigachat_auth.GigaChat = mock_giga_class
        try:
            create_gigachat_client_for_request(settings, "giga-auth-my-access-token")
        finally:
            gigachat_auth.GigaChat = orig
    mock_giga_class.assert_called_once()
    call_kw = mock_giga_class.call_args.kwargs
    assert call_kw.get("access_token") == "my-access-token"
    assert "credentials" not in call_kw


def test_pass_token_unknown_prefix():
    # Should do nothing (or clear creds?) code says: sets creds/user/pass to None then checks prefix
    giga = SimpleNamespace(
        _settings=SimpleNamespace(
            user="old", password="old", credentials="old", access_token="old"
        )
    )
    token = "just-token"
    res = pass_token_to_gigachat(giga, token)
    assert res._settings.user is None
    assert res._settings.password is None
    assert res._settings.credentials is None
    assert (
        res._settings.access_token == "old"
    )  # access_token is NOT cleared in the code, only set if prefix matches


def test_convert_tool_to_giga_functions_tools_format():
    data = {
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "func1",
                    "description": "desc1",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
    }
    funcs = convert_tool_to_giga_functions(data)
    assert len(funcs) == 1
    assert isinstance(funcs[0], Function)
    assert funcs[0].name == "func1"


def test_convert_tool_to_giga_functions_functions_format():
    # Deprecated format support
    data = {
        "functions": [
            {
                "name": "func2",
                "description": "desc2",
                "parameters": {"type": "object", "properties": {}},
            }
        ]
    }
    funcs = convert_tool_to_giga_functions(data)
    assert len(funcs) == 1
    assert funcs[0].name == "func2"
