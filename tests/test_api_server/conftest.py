import os

import pytest


_LOCAL_DOTENV_KEYS = (
    "GPT2GIGA_GIGACHAT_API_MODE",
    "GPT2GIGA_STRUCTURED_OUTPUT_MODE",
)


@pytest.fixture(autouse=True)
def isolate_local_dotenv(monkeypatch, tmp_path):
    """Keep api-server tests independent from the repository-local .env."""
    monkeypatch.chdir(tmp_path)
    for key in _LOCAL_DOTENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield
    for key in _LOCAL_DOTENV_KEYS:
        os.environ.pop(key, None)
