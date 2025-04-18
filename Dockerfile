FROM python:3.9-slim

WORKDIR /app

RUN pip install poetry

COPY . .

RUN poetry install

CMD ["poetry", "run", "gpt2giga"]
