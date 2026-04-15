ARG PYTHON_VERSION=3.10

FROM python:${PYTHON_VERSION}-slim AS builder

WORKDIR /app

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md ./
COPY gigachat-0.2.2a1-py3-none-any.whl ./
COPY gpt2giga/ gpt2giga/
COPY packages/gpt2giga-ui/ packages/gpt2giga-ui/
RUN uv build --wheel \
    && cd packages/gpt2giga-ui \
    && uv build --out-dir /app/dist


FROM python:${PYTHON_VERSION}-slim AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

COPY --from=builder /app/dist/*.whl /tmp/
COPY gigachat-0.2.2a1-py3-none-any.whl /tmp/gigachat-0.2.2a1-py3-none-any.whl

RUN python -m venv "$VIRTUAL_ENV" \
    && pip install --no-cache-dir /tmp/gigachat-0.2.2a1-py3-none-any.whl \
    && pip install --no-cache-dir /tmp/gpt2giga-*.whl \
    && pip install --no-cache-dir /tmp/gpt2giga_ui-*.whl \
    && rm -rf /tmp/*.whl \
    && find "$VIRTUAL_ENV" -type d -name "__pycache__" -prune -exec rm -rf '{}' + \
    && find "$VIRTUAL_ENV" -type f -name "*.pyc" -delete \
    && find "$VIRTUAL_ENV" -type d \( -name "tests" -o -name "test" \) -prune -exec rm -rf '{}' + \
    && pip uninstall -y pip setuptools wheel

CMD ["gpt2giga"]
