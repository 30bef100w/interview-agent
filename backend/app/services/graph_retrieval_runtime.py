"""MG/KG adapter: cached snapshot -> seed resolution -> BFS -> semantic rerank.

All model work uses the existing per-interview, metered LLM port. The core graph
remains immutable; callers own the legacy fallback when preparation fails.
"""
from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from pathlib import Path
import random
import re
import time
from typing import Any, Iterable, Mapping

from app.config import settings
from app.services.graph_retrieval import (
    GraphIndex, GraphRetriever, GraphRetrievalConfig, _Candidate,
)
from app.services.graph_seed_resolver import GraphSeedResolver
from app.services.graph_reranker import rerank
from app.services.graph_snapshot import read_snapshot


def _load_snapshot(path: Path, include_drafts: bool, require_release: bool = False) -> GraphIndex:
    nodes, edges, manifest = read_snapshot(path, require_release=require_release)
    graph = GraphIndex(nodes, edges, include_drafts=include_drafts)
    graph.runtime_manifest = manifest
    return graph


def _snapshot_path() -> Path:
    raw = str(settings.graph_snapshot_path or "").strip()
    if not raw:
        raise ValueError("graph snapshot path cannot be empty")
    configured = Path(raw)
    if configured.is_absolute():
        return configured
    # Prefer files bundled with the backend (also valid in the Docker image),
    # then repository-relative legacy/demo paths. Never depend on process cwd.
    backend = Path(__file__).resolve().parents[2]
    bundled = backend / configured
    if bundled.exists():
        return bundled
    source = backend.parent / configured
    if source.exists():
        return source
    return bundled


@lru_cache(maxsize=2)
def _load_cached(path_text: str, include_drafts: bool, require_release: bool = False) -> GraphIndex:
    return _load_snapshot(Path(path_text), include_drafts, require_release)


def _norm(value) -> str:
    return re.sub(r"\W+", "", str(value or "").casefold())


def content_key(row: Mapping) -> tuple:
    """Same conservative content rule as the frozen four-arm experiment."""
    body, answer = _norm(row.get("question")), _norm(row.get("answer"))
    context = tuple(str(ref.get("quote", "")) for ref in row.get("context_refs", [])
                    if isinstance(ref, dict))
    return (body, answer, context) if len(body) < 16 else (body, answer)


def deduplicate(rows: list[dict]) -> list[dict]:
    seen = {}; identities = {}; result = []
    for row in rows:
        key = content_key(row)
        identity = row["canonical_question_id"]
        old = identities.get(identity) or seen.get(key)
        if old is not None:
            old["channels"] = sorted(set(old["channels"]) | set(row["channels"]))
            old["direct_scene"] |= row["direct_scene"]
            old["source_question_ids"] = sorted(set(old["source_question_ids"]) | set(row["source_question_ids"]))
            old["companies"] = sorted({str(value) for source in (old, row)
                                       for value in [source.get("company"), *(source.get("companies") or [])]
                                       if value})
            old["company_match"] = bool(old.get("company_match") or row.get("company_match"))
            old["paths"] = (old["paths"] + row["paths"])[:12]
            identities[identity] = old
            seen[key] = old
            continue
        item = dict(row)
        seen[key] = item; identities[identity] = item; result.append(item)
    return result


def select_quota(rows: list[dict], config: GraphRetrievalConfig, has_scene: bool) -> list[dict]:
    # Use the same allocator as the offline experiment, preserving supplied order.
    objects = []
    for row in rows:
        item = _Candidate(row["canonical_question_id"], row["question_id"])
        item.channels = set(row["channels"]); item.direct_scene = row["direct_scene"]
        objects.append(item)
    _, assignments, _ = GraphRetriever._select(objects, config, has_scene)
    return [{**row, "assigned_lane": assignments[row["canonical_question_id"]]}
            for row in rows if row["canonical_question_id"] in assignments]


def prioritize_company(rows: list[dict], company: str | None) -> list[dict]:
    """企业题优先于通用题；只改变候选顺序，不丢弃通用题。"""
    if not company:
        return list(rows)
    return sorted(
        rows,
        key=lambda row: (
            0 if row.get("company_match") else (1 if not row.get("company") else 2),
            0 if row.get("direct_scene") else 1,
            -float(row.get("score") or 0),
        ),
    )


