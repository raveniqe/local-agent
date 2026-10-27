FROM python:3.13-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:0.12.22 /uv /uvx /bin/

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./

RUN uv sync --locked --no-dev --no-install-project

COPY README.md ./
COPY src ./src
COPY config ./config

RUN uv sync --locked --no-dev

CMD ["uvicorn", "local_agent.api:app", "--host", "0.0.0.0", "--port", "8000"]
