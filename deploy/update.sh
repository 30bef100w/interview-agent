#!/usr/bin/env bash
# 服务器一键更新（git pull + 重建容器）
# 用法: ./deploy/update.sh
set -euo pipefail
cd "$(dirname "$0")/.."
echo "==> pull latest"
git pull --ff-only origin main
echo "==> rebuild & restart"
docker compose up -d --build --wait --wait-timeout 180
echo "==> health"
curl --fail --silent --show-error --retry 10 --retry-all-errors --retry-delay 3 \
  --connect-timeout 3 --max-time 5 http://localhost/api/ready
echo ""
docker compose ps
