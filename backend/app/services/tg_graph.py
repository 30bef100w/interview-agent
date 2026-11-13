"""轻量 Trace Graph（TG）存储与有向召回。

TG 的节点是可复用的并列追问模式：intent / problem / when。
生成拷打链只负责挂载节点；只有面试运行时自然触发的有序节点，才创建
OBSERVED_NEXT 有向边。文件存储便于开发环境直接查看，后续可无缝替换为图数据库。
"""
from __future__ import annotations

from collections import defaultdict, deque
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from threading import RLock
from typing import Iterable, Mapping

from app.config import settings


def _norm(value: object) -> str:
    return re.sub(r"\W+", "", str(value or "").casefold())


def _path() -> Path:
    raw = str(getattr(settings, "tg_graph_path", "data/tg_graph.json") or "").strip()
    configured = Path(raw)
    if configured.is_absolute():
        return configured
    return Path(__file__).resolve().parents[2] / configured


class TraceGraphStore:
    """JSON-backed TG store with conservative node reuse and bounded forward search."""

    _lock = RLock()

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else _path()

    def _empty(self) -> dict:
        return {"schema_version": 2, "nodes": {}, "edges": {}, "runs": []}

    def _load(self) -> dict:
        if not self.path.exists():
            return self._empty()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self._empty()
        if not isinstance(value, dict):
            return self._empty()
        try:
            value["schema_version"] = max(2, int(value.get("schema_version") or 1))
        except (TypeError, ValueError):
            value["schema_version"] = 2
        value.setdefault("nodes", {})
        value.setdefault("edges", {})
        value.setdefault("runs", [])
        # v1 文件可以继续读取；这些字段让命中率按“会话”统计，避免同一场
        # 面试重复展示/触发把分母和分子放大。
        for node in value["nodes"].values():
            if isinstance(node, dict):
                node.setdefault("trigger_session_ids", [])
                node.setdefault("presented_session_ids", [])
        for edge in value["edges"].values():
            if isinstance(edge, dict):
                edge.setdefault("session_ids", [])
        return value

    def _save(self, graph: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".tg-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(graph, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    @staticmethod
    def _probe_key(intent: str, problem: str, when: str) -> str:
        raw = "|".join((_norm(intent), _norm(problem), _norm(when)))
        return "probe:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _clean_probe(raw: Mapping) -> dict | None:
        intent = str(raw.get("intent") or "").strip()
        problem = str(raw.get("problem") or raw.get("question") or "").strip()
        when = str(raw.get("when") or raw.get("trigger") or "").strip()
        if not intent or not problem or not when:
            return None
        return {
            "intent": intent[:240],
            "problem": problem[:600],
            "when": when[:300],
            "source_question_ids": sorted({str(x) for x in (raw.get("source_question_ids") or []) if str(x).strip()}),
        }

    @staticmethod
    def _edge_key(src: str, relation: str, dst: str) -> str:
        return "edge:" + hashlib.sha256(f"{src}|{relation}|{dst}".encode()).hexdigest()[:24]

    def ingest_chain(
        self,
        chain: Mapping,
        *,
        scene_anchor_ids: Iterable[str] = (),
        concept_anchor_ids: Iterable[str] = (),
        company_scope: str | None = None,
        session_id: int | str | None = None,
    ) -> dict:
        """简单筛选后直接写入：同义三元组复用节点，初始不建立节点间顺序边。"""
        project = str(chain.get("project") or "").strip()
        clean = []
        with self._lock:
            graph = self._load()
            for raw in chain.get("chains") or []:
                if not isinstance(raw, Mapping):
                    continue
                probe = self._clean_probe(raw)
                if probe is None:
                    continue
                probe_id = self._probe_key(probe["intent"], probe["problem"], probe["when"])
                node = graph["nodes"].setdefault(
                    probe_id,
                    {
                        "id": probe_id,
                        "node_type": "ProbeNode",
                        **probe,
                        "hit_count": 0,
                        "presented_count": 0,
                        "source_chain_count": 0,
                        "company_scopes": [],
                        "trigger_session_ids": [],
                        "presented_session_ids": [],
                    },
                )
                node["source_question_ids"] = sorted(
                    set(node.get("source_question_ids") or []) | set(probe["source_question_ids"])
                )
                node["source_chain_count"] = int(node.get("source_chain_count", 0)) + 1
                if company_scope:
                    scopes = set(node.get("company_scopes") or [])
                    scopes.add(str(company_scope))
                    node["company_scopes"] = sorted(scopes)
                for anchor_type, anchors in (("scene", scene_anchor_ids), ("concept", concept_anchor_ids)):
                    for anchor in sorted({str(x) for x in anchors if str(x).strip()}):
                        edge_id = self._edge_key(anchor, "MOUNTS_PROBE", probe_id)
                        graph["edges"].setdefault(
                            edge_id,
                            {"id": edge_id, "src_id": anchor, "relation": "MOUNTS_PROBE", "dst_id": probe_id,
                             "anchor_type": anchor_type, "observed_count": 0},
                        )
                item = dict(probe)
                item["probe_id"] = probe_id
                clean.append(item)
            if clean:
                run_id = f"generated:{session_id or 'unknown'}:{hashlib.sha1((project + json.dumps(clean, ensure_ascii=False, sort_keys=True)).encode()).hexdigest()[:16]}"
                graph["runs"].append({"run_id": run_id, "kind": "generated", "session_id": session_id,
                                      "project": project, "probe_ids": [x["probe_id"] for x in clean]})
                graph["runs"] = graph["runs"][-20000:]
                self._save(graph)
        return {"project": project, "nodes": clean}

    def record_trigger(
        self,
        probe_id: str,
        *,
        session_id: int | str | None = None,
        previous_probe_id: str | None = None,
        scene_anchor_ids: Iterable[str] = (),
        concept_anchor_ids: Iterable[str] = (),
    ) -> bool:
        """记录一次自然触发，并按本场实际顺序创建相邻 OBSERVED_NEXT 边。

        一个节点在同一场面试中重复被模型判定命中时只计一次，避免模型重试
        或重复追问把 TG 的命中率虚高。方法保持幂等，写入失败也不会抛到面试主链。
        """
        with self._lock:
            graph = self._load()
            node = graph["nodes"].get(str(probe_id))
            if not node:
                return False
            session_key = str(session_id) if session_id is not None else None
            observed_sessions = node.setdefault("trigger_session_ids", [])
            already_observed = session_key is not None and session_key in observed_sessions
            if not already_observed:
                node["hit_count"] = int(node.get("hit_count", 0)) + 1
                if session_key is not None:
                    observed_sessions.append(session_key)
                    del observed_sessions[:-5000]
                node["last_triggered_at"] = time.time()
            if previous_probe_id and previous_probe_id != probe_id and previous_probe_id in graph["nodes"]:
                edge_id = self._edge_key(previous_probe_id, "OBSERVED_NEXT", probe_id)
                edge = graph["edges"].setdefault(
                    edge_id,
                    {"id": edge_id, "src_id": previous_probe_id, "relation": "OBSERVED_NEXT", "dst_id": probe_id,
                     "observed_count": 0, "session_ids": []},
                )
                sessions = edge.setdefault("session_ids", [])
                edge_session_key = session_key
                if edge_session_key is None or edge_session_key not in {str(x) for x in sessions}:
                    edge["observed_count"] = int(edge.get("observed_count", 0)) + 1
                if edge_session_key is not None and edge_session_key not in {str(x) for x in sessions}:
                    sessions.append(edge_session_key)
                    del sessions[:-5000]
            if not already_observed:
                run = {"run_id": f"observed:{session_id or 'unknown'}:{len(graph['runs'])}", "kind": "observed",
                       "session_id": session_id, "probe_ids": [str(probe_id)]}
                graph["runs"].append(run)
                graph["runs"] = graph["runs"][-20000:]
            self._save(graph)
        return True

    def retrieve(
        self,
        *,
        scene_anchor_ids: Iterable[str] = (),
        concept_anchor_ids: Iterable[str] = (),
        company_scope: str | None = None,
        max_depth: int = 2,
        max_nodes: int = 12,
        session_id: int | str | None = None,
    ) -> dict:
        """从场景/MG知识点挂载节点出发，只沿 OBSERVED_NEXT 正向探索。"""
        anchors = [str(x) for x in list(scene_anchor_ids) + list(concept_anchor_ids) if str(x).strip()]
        max_depth, max_nodes = max(0, int(max_depth)), max(1, int(max_nodes))
        with self._lock:
            graph = self._load()
        mounted: dict[str, list[str]] = defaultdict(list)
        outgoing: dict[str, list[dict]] = defaultdict(list)
        for edge in graph["edges"].values():
            if edge.get("relation") == "MOUNTS_PROBE" and edge.get("src_id") in anchors:
                mounted[edge["src_id"]].append(edge["dst_id"])
            elif edge.get("relation") == "OBSERVED_NEXT":
                outgoing[edge["src_id"]].append(edge)
        mounted_probe_ids = list(dict.fromkeys(sum(mounted.values(), [])))
        mounted_set = set(mounted_probe_ids)
        # 一个节点既可能被锚点直接挂载，也可能是另一节点的后继。若它已有
        # 同一锚点范围内的真实前驱，从前驱开始即可，避免同时返回 B 和 A→B
        # 两条重叠路径，把顺序打散。
        downstream = {
            str(item.get("dst_id"))
            for edge_list in outgoing.values()
            for item in edge_list
            if str(item.get("src_id")) in mounted_set
            and str(item.get("dst_id")) in mounted_set
        }
        roots = [probe for probe in mounted_probe_ids if probe not in downstream]
        if not roots:
            roots = mounted_probe_ids
        queue = deque((probe, 0, [probe]) for probe in roots)
        seen: set[str] = set(); seen_paths: set[tuple[str, ...]] = set(); paths = []
        while queue and len(seen) < max_nodes:
            probe_id, depth, path = queue.popleft()
            path_key = tuple(path)
            if path_key in seen_paths or probe_id not in graph["nodes"]:
                continue
            seen_paths.add(path_key)
            seen.add(probe_id)
            node = graph["nodes"][probe_id]
            hit = int(node.get("hit_count", 0)); presented = int(node.get("presented_count", 0))
            # 只有经过足够曝光仍零命中的节点才视为冷节点；新节点和低样本
            # 节点继续保留，避免 TG 冷启动时把候选全部过滤掉。
            if presented >= 5 and hit == 0:
                continue
            paths.append({"probe_id": probe_id, "node": node, "path": path,
                          "hit_rate": round(hit / presented, 4) if presented else 0.0})
            if depth >= max_depth:
                continue
            next_edges = sorted(outgoing.get(probe_id, []), key=lambda e: int(e.get("observed_count", 0)), reverse=True)
            for edge in next_edges:
                target = edge["dst_id"]
                if target not in path:
                    queue.append((target, depth + 1, path + [target]))
        # 召回给 Agent 时保留有向路径顺序；命中率只用于路径/节点的候选排序，
        # 不能把一条真实路径按分数打散成无序列表。
        paths.sort(key=lambda x: (len(x["path"]), -x["hit_rate"], -int(x["node"].get("hit_count", 0))))
        # 只把不能再向前扩展的路径作为“拷打链”返回；前缀节点仍保留在
        # nodes 中供 Agent 选择，避免把 A、A→B、A→B→C 重复展示三遍。
        path_tuples = [tuple(x["path"]) for x in paths]
        maximal = [
            item
            for item in paths
            if not any(
                len(other) > len(item["path"])
                and other[: len(item["path"])] == tuple(item["path"])
                for other in path_tuples
            )
        ]
        paths = maximal or paths
        chains: list[list[dict]] = []
        for item in paths:
            chain = []
            for node_id in item["path"]:
                node = graph["nodes"].get(node_id)
                if node is not None:
                    chain.append(node)
            if chain:
                chains.append(chain)
        ordered_nodes = []
        seen_nodes: set[str] = set()
        for chain in chains:
            for node in chain:
                if node["id"] not in seen_nodes:
                    seen_nodes.add(node["id"])
                    ordered_nodes.append(node)
        if company_scope:
            ordered_nodes.sort(
                key=lambda node: (
                    0 if str(company_scope) in set(node.get("company_scopes") or []) else 1,
                    -int(node.get("hit_count", 0)),
                )
            )
        # 只有真正返回给 Agent 的节点才计入 presented_count，而不是生成链时
        # 就算曝光；这样 hit_rate 的分母对应实际可用的面试场次。
        if ordered_nodes:
            with self._lock:
                latest = self._load()
                for node in ordered_nodes:
                    stored = latest["nodes"].get(node["id"])
                    if stored is not None:
                        presented_sessions = stored.setdefault("presented_session_ids", [])
                        session_key = str(session_id) if session_id is not None else None
                        if session_key is None or session_key not in presented_sessions:
                            stored["presented_count"] = int(stored.get("presented_count", 0)) + 1
                            if session_key is not None:
                                presented_sessions.append(session_key)
                                del presented_sessions[:-5000]
                        node["presented_count"] = stored["presented_count"]
                self._save(latest)
        return {"anchors": anchors, "nodes": ordered_nodes, "paths": paths, "chains": chains}

    def stats(self) -> dict:
        """返回 TG 的可审计质量摘要，不修改图，也不把新节点误判为低质量。"""
        with self._lock:
            graph = self._load()
        nodes = [n for n in graph.get("nodes", {}).values() if isinstance(n, dict)]
        edges = [e for e in graph.get("edges", {}).values() if isinstance(e, dict)]
        observed_edges = [e for e in edges if e.get("relation") == "OBSERVED_NEXT"]
        new_nodes = [n for n in nodes if int(n.get("presented_count", 0)) < 3]
        proven_nodes = [
            n for n in nodes
            if int(n.get("presented_count", 0)) >= 3
            and int(n.get("hit_count", 0)) > 0
        ]
        cold_nodes = [
            n for n in nodes
            if int(n.get("presented_count", 0)) >= 5
            and int(n.get("hit_count", 0)) == 0
        ]
        total_presented = sum(int(n.get("presented_count", 0)) for n in nodes)
        total_hits = sum(int(n.get("hit_count", 0)) for n in nodes)
        return {
            "schema_version": int(graph.get("schema_version", 1)),
            "nodes": len(nodes),
            "edges": len(edges),
            "observed_edges": len(observed_edges),
            "runs": len(graph.get("runs") or []),
            "total_presented": total_presented,
            "total_hits": total_hits,
            "new_nodes": len(new_nodes),
            "proven_nodes": len(proven_nodes),
            "cold_nodes": len(cold_nodes),
            "coverage": round(total_hits / total_presented, 4) if total_presented else 0.0,
        }
