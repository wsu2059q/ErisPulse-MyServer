#!/usr/bin/env bash
# ErisPulse-MyServer 一键部署：curl -fsSL https://raw.githubusercontent.com/wsu2059q/ErisPulse-MyServer/main/deploy.sh | bash
set -euo pipefail

PORT="${MYSERVER_PORT:-8000}"
DIR="${MYSERVER_DIR:-$HOME/myserver}"
TOKEN="$(head -c 32 /dev/urandom | md5sum | cut -c1-24)"

echo "==> 部署目录：$DIR"
mkdir -p "$DIR/config"

if docker ps -a --format '{{.Names}}' | grep -q '^erispulse-myserver$'; then
  echo "==> 已存在容器 erispulse-myserver，先移除"
  docker rm -f erispulse-myserver >/dev/null
fi

echo "==> 拉取并启动（面板令牌：$TOKEN）"
docker run -d \
  --name erispulse-myserver \
  -p "$PORT:8000" \
  -v "$DIR/config:/app/config" \
  -e TZ="${TZ:-Asia/Shanghai}" \
  -e ERISPULSE_DASHBOARD_TOKEN="$TOKEN" \
  --restart unless-stopped \
  ghcr.io/wsu2059q/erispulse-myserver

sleep 3
if docker ps --format '{{.Names}}' | grep -q '^erispulse-myserver$'; then
  echo
  echo "✅ 部署完成"
  echo "   控制台  http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo '<你的IP>'):$PORT/Dashboard"
  echo "   公开页  http://<你的IP>:$PORT/MyServer/public（在设置里开启 public_page 后生效）"
  echo "   令牌    $TOKEN"
  echo
  echo "下一步：控制台 → 服务器机房 → ＋添加机器（SSH 密码或私钥）。"
  echo "装了 QvQChat 的话，直接在聊天里说「看看 web-1 的状态」就行。"
else
  echo "❌ 容器未起来，查看日志：docker logs erispulse-myserver"
  exit 1
fi
