# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN addgroup --system agora \
    && adduser --system --ingroup agora --home /home/agora agora

COPY pyproject.toml uv.lock README.md alembic.ini ./
COPY app ./app
COPY alembic ./alembic

RUN python -m pip install uv==0.10.12 \
    && uv sync --frozen --no-dev --no-editable \
    && chown -R agora:agora /app /home/agora

USER agora

EXPOSE 8000

CMD ["uvicorn", "app.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
