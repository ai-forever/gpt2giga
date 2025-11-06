ARG PYTHON_VERSION=3.10

FROM python:${PYTHON_VERSION}-slim AS builder

WORKDIR /app

RUN pip install poetry

COPY pyproject.toml README.md ./

COPY gpt2giga/ gpt2giga/


RUN poetry build

FROM python:${PYTHON_VERSION}-slim

WORKDIR /app

COPY --from=builder /app/dist/*.whl .

RUN pip install *.whl && rm *.whl

CMD ["gpt2giga"]