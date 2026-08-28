# 服务器 Git 化与日常更新

## 首次（已在服务器执行过一次）

```bash
# 备份旧目录与 .env
mv /home/ubuntu/face-agent /home/ubuntu/face-agent.bak.YYYYMMDD
git clone https://github.com/30bef100w/interview-agent.git /home/ubuntu/face-agent
cp /home/ubuntu/face-agent.bak.*/.env /home/ubuntu/face-agent/.env
cd /home/ubuntu/face-agent
docker compose up -d --build
```

`.env` **不要**提交到 GitHub，只在服务器本地保留。

## 日常更新

```bash
cd /home/ubuntu/face-agent
./deploy/update.sh
```

或手动：

```bash
git pull origin main
docker compose up -d --build
```

## 飞书告警（可选）

`.env` 配置 `FEISHU_WEBHOOK_URL` 后，应用内自动告警：流量过载、平台 Key 余额/鉴权失败、未捕获 500。

**宕机探测**需额外加 cron（服务挂了应用内告警发不出去）：

```bash
crontab -e
# 每 2 分钟探测一次（在 backend 容器内跑，复用已装依赖）
*/2 * * * * cd /home/ubuntu/face-agent && docker compose exec -T backend python scripts/health_watchdog.py >> logs/health_watchdog.log 2>&1
```

可调参数：`ALERT_COOLDOWN_SECONDS`（默认 600）、`ALERT_RPM_THRESHOLD`（默认 180，0=关闭流量告警）。

## 注意

- 题库大文件（`questions_dedup.jsonl`）不进公开仓库，服务器上若已有备份，clone 后需从 bak 目录拷回 `backend/data/knowledge_base/`。
- PostgreSQL 数据在 Docker volume 里，`git pull` 不会丢用户数据。
