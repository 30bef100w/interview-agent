# Interview Agent

模拟技术面试系统：上传简历、选定岗位和企业，按真实一面的节奏推进——自我介绍、项目拷打、八股、手撕算法、HR、反问，最后出量化报告。

**核心立场：LLM 只负责说话，出什么题、何时追问、何时切下一题，全部由引擎决定。**

作者：[@30bef100w](https://github.com/30bef100w)  
仓库：https://github.com/30bef100w/interview-agent

![面试会话](frontend/public/chat-preview.png)

## 它能干什么

1. **读简历开面**  
   上传 PDF 简历，抽出技术栈和项目画像；开练时选目标岗位（Java 后端 / AI Agent / 前端…）和目标企业（腾讯 / 字节 / 阿里…）。岗位定方向，简历当素材。

2. **全流程或专项**  
   - 全流程混合面：项目 + 八股 + 算法 + HR，题量按轮次和简历动态配  
   - 专项：只练项目拷打、只练八股、只练算法、只练 HR

3. **像一面一样往下追**  
   开场先规划整场题单，再按状态机执行。项目题会结合简历现编拷打链；八股优先从题库抽（有企业原题就亮「原题」）；答完可以追问，空话会被打回重出。

4. **手撕算法 + 对拍判题**  
   在线编辑器支持函数模式和手撕模式。对错由本地跑示例 / 随机对拍决定，模型不判题，只点评。

5. **语音也能答**  
   会话里可以语音输入，转写后再交给面试官。

6. **练完能看见差在哪**  
   逐题打分、能力雷达图、参考答；报告可导出 Word / PDF。成长档案汇总多场短板，下一场可以针对性开练。

![能力报告](frontend/public/report-preview.png)

## 和「套一层 ChatGPT」差在哪

| 常见做法 | 这里怎么做 |
|---|---|
| 模型自己决定问什么 | 开场一次规划题单，执行期按游标推进，模型不能改剧本 |
| 同一句话换个说法再问一遍 | 跨场去重：挡同一问法，不永封技术词（LangChain 换角度仍可出） |
| 八股让模型现编 | 有题库时从库里抽，面试官只在候选池里选和润色口头问法 |
| 项目题泛泛而谈 | 按岗位路 + 场景路召回，再按简历项目生成拷打链 |
| 算法题靠模型说对错 | 本地执行参考解对拍，超时 / WA / AC 是跑出来的 |

流程示意（本地打开 [`chain-flow.html`](chain-flow.html) 更清楚）：

```text
创建会话：开场官 → 多路召回 + 拷打链 → 规划题单 → 八股注入 → 去重补齐
     │
     ▼
执行中：自我介绍 → 出题 → 作答 → 追问∥评分 → 下一题 → 反问 → 终评
```

更细的设计写在 [`docs/设计文档-后端与Agent.md`](docs/设计文档-后端与Agent.md)。

## 使用流程

1. 注册登录  
2. 上传简历，必要时跑一次 AI 简历分析  
3. 开始面试：选全流程或专项、岗位、企业、轮次  
4. 文字或语音作答  
5. 看报告，导出或去成长档案看趋势  

![工作台](frontend/public/dashboard-preview.png)

## 技术栈

- 前端：Next.js  
- 后端：FastAPI  
- 引擎：规划 / 检索 / 拷打链 / 去重 / 状态机都在 `backend/app/services/`  
- 模型：DeepSeek 等 OpenAI 兼容接口，Key 在设置页或 `.env` 里配，不进仓库

## 本地运行

需要 Python 3.11+、Node.js。

**后端**

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY，生产环境请改 JWT_SECRET
uvicorn app.main:app --reload --port 8001
```

Linux / macOS 把 `copy` 换成 `cp`。

**前端**

```bash
cd frontend
npm install
npm run dev
```

打开 http://localhost:3000 。前端默认请求 `http://localhost:8001`，可用 `NEXT_PUBLIC_API_BASE` 改掉。

## 开源范围

本仓库开的是**产品架构和代码**。自行整理的面经、结构化题库、算法题配置不随仓库分发。

克隆下来，注册登录、上传简历、把会话流程跑通就可以；要把八股抽准、算法能判题，需要自己补数据：

| 要补的 | 放哪 | 不补会怎样 |
|---|---|---|
| LLM Key | `backend/.env` 的 `DEEPSEEK_API_KEY` | 后端能起，对话会失败 |
| 面试题库 | `backend/data/knowledge_base/questions_dedup.jsonl` | 八股召回为空，更多靠模型现编 |
| 讲解原文（可选） | `backend/data/knowledge_base/knowledge.jsonl` | 评分讲解素材变少 |
| 算法题配置（可选） | `backend/data/coding_problems.json` | 算法环节没有可判的题 |
| 语音模型（可选） | `backend/data/whisper-tiny/` | 语音输入不可用 |

仓库里自带的是标签表，不是题：`job_roles.json`、`companies.json`、`project_scenes.json`、`llm_providers.json`（价目，不含 Key）。

题库字段说明：[`backend/data/knowledge_base/README.md`](backend/data/knowledge_base/README.md)。  
**不要把 `.env` 提交进 git。**

## 目录

```
backend/app/       FastAPI、面试引擎、检索、评分、判题
backend/data/      岗位/企业/场景标签；题库与算法题需自备
frontend/         Next.js 界面
docs/             设计文档与迭代记录
chain-flow.html   面试链路示意
```

## License

MIT