class GraphRetrievalRuntime:
    def __init__(self, llm, *, snapshot: str | Path | None = None,
                 include_drafts: bool | None = None):
        self.llm = llm
        path = Path(snapshot) if snapshot is not None else _snapshot_path()
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[3] / path
        self.snapshot = path
        self.include_drafts = settings.graph_include_drafts if include_drafts is None else bool(include_drafts)
        production = bool(getattr(settings, "is_production", False))
        if production and self.include_drafts:
            raise ValueError("production graph cannot enable draft retrieval")
        self.graph = _load_cached(str(path), self.include_drafts, production)
        self.retriever = GraphRetriever(self.graph)
        self.resolver = GraphSeedResolver(
            self.graph, max_scene_seeds=settings.graph_max_scene_seeds,
            max_concept_seeds=settings.graph_max_concept_seeds,
            max_catalog_chars=settings.graph_seed_catalog_chars,
        )

    @staticmethod
    def _projects(profile: Mapping[str, Any]) -> list[dict]:
        return [p for p in profile.get("projects", []) or [] if isinstance(p, Mapping)
                ][:max(1, settings.graph_max_projects)]

    @staticmethod
    def _to_hit(item: Mapping[str, Any]) -> dict:
        props = item.get("original_tags") or {}
        return {
            "question": item.get("question") or "", "answer": item.get("answer") or "",
            "company": item.get("company") or "", "companies": item.get("companies") or [],
            "roles": item.get("roles") or [], "era": item.get("era") or "",
            "business_scene": props.get("business_scene") or [], "tech_scene": props.get("tech_scene") or [],
            "category": props.get("category") or "", "tags": props.get("tags") or [],
            "source_file": item.get("source_file") or "", "source_locator": item.get("source_locator") or "",
            "graph_question_id": item.get("question_id") or "",
            "graph_source_question_ids": item.get("source_question_ids") or [],
            "graph_canonical_question_id": item.get("canonical_question_id") or "",
            "graph_channels": item.get("channels") or [], "graph_paths": item.get("paths") or [],
            "graph_assigned_lane": item.get("assigned_lane"), "graph_score": item.get("score"),
            "graph_direct_scene": bool(item.get("direct_scene")),
            "graph_company_match": bool(item.get("company_match")),
        }

    def retrieve_projects(self, profile: Mapping[str, Any], *, company: str | None = None,
                          asked_norms: Iterable[str] = (), asked_question_ids: Iterable[str] = (),
                          seed: int = 0, roles: Iterable[str] = (), target_role: str = "",
                          focus: str = "", job_description: str = "", material_limit: int = 16) -> dict:
        cfg = GraphRetrievalConfig(
            kg_candidate_limit=settings.graph_kg_candidate_limit,
            mg_candidate_limit=settings.graph_mg_candidate_limit,
            final_limit=settings.graph_final_limit,
            kg_final_quota=settings.graph_kg_final_quota, mg_final_quota=settings.graph_mg_final_quota,
            max_depth=settings.graph_max_depth,
            max_scene_seeds=settings.graph_max_scene_seeds, max_concept_seeds=settings.graph_max_concept_seeds,
        )
        hits = []; seen_ids = set(); seen_content = set(); meta = []; domains = []
        projects = self._projects(profile)
        role_set = set(roles)
        asked_norms, asked_question_ids = tuple(asked_norms), tuple(asked_question_ids)
        per_project = max(1, material_limit // max(1, len(projects)))
        for index, project in enumerate(projects):
            started = time.perf_counter()
            resolution = self.resolver.resolve(project, self.llm, project_id=f"p{index + 1}",
                                               company=company, focus=focus)
            seed_ms = (time.perf_counter() - started) * 1000
            domains.extend(resolution.query.concept_ids)
            started = time.perf_counter()
            result = self.retriever.project_retrieve(
                resolution.query, config=cfg, seed=seed + index,
                asked_question_ids=asked_question_ids, asked_question_norms=asked_norms,
                exclude_question_ids=seen_ids,
            )
            rows = deduplicate(result["candidates"])
            # Preserve the existing target-role boundary before shortlisting.
            rows = [row for row in rows if (not role_set or role_set & set(row.get("roles") or []))
                    and content_key(row) not in seen_content]
            rows = prioritize_company(rows, company)
            retrieval_ms = (time.perf_counter() - started) * 1000
            has_scene = bool(resolution.query.scene_ids)
            limit = min(cfg.final_limit, per_project + (index < material_limit % max(1, len(projects))))
            shortlist_n = max(limit, min(100, max(1, settings.graph_rerank_shortlist)))
            shortlist = select_quota(rows, replace(cfg, final_limit=shortlist_n), has_scene)
            rank_status = "disabled"; rank_error = ""; started = time.perf_counter()
            if settings.graph_rerank_enabled and len(shortlist) > 1:
                try:
                    shortlist = rerank(shortlist, self.llm, project_text=resolution.query.project_text,
                                       target_role=target_role, focus=focus,
                                       job_description=job_description, seed=seed + index)
                    rank_status = "llm"
                except Exception as exc:
                    # Invalid/partial permutations cannot inject or silently drop questions.
                    rank_status = "rules_fallback"; rank_error = type(exc).__name__
            elif settings.graph_rerank_enabled:
                rank_status = "not_needed"
            rerank_ms = (time.perf_counter() - started) * 1000
            # LLM 重排只决定同一优先级内的顺序；企业匹配是硬优先级，避免
            # 重排器因题面语义把目标企业原题挤到普通题之后。
            shortlist = prioritize_company(shortlist, company)
            selected = select_quota(shortlist, replace(cfg, final_limit=limit), has_scene)
            project_hits = []
            for item in selected:
                seen_ids.update(item["source_question_ids"])
                seen_ids.add(item["canonical_question_id"]); seen_content.add(content_key(item))
                hit = self._to_hit(item)
                hit["graph_project_id"] = resolution.query.project_id
                hit["graph_project_name"] = project.get("name") or resolution.query.project_id
                project_hits.append(hit)
            hits.extend(project_hits)
            meta.append({
                "project_id": resolution.query.project_id, "project_name": project.get("name") or "",
                "scene_ids": list(resolution.query.scene_ids), "concept_ids": list(resolution.query.concept_ids),
                "scene_evidence": list(resolution.scene_evidence), "concept_evidence": list(resolution.concept_evidence),
                "candidate_count": len(rows), "shortlist_count": len(shortlist), "selected_count": len(selected),
                "seed_ms": round(seed_ms, 3), "retrieval_ms": round(retrieval_ms, 3),
                "rerank_ms": round(rerank_ms, 3), "rerank_status": rank_status, "rerank_error": rank_error,
                "trace": result["meta"]["trace"],
            })
        # Round-robin so a limited planner prompt still contains every project.
        ordered = []
        for offset in range(max((len([h for h in hits if h["graph_project_id"] == m["project_id"]]) for m in meta), default=0)):
            for m in meta:
                group = [h for h in hits if h["graph_project_id"] == m["project_id"]]
                if offset < len(group): ordered.append(group[offset])
        return {"hits": ordered, "projects": meta, "domain_concept_ids": list(dict.fromkeys(domains)),
                "snapshot": self.snapshot.name, "include_drafts": self.include_drafts,
                "release": getattr(self.graph, "runtime_manifest", None),
                "selected": [{key: h[key] for key in ("graph_project_id", "graph_question_id",
                              "graph_source_question_ids", "graph_channels", "graph_paths", "graph_assigned_lane")}
                             for h in ordered],
                "selected_question_ids": sorted(seen_ids)}

    def retrieve_general(self, *, count: int = 4, asked_norms: Iterable[str] = (),
                         seed: int | None = None, company: str | None = None) -> list[dict]:
        """Approved behavioral references only; never mix these into technical recall."""
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("count must be a non-negative integer")
        asked = {_norm(s) for s in asked_norms}
        rows = []
        for qid in self.graph.general_question_ids:
            if self.retriever._blocked(qid, set(), asked, set()):
                continue
            item = _Candidate(self.graph.identity(qid), qid)
            item.source_question_ids.add(qid)
            self.retriever._score(item, company, {}, time.time())
            rows.append(self.retriever._result(item))
        random.Random(seed).shuffle(rows)
        rows = prioritize_company(deduplicate(rows), company)
        return [{**self._to_hit(row), "general_pool_kind": "behavioral"} for row in rows[:count]]

    def retrieve_bagu(self, *, domain_concept_ids: Iterable[str], count: int,
                      asked_norms: Iterable[str] = (), asked_question_ids: Iterable[str] = (),
                      exclude_question_ids: Iterable[str] = (), seed: int | None = None,
                      roles: Iterable[str] = (), company: str | None = None) -> list[dict]:
        # Find top technical ancestors once for the BAGU scope. This does not
        # change project BFS or introduce cross-scene traversal.
        domains = set(); seen = set(); pending = list(domain_concept_ids)
        while pending:
            node = pending.pop()
            if node in seen or not self.graph.typed(node, "Concept"):
                continue
            seen.add(node)
            parents = [parent for parent in self.graph.neighbors(node, "HAS_SUBTOPIC", reverse=True)
                       if self.graph.nodes[parent].get("properties", {}).get("kind") != "navigation"]
            if parents:
                pending.extend(parents)
            else:
                domains.add(node)
        result = self.retriever.bagu_retrieve(
            domain_concept_ids=sorted(domains), count=len(self.graph.canonical), seed=seed,
            asked_question_ids=asked_question_ids, asked_question_norms=asked_norms,
            exclude_question_ids=exclude_question_ids,
        )
        # Random leaf pool first, then role gate and conservative exact dedup.
        role_set = set(roles)
        rows = [row for row in result["questions"]
                if not role_set or role_set & set(row.get("roles") or [])]
        rows = deduplicate(rows)
        if company:
            # 叶子题池仍然随机抽样，但企业原题先进入候选池；通用题用于补足。
            rows.sort(key=lambda row: 0 if company in ({row.get("company")} | set(row.get("companies") or []))
                      else (1 if not row.get("company") and not row.get("companies") else 2))
        return [self._to_hit(item) for item in rows[:count]]
