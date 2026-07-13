import pytest

from gpt2giga.common.exceptions import exceptions_handler


class DummyError(Exception):
    pass


@exceptions_handler
async def dummy_func_error():
    raise DummyError("test error")


async def test_exceptions_handler_success():
    @exceptions_handler
    async def ok():
        return "ok"

    assert await ok() == "ok"


async def test_exceptions_handler_redacts_unhandled_exception_details():
    @exceptions_handler
    async def boom():
        raise DummyError("secret=/srv/private/config.toml")

    response = await boom()

    assert response.status_code == 500
    assert response.body == (
        b'{"error":{"message":"Internal server error","type":"server_error",'
        b'"param":null,"code":null}}'
    )
    assert b"secret" not in response.body
    assert b"/srv/private/config.toml" not in response.body


async def test_exceptions_handler_converts_gigachat_response_error(monkeypatch):
    import gigachat

    class FakeResponseError(gigachat.exceptions.ResponseError):
        pass

    err = FakeResponseError("http://example.com", 400, '{"error":"bad"}', None)

    @exceptions_handler
    async def boom():
        raise err

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as ex:
        await boom()
    assert ex.value.status_code == 400
    assert ex.value.detail["url"].startswith("http://example.com")
