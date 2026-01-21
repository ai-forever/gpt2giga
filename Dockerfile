ARG PYTHON_VERSION=3.10

FROM python:${PYTHON_VERSION}-slim AS builder

WORKDIR /app

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md ./
COPY gpt2giga/ gpt2giga/

RUN uv build --wheel


FROM python:${PYTHON_VERSION}-slim AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

COPY --from=builder /app/dist/*.whl /tmp/

RUN python -m venv "$VIRTUAL_ENV" \
    && pip install --no-cache-dir /tmp/*.whl \
    && rm -rf /tmp/*.whl \
    && find "$VIRTUAL_ENV" -type d -name "__pycache__" -prune -exec rm -rf '{}' + \
    && find "$VIRTUAL_ENV" -type f -name "*.pyc" -delete \
    && find "$VIRTUAL_ENV" -type d \( -name "tests" -o -name "test" \) -prune -exec rm -rf '{}' + \
    && pip uninstall -y pip setuptools wheel

CMD ["gpt2giga"]