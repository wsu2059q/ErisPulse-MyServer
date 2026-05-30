# ===========================================================================
# ErisPulse-MyServer Docker Image
# https://github.com/wsu2059q/ErisPulse-MyServer
#
# Usage:
#   docker build -t ghcr.io/wsu2059q/erispulse-myserver:latest .
#
# Environment variables (runtime):
#   ERISPULSE_DASHBOARD_TOKEN   - Dashboard 登录令牌
#
# ===========================================================================
FROM erispulse/erispulse:latest

LABEL org.opencontainers.image.title="ErisPulse-MyServer" \
      org.opencontainers.image.description="ErisPulse 服务器管理模块" \
      org.opencontainers.image.url="https://github.com/wsu2059q/ErisPulse-MyServer" \
      org.opencontainers.image.source="https://github.com/wsu2059q/ErisPulse-MyServer"

COPY pyproject.toml README.md ./
COPY MyServer/ ./MyServer/

RUN uv pip install --system -e .

RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*
