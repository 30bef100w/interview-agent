"""面经检索（RAG 核心）：画像 → 检索 questions_dedup（12,287 题）→ era 加权排序。

knowledge.jsonl（原文块）作为参考答案素材：get_answer_material 按 source_file 取扩展讲解。
"""
import json
import random
import re
from functools import lru_cache
from pathlib import Path

KB = Path(__file__).resolve().parents[2] / "data" / "knowledge_base"


def _era_weight(era: str | None) -> float:
    """用户定稿的时效权重：2025-26 ×1.0 / unknown ×0.8 / 2023-24 ×0.7 / 2021-22 ×0.4 / ≤2020 ×0.2"""
    if not era:
        return 0.8
    if era >= "2025":
        return 1.0
    if era >= "2023":
        return 0.7
    if era >= "2021":
        return 0.4
    return 0.2


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


@lru_cache(maxsize=1)
def load_questions() -> list[dict]:
    return _load_jsonl(KB / "questions_dedup.jsonl")


@lru_cache(maxsize=1)
def load_knowledge() -> list[dict]:
    return _load_jsonl(KB / "knowledge.jsonl")


def _norm(s: str) -> str:
    return re.sub(r"\W+", "", (s or "").lower())


def _question_norm(q: dict) -> str:
    return _norm(q.get("question"))


def _score_question(
    q: dict,
    roles: set[str],
    company: str | None,
    skills_low: list[str],
    scenes_set: set[str],
    category: str | None,
    recall_boost_terms: list[str] | None = None,
) -> float:
    if category and q.get("category") != category:
        return 0.0
    score = 0.0
    q_roles = set(q.get("roles") or [])
    if roles:
        # 有目标岗位时：岗位是硬门槛，简历技能/场景不能把无关岗位题捞进来
        overlap = q_roles & roles
        if not overlap:
            return 0.0
        primary = (q.get("roles") or [None])[0]
        if primary in roles:
            score += 80
        else:
            score += 35  # 仅次标签命中，弱于主岗位
        # 岗位关键词命中：同标签池内优先真正相关题（KB 弱标签噪音多）
        from app.services.job_roles import all_roles

        text_all = f"{q.get('question','')} {q.get('answer') or ''}".lower()
        kw_hits = 0
        for rid in overlap:
            for kw in all_roles().get(rid, {}).get("keywords") or []:
                if kw.lower() in text_all:
                    kw_hits += 1
        score += min(kw_hits, 6) * 12
    if company and q.get("company") == company:
        score += 120  # 企业定向权重最高，防止被弱标签噪音淹没
    if scenes_set:
        q_scene_list = list((q.get("business_scene") or []) + (q.get("tech_scene") or []))
        from app.services.scene_tag_similarity import scene_score_bonus

        score += scene_score_bonus(list(scenes_set), q_scene_list, has_roles=bool(roles))
    if skills_low:
        text = f"{q.get('question','')} {q.get('answer') or ''}".lower()
        skill_hits = sum(1 for s in skills_low if s in text)
        score += skill_hits * (4 if roles else 10)
    boost_terms = recall_boost_terms if recall_boost_terms is not None else None
    if boost_terms is None:
        from app.services.recall_boost import active_recall_boost_terms

        boost_terms = active_recall_boost_terms()
    if boost_terms:
        text = f"{q.get('question','')} {q.get('answer') or ''}".lower()
        boost_hits = sum(1 for t in boost_terms if str(t).lower() in text)
        score += min(boost_hits, 8) * 7
    if score <= 0:
        return 0.0
    score *= _era_weight(q.get("era"))
    # 基础题降权：以"是什么？"结尾的简单概念题，避免占满候选池
    if str(q.get("question") or "").rstrip().endswith(("是什么？", "是什么")):
        score *= 0.3
    return score


