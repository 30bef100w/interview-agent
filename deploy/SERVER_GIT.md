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

## 注意

- 题库大文件（`questions_dedup.jsonl`）不进公开仓库，服务器上若已有备份，clone 后需从 bak 目录拷回 `backend/data/knowledge_base/`。
- PostgreSQL 数据在 Docker volume 里，`git pull` 不会丢用户数据。
