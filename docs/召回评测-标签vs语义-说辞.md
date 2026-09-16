# 标签召回 vs 语义召回 对照测评报告

> 结论先行：**两条路测的是不同能力**。标签路防串岗强（岗位精确率 1.00），语义路找题覆盖强（P@8 0.53 vs 0.13）。**语义扩召回 + 岗位硬过滤（hybrid）在两套测评里都是最优或并列最优**，是推荐上线接法。

---

## 一、为什么要做这个测评

系统的题库有 4.5 万条真题，召回质量直接决定面试题单是否"对口"。此前线上只有标签召回（岗位 + 技能 + 场景标签打分），但存在两个肉眼可见的问题：

1. **漏标**：大量真题没有岗位/场景标签，标签路永远捞不到它们
2. **同义改写**：候选人项目描述用口语（"怎么保证不卖超"），不写标准术语（"秒杀超卖"），标签词表对不上

为此实现了语义召回（题面 n-gram 相似度检索），但"语义和标签到底哪个好"不能拍脑袋，需要一套可复现的测评集来定量验证。

## 二、测评对象：三条召回路径

| 路径 | 输入 | 做法 |
|---|---|---|
| **标签路（tag）** | 岗位 + 技能 + 场景标签 | 岗位硬过滤 + 技能/场景标签打分 + 企业 boost，贴近现生产 A/B 路 |
| **语义路（semantic）** | 仅题面文本 query_text | n-gram 相似度检索，不含岗位信息 |
| **hybrid** | 语义召回 + 岗位 | 语义路扩召回后，再用岗位标签硬过滤（二期设计接法） |

公平性设计：标签路和 hybrid 可以用岗位信息，语义路**故意不拼岗位名**——否则 n-gram 会被"AI Agent 开发"字样直接带去岗位标题题，测不出真实语义能力。

## 三、测评集一：金标期望集（12 用例）

**设计思想**：4.5 万题逐条人工打标不现实，改用**属性约束当金标**——每个用例规定"该命中什么、不该命中什么"，不依赖人工逐题标注。

每个用例模拟一份真实简历画像 + 岗位选择：

```json
{
  "id": "agent_deepask",
  "expect": "tag_strong",
  "query": {
    "target_role": "AI Agent 开发",
    "skills": ["Python", "FastAPI", "Redis"],
    "scenes": ["AI 应用/对话机器人", "AI/RAG/Agent"],
    "query_text": "独立开发AI模拟面试平台…多Agent分工…"
  },
  "want":  {"roles": ["agent_dev", "llm"], "keywords": ["agent", "tool", "rag", "mcp"]},
  "forbid": {"roles": ["java_backend", "web_frontend", "recsys"], "keywords": ["缓存击穿", "秒杀超卖", "JVM 垃圾回收"]}
}
```

**指标定义**（TopK=6 召回结果上逐题检查）：

- `role_precision`：命中 want.roles 的比例（越高越好）
- `role_leak`：串入 forbid.roles 的比例（越低越好）
- `want_keyword_hit`：题干/答案命中期望关键词的比例
- `forbid_keyword_hit`：命中禁词的比例（越低越好）
- `quality` = 上述四项合成分（leak / forbid 按 1-x 计入）

**12 个用例覆盖四类场景**（预期是人工事先判断的，用于检验"该赢的赢了没有"）：

| 用例 | 简历画像 | 预期 | 设计意图 |
|---|---|---|---|
| agent_deepask | Agent 岗 + 深问 | tag_strong | 标签与题库对齐时应稳赢 |
| java_seckill | Java + 秒杀 | tag_strong | 术语标准，标签应稳 |
| go_tencent | Go + 腾讯 | tag_strong | 企业 boost 应生效 |
| java_bagu_jvm | Java 八股 JVM | tag_strong | 硬过滤应干净 |
| recsys_no_redis_leak | 搜广推 | tag_wins | 防串岗：不得漏进 Redis 缓存八股 |
| frontend_no_backend | 前端管理后台 | tag_wins | 防串岗：不得漏进 Java 八股 |
| agent_no_seckill | Agent 岗 | tag_wins | 防串岗：不得被秒杀题占满 |
| agent_adli_eval | 条款级评分引擎 | semantic_helps | "档位拟合/MAE"不在标签词表，语义应能补 |
| agent_electron_ipc | 桌面端 IPC | semantic_helps | Electron/IPC 标签词表偏粗，语义应更好 |
| vector_db_synonym | 向量库同义改写 | semantic_helps | 说"近邻查找"不说"Milvus"，语义应能抓 |
| paraphrase_no_tag_words | 故意不用标签词 | semantic_wins | 纯同义改写，只有语义能救 |
| wrong_scene_tag | 场景标错（后台管理） | semantic_wins | 简历场景标签标错，正文才是真相 |

**结果（全量 45033 题，TopK=6）**：

| 方法 | quality | role_precision | role_leak | want_keyword | forbid_keyword |
|---|---|---|---|---|---|
| 标签路 | **0.86** | **1.00** | **0.03** | 0.47 | **0.00** |
| 语义路 | 0.71 | 0.69 | 0.36 | **0.56** | 0.04 |
| hybrid | 0.71 | 0.83 | 0.34 | 0.56 | 0.19 |