@lru_cache(maxsize=1)
def _tech_words() -> set[str]:
    """技术词表：job_roles + project_scenes + 通用技术概念词。"""
    from app.services.job_roles import all_roles
    import json as _json

    words: set[str] = set()
    for cfg in all_roles().values():
        words.update(k.lower() for k in cfg.get("keywords", []))
    scenes_path = Path(__file__).resolve().parents[2] / "data" / "project_scenes.json"
    try:
        scenes = _json.loads(scenes_path.read_text(encoding="utf-8"))
        for group in ("business_scenes", "tech_scenes"):
            for s in scenes.get(group, []):
                words.update(k.lower() for k in s.get("keywords", []))
    except OSError:
        pass
    # 通用技术概念词（参考答案素材检索用，覆盖词表外的常见概念）
    words.update(
        "jvm 内存模型 垃圾回收 线程池 线程 进程 并发 锁 索引 事务 索引 分库分表 主从 读写分离 "
        "序列化 反射 泛型 注解 依赖注入 aop ioc 网关 限流 熔断 降级 幂等 分布式 一致性 消息 "
        "网络 tcp http websocket 操作系统 页面置换 死锁 阻塞 异步 缓存 双写 延迟 队列 定时任务 "
        "安全 认证 授权 加密 压缩 序列化 深拷贝 浅拷贝 迭代器 动态代理 单例 工厂 观察者 适配器".split()
    )
    return words


def _is_noisy(q: dict) -> bool:
    """弱标签噪音 / 低质量碎片 / 求职攻略题 / 目录标题。"""
    roles = q.get("roles") or []
    if len(roles) > 3:
        return True
    q_text = (q.get("question") or "").strip()
    if len(q_text) < 10:
        return True
    # 纯英文目录/合集标题（无汉字）
    if re.search(r"[A-Za-z]{4,}", q_text) and not re.search(r"[\u4e00-\u9fff]", q_text):
        return True
    junk = (
        "秋招攻略", "保姆级", "如何备战", "直接导入", "原型图", "工作台",
        "课程资料", "根据id删除", "根据id查询",
        # 求职攻略类（非技术题）
        "准备重点有什么区别", "没有项目经验怎么办", "简历应该怎么写", "练手项目",
        "跟着视频做的项目", "面试官嫌弃", "推荐一个可写简历",
        "按什么顺序准备", "面经应该怎么用", "面试紧张", "如何复盘", "怎么弥补",
        "如何提炼技术难点", "有没有还不错的项目", "知识点最值得优先复习",
        "哪些知识点是重点", "面试重点有哪些", "复习哪些", "怎么准备面试",
        "面试参考", "题库合集", "知识体系",
        # 课程代码碎片
        ".java", ".xml", "mapper", "controller", "countByMap",
        "poi", "excel文件", "接口文档测试", "前后端联调", "接下来我们",
    )
    low = q_text.lower()
    if any(j in low for j in junk):
        return True
    if "interview reference" in low or (
        "reference" in low and ("interview" in low or "llm" in low)
    ):
        return True
    # 攻略题规则：简历/校招主题 + 建议问法（"面试中如何实现分布式锁"这类真技术题不含简历/校招，不误伤）
    if ("简历" in q_text or "校招" in q_text) and any(
        w in q_text for w in ("如何", "应该", "哪些", "会不会", "要不要", "怎么")
    ):
        return True
    # 「XX面试哪些/什么是重点」元问题
    if "面试" in q_text and any(w in q_text for w in ("重点", "知识点", "怎么准备", "如何准备")):
        if not any(w in low for w in ("jvm", "hashmap", "redis", "线程", "索引", "事务", "rag", "agent")):
            return True
    # 技术词判定：短问句且不含任何技术栈/场景关键词 → 求职建议/闲聊题
    # 含 HashMap/JVM 等英文技术专名的不算「无技术」
    has_latin_tech = bool(re.search(r"[A-Za-z][A-Za-z0-9_+#.-]{2,}", q_text))
    if (
        len(q_text) < 45
        and not has_latin_tech
        and not any(w in low for w in _tech_words())
    ):
        return True
    return False


def sanitize_hits(
    hits: list[dict],
    roles: list[str] | None = None,
    company: str | None = None,
    *,
    require_role: bool = False,
) -> list[dict]:
    """召回后清洗：去噪音/错题/攻略题，岗位硬过滤，目标企业时剔其他公司标签题。"""
    roles_set = set(roles or [])
    out: list[dict] = []
    seen: set[str] = set()
    for h in hits:
        if _is_noisy(h):
            continue
        q_norm = _question_norm(h)
        if not q_norm or q_norm in seen:
            continue
        q_roles = set(h.get("roles") or [])
        if roles_set:
            if require_role or q_roles:
                if not (q_roles & roles_set):
                    continue
        h_company = str(h.get("company") or "").strip()
        if company and h_company and h_company != company:
            continue
        seen.add(q_norm)
        out.append(h)
    return out


