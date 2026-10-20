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

## 9. 隔离判题

`CODE_RUNNER_BACKEND=auto` 在生产环境选择 Docker 隔离执行；开发环境选择本地执行，本地模式只用于受信任代码。生产环境即使设置 `local` 也会禁用执行。Docker、镜像或资源不可用时返回错误，不回退到后端进程。其他面试功能可以继续使用。

在后端实际使用的 Docker 引擎上构建判题镜像（项目根目录执行）：

```bash
docker build -f backend/sandbox/Dockerfile -t deepask-code-runner:local backend
```

执行后端的系统账号需要可用的 Docker CLI，以及专用 rootless Docker 引擎的访问权限。执行主机应使用 cgroup v2，并为 rootless 引擎配置资源控制委派；启用前运行下述集成测试确认内存和进程限制实际生效。可以通过 `DOCKER_HOST` 指向已配置好的引擎；TLS 连接支持 `DOCKER_TLS_VERIFY` 和 `DOCKER_CERT_PATH`。后端与引擎使用同一个镜像标签，判题期间不自动拉取镜像。

默认 Compose 不把宿主机 Docker socket 挂进 Web 后端，也不默认安装 Docker CLI，因此直接使用默认 Compose 时算法执行会返回“隔离判题环境不可用”。启用公网判题前，需先为后端配置上述执行环境；勿为了快速启用而把宿主机 root Docker socket 挂入 Web 容器。建议使用专用执行主机或虚拟机上的 rootless 引擎，并限制后端到引擎的访问。

每次请求创建临时容器，使用非 root 用户、只读根目录、独立临时目录、断网、去除 capabilities 和禁止权限提升。单容器限制 512 MiB 内存、1 CPU、64 个进程，限制文件大小、文件描述符、CPU 时间和输出；后端每个进程最多同时处理两次隔离执行。超时后强制删除容器，正常结束也删除。生成测试用例和参考解也通过同一执行边界。环境不可用或繁忙时接口返回 503，不评分、不推进面试题目。

执行容器不挂载题库、数据库、上传文件或源码工作区，不继承 API Key、JWT Secret 或数据库连接。容器仍共享执行主机内核；对于公开接受恶意提交的服务，应在专用虚拟机上运行并保持引擎与内核更新。

构建镜像后可运行隔离回归（会真实启动临时容器）：

```bash
cd backend
RUN_SANDBOX_TESTS=1 python -m pytest tests/test_code_security.py -q
```

CI 的 `sandbox` 任务执行相同检查，验证四种语言、完整程序模式，以及文件、网络和环境变量隔离。不具备 Docker 的本地环境会跳过这些集成用例，其余回归仍执行。