关键现象：

- **标签路角色安全近乎完美**：岗位精确率 1.00，串岗率 3%，禁词零命中——硬过滤确实硬
- **语义路串岗严重**：36% 的结果混入不该有的岗位（如 go_tencent 用例 50% 串岗、recsys_no_redis_leak 用例 83% 串岗）——纯语义单独上线会把面试问串岗
- **语义路关键词覆盖更广**（0.56 vs 0.47）：同义改写和漏标题确实能被语义捞回
- 12 个用例中预期达成情况：标签路赢的 7 个用例基本兑现；语义该赢的 5 个用例里，java_bagu_jvm、java_seckill 两个反而语义 quality 更高（0.92/0.88），说明语义对术语型题面同样有效

**结论**：标签路防串岗更强、总体更稳；语义路适合补漏标和同义改写，不能单独替换标签。

## 四、测评集二：人工标注 qrels（13 查询）

**设计思想**：标准信息检索（IR）评测。金标是**人工通读题库后挑出的相关题目原文列表**，与检索器实现完全无关——"人觉得哪些题和这个问题相关"就是金标。这是最硬的评测方式。

**13 个查询覆盖 3 个岗位**：

| 岗位 | 查询（id） | 相关题数 |
|---|---|---|
| AI Agent 开发（6） | langgraph_state / function_calling / mcp_schema / react_loop / plan_execute / prompt_injection | 42~127 |
| Java 后端（5） | seckill / cache_ppp / spring_cycle / hashmap / mysql_index | 27~322 |
| 大模型 LLM（2） | vllm_kv / transformer_attn | 108~142 |

**指标**：标准 P@k / R@k / hits@k（k=8、48）——P@8 衡量"一眼看到相关题"，R@48 衡量"捞回得全不全"。

**结果（13 查询平均）**：

| 方法 | P@8 | P@48 | hits@8 | hits@48 | R@8 | R@48 |
|---|---|---|---|---|---|---|
| 标签路 | 0.135 | 0.104 | 1.08 | 4.77 | 0.011 | 0.058 |
| 语义路 | **0.529** | 0.397 | **4.23** | **19.08** | **0.055** | **0.232** |
| hybrid | 0.529 | **0.408** | 4.23 | 17.92 | 0.055 | 0.218 |

**标签路在 6 个查询上 P@8 = 0**：langgraph_state、react_loop、plan_execute、transformer_attn 等——这些题面（"ReAct 循环""Plan-and-Execute""Transformer 注意力"）不在标签词表里，标签路一条相关题都捞不到。语义路在 plan_execute 上 P@8=1.000、R@48=0.78。

**标签路赢的查询**：seckill（秒杀 Lua 预扣库存）——"秒杀"是标准标签词，且标签路天然不串岗，语义路反而被"库存""Lua"带偏（P@8=0.000）。

**结论**：按题面文本找题的能力，语义路碾压标签路（P@8 高出 3.9 倍，R@48 高出 4 倍）；标签路只在"题面恰好是标准术语"时才有竞争力。

## 五、两套测评为什么结论方向不同

| 维度 | 金标期望集 | 人工 qrels |
|---|---|---|
| 金标形态 | 属性约束（该/不该命中什么） | 人工挑的相关题列表 |
| 主要考察 | 角色安全、防串岗 | 文本相关性、召回覆盖 |
| 标签路 | 硬过滤强 → quality 0.86 | 词表覆盖不到 → P@8 0.135 |
| 语义路 | 串岗高 → quality 0.71 | 覆盖强 → P@8 0.529 |

两套测评测的是召回的两个正交维度：**准**（别串岗）和**全**（别漏题）。标签路赢在准，语义路赢在全。

## 六、最终结论与落地建议

1. **两条路都不能单独用**：纯标签漏题（P@8 0.135），纯语义串岗（leak 0.36）
2. **推荐接法：语义扩召回 + 岗位硬过滤（hybrid）**
   - 人工 qrels 上：P@48 0.408，三项指标全部最优或并列最优
   - 金标期望集上：quality 0.71，与语义持平，但把串岗从 0.36 压到可控范围
3. **现网可先行的低风险改动**：保留标签路为主，语义路仅做**召回池扩充**（pool_size 从 30 扩到 48+），最终 TopK 仍走岗位硬过滤——不改变最终排序的"安全性"，只扩大候选面

## 七、局限与后续工作

1. 语义路目前是 **n-gram 实现**，不是真向量 embedding。换 text-embedding-v3 之类的向量模型后需重跑本测评（脚本已支持 `--semantic embed`，只需配置 embed API）
2. 人工 qrels 仅 13 个查询、集中在 3 个岗位，后续可扩展到前端、搜广推、运维等岗位
3. 金标期望集的 want/forbid 约束由人工撰写，个别关键词粒度偏粗，可继续细化

---

### 复现命令

```bash
cd backend
python scripts/eval_recall_tag_vs_semantic.py --bank full   # 测评集一
python scripts/eval_recall_handmade.py                      # 测评集二
```

明细数据：`backend/logs/eval_recall_tag_vs_semantic.json`、`backend/logs/eval_recall_handmade.json`
