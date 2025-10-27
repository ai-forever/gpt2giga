ARG PYTHON_VERSION=3.10

FROM python:${PYTHON_VERSION}-slim

WORKDIR /app

RUN pip install poetry

COPY pyproject.toml README.md ./

RUN poetry install --no-root

COPY gpt2giga/ gpt2giga/

RUN poetry install

CMD ["poetry", "run", "gpt2giga"]