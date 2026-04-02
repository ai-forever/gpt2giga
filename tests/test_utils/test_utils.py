import pytest

from gpt2giga.common.exceptions import exceptions_handler


class DummyError(Exception):
    pass


@exceptions_handler
async def dummy_func_error():
    raise DummyError("test error")


@pytest.mark.asyncio
async def test_exceptions_handler_success():
    @exceptions_handler
    async def ok():
        return "ok"

    assert await ok() == "ok"


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_exceptions_handler_sanitizes_surrogates_in_error_message():
    @exceptions_handler
    async def boom():
        raise DummyError("broken \udcd0 text")

    response = await boom()

    assert response.status_code == 500
    assert response.body == (
        b'{"error":{"message":"broken \\\\udcd0 text","type":"server_error","param":null,"code":null}}'
    )
