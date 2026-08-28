#!/bin/bash
# 在腾讯云「免密登录」终端里执行（Ubuntu 22.04）
# 用法：
#   1. 先把 face-agent-deploy.tar.gz 上传到 /home/ubuntu/
#   2. bash server-setup.sh
set -euo pipefail

REMOTE_DIR="/home/ubuntu/face-agent"
TAR="/home/ubuntu/face-agent-deploy.tar.gz"

if [[ ! -f "$TAR" ]]; then
  echo "❌ 未找到 $TAR"
  echo "请先把打包文件上传到 /home/ubuntu/face-agent-deploy.tar.gz"
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo ">>> 安装 Docker ..."
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker ubuntu || true
fi

if ! docker compose version >/dev/null 2>&1; then
  echo ">>> 安装 Docker Compose 插件 ..."
  sudo apt-get update -qq
  sudo apt-get install -y docker-compose-plugin
fi

echo ">>> 解压项目 ..."
sudo rm -rf "$REMOTE_DIR"
mkdir -p "$REMOTE_DIR"
tar -xzf "$TAR" -C "$REMOTE_DIR"

cd "$REMOTE_DIR"

if [[ ! -f .env ]]; then
  echo ">>> 创建 .env（请按提示填写）"
  read -r -p "DEEPSEEK_API_KEY: " DEEPSEEK_KEY
  read -r -p "管理员用户名 ADMIN_USERNAMES [xyq]: " ADMIN_USER
  ADMIN_USER=${ADMIN_USER:-xyq}
  JWT_SECRET=$(openssl rand -base64 48 | tr -d '\n')
  PG_PASS=$(openssl rand -base64 24 | tr -d '\n')
  cat > .env <<EOF
DEEPSEEK_API_KEY=${DEEPSEEK_KEY}
DEEPSEEK_MODEL=deepseek-v4-flash
JWT_SECRET=${JWT_SECRET}
POSTGRES_PASSWORD=${PG_PASS}
APP_ENV=production
DEBUG=false
ADMIN_USERNAMES=${ADMIN_USER}
DEFAULT_PLATFORM_QUOTA=3
CORS_ORIGINS=
PUBLIC_ORIGIN=http://deeplyask.online
DATABASE_URL=postgresql+psycopg2://face_agent:${PG_PASS}@postgres:5432/face_agent
REDIS_URL=redis://redis:6379/0
NEXT_PUBLIC_API_BASE=
EOF
  echo "✅ .env 已生成"
else
  echo ">>> 使用已有 .env"
fi

echo ">>> 构建并启动（约 5～15 分钟）..."
sudo docker compose --profile bundled-db up -d --build

echo ">>> 等待健康检查 ..."
sleep 10
curl -sf http://127.0.0.1/api/health && echo "" || echo "健康检查未通过，请执行: sudo docker compose logs -f backend"

echo ""
echo "=========================================="
echo "部署完成！浏览器访问："
echo "  http://124.223.107.171"
echo "  http://deeplyask.online （需 DNS + 备案）"
echo "管理员用户名: 见 .env 中 ADMIN_USERNAMES"
echo "=========================================="
