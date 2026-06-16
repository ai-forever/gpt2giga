import os

import pytest


_LOCAL_DOTENV_KEYS = (
    "GIGACHAT_BASE_URL",
    "GIGACHAT_CREDENTIALS",
    "GIGACHAT_MODEL",
    "GIGACHAT_PASSWORD",
    "GIGACHAT_SCOPE",
    "GIGACHAT_USER",
    "GPT2GIGA_GIGACHAT_API_MODE",
    "GPT2GIGA_MODEL_MAX_CONNECTIONS",
    "GPT2GIGA_MODEL_MAX_CONNECTIONS_ACQUIRE_TIMEOUT",
    "GPT2GIGA_MODEL_MAX_CONNECTIONS_DEFAULT",
    "GPT2GIGA_STRUCTURED_OUTPUT_MODE",
)


@pytest.fixture(autouse=True)
def isolate_local_dotenv(monkeypatch, tmp_path):
    """Keep CLI tests from reading or leaking the workspace .env values."""
    monkeypatch.chdir(tmp_path)
    for key in _LOCAL_DOTENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield
    for key in _LOCAL_DOTENV_KEYS:
        os.environ.pop(key, None)
