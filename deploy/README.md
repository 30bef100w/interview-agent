# 生产部署（Docker Compose）

一键启动：**Nginx（80） + 前端 + 后端 + PostgreSQL**。

## 1. 准备环境

- 安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/)（Windows / macOS）或 Docker Engine（Linux）
- 准备 `DEEPSEEK_API_KEY`

## 2. 配置

```bash
cp deploy/env.example .env
```

编辑 `.env`，至少修改：

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | LLM 接口 Key |
| `JWT_SECRET` | 随机长字符串，勿用默认值 |
| `POSTGRES_PASSWORD` | 数据库密码 |
| `ADMIN_USERNAMES` | 管理员用户名（逗号分隔） |

若使用**本机已有 PostgreSQL**，注释 compose 里的 `postgres` 服务，并把 `DATABASE_URL` 改为：

```env
DATABASE_URL=postgresql+psycopg2://user:pass@host.docker.internal:5432/face_agent
```

（Linux 上把 `host.docker.internal` 换成宿主机 IP 或 `172.17.0.1`）

## 3. 启动

**内置 PostgreSQL（默认）：**

```bash
docker compose --profile bundled-db up -d --build
```

**使用本机已有 PostgreSQL：**

1. 在 `.env` 中设置 `DATABASE_URL=postgresql+psycopg2://user:pass@host.docker.internal:5432/face_agent`
2. 不要加 `bundled-db` profile：

```bash
docker compose up -d --build
```

浏览器访问：**http://服务器IP**（或 `HTTP_PORT` 指定的端口）。

健康检查：`curl http://localhost/api/health`

## 4. 架构说明

```text
浏览器 → Nginx:80
           ├─ /      → frontend:3000
           ├─ /api/* → backend:8001
           └─ /ws/*  → backend:8001（WebSocket）
```

前端 `NEXT_PUBLIC_API_BASE` 留空时走同源 `/api`，无需额外配 CORS。

## 5. 本地开发（仍用 SQLite）

不受影响，继续：

```bash
# 后端
cd backend && uvicorn app.main:app --reload --port 8001

# 前端
cd frontend && npm run dev
```

本地 `.env` 保持 `APP_ENV=development`，`DATABASE_URL=sqlite:///./data/face_agent.db` 即可。

## 6. 常用命令

```bash
docker compose logs -f backend
docker compose down
docker compose down -v   # 同时删除数据库卷（慎用）
```

## 7. HTTPS

当前 Nginx 仅 HTTP。上线 HTTPS 可在前面加 Caddy / 云厂商负载均衡，或使用 certbot 扩展 `deploy/nginx.conf`。

## 8. 运维与排障

可观测性（trace / guard / 飞书告警）与引擎兜底机制见：[`docs/开发与运维-可观测性与兜底.md`](../docs/开发与运维-可观测性与兜底.md)。
