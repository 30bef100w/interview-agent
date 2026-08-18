# Face Agent

模拟技术面试：**LLM 只负责说话，流程由引擎控制**（规划 → 出题 → 追问 → 评分 → 终评）。

作者：[@30bef100w](https://github.com/30bef100w)

本仓库开源的是**架构和代码**。面经题库、算法题配置等核心数据不随仓库分发。

## 仓库里有什么

- `backend/app/`：FastAPI、面试状态机、多路召回、拷打链、评分
- `frontend/`：Next.js 界面
- `docs/`：设计说明
- `backend/data/job_roles.json` / `companies.json` / `project_scenes.json`：岗位、企业、场景的标签表（给检索用的词表，不是题）
- `backend/data/llm_providers.json`：模型价目（不含 Key）

## 仓库里没有什么

这些已写入 `.gitignore`，克隆后需要自己准备：

| 缺什么 | 放哪 | 不做会怎样 |
|---|---|---|
| LLM Key | `backend/.env` 的 `DEEPSEEK_API_KEY` | 后端能起，对话会失败 |
| 面试题库 | `backend/data/knowledge_base/questions_dedup.jsonl` | 服务能起，八股召回为空 |
| 讲解原文（可选） | `backend/data/knowledge_base/knowledge.jsonl` | 评分讲解素材变少 |
| 算法题配置（可选） | `backend/data/coding_problems.json` | 算法环节没有可判题的题目 |
| 语音模型（可选） | `backend/data/whisper-tiny/` | 语音输入不可用 |

题库字段说明见 [`backend/data/knowledge_base/README.md`](backend/data/knowledge_base/README.md)。

算法题 JSON 的结构：每道题一个 slug，包含 `method`、`examples`、`reference`（参考解）、`generator`（随机用例）、`performance`。可参考 `backend/scripts/` 里的判题与选题代码自行维护一份。

## 能跑起来最少要做什么

### 1. 后端

需要 Python 3.11+。

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY
uvicorn app.main:app --reload --port 8001
```

Linux / macOS 把 `copy` 换成 `cp`。

`.env` 至少填：

```
DEEPSEEK_API_KEY=你的密钥
JWT_SECRET=自己换一个
```

也可用设置页里的兼容 OpenAI 接口（智谱 / 通义等），见 `llm_providers.json`。**不要提交 `.env`。**

### 2. 前端

```bash
cd frontend
npm install
npm run dev
```

浏览器打开 http://localhost:3000 。前端默认请求 `http://localhost:8001`，可用环境变量 `NEXT_PUBLIC_API_BASE` 改掉。

### 3. 想把面试问完整

1. 把去重后的题库存成 `backend/data/knowledge_base/questions_dedup.jsonl`
2. （可选）放 `knowledge.jsonl`
3. （可选）放 `coding_problems.json` 后算法环节才有对拍判题
4. 重启后端

没有题库时：注册登录、上传简历、走完会话流程仍可以；只是八股不能从库里抽，项目追问会更依赖简历 + 模型现编。

## 目录

```
backend/app/                 引擎与 API
backend/data/                标签表；题库 jsonl / 算法题需自备
backend/tests/               单测（完整召回测试依赖本地题库）
frontend/                   Next.js
docs/                       设计与迭代笔记
chain-flow.html             流程示意
```

## License

MIT