def _bigrams(text: str) -> set[str]:
    norm = re.sub(r"\W+", "", (text or "").lower())
    return {norm[i : i + 2] for i in range(len(norm) - 1)} if len(norm) > 2 else set()


def _asked_score_penalty(q_norm: str, asked: set[str]) -> float:
    """历史已问/已捞过题的检索惩罚：精确几乎排除，近似强降权，逼检索换新题。"""
    if not asked or not q_norm or len(q_norm) < 8:
        return 1.0
    if q_norm in asked:
        return 0.01
    # 控制复杂度：只对较长历史问法做近似比对
    sample = [a for a in asked if len(a) >= 10]
    if len(sample) > 180:
        sample = sample[:180]
    q_grams = (
        {q_norm[i : i + 2] for i in range(len(q_norm) - 1)} if len(q_norm) > 2 else set()
    )
    best_overlap = 0.0
    for a in sample:
        if a in q_norm or q_norm in a:
            return 0.04
        if len(a) >= 16 and len(q_norm) >= 16:
            n = min(12, len(a), len(q_norm))
            for i in range(0, len(a) - n + 1, 3):
                if a[i : i + n] in q_norm:
                    return 0.1
        if q_grams and len(a) > 2:
            a_grams = {a[i : i + 2] for i in range(len(a) - 1)}
            if a_grams:
                overlap = len(q_grams & a_grams) / max(len(q_grams), len(a_grams))
                if overlap > best_overlap:
                    best_overlap = overlap
    if best_overlap >= 0.55:
        return 0.12
    if best_overlap >= 0.42:
        return 0.3
    return 1.0


