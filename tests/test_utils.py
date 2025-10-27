import pytest
from gpt2giga.utils import exceptions_handler


class DummyError(Exception):
    pass


def dummy_func_good():
    return 42


@exceptions_handler
def dummy_func_error():
    raise DummyError("test error")


@pytest.mark.asyncio
async def test_exceptions_handler_success():
    @exceptions_handler
    async def ok():
        return "ok"

    assert await ok() == "ok"
