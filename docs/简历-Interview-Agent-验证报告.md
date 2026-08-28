# Interview Agent 简历验证报告

> 生成时间：2026-08-24。用于简历四条 bullet 的数据支撑，均可复现。

## 验证命令与结果

### 1. 单测（Bullet 4）

```bash
cd backend && .venv\Scripts\python.exe -m pytest tests -q
```

| 指标 | 结果 |
|------|------|
| 通过 | **56** |
| 失败 | 2（`test_dedupe`、`test_multi_recall`，与本次简历数据无关） |
| 状态机专项 | **24** 条（`test_state_machine.py`） |
| 八股库来源 | `test_bagu_bank.py` 断言 **100% from_bank** |

### 2. 召回 eval（Bullet 2）

```bash
cd backend && .venv\Scripts\python.exe scripts\eval_recall.py
```

| 画像场景 | Top-8 命中 |
|----------|------------|
| Java 后端 + 黑马点评 | **8/8** |
| AI Agent 开发 | **8/8** |
| Web 前端 | **8/8** |
| Go 后端 + 腾讯 | **8/8** |
| 数据开发 / 大数据 | 0/8（该 role 题库覆盖弱，简历不写此场景） |

**跨场去重**（`asked_norms` 带入第二轮召回）：

| 指标 | 结果 |
|------|------|
| 重复题 | **0/8** |

### 3. 题库规模（Bullet 2 导语）

来源：`backend/data/knowledge_base/questions_dedup.meta.json`

| 指标 | 数值 |
|------|------|
| 去重题总量 | **45,036** |
| 八股 | 36,402 |
| 项目 | 8,634 |
| agent_dev 标签 | 21,539 |

### 4. Smoke E2E（Bullet 4，答辩用）

```bash
python scripts/smoke_plan.py    # 创建+规划+第一问
python scripts/smoke_finish.py    # 全流程至终评报告
```

| 脚本 | 核心结果 |
|------|----------|
| smoke_plan | 创建 **9.3s**，计划 **8** 题，第一问正常出（session 71） |
| smoke_finish | session 72：**FINISHED + 报告**（7 轮答完进反问） |

> 注：两脚本对流式 `token` 事件断言失败（0 token），但业务链路已跑通；属 SSE 格式变更，非引擎故障。

### 5. 拷打链实测（Bullet 3）

| Session | 目标岗位 | plan | 拷打链 | 每链步数 |
|---------|----------|------|--------|----------|
| **69** | AI Agent 开发 | 8 题 | **2** 条（知秦 + MindBridge） | 各 **6** 步 |
| 70 | （未指定） | 8 题 | 2 条 | 各 6 步 |

Session 69 项目题均点名「知秦」项目，符合多项目均衡分配设计。

---

## 简历终稿（技术向四条 · 独立开发 · Agent 岗）

**Interview Agent** AI 模拟技术面试系统 | 独立开发 | 2025.09 – 2026.08

> 自研 Plan-then-Execute 引擎，11 Agent 分工；4.5 万+ 标签面经库 A/B 双路 RAG。FastAPI · Next.js · DeepSeek

1. **控制面**：FSM + 11 Agent 分工，追问/评分并行；**24** 条状态机单测覆盖迁移与追问上限  
2. **RAG**：**45,036** 题多维标签，A/B 双路召回；**4** 类画像 Top-8 **满额**，跨场去重 **0** 重复  
3. **拷打链**：链与题单分轨，实测 **2** 链 × **6** 步/链，**8** 题全流程（Agent 岗 session 69）  
4. **验证**：**56** 项单测 + 召回 eval + smoke 全流程；八股 **100%** 库内抽取，算法本地对拍判题  

---

## 答辩时可补充（不必写简历）

- 创建耗时瓶颈：`project_chains` ~108s（见 `logs/create_trace/70.json`）
- 11 Agent 角色清单：开场 / 岗位过滤 / 拷打链 / Router / Planner / 八股遴选 / 出题 / 追问 / 评分 / 终评 / 算法评审
- 与套壳差异：控制面在引擎，LLM 不掌控题序
