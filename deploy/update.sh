#!/usr/bin/env bash
# 服务器一键更新（git pull + 重建容器）
# 用法: ./deploy/update.sh
set -euo pipefail
cd "$(dirname "$0")/.."
echo "==> pull latest"
git pull origin main
echo "==> rebuild & restart"
docker compose up -d --build
echo "==> health"
curl -sf http://localhost/api/health
echo ""
docker compose ps
