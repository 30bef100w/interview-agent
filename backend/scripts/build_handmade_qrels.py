"""从候选题干里按题意筛金标（先读列表，再剔除跑题），写出 handmade_qrels.json。

候选来自题库 question 字段的主题扫描，不是检索器 TopK。评价时只用这里的题干列表。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAND = ROOT / "logs" / "handmade_candidates"
OUT = ROOT / "data" / "eval" / "handmade_qrels.json"


def _titles(name: str) -> list[str]:
    path = CAND / f"{name}.txt"
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if not t:
            continue
        # "   12  题干"
        parts = t.split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            t = parts[1]
        rows.append(t)
    return rows


def _has(t: str, *needles: str) -> bool:
    low = t.lower()
    return any(n.lower() in low or n in t for n in needles)


def langgraph(titles: list[str]) -> list[str]:
    keep = []
    vs_only = ("autogen", "crewai", "dify", "n8n", "openai agents", "hermes", "openclaw", "llamaindex", "pi-mono")
    mech = (
        "state", "reducer", "循环", "死循环", "human-in-the-loop", "hitl",
        "人在环", "人机", "node", "edge", "checkpoint", "递归", "条件边",
        "条件分支", "fan-out", "fan-in", "thread_id", "retry", "断点",
        "stategraph", "状态",
    )
    for t in titles:
        low = t.lower()
        if any(x in low for x in vs_only) and not any(x in low for x in ("state", "reducer", "循环", "human", "node", "edge", "checkpoint")):
            continue
        if any(x in low for x in mech):
            keep.append(t)
    return keep


def function_calling(titles: list[str]) -> list[str]:
    keep = []
    for t in titles:
        if _has(t, "mcp") and not _has(t, "function calling", "参数", "schema"):
            continue
        if _has(t, "prompt injection", "越权", "沙箱", "langgraph"):
            continue
        if _has(
            t,
            "调错参数",
            "参数生成失败",
            "json schema",
            "schema 怎么设计",
            "schema怎么设计",
            "选对工具",
            "选错",
            "structured output",
            "json mode",
            "工具调用失败",
            "失败怎么办",
            "失败如何",
            "失败时",
            "重试",
            "校验参数",
        ):
            keep.append(t)
            continue
        if _has(t, "function calling") and _has(
            t, "原理", "流程", "工作", "是什么", "完整", "参数", "schema", "失败", "tool"
        ):
            keep.append(t)
    return keep


def mcp(titles: list[str]) -> list[str]:
    drop_sub = (
        "240 道", "主项目", "企业级叙事", "README", "具体工作内容和成果",
    )
    keep = []
    for t in titles:
        if any(s in t for s in drop_sub):
            continue
        if not (_has(t, "mcp") or "MCP" in t):
            continue
        if _has(
            t,
            "schema",
            "鉴权",
            "权限",
            "认证",
            "授权",
            "json-rpc",
            "jsonrpc",
            "stdio",
            "安全",
            "host",
            "client",
            "server",
            "tools",
            "resources",
            "prompts",
            "function calling",
            "是什么",
            "协议",
        ):
            keep.append(t)
    return keep


def react(titles: list[str]) -> list[str]:
    drop = (
        "react.memo", "useeffect", "usestate", "usecallback", "usememo",
        "fibernode", "hooks", "vue", "proactor", "netty", "react 中",
        "react中", "react/", "react 点击", "react 不可变", "react 状态",
        "react18", "react 性能", "react 兄弟", "react 合成", "input.onchange",
        "render prop", "react-query", "react-apollo", "全栈以后", "学 vue",
        "reactor 模型", "reactor模式", "reactor 模式",
    )
    keep = []
    for t in titles:
        low = t.lower()
        if any(x in low for x in drop):
            continue
        if "reactor" in low:
            continue
        if "ReAct" not in t and "react 循环" not in low and "react循环" not in low:
            continue
        if _has(
            t,
            "循环",
            "失败",
            "thought",
            "observation",
            "action",
            "怎么停",
            "死循环",
            "失效",
            "debug",
            "三段式",
            "工作流程",
            "完整运行",
            "execution loop",
            "loop",
            "幻觉",
        ):
            keep.append(t)
    return keep


def plan_execute(titles: list[str]) -> list[str]:
    return list(titles)


def prompt_injection(titles: list[str]) -> list[str]:
    drop = (
        "sql 注入", "sql注入", "依赖注入", "构造器注入", "字段注入",
        "@autowired", "lora", "人脸", "docker", "故障注入", "环境变量",
        "音频注入", "身份注入", "图像条件", "q-former", "referencenet",
        "pdo", "mongodb", "二阶注入", "order by 在注入", "写 shell",
        "ioc", "spring 中", "bean", "collection", "混沌", "领域知识",
        "dataagentcontext", "动态约束注入", "记忆吗", "hunyuan", "svd",
        "i2v", "图生视频", "websocket", "whereRaw",
    )
    keep = []
    for t in titles:
        low = t.lower()
        if any(x in low for x in drop):
            continue
        if _has(t, "prompt injection", "prompt 注入", "提示词注入", "提示注入", "jailbreak", "越狱"):
            keep.append(t)
    return keep


def seckill(titles: list[str]) -> list[str]:
    drop = (
        "保险品", "开源技术或模型秒杀", "京东限时秒杀、抖音", "测试用例",
        "拼多多、天猫之间的对比",
    )
    return [t for t in titles if not any(s in t for s in drop)]


def cache_ppp(titles: list[str]) -> list[str]:
    keep = []
    for t in titles:
        if _has(t, "击穿", "穿透", "雪崩"):
            keep.append(t)
            continue
        if "布隆" in t and "穿透" in t:
            keep.append(t)
    return keep


def spring(titles: list[str]) -> list[str]:
    drop = (
        "微服务拆分", "RAG 系统的三级缓存", "IOC / AOP / 循环依赖 / Boot",
        "IoC 容器初始化流程 & Bean 生命周期", "IoC & AOP & Bean 生命周期",
        "循环依赖（Circular Dependencies）的特征", "循环依赖的两种解决策略",
    )
    return [t for t in titles if not any(s in t for s in drop)]


def hashmap(titles: list[str]) -> list[str]:
    drop = (
        "threadlocal", "arraylist", "linkedlist", "流式算法",
        "vector、deque", "juc 还了解", "juc还了解", "cow 相比",
        "介绍一下 java 集合", "介绍一下你熟悉的 java 集合",
        "手写一个 lru，用 linkedhashmap", "linkedhashmap 简介",
        "linkedhashmap 源码", "linkedhashmap 如何做到",
        "linkedhashmap 重写了", "不允许继承 linkedhashmap",
        "linkedhashmap 有几种迭代", "无参构造 `new linkedhashmap",
        "你了解 `linkedhashmap`", "迭代 `linkedhashmap`",
        "hashmap 和 linkedhashmap 的实现原理是什么？lrucache",
    )
    keep = []
    for t in titles:
        low = t.lower()
        if "treenode" in low and "linkedhashmap" in low:
            keep.append(t)
            continue
        if any(s in low for s in drop):
            continue
        if _has(t, "hashmap", "concurrenthashmap", "hashtable"):
            keep.append(t)
    return keep


def mysql_index(titles: list[str]) -> list[str]:
    drop = (
        "MVCC、事务隔离", "四种隔离级别，几种特性，存储引擎的区别、联合索引、分库分表",
    )
    return [t for t in titles if not any(s in t for s in drop)]


def vllm(titles: list[str]) -> list[str]:
    drop = (
        "为什么选择这个 agent", "langchain、llamaindex", "openai sdk 调用",
        "熟悉推理引擎如 pytorch", "vllm、langchain",
    )
    keep = []
    for t in titles:
        low = t.lower()
        if any(s in low for s in drop):
            continue
        if _has(t, "vllm", "pagedattention", "kv cache", "kvcache", "continuous batching", "连续批"):
            keep.append(t)
    return keep


def transformer(titles: list[str]) -> list[str]:
    drop = ("qwen2-vl", "hunyuan", "m-rope如何统一", "多模态预训练模型中的位置编码设计")
    keep = []
    for t in titles:
        low = t.lower()
        if any(s in low for s in drop):
            continue
        if _has(t, "self-attention", "自注意力", "位置编码", "positional", "rope"):
            keep.append(t)
    return keep


QUERIES = [
    {
        "id": "langgraph_state",
        "file": "langgraph",
        "fn": langgraph,
        "target_role": "AI Agent 开发",
        "skills": ["LangGraph", "Python", "LangChain"],
        "scenes": ["AI/RAG/Agent"],
        "query_text": "用 LangGraph 做有状态多步 Agent，节点之间怎么传状态、怎么避免死循环。",
    },
    {
        "id": "function_calling",
        "file": "function_calling",
        "fn": function_calling,
        "target_role": "AI Agent 开发",
        "skills": ["Function Calling", "Python"],
        "scenes": ["AI/RAG/Agent"],
        "query_text": "Function Calling 选错 tool 怎么缩小工具集、校验参数并重试。",
    },
    {
        "id": "mcp_schema",
        "file": "mcp",
        "fn": mcp,
        "target_role": "AI Agent 开发",
        "skills": ["MCP", "Python"],
        "scenes": ["AI/RAG/Agent"],
        "query_text": "接入 MCP 把外部工具暴露给模型，schema 和鉴权怎么设计。",
    },
    {
        "id": "react_loop",
        "file": "react",
        "fn": react,
        "target_role": "AI Agent 开发",
        "skills": ["ReAct", "Python"],
        "scenes": ["AI/RAG/Agent"],
        "query_text": "ReAct 推理循环里 thought-action-observation 失败怎么停。",
    },
    {
        "id": "plan_execute",
        "file": "plan_execute",
        "fn": plan_execute,
        "target_role": "AI Agent 开发",
        "skills": ["Plan-and-Execute", "Python"],
        "scenes": ["AI/RAG/Agent"],
        "query_text": "Plan-and-Execute 把规划和执行拆开，比 ReAct 好在哪、坑在哪。",
    },
    {
        "id": "prompt_injection",
        "file": "injection",
        "fn": prompt_injection,
        "target_role": "AI Agent 开发",
        "skills": ["Prompt Injection", "Python"],
        "scenes": ["AI/RAG/Agent"],
        "query_text": "Prompt 注入和工具越权，Agent 怎么做权限隔离。",
    },
    {
        "id": "seckill",
        "file": "seckill",
        "fn": seckill,
        "target_role": "Java 后端",
        "skills": ["Redis", "Lua", "Java"],
        "scenes": ["高并发", "缓存"],
        "query_text": "秒杀 Lua 预扣库存，如何保证不超卖。",
    },
    {
        "id": "cache_ppp",
        "file": "cache_ppp",
        "fn": cache_ppp,
        "target_role": "Java 后端",
        "skills": ["Redis", "Java"],
        "scenes": ["缓存"],
        "query_text": "缓存击穿、穿透、雪崩分别怎么防。",
    },
    {
        "id": "spring_cycle",
        "file": "spring",
        "fn": spring,
        "target_role": "Java 后端",
        "skills": ["Spring", "Spring Boot"],
        "scenes": [],
        "query_text": "Spring 循环依赖和三级缓存。",
    },
    {
        "id": "hashmap",
        "file": "hashmap",
        "fn": hashmap,
        "target_role": "Java 后端",
        "skills": ["HashMap", "ConcurrentHashMap", "Java"],
        "scenes": [],
        "query_text": "HashMap 1.8 和并发 ConcurrentHashMap。",
    },
    {
        "id": "mysql_index",
        "file": "mysql_index",
        "fn": mysql_index,
        "target_role": "Java 后端",
        "skills": ["MySQL", "Java"],
        "scenes": ["存储/数据库"],
        "query_text": "MySQL 最左前缀、覆盖索引、回表。",
    },
    {
        "id": "vllm_kv",
        "file": "vllm",
        "fn": vllm,
        "target_role": "大模型 / LLM",
        "skills": ["vLLM", "Python"],
        "scenes": ["推理/部署"],
        "query_text": "vLLM 连续批处理、KV cache、吞吐和延迟怎么折中。",
    },
    {
        "id": "transformer_attn",
        "file": "transformer",
        "fn": transformer,
        "target_role": "大模型 / LLM",
        "skills": ["Transformer", "Python"],
        "scenes": [],
        "query_text": "Transformer 自注意力、位置编码。",
    },
]


def main() -> None:
    queries = []
    for spec in QUERIES:
        titles = spec["fn"](_titles(spec["file"]))
        seen: set[str] = set()
        uniq = []
        for t in titles:
            if t in seen:
                continue
            seen.add(t)
            uniq.append(t)
        print(f"{spec['id']:20} |Rel|={len(uniq)}")
        if len(uniq) < 8:
            raise SystemExit(f"{spec['id']} gold too small: {len(uniq)}")
        queries.append(
            {
                "id": spec["id"],
                "target_role": spec["target_role"],
                "skills": spec["skills"],
                "scenes": spec["scenes"],
                "query_text": spec["query_text"],
                "relevant_questions": uniq,
            }
        )
    payload = {
        "protocol": {
            "name": "deepask-handmade-v2",
            "how": "金标是读题干留下的 question 原文，不用 roles[]。标签路按生产：岗位 + 简历技能 + 把 query_text 当练习焦点做 recall_boost。语义路只用 query_text 做 n-gram。",
            "k": [8, 48],
        },
        "queries": queries,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("写到", OUT)


if __name__ == "__main__":
    main()