def retrieve(
    roles: list[str] | None = None,
    company: str | None = None,
    skills: list[str] | None = None,
    scenes: list[str] | None = None,
    category: str | None = None,
    asked_norms: set[str] | None = None,
    top_n: int = 8,
    pool_size: int = 30,
    min_score: int = 30,
    recall_boost_terms: list[str] | None = None,
) -> list[dict]:
    """召回：打分 → 历史已问惩罚 → 候选池 → 主题分散 → 抽 top_n。

    asked_norms：历史问过的题（归一化）；精确命中 ×0.01，近似命中强降权。
    """
    roles_set = set(roles or [])
    skills_low = [s.lower() for s in (skills or []) if s]
    scenes_set = set(scenes or [])
    asked = asked_norms or set()

    scored: list[tuple[float, dict]] = []
    for q in load_questions():
        if _is_noisy(q):
            continue
        s = _score_question(
            q, roles_set, company, skills_low, scenes_set, category, recall_boost_terms
        )
        if s < min_score:
            continue
        s *= _asked_score_penalty(_question_norm(q), asked)
        if s < min_score * 0.05:
            continue
        scored.append((s, q))
    scored.sort(key=lambda x: x[0], reverse=True)
    if company:
        # 企业原题 + 无公司标签 双路留坑，避免企业分过高把通用题挤出池子
        company_hits = [
            x
            for x in scored
            if x[1].get("company") == company and _question_norm(x[1]) not in asked
        ]
        untagged_hits = [
            x
            for x in scored
            if not x[1].get("company") and _question_norm(x[1]) not in asked
        ]
        reserve = max(2, pool_size // 3)
        pool: list[tuple[float, dict]] = []
        seen_pool: set[str] = set()

        def _push(group: list[tuple[float, dict]], cap: int | None = None) -> None:
            n = 0
            for item in group:
                key = _question_norm(item[1])
                if not key or key in seen_pool:
                    continue
                seen_pool.add(key)
                pool.append(item)
                n += 1
                if len(pool) >= pool_size:
                    return
                if cap is not None and n >= cap:
                    return

        _push(company_hits, reserve)
        _push(untagged_hits, reserve)
        _push(scored)  # 其余按分补齐（可含其他企业同岗题）
    else:
        pool = scored[:pool_size]
    if not pool:
        return []

    picked: list[dict] = []
    picked_grams: set[str] = set()
    remaining = pool
    while len(picked) < top_n and remaining:
        remaining.sort(key=lambda x: x[0], reverse=True)
        _best_score, best = remaining[0]
        remaining = remaining[1:]
        picked.append(best)
        grams = _bigrams(best.get("question"))
        picked_grams |= grams
        if grams:
            remaining = [
                (s * 0.5 if len(_bigrams(q.get("question")) & picked_grams) >= 3 else s, q)
                for s, q in remaining
            ]
    return picked


def search_questions(
    roles: list[str] | None = None,
    company: str | None = None,
    skills: list[str] | None = None,
    scenes: list[str] | None = None,
    category: str | None = None,
    asked_norms: set[str] | None = None,
    top_n: int = 8,
    min_score: int = 10,
    recall_boost_terms: list[str] | None = None,
) -> list[dict]:
    """简单版：纯打分排序取 Top N；同样对历史已问题目降权。"""
    roles_set = set(roles or [])
    skills_low = [s.lower() for s in (skills or []) if s]
    scenes_set = set(scenes or [])
    asked = asked_norms or set()
    scored = []
    for q in load_questions():
        if _is_noisy(q):
            continue
        s = _score_question(
            q, roles_set, company, skills_low, scenes_set, category, recall_boost_terms
        )
        if s < min_score:
            continue
        s *= _asked_score_penalty(_question_norm(q), asked)
        if s < min_score * 0.05:
            continue
        scored.append((s, q))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [q for _, q in scored[:top_n]]


def pick_bagu_questions(
    roles: list[str] | None = None,
    company: str | None = None,
    skills: list[str] | None = None,
    asked_norms: set[str] | None = None,
    n: int = 3,
) -> list[dict]:
    """八股专用抽取：只从 category=bagu 题库取题。

    有目标岗位时：全程硬卡岗位，绝不拿「同企业其他岗位」凑数。
      1) 该企业 × 目标岗位
      2) 同岗位其他企业真题 / 无企业标签
      3) 同岗位放宽分数兜底
    无目标岗位时：才按企业/技能弱约束抽。
    """
    if n <= 0:
        return []
    asked = asked_norms or set()
    picked: list[dict] = []
    seen: set[str] = set()

    def _take(hits: list[dict], *, require_company: bool = False) -> None:
        for h in hits:
            if len(picked) >= n:
                return
            key = _question_norm(h)
            if not key or key in seen or key in asked:
                continue
            if _is_noisy(h):
                continue
            # 有目标岗位时：题面 roles 必须与目标岗位有交集（防串岗）
            if roles:
                q_roles = set(h.get("roles") or [])
                if not (q_roles & set(roles)):
                    continue
            if require_company and not h.get("company"):
                continue
            seen.add(key)
            picked.append(h)

    def _company_role_pool() -> list[dict]:
        """目标企业 × 目标岗位（双硬过滤，不放宽岗位）。"""
        assert company and roles
        hits = retrieve(
            roles=list(roles),
            company=company,
            skills=skills,
            category="bagu",
            asked_norms=asked,
            top_n=max(n * 3, 10),
            min_score=10,
        )
        hits = [
            h
            for h in hits
            if h.get("company") == company and set(h.get("roles") or []) & set(roles)
        ]
        if len(hits) < n:
            more = search_questions(
                roles=list(roles),
                company=company,
                skills=skills,
                category="bagu",
                asked_norms=asked,
                top_n=n * 8,
                min_score=1,
            )
            seen_q = {_question_norm(h) for h in hits}
            for h in more:
                if h.get("company") != company:
                    continue
                if not (set(h.get("roles") or []) & set(roles)):
                    continue
                k = _question_norm(h)
                if k and k not in seen_q and not _is_noisy(h):
                    hits.append(h)
                    seen_q.add(k)
                if len(hits) >= n * 3:
                    break
        return hits

    # 1) 目标企业 × 目标岗位
    if company and roles:
        _take(_company_role_pool())
    # 2) 同岗位补齐（可跨企业）；禁止「同企业任意岗」
    if len(picked) < n and roles:
        role_hits = retrieve(
            roles=roles,
            company=None,
            skills=skills,
            category="bagu",
            asked_norms=asked | seen,
            top_n=max(n * 4, 12),
            min_score=10,
        )
        tagged_same = [
            h for h in role_hits if company and h.get("company") == company
        ]
        tagged_other = [
            h for h in role_hits if h.get("company") and h.get("company") != company
        ]
        untagged = [h for h in role_hits if not h.get("company")]
        _take(tagged_same)
        _take(tagged_other)
        if len(picked) < n:
            _take(untagged)
        if len(picked) < n:
            more = search_questions(
                roles=roles,
                skills=skills,
                category="bagu",
                asked_norms=asked | seen,
                top_n=n * 5,
                min_score=5,
            )
            _take([h for h in more if h.get("company")])
            _take([h for h in more if not h.get("company")])

    # 3) 极端兜底：仍只从 bagu 库；有岗位时绝不放开无岗位 / 其他岗位池
    if len(picked) < n:
        if roles:
            more = search_questions(
                roles=roles,
                skills=skills,
                category="bagu",
                asked_norms=asked | seen,
                top_n=n * 10,
                min_score=0,
            )
            _take([h for h in more if h.get("company")])
            _take(more)
        else:
            more = search_questions(
                category="bagu", asked_norms=asked | seen, top_n=n * 8, min_score=0
            )
            if company:
                _take([h for h in more if h.get("company") == company])
                _take([h for h in more if h.get("company")], require_company=True)
            _take(more)
    return picked[:n]


def search_projects(
    project_name: str,
    skills: list[str],
    scenes: list[str] | None,
    top_n: int = 4,
    asked_norms: set[str] | None = None,
) -> list[dict]:
    """项目定向检索：项目名关键词 + 技术栈 + 场景 → project 类条目。"""
    name_parts = [p for p in re.split(r"[\s\-_（）()]", project_name) if len(p) >= 2]
    asked = asked_norms or set()
    scored: list[tuple[float, dict]] = []
    for q in load_questions():
        if q.get("category") != "project":
            continue
        text = f"{q.get('question','')} {q.get('answer') or ''}"
        score = 0.0
        if any(p.lower() in text.lower() for p in name_parts):
            score += 60
        if skills:
            score += sum(10 for s in skills if s and s.lower() in text.lower())
        if scenes:
            q_scene_list = list((q.get("business_scene") or []) + (q.get("tech_scene") or []))
            from app.services.scene_tag_similarity import scene_score_bonus

            score += scene_score_bonus(scenes, q_scene_list, has_roles=False)
        if score < 20:
            continue
        score *= _era_weight(q.get("era"))
        score *= _asked_score_penalty(_question_norm(q), asked)
        if score < 1:
            continue
        scored.append((score, q))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [q for _, q in scored[:top_n]]


@lru_cache(maxsize=1)
def _knowledge_index() -> dict[str, list[dict]]:
    """source_file → 原文块列表（参考答案扩展素材）。"""
    idx: dict[str, list[dict]] = {}
    for b in load_knowledge():
        key = b.get("source_file") or ""
        idx.setdefault(key, []).append(b)
    return idx


def get_answer_material(source_file: str | None, max_blocks: int = 3) -> list[dict]:
    if not source_file:
        return []
    return _knowledge_index().get(source_file, [])[:max_blocks]


def search_knowledge_blocks(text: str, top_n: int = 2, min_hit: int = 2) -> list[dict]:
    """按技术关键词在 knowledge.jsonl（原文块）检索 → 终评官参考答案素材。

    优先 knowledge 类型（知识讲解），面经原文降权，跳过目录/索引块；
    题面 2-gram 与块内容共现加分（连续上下文更相关）。
    """
    low = text.lower()
    kws = [w for w in _tech_words() if w in low]
    if not kws:
        return []
    grams = _bigrams(text)
    scored: list[tuple[float, dict]] = []
    for b in load_knowledge():
        content = (b.get("content") or "").lower()
        hit = sum(1 for k in kws if k in content)
        if hit < min_hit:
            continue
        # 目录/索引块跳过（含模块清单的汇总文档）
        if any(m in content[:200] for m in ("面试题汇总", "模块", "目录", "精要版", "8 大模块")):
            continue
        weight = 2.0 if b.get("type") == "knowledge" else 0.5
        gram_hit = len(grams & _bigrams(content))
        scored.append((hit * weight + gram_hit * 0.1, b))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [b for _, b in scored[:top_n]]


def format_answer_material(text: str, top_n: int = 2, max_chars: int = 250) -> str:
    """题目 → 参考答案素材文本块（供终评官 reference_answer 参考）。"""
    blocks = search_knowledge_blocks(text, top_n=top_n)
    if not blocks:
        return ""
    parts = []
    for b in blocks:
        content = (b.get("content") or "").strip()
        parts.append(content[:max_chars])
    return "\n\n".join(parts)


def merge_company_and_untagged(
    company_hits: list[dict],
    untagged_hits: list[dict],
    *,
    company: str | None = None,
    limit: int = 10,
    extra: list[dict] | None = None,
) -> list[dict]:
    """场景/岗位多路：目标企业题 + 无公司标签题交错合并（去重）。

    company 有值时，第一路只保留该公司标签；第二路只保留无 company 字段的题。
    """
    tagged = company_hits
    if company:
        tagged = [h for h in company_hits if h.get("company") == company]
    plain = [h for h in untagged_hits if not h.get("company")]
    # 交错：企业 / 无标签 / 企业 / 无标签 …
    interleaved: list[dict] = []
    i = j = 0
    while i < len(tagged) or j < len(plain):
        if i < len(tagged):
            interleaved.append(tagged[i])
            i += 1
        if j < len(plain):
            interleaved.append(plain[j])
            j += 1
    groups = [interleaved]
    if extra:
        groups.append(extra)
    return merge_hits(*groups, limit=limit)


def format_hits(
    hits: list[dict],
    limit: int = 8,
    company: str | None = None,
    company_label: str | None = None,
) -> str:
    """检索结果 → 注入 prompt 的文本块。企业原题（company 匹配）加【企业原题·展示名】标注。"""
    if not hits:
        return ""
    label = (company_label or company or "").strip()
    lines = []
    for i, h in enumerate(hits[:limit], 1):
        tag = []
        if h.get("company"):
            tag.append(h["company"])
        if h.get("roles"):
            tag.append("/".join(h["roles"][:2]))
        if h.get("era"):
            tag.append(h["era"])
        scenes = (h.get("business_scene") or []) + (h.get("tech_scene") or [])
        if scenes:
            tag.append("/".join(str(s) for s in scenes[:2]))
        is_original = bool(company and h.get("company") == company)
        if is_original and label:
            original = f"【企业原题·{label}】"
        elif company and not h.get("company"):
            original = "【通用·无企业标签】"
        else:
            original = ""
        prefix = f"  [{', '.join(tag)}] " if tag else "  "
        ans = (h.get("answer") or "").strip()
        lines.append(f"{i}. {original}{h['question']}")
        if ans:
            lines.append(f"{prefix}要点：{ans[:120]}")
    return "\n".join(lines)


def format_dual_hits(
    role_hits: list[dict],
    scene_hits: list[dict],
    *,
    company: str | None = None,
    company_label: str | None = None,
    role_limit: int = 8,
    scene_limit: int = 6,
) -> str:
    """岗位路 + 场景路 → 分区注入规划官；两路都有时模型综合出题单/参考。"""
    parts: list[str] = []
    role_block = format_hits(
        role_hits, limit=role_limit, company=company, company_label=company_label
    )
    if role_block:
        parts.append("【A. 目标岗位相关真实面试题/高频题】\n" + role_block)
    scene_block = format_hits(
        scene_hits, limit=scene_limit, company=company, company_label=company_label
    )
    if scene_block:
        parts.append(
            "【B. 简历项目场景相关真实面试题/高频题】\n"
            "（目标企业场景题 + 无企业标签通用场景题，二者一起参考；"
            "同类业务/技术场景下真人常怎么挖项目；规划项目题与拷打方向时必须参考）\n"
            + scene_block
        )
    if not parts:
        return ""
    parts.append(
        "【规划用法】题单与项目深挖综合 A+B："
        "A 定岗位考察能力，B 定场景下真人问法；企业原题与无企业标签题都要吃，丰富问法；"
        "改写组织语言，严禁照搬原题面；"
        "优先做「场景真题 × 岗位考察点」交叉，勿只空编脱离简历场景的设计题。"
    )
    return "\n\n".join(parts)


def merge_hits(*groups: list[dict], limit: int = 20) -> list[dict]:
    """多路命中按题面去重合并（保序）。"""
    seen: set[str] = set()
    out: list[dict] = []
    for group in groups:
        for h in group:
            q = str(h.get("question") or "").strip()
            if not q or q in seen:
                continue
            seen.add(q)
            out.append(h)
            if len(out) >= limit:
                return out
    return out
