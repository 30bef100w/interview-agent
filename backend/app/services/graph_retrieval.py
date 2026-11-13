"""Pure graph retrieval core shared by offline evaluation and the interview adapter.

Project questions: KG + MG bounded randomized BFS, shared budgets, identity
merging and quota-aware selection. Bagu: cached domain/leaf TESTS pools sampled
without replacement. No embeddings, lexical recall, implicit graph edges or LLM
calls are used here. Semantic resume-to-seed resolution is an upstream boundary.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import re
from typing import Any, Iterable, Mapping

RELATIONS = {
    "HAS_SUBTOPIC": ("Concept", "Concept"),
    "COVERS_TOPIC": ("Concept", "Concept"),
    "TESTS": ("Question", "Concept"),
    "REQUIRES": ("Question", "Concept"),
    "HAS_QUESTION": ("Scene", "Question"),
    "INVOLVES": ("Scene", "Concept"),
}


def _norm(value: str) -> str:
    return re.sub(r"\W+", "", str(value).casefold())


@dataclass(frozen=True)
class GraphRetrievalConfig:
    kg_candidate_limit: int = 300
    mg_candidate_limit: int = 200
    final_limit: int = 100
    kg_final_quota: int = 60
    mg_final_quota: int = 40
    max_depth: int = 2
    max_scene_seeds: int = 2
    max_concept_seeds: int = 6  # per route, including Scene -> INVOLVES roots
    max_children_per_node: int = 6
    max_nodes_per_branch: int = 20  # each root's first child and its descendants
    max_concept_nodes: int = 200  # shared unique-node budget for KG + MG
    questions_per_turn: int = 5
    max_question_checks: int = 10000  # includes duplicate/filtered hits
    min_scene_direct: int = 1
    max_paths_per_question: int = 12

    def __post_init__(self):
        for name, value in vars(self).items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        for name in ("questions_per_turn", "max_paths_per_question"):
            if getattr(self, name) == 0:
                raise ValueError(f"{name} must be positive")
        if self.final_limit and not (self.kg_final_quota + self.mg_final_quota):
            raise ValueError("at least one final quota weight is required")


@dataclass(frozen=True)
class ProjectQuery:
    """A single project's semantically resolved seeds; never merge projects here.

    IDs must be exact graph IDs. project_text/focus are trace context only; no
    substring matching is performed to invent seeds or rank question semantics.
    """
    project_id: str = "project"
    project_text: str = ""
    focus: str = ""
    scene_ids: tuple[str, ...] = ()
    concept_ids: tuple[str, ...] = ()
    company: str | None = None


@dataclass
class _Candidate:
    identity: str
    question_id: str
    source_question_ids: set[str] = field(default_factory=set)
    channels: set[str] = field(default_factory=set)
    direct_scene: bool = False
    depth: int | None = None
    paths: list[dict] = field(default_factory=list)
    path_keys: set[str] = field(default_factory=set)
    score: float = 0
    company_match: bool = False
    history_factor: float = 1


class GraphIndex:
    """Validated, read-only-by-convention snapshot with eligible adjacency lists.

    Explicit canonical_question_id (or duplicate_ids) merges verified duplicates.
    Identical short text alone is intentionally not sufficient to merge questions
    from different contexts. Draft state is controlled once when loading.
    """

    def __init__(self, nodes: Iterable[dict], edges: Iterable[dict], *,
                 include_drafts: bool = False, duplicate_ids: Mapping[str, str] | None = None):
        self.include_drafts = include_drafts
        self.nodes: dict[str, dict] = {}
        for node in nodes:
            if node["id"] in self.nodes:
                raise ValueError(f"duplicate node: {node['id']}")
            self.nodes[node["id"]] = node
        self.outgoing: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.incoming: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.edge_states: dict[tuple[str, str, str], str] = {}
        self.structural_children: dict[str, set[str]] = defaultdict(set)
        self.canonical: dict[str, str] = {}
        for edge in edges:
            src, rel, dst = edge["src_id"], edge["relation"], edge["dst_id"]
            if rel not in RELATIONS or src not in self.nodes or dst not in self.nodes:
                raise ValueError(f"unknown graph relation/endpoint: {src} {rel} {dst}")
            if (self.nodes[src]["node_type"], self.nodes[dst]["node_type"]) != RELATIONS[rel]:
                raise ValueError(f"invalid endpoint types for {rel}")
            if (src, rel, dst) in self.edge_states:
                raise ValueError("duplicate edge triple")
            self.edge_states[(src, rel, dst)] = edge.get("state", "active")
            if rel == "HAS_SUBTOPIC":
                self.structural_children[src].add(dst)
            allowed_states = {"active", "draft"} if include_drafts else {"active"}
            if edge.get("state", "active") not in allowed_states or not self.eligible(src) or not self.eligible(dst):
                continue
            self.outgoing[(src, rel)].append(dst)
            self.incoming[(dst, rel)].append(src)
        # Validate full structural hierarchy, not only the filtered active view.
        indegree = {nid: 0 for nid, n in self.nodes.items() if n["node_type"] == "Concept"}
        for children in self.structural_children.values():
            for child in children:
                indegree[child] += 1
        frontier = [nid for nid, degree in indegree.items() if not degree]
        count = 0
        while frontier:
            node_id = frontier.pop(); count += 1
            for child in self.structural_children.get(node_id, ()):
                indegree[child] -= 1
                if not indegree[child]: frontier.append(child)
        if count != len(indegree):
            raise ValueError("knowledge hierarchy contains a cycle")
        for table in (self.outgoing, self.incoming):
            for key in table: table[key] = sorted(table[key])
        redirects = dict(duplicate_ids or {})
        for nid, node in self.nodes.items():
            target = node.get("properties", {}).get("canonical_question_id")
            if target:
                if nid in redirects and redirects[nid] != target:
                    raise ValueError(f"conflicting canonical identity: {nid}")
                redirects[nid] = target
        for nid in redirects:
            if nid not in self.nodes or self.nodes[nid]["node_type"] != "Question":
                raise ValueError(f"unknown duplicate source question: {nid}")
        for nid, node in self.nodes.items():
            if node["node_type"] != "Question": continue
            current = nid; seen = set()
            while current in redirects and redirects[current] != current:
                if current in seen: raise ValueError("duplicate identity cycle")
                seen.add(current); current = redirects[current]
            if current in self.nodes and self.nodes[current]["node_type"] != "Question":
                raise ValueError("canonical identity cannot be a non-question node")
            self.canonical[nid] = current
        self.question_groups: dict[str, set[str]] = defaultdict(set)
        for qid, identity in self.canonical.items():
            self.question_groups[identity].add(qid)
        self._bagu_cache: dict[tuple[str, ...], tuple[tuple[str, ...], dict[str, tuple[str, ...]]]] = {}
        self.general_question_ids = tuple(nid for nid, n in self.nodes.items()
                                          if n["node_type"] == "Question" and self.eligible(nid)
                                          and n.get("properties", {}).get("general_pool_kind") == "behavioral")

    @classmethod
    def from_directory(cls, directory: str | Path, *, include_drafts: bool = False,
                       duplicate_ids: Mapping[str, str] | None = None):
        directory = Path(directory)
        def rows(name):
            with (directory / name).open(encoding="utf-8") as handle:
                return [json.loads(line) for line in handle if line.strip()]
        return cls(rows("nodes.jsonl"), rows("edges.jsonl"),
                   include_drafts=include_drafts, duplicate_ids=duplicate_ids)

    def eligible(self, node_id: str) -> bool:
        node = self.nodes.get(node_id)
        states = {"active", "draft"} if self.include_drafts else {"active"}
        return bool(node and node.get("state", "active") in states)

    def is_leaf(self, node_id: str) -> bool:
        return not (self.structural_children.get(node_id) or
                    self.nodes[node_id].get("properties", {}).get("structural_has_children"))

    def typed(self, node_id: str, kind: str) -> bool:
        return self.eligible(node_id) and self.nodes[node_id]["node_type"] == kind

    def neighbors(self, node_id: str, relation: str, *, reverse=False) -> list[str]:
        return list((self.incoming if reverse else self.outgoing).get((node_id, relation), ()))

    def identity(self, question_id: str) -> str:
        return self.canonical.get(question_id, question_id)

    def bagu_pool(self, roots: Iterable[str]):
        """Cache domain reachability; sampling calls never do project BFS."""
        key = tuple(sorted(set(roots)))
        if key not in self._bagu_cache:
            seen = set(); pending = list(key); leaves = []; questions = defaultdict(set)
            while pending:
                node_id = pending.pop()
                if node_id in seen or not self.typed(node_id, "Concept"): continue
                seen.add(node_id)
                pending.extend(self.outgoing.get((node_id, "HAS_SUBTOPIC"), ()))
                # A parent with draft children is not a real leaf.
                if not self.is_leaf(node_id): continue
                leaves.append(node_id)
                for qid in self.incoming.get((node_id, "TESTS"), ()):
                    props = self.nodes[qid].get("properties", {})
                    category = props.get("category") or (props.get("original_tags") or {}).get("category")
                    tags = props.get("tags") or []
                    if category == "bagu" or "bagu" in tags or "八股" in tags:
                        questions[qid].add(node_id)
            self._bagu_cache[key] = (tuple(sorted(leaves)), {qid: tuple(sorted(v)) for qid, v in sorted(questions.items())})
        return self._bagu_cache[key]


class GraphRetriever:
    def __init__(self, graph: GraphIndex):
        self.graph = graph

    def _seeds(self, values, kind, cap):
        values = list(dict.fromkeys(values))
        unknown = [nid for nid in values if nid not in self.graph.nodes or self.graph.nodes[nid]["node_type"] != kind]
        if unknown: raise ValueError(f"invalid {kind} seed IDs: {unknown}")
        eligible = [nid for nid in values if self.graph.typed(nid, kind)]
        return eligible[:cap], [nid for nid in values if nid not in eligible[:cap]]

    def _path(self, channel, kind, branch, depth, steps):
        return {"channel": channel, "kind": kind, "branch_id": branch,
                "concept_depth": depth, "steps": [
                    {"src_id": a, "relation": r, "dst_id": b, "state": self.graph.edge_states[(a, r, b)]}
                    for a, r, b in steps]}

    @staticmethod
    def _round_robin(groups, batch):
        # Each node emits only a small batch before another node gets its turn.
        groups = [iter(group) for group in groups]
        while groups:
            remaining = []
            for group in groups:
                for _ in range(batch):
                    try: yield next(group)
                    except StopIteration: break
                else:
                    remaining.append(group); continue
            groups = remaining

    def _concept_events(self, roots, channel, cfg, rng, trace, expanded):
        # (node, depth, seed, first-child branch, path). BFS, never reverse INVOLVES.
        frontier = [(nid, 0, nid, f"{channel}:{nid}:direct", steps) for nid, steps in roots]
        seen = set(); branch_nodes = defaultdict(set); deferred = defaultdict(list)
        while frontier:
            rng.shuffle(frontier)
            next_frontier = []; groups = defaultdict(list)
            for node_id, depth, seed, branch, steps in frontier:
                visit_key = (seed, node_id)
                if visit_key in seen or not self.graph.typed(node_id, "Concept"): continue
                if depth and len(branch_nodes[branch]) >= cfg.max_nodes_per_branch:
                    trace["branch_node_limit_hits"] += 1; continue
                if node_id not in expanded and len(expanded) >= cfg.max_concept_nodes:
                    trace["concept_node_limit_hits"] += 1; continue
                seen.add(visit_key); branch_nodes[branch].add(node_id); expanded.add(node_id)
                trace[f"{channel}_concept_visits"] += 1
                qids = self.graph.neighbors(node_id, "TESTS", reverse=True)
                rng.shuffle(qids)
                path = self._path(channel, "knowledge", branch, depth, steps)
                def events(qids, path=path, node_id=node_id):
                    for qid in qids:
                        yield qid, {**path, "steps": path["steps"] + [
                            {"src_id": qid, "relation": "TESTS", "dst_id": node_id,
                             "state": self.graph.edge_states[(qid, "TESTS", node_id)]}]}
                # First take one batch per node, then expand the next concept
                # layer. Hundreds of parent questions must not starve children.
                groups[branch].append(events(qids[:cfg.questions_per_turn]))
                if len(qids) > cfg.questions_per_turn:
                    deferred[branch].append(events(qids[cfg.questions_per_turn:]))
                if depth >= cfg.max_depth:
                    if self.graph.outgoing.get((node_id, "HAS_SUBTOPIC")):
                        trace["depth_limit_hits"] += 1
                    continue
                children = self.graph.neighbors(node_id, "HAS_SUBTOPIC"); rng.shuffle(children)
                if len(children) > cfg.max_children_per_node: trace["child_limit_hits"] += 1
                for child in children[:cfg.max_children_per_node]:
                    child_branch = f"{channel}:{seed}:{child}" if depth == 0 else branch
                    next_frontier.append((child, depth + 1, seed, child_branch,
                                          steps + [(node_id, "HAS_SUBTOPIC", child)]))
            # All nodes at this depth are served before any deeper node.
            branch_streams = [self._round_robin(streams, cfg.questions_per_turn) for streams in groups.values()]
            yield from self._round_robin(branch_streams, cfg.questions_per_turn)
            frontier = next_frontier
        # Unused candidate budget returns to remaining questions of visited
        # nodes; a narrow or leaf-only domain can still fill its candidate pool.
        yield from self._round_robin(
            [self._round_robin(streams, cfg.questions_per_turn) for streams in deferred.values()],
            cfg.questions_per_turn,
        )

    def _kg_events(self, scenes, cfg, rng, trace, expanded):
        groups = []
        for scene in scenes:
            qids = self.graph.neighbors(scene, "HAS_QUESTION"); rng.shuffle(qids)
            # Bind scene in a helper; generators otherwise capture the last loop value.
            def events(scene=scene, qids=qids):
                for qid in qids:
                    yield qid, self._path("kg", "scene_direct", scene, 0, [(scene, "HAS_QUESTION", qid)])
            groups.append(events())
        yield from self._round_robin(groups, cfg.questions_per_turn)
        roots = []
        # Scene roots get turns when choosing their bounded knowledge seeds too.
        lists = []
        for scene in scenes:
            ids = self.graph.neighbors(scene, "INVOLVES"); rng.shuffle(ids)
            lists.append([(cid, [(scene, "INVOLVES", cid)]) for cid in ids])
        seen = set()
        for cid, steps in self._round_robin(lists, 1):
            if cid in seen: continue
            seen.add(cid)
            if len(roots) < cfg.max_concept_seeds: roots.append((cid, steps))
            else: trace["kg_knowledge_seed_limit_hits"] += 1
        yield from self._concept_events(roots, "kg", cfg, rng, trace, expanded)

    @staticmethod
    def _timestamp(value):
        if isinstance(value, (int, float)): return float(value)
        if isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if dt.tzinfo is None: return None  # reject ambiguous local wall times
                return dt.timestamp()
            except ValueError: return None
        return None

    def _history_factor(self, ids, identity, history, now):
        factors = [1.0]
        for qid in set(ids) | {identity} | self.graph.question_groups.get(identity, set()):
            event = history.get(qid) or {}
            if not isinstance(event, Mapping): continue
            # Merely recalled candidates do NOT get a usage penalty.
            for key, maximum in (("last_asked_at", .45), ("last_selected_at", .20)):
                timestamp = self._timestamp(event.get(key))
                if timestamp is not None:
                    age_days = max(0, now - timestamp) / 86400
                    factors.append(1 - maximum * max(0, 1 - age_days / 7))
        return min(factors)

    def _blocked(self, qid, asked, asked_norms, excluded):
        node = self.graph.nodes[qid]; props = node.get("properties", {})
        identity = self.graph.identity(qid)
        return (identity in asked or identity in excluded or _norm(node["name"]) in asked_norms
                or bool(props.get("disabled") or props.get("withdrawn")))

    def _score(self, item, company, history, now):
        companies = set()
        for qid in item.source_question_ids:
            props = self.graph.nodes[qid].get("properties", {})
            if props.get("company"): companies.add(str(props["company"]))
            companies.update(str(x) for x in (props.get("companies") or []))
        item.company_match = bool(company and company in companies)
        item.history_factor = self._history_factor(item.source_question_ids, item.identity, history, now)
        base = 100 if item.direct_scene else 80 - 7 * (item.depth or 0)
        if len(item.channels) == 2: base += 4  # bounded, not per-path accumulation
        if item.company_match: base += 8
        item.score = round(base * item.history_factor, 6)

    def project_retrieve(self, query: ProjectQuery, *, config: GraphRetrievalConfig | None = None,
                         seed: int | None = None, asked_question_ids: Iterable[str] = (),
                         asked_question_norms: Iterable[str] = (), exclude_question_ids: Iterable[str] = (),
                         history: Mapping[str, Mapping] | None = None, now: datetime | None = None):
        cfg = config or GraphRetrievalConfig(); rng = random.Random(seed)
        scenes, ignored_scenes = self._seeds(query.scene_ids, "Scene", cfg.max_scene_seeds)
        concepts, ignored_concepts = self._seeds(query.concept_ids, "Concept", cfg.max_concept_seeds)
        asked = {self.graph.identity(qid) for qid in asked_question_ids}
        excluded = {self.graph.identity(qid) for qid in exclude_question_ids}
        # Explicit caller exclusions apply to the whole verified duplicate group.
        asked_norms = {_norm(s) for s in asked_question_norms if s}
        for qid, node in self.graph.nodes.items():
            if node["node_type"] == "Question" and _norm(node["name"]) in asked_norms:
                asked.add(self.graph.identity(qid))
        trace = Counter(); expanded = set(); pool: dict[str, _Candidate] = {}
        limits = {"kg": cfg.kg_candidate_limit, "mg": cfg.mg_candidate_limit}
        budget = sum(limits.values())
        live = {"kg": bool(scenes) and limits["kg"] > 0,
                "mg": bool(concepts) and limits["mg"] > 0}
        streams = {
            "kg": iter(self._kg_events(scenes, cfg, rng, trace, expanded)),
            "mg": iter(self._concept_events([(cid, []) for cid in concepts], "mg", cfg, rng, trace, expanded)),
        }
        credits = Counter(); targets = dict(limits)
        if live["mg"] and not live["kg"]: targets["mg"] = budget
        if live["kg"] and not live["mg"]: targets["kg"] = budget
        while len(pool) < budget and trace["question_checks"] < cfg.max_question_checks:
            active = [lane for lane in ("kg", "mg") if live[lane] and credits[lane] < targets[lane]]
            if not active:
                remaining_lanes = [lane for lane in ("kg", "mg") if live[lane]]
                if not remaining_lanes: break
                # Paused routes resume with recycled capacity. Overlap isn't a cost.
                extra = budget - len(pool)
                for i, lane in enumerate(remaining_lanes):
                    targets[lane] = credits[lane] + extra // len(remaining_lanes) + (i < extra % len(remaining_lanes))
                trace["quota_reallocations"] += 1
                continue
            for lane in active:
                for _ in range(cfg.questions_per_turn):
                    if len(pool) >= budget or trace["question_checks"] >= cfg.max_question_checks: break
                    if credits[lane] >= targets[lane]: break
                    try: qid, path = next(streams[lane])
                    except StopIteration:
                        live[lane] = False; break
                    trace["question_checks"] += 1
                    if self._blocked(qid, asked, asked_norms, excluded):
                        trace["filtered_hits"] += 1; continue
                    identity = self.graph.identity(qid)
                    if identity not in pool:
                        pool[identity] = _Candidate(identity, qid); credits[lane] += 1
                    else: trace["duplicate_hits"] += 1
                    item = pool[identity]; item.source_question_ids.add(qid); item.channels.add(lane)
                    item.direct_scene |= path["kind"] == "scene_direct"
                    if path["kind"] == "knowledge":
                        item.depth = path["concept_depth"] if item.depth is None else min(item.depth, path["concept_depth"])
                    path_key = json.dumps(path, sort_keys=True)
                    if path_key not in item.path_keys:
                        item.path_keys.add(path_key)
                        if len(item.paths) < cfg.max_paths_per_question: item.paths.append(path)
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None: raise ValueError("now must have an explicit timezone")
        for item in pool.values(): self._score(item, query.company, history or {}, now.timestamp())
        ranked = list(pool.values()); rng.shuffle(ranked); ranked.sort(key=lambda x: x.score, reverse=True)
        selected, assignments, targets = self._select(ranked, cfg, bool(scenes))
        selected_ids = {item.identity for item in selected}
        stop = ("candidate_limit" if len(pool) >= budget else "question_check_limit"
                if trace["question_checks"] >= cfg.max_question_checks else "routes_exhausted")
        return {"questions": [self._result(item, assignments.get(item.identity)) for item in selected],
                "candidates": [self._result(item, assignments.get(item.identity)) for item in ranked],
                "meta": {"project_id": query.project_id, "seed": seed,
                         "scene_seed_ids": scenes, "concept_seed_ids": concepts,
                         "ignored_scene_ids": ignored_scenes, "ignored_concept_ids": ignored_concepts,
                         "unique_candidates": len(pool), "selected_count": len(selected_ids),
                         "admitted_by_lane": dict(credits), "assigned_by_lane": dict(Counter(assignments.values())),
                         "final_quota_targets": targets, "unique_concepts_expanded": len(expanded),
                         "stop_reason": stop, "trace": dict(trace), "include_drafts": self.graph.include_drafts,
                         "ranking": "graph_structure_company_history_v1; no semantic reranker"}}

    @staticmethod
    def _select(ranked, cfg, has_scene):
        total = cfg.final_limit
        weight = cfg.kg_final_quota + cfg.mg_final_quota
        kg = int(total * cfg.kg_final_quota / weight) if has_scene and weight else 0
        mg = total - kg
        if has_scene and total >= 2 and cfg.kg_final_quota and cfg.mg_final_quota:
            kg = max(1, min(total - 1, kg)); mg = total - kg
        direct = [item for item in ranked if item.direct_scene][:min(cfg.min_scene_direct, total)] if has_scene else []
        if len(direct) > kg: kg = len(direct); mg = total - kg
        targets = {"kg": kg, "mg": mg}; buckets = {"kg": [], "mg": []}; assignments = {}; fixed = set()
        for item in direct:
            buckets["kg"].append(item); assignments[item.identity] = "kg"; fixed.add(item.identity)
        # A small two-lane matching: move overlapping items between quota slots
        # instead of counting one question as satisfying both reservations.
        for item in ranked:
            if item.identity in assignments: continue
            for lane in ("kg", "mg"):
                if lane not in item.channels: continue
                if len(buckets[lane]) < targets[lane]:
                    buckets[lane].append(item); assignments[item.identity] = lane; break
                other = "mg" if lane == "kg" else "kg"
                if len(buckets[other]) >= targets[other]: continue
                movable = next((x for x in reversed(buckets[lane]) if x.identity not in fixed and other in x.channels), None)
                if movable:
                    buckets[lane].remove(movable); buckets[other].append(movable); assignments[movable.identity] = other
                    buckets[lane].append(item); assignments[item.identity] = lane; break
        # Exhausted-route quota returns to available candidates.
        for item in ranked:
            if len(assignments) >= total: break
            if item.identity not in assignments:
                lane = "kg" if item.direct_scene else ("mg" if "mg" in item.channels else "kg")
                assignments[item.identity] = lane
        return [item for item in ranked if item.identity in assignments], assignments, targets

    def _result(self, item, assigned_lane=None):
        q = self.graph.nodes[item.question_id]; props = q.get("properties", {})
        return {"question_id": item.question_id, "canonical_question_id": item.identity,
                "source_question_ids": sorted(item.source_question_ids), "question": q["name"],
                "normalized_question": props.get("normalized_question"), "answer": props.get("answer"),
                "company": props.get("company"), "companies": props.get("companies", []),
                "roles": props.get("roles", []), "era": props.get("era"),
                "context_refs": props.get("context_refs", []), "original_tags": props.get("original_tags", {}),
                "source_locator": props.get("source_locator"), "source_file": props.get("source_file"),
                "state": q.get("state", "active"), "channels": sorted(item.channels),
                "direct_scene": item.direct_scene, "concept_depth": item.depth,
                "paths": item.paths, "path_count": len(item.path_keys),
                "score": item.score, "company_match": item.company_match,
                "history_factor": item.history_factor, "assigned_lane": assigned_lane}

    def bagu_retrieve(self, *, domain_concept_ids: Iterable[str], count: int, seed: int | None = None,
                      asked_question_ids: Iterable[str] = (), asked_question_norms: Iterable[str] = (),
                      exclude_question_ids: Iterable[str] = ()):
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("count must be a non-negative integer")
        domains = list(dict.fromkeys(domain_concept_ids))
        roots, ignored = self._seeds(domains, "Concept", len(domains))
        leaves, raw = self.graph.bagu_pool(roots)
        asked = {self.graph.identity(x) for x in asked_question_ids}
        excluded = {self.graph.identity(x) for x in exclude_question_ids}
        norms = {_norm(x) for x in asked_question_norms if x}
        for qid in raw:
            if _norm(self.graph.nodes[qid]["name"]) in norms: asked.add(self.graph.identity(qid))
        pool = {}; leaf_hits = defaultdict(set)
        for qid, linked_leaves in raw.items():
            if self._blocked(qid, asked, norms, excluded): continue
            identity = self.graph.identity(qid)
            if identity not in pool: pool[identity] = _Candidate(identity, qid)
            pool[identity].source_question_ids.add(qid); leaf_hits[identity].update(linked_leaves)
        rng = random.Random(seed)
        chosen = rng.sample(list(pool.values()), min(count, len(pool)))
        questions = []
        for item in chosen:
            result = self._result(item); result.update(leaf_concept_ids=sorted(leaf_hits[item.identity]), selection="random_leaf_bagu")
            questions.append(result)
        return {"questions": questions,
                "meta": {"seed": seed, "domain_seed_ids": roots, "ignored_domain_ids": ignored,
                         "leaf_count": len(leaves), "pool_count": len(pool), "selected_count": len(chosen),
                         "include_drafts": self.graph.include_drafts}}
