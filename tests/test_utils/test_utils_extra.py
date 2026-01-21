from types import SimpleNamespace
from gpt2giga.utils import pass_token_to_gigachat, convert_tool_to_giga_functions
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


def test_pass_token_giga_auth():
    giga = SimpleNamespace(
        _settings=SimpleNamespace(
            user=None, password=None, credentials=None, access_token=None
        )
    )
    token = "giga-auth-sometoken"
    res = pass_token_to_gigachat(giga, token)
    assert res._settings.access_token == "sometoken"


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
