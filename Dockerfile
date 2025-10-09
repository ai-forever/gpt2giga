ARG PYTHON_VERSION=3.10

FROM python:${PYTHON_VERSION}-slim

WORKDIR /app

RUN pip install poetry

COPY . .

RUN poetry install

CMD ["poetry", "run", "gpt2giga"]
