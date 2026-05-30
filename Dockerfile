FROM python:3.13-slim AS production

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY MyServer/ ./MyServer/

RUN uv pip install --system -e .

RUN mkdir -p /app/config

VOLUME ["/app/config"]
EXPOSE 8000

CMD ["epsdk", "run", "main.py"]
