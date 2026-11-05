#!/usr/bin/env python3
"""Build reproducible offline MG/KG views from annotation-contract v1.

No text matching, ancestry guessing, scene co-occurrence or semantic question
deduplication occurs here. MG and KG are views of one shared entity graph.
Draft entities and relations stay draft; excluded source rows are archived.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BATCH = ROOT / "data/semantic_annotations/2026-11-05-complete-s0001-s9000"
DEFAULT_INDEX = ROOT / "data/index_review/2026-11-03"
RELATIONS = {
    "HAS_SUBTOPIC": ("Concept", "Concept"),
    "COVERS_TOPIC": ("Concept", "Concept"),
    "TESTS": ("Question", "Concept"),
    "REQUIRES": ("Question", "Concept"),
    "HAS_QUESTION": ("Scene", "Question"),
    "INVOLVES": ("Scene", "Concept"),
}
MG_RELATIONS = {"HAS_SUBTOPIC", "COVERS_TOPIC", "TESTS", "REQUIRES"}
KG_RELATIONS = {"HAS_QUESTION", "INVOLVES"}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_jsonl(path):
    with Path(path).open(encoding="utf-8-sig") as handle:
        for line_no, line in enumerate(handle, 1):
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"{path}:{line_no}: expected object")
                yield row


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def save_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def unique(rows, key, label):
    result = {}
    for row in rows:
        value = row[key]
        if value in result:
            raise ValueError(f"duplicate {label}: {value}")
        result[value] = row
    return result


class Resolver:
    """Only explicit identity decisions apply; new:* is not stripped heuristically."""

    def __init__(self, aliases):
        self.aliases = aliases
        for key in aliases:
            self(key)

    def __call__(self, value):
        seen = set()
        current = value
        while current in self.aliases and self.aliases[current] != current:
            if current in seen:
                raise ValueError(f"alias cycle: {value}")
            seen.add(current)
            current = self.aliases[current]
        return current


class Graph:
    def __init__(self):
        self.nodes = {}
        self.edges = {}
        self.evidence_seen = defaultdict(set)

    def node(self, node_id, node_type, name, state="active", **properties):
        if node_id in self.nodes:
            raise ValueError(f"duplicate node: {node_id}")
        self.nodes[node_id] = {
            "id": node_id, "node_type": node_type, "name": name,
            "state": state, "schema_version": 2, "properties": properties,
        }

    def edge(self, src, relation, dst, evidence, state=None):
        if src not in self.nodes or dst not in self.nodes:
            raise ValueError(f"unknown endpoint: {src} -{relation}-> {dst}")
        actual = (self.nodes[src]["node_type"], self.nodes[dst]["node_type"])
        if RELATIONS.get(relation) != actual:
            raise ValueError(f"invalid endpoint types: {relation}: {actual}")
        # Semantic review of a question does not approve its candidate ontology.
        if any(self.nodes[x]["state"] != "active" for x in (src, dst)):
            state = "draft"
        state = state or "active"
        payload = json.dumps([src, relation, dst], ensure_ascii=False, separators=(",", ":"))
        edge_id = "edge:" + hashlib.sha256(payload.encode()).hexdigest()[:24]
        if edge_id not in self.edges:
            self.edges[edge_id] = {
                "id": edge_id, "src_id": src, "relation": relation, "dst_id": dst,
                "state": state, "schema_version": 2,
                "properties": {"evidence_refs": []},
            }
        elif self.edges[edge_id]["state"] != state:
            # A vetted structure and an extra candidate parent can share a triple.
            if state == "active":
                self.edges[edge_id]["state"] = "active"
        marker = json.dumps(evidence, sort_keys=True, ensure_ascii=False)
        if marker not in self.evidence_seen[edge_id]:
            self.evidence_seen[edge_id].add(marker)
            self.edges[edge_id]["properties"]["evidence_refs"].append(evidence)

    def check(self):
        children = defaultdict(list)
        triples = set()
        for edge in self.edges.values():
            src, relation, dst = (edge[k] for k in ("src_id", "relation", "dst_id"))
            if src not in self.nodes or dst not in self.nodes:
                raise ValueError("dangling edge")
            if RELATIONS.get(relation) != (self.nodes[src]["node_type"], self.nodes[dst]["node_type"]):
                raise ValueError("invalid relation endpoint types")
            triple = (src, relation, dst)
            if triple in triples:
                raise ValueError("duplicate edge triple")
            triples.add(triple)
            if relation == "HAS_SUBTOPIC":
                children[src].append(dst)
        colors = {}

        def visit(node):
            if colors.get(node) == 1:
                raise ValueError(f"hierarchy cycle: {node}")
            if colors.get(node) == 2:
                return
            colors[node] = 1
            for child in children.get(node, []):
                visit(child)
            colors[node] = 2

        for node in children:
            visit(node)
        return {"dangling_edges": 0, "invalid_relation_types": 0,
                "hierarchy_cycles": 0, "duplicate_edge_triples": 0}


def build(batch, out, *, index_dir=DEFAULT_INDEX, root=ROOT):
    batch, out, index_dir, root = map(Path, (batch, out, index_dir, root))
    if out.exists():
        raise FileExistsError(f"choose a fresh output directory: {out}")
    manifest = read_json(batch / "manifest.json")
    source = Path(manifest["source_file"])
    source = source if source.is_absolute() else root / source
    source_hash = sha256(source)
    if source_hash != manifest["source_sha256"]:
        raise ValueError("source SHA256 mismatch")
    scene_path = batch / "scene_registry.json"
    if sha256(scene_path) != manifest["scene_registry_sha256"]:
        raise ValueError("scene registry SHA256 mismatch")
    scene_registry = read_json(scene_path)
    if scene_registry["registry_version"] != manifest["scene_registry_version"]:
        raise ValueError("scene registry version mismatch")
    annotations = unique(read_jsonl(batch / "annotations.jsonl"), "sample_id", "annotation")
    planned = manifest["planned_sample_ids"]
    if len(set(planned)) != len(planned) or set(planned) != set(annotations):
        raise ValueError("planned annotation coverage mismatch")
    if set(manifest["completed_sample_ids"]) != set(annotations):
        raise ValueError("completed annotation coverage mismatch")
    samples = unique(read_jsonl(source), "sample_id", "source sample")
    missing = set(annotations) - set(samples)
    if missing:
        raise ValueError(f"missing source samples: {sorted(missing)}")
    corpus = manifest["corpus_id"]
    for row in annotations.values():
        if row["corpus_id"] != corpus or row["registry_version"] != manifest["registry_version"]:
            raise ValueError("annotation corpus/registry mismatch")
        if row["record_status"] not in {"labeled", "not_question", "needs_context"}:
            raise ValueError("unknown record_status")
        if row["record_status"] != "labeled" and any(row[k] for k in ("tests", "requires", "scenes", "scene_concept_links")):
            raise ValueError(f"excluded annotation has relationships: {row['sample_id']}")
    status_counts = dict(Counter(x["record_status"] for x in annotations.values()))
    if status_counts != manifest["status_counts"]:
        raise ValueError("manifest status counts mismatch")

    registry = unique(read_json(index_dir / "registry.json"), "id", "registered concept")
    old_nodes = unique(read_jsonl(index_dir / "nodes.jsonl"), "id", "index node")
    scenes = unique(scene_registry["scenes"], "id", "scene")
    proposals = unique(read_jsonl(batch / "node_proposals.jsonl"), "id", "proposal")
    changes = list(read_jsonl(batch / "index_changes.jsonl"))
    aliases = {x["source"]: x["target"] for x in read_json(index_dir / "aliases.json")}
    for item in changes:
        if item["operation"] == "merge":
            aliases[item["source_id"]] = item["target_id"]
        elif item["operation"] not in {"add_parent", "add_alias"}:
            raise ValueError(f"unsupported index change: {item['operation']}")
    for sid, item in scenes.items():
        if item.get("redirect_to"):
            aliases[sid] = item["redirect_to"]
    resolve = Resolver(aliases)
    profile_path = root / "backend/data/knowledge_node_profiles_v01.json"
    concept_profiles = read_json(profile_path)["concepts"] if profile_path.exists() else {}
    graph = Graph()
    for cid, item in registry.items():
        if resolve(cid) != cid:
            continue
        old = old_nodes.get(f"concept:{cid}")
        if not old or old["node_type"] != "Concept":
            raise ValueError(f"missing baseline concept state: {cid}")
        graph.node(f"concept:{cid}", "Concept", item["name"], old["state"],
                   concept_id=cid, kind=item.get("kind", "topic"),
                   definition=item.get("definition"), aliases=item.get("aliases", []),
                   review_status=item.get("review_status"), parent_basis=item.get("parent_basis"),
                   origin="fixed_index_registry", detail_profile=concept_profiles.get(cid))

    # A proposal merged into an existing concept must not overwrite that concept.
    # Temporary proposal IDs remain distinct unless an explicit merge says otherwise.
    for pid, item in proposals.items():
        if resolve(pid) != pid:
            continue
        node_type = item["node_type"]
        if node_type not in {"Concept", "Scene"} or not item.get("definition"):
            raise ValueError(f"invalid proposal definition/type: {pid}")
        nid = f"concept:{pid}" if node_type == "Concept" else pid
        graph.node(nid, node_type, item["name"], "draft", concept_id=pid if node_type == "Concept" else None,
                   kind="proposed", definition=item["definition"], aliases=item.get("aliases", []),
                   proposal_id=pid, origin="unapproved_node_proposal", proposal_evidence=item.get("evidence"),
                   detail_profile=concept_profiles.get(pid))
    for sid, item in scenes.items():
        if resolve(sid) != sid:
            continue
        if item["tag_policy"] in {"module_only", "redirect", "context_review"}:
            continue
        graph.node(sid, "Scene", item["name"], definition=item["definition"], scene_id=sid,
                   aliases=item.get("aliases", []), scope_type=item.get("scope_type"),
                   classification_group=item.get("classification_group"),
                   tag_policy=item["tag_policy"], match_when=item.get("match_when", []),
                   exclude_when=item.get("exclude_when", []), origin="fixed_scene_registry",
                   detail_profile=item.get("detail_profile"))

    # Registered hierarchy only: no English prefix or namespace parent inference.
    for cid, item in registry.items():
        target = f"concept:{resolve(cid)}"
        for parent in item.get("parents", []):
            src = f"concept:{resolve(parent)}"
            if src != target:
                graph.edge(src, "HAS_SUBTOPIC", target, {
                    "basis": "fixed_index_hierarchy", "registry_id": cid,
                    "parent_basis": item.get("parent_basis"),
                    "review_status": item.get("review_status"),
                })
    for pid, item in proposals.items():
        if resolve(pid) != pid or item["node_type"] != "Concept":
            continue
        if not item.get("parents"):
            raise ValueError(f"proposal requires explicit parents: {pid}")
        for parent in item["parents"]:
            graph.edge(f"concept:{resolve(parent)}", "HAS_SUBTOPIC", f"concept:{pid}", {
                "basis": "node_proposal_parent", "proposal_id": pid,
                "evidence": item["evidence"],
            }, state="draft")
    for edge in read_jsonl(index_dir / "edges.jsonl"):
        if edge["relation"] == "COVERS_TOPIC":
            src = f"concept:{resolve(edge['src_id'].removeprefix('concept:'))}"
            dst = f"concept:{resolve(edge['dst_id'].removeprefix('concept:'))}"
            for ref in edge["properties"]["evidence_refs"]:
                graph.edge(src, "COVERS_TOPIC", dst, ref, state=edge["state"])
    for change in changes:
        if change["operation"] == "add_parent":
            graph.edge(f"concept:{resolve(change['parent_id'])}", "HAS_SUBTOPIC",
                       f"concept:{resolve(change['target_id'])}",
                       {"basis": "explicit_index_change", **change}, state="draft")
        elif change["operation"] == "add_alias":
            target = resolve(change["target_id"])
            nid = f"concept:{target}" if f"concept:{target}" in graph.nodes else target
            if nid not in graph.nodes:
                raise ValueError(f"alias target missing: {target}")
            graph.nodes[nid]["properties"].setdefault("aliases", []).append(change["alias"])

    issues = []
    archived = []
    def annotation_evidence(annotation, item):
        if not item.get("evidence", {}).get("quote") or not item.get("reason"):
            raise ValueError("missing relation evidence/reason")
        if item["basis"] not in {"question", "source_context", "answer_clarification"}:
            raise ValueError("invalid relation evidence basis")
        return {**item, "annotation_locator": f"annotations.jsonl:{annotation_lines[annotation['sample_id']]}",
                "corpus_id": corpus, "sample_id": annotation["sample_id"],
                "review_stage": annotation.get("review_stage"), "review_scope": annotation.get("review_scope")}

    annotation_lines = {sid: n for n, sid in enumerate(annotations, 1)}
    question_ids = {}
    for sid, annotation in annotations.items():
        source_row = samples[sid]
        status = annotation["record_status"]
        qid = f"question:{corpus}:{sid}"
        archived.append({"corpus_id": corpus, "sample_id": sid, "record_status": status,
                         "question_id": qid if status == "labeled" else None,
                         "source_locator": annotation["source_locator"], "raw_record": source_row,
                         "annotation_reason": annotation["reason"]})
        if status != "labeled":
            continue
        question_ids[sid] = qid
        graph.node(qid, "Question", source_row["question"],
                   corpus_id=corpus, sample_id=sid, record_status=status,
                   normalized_question=annotation.get("normalized_question"),
                   context_refs=annotation["context_refs"],
                   source_locator=annotation["source_locator"], source_index=source_row.get("source_index"),
                   source_line=source_row.get("source_line"), source_repo=source_row.get("source_repo"),
                   source_file=source_row.get("source_file"), answer=source_row.get("answer"),
                   company=source_row.get("company"), companies=source_row.get("companies", []),
                   roles=source_row.get("roles", []), era=source_row.get("era"),
                   original_tags={k: source_row.get(k) for k in ("category", "tech_scene", "business_scene")},
                   review_stage=annotation.get("review_stage"), review_scope=annotation.get("review_scope"))
        attached_scenes = {resolve(item["scene_id"]) for item in annotation["scenes"]}
        for field, relation in (("tests", "TESTS"), ("requires", "REQUIRES")):
            for item in annotation[field]:
                target = f"concept:{resolve(item['concept_id'])}"
                if target not in graph.nodes:
                    raise ValueError(f"unregistered concept: {sid}: {item['concept_id']}")
                state = None
                if graph.nodes[target]["properties"].get("kind") == "navigation":
                    state = "draft"
                    issues.append({"code": "navigation_used_as_semantic_target", "sample_id": sid,
                                   "relation": relation, "concept_id": resolve(item["concept_id"]),
                                   "action": "保留原标签为草稿边，未自动改成技术知识点；待语义复核。"})
                graph.edge(qid, relation, target, annotation_evidence(annotation, item), state=state)
        for item in annotation["scenes"]:
            target = resolve(item["scene_id"])
            if item["basis"] not in {"question", "source_context"}:
                raise ValueError("scene edge cannot use answer-only evidence")
            graph.edge(target, "HAS_QUESTION", qid, annotation_evidence(annotation, item))
        for item in annotation["scene_concept_links"]:
            scene = resolve(item["scene_id"])
            if scene not in attached_scenes:
                raise ValueError(f"scene_concept_link has no explicit scene attachment: {sid}")
            if item["basis"] not in {"question", "source_context"}:
                raise ValueError("scene_concept_link cannot use answer-only evidence")
            graph.edge(scene, "INVOLVES", f"concept:{resolve(item['concept_id'])}",
                       annotation_evidence(annotation, item))

    checks = graph.check()
    parent_ids = {e["dst_id"] for e in graph.edges.values() if e["relation"] == "HAS_SUBTOPIC"}
    orphaned = [nid for nid, n in graph.nodes.items() if n["node_type"] == "Concept"
                and nid not in parent_ids and n["properties"].get("kind") != "navigation"]
    if orphaned:
        raise ValueError(f"non-navigation concepts lack parents: {orphaned}")
    # Guard against emitting excluded rows as questions, companies as entities,
    # or reverse semantic edges. Source records are kept outside both views.
    if sum(n["node_type"] == "Question" for n in graph.nodes.values()) != status_counts.get("labeled", 0):
        raise ValueError("question count mismatch")
    mg_edges = [e for e in graph.edges.values() if e["relation"] in MG_RELATIONS]
    kg_edges = [e for e in graph.edges.values() if e["relation"] in KG_RELATIONS]
    mg_nodes = {nid for nid, n in graph.nodes.items() if n["node_type"] in {"Concept", "Question"}}
    # KG is an actual view, not another full copy of MG. Include registry entry
    # scenes and only concepts/questions referenced by KG edges.
    kg_nodes = {nid for nid, n in graph.nodes.items() if n["node_type"] == "Scene"}
    kg_nodes.update(nid for e in kg_edges for nid in (e["src_id"], e["dst_id"]))
    used_concepts = {e["dst_id"] for e in graph.edges.values() if e["relation"] in {"TESTS", "REQUIRES", "INVOLVES"}}
    used_scenes = {e["src_id"] for e in kg_edges}
    source_paths = [batch / name for name in ("manifest.json", "annotations.jsonl", "node_proposals.jsonl", "index_changes.jsonl", "scene_registry.json")]
    source_paths += [source, index_dir / "registry.json", index_dir / "aliases.json", index_dir / "nodes.jsonl", index_dir / "edges.jsonl", Path(__file__)]
    if profile_path.exists():
        source_paths.append(profile_path)
    inputs = {str(path.resolve()): sha256(path) for path in source_paths}
    for name in ("validation.json", "quote_audit.json"):
        if (batch / name).exists():
            inputs[str((batch / name).resolve())] = sha256(batch / name)
    report = {
        "schema_version": 2, "corpus_id": corpus, "annotation_count": len(annotations),
        "status_counts": status_counts, "source_total_records": len(samples),
        "source_records_outside_scope": len(samples) - len(annotations),
        "nodes_by_type": dict(Counter(n["node_type"] for n in graph.nodes.values())),
        "concepts_by_state": dict(Counter(n["state"] for n in graph.nodes.values() if n["node_type"] == "Concept")),
        "edges_by_relation": dict(Counter(e["relation"] for e in graph.edges.values())),
        "edges_by_state": dict(Counter(e["state"] for e in graph.edges.values())),
        "edges_by_relation_and_state": {r: dict(Counter(e["state"] for e in graph.edges.values() if e["relation"] == r)) for r in RELATIONS},
        "views": {"MG": {"nodes": len(mg_nodes), "edges": len(mg_edges)}, "KG": {"nodes": len(kg_nodes), "edges": len(kg_edges)}},
        "used_concepts": len(used_concepts), "used_scenes": len(used_scenes),
        "nodes_with_detail_profiles": dict(Counter(n["node_type"] for n in graph.nodes.values() if n["properties"].get("detail_profile"))),
        "questions_without_concept_edges": len(question_ids) - len({e["src_id"] for e in graph.edges.values() if e["relation"] in {"TESTS", "REQUIRES"}}),
        "canonical_proposal_concepts": sum(n["properties"].get("origin") == "unapproved_node_proposal" and n["node_type"] == "Concept" for n in graph.nodes.values()),
        "checks": {**checks, "non_navigation_without_parent": 0,
                   "excluded_question_nodes": 0, "unregistered_references": 0,
                   "source_hash_verified": True, "scene_registry_hash_verified": True},
        "issues": {"navigation_target_edges": len(issues), "navigation_target_questions": len({i['sample_id'] for i in issues})},
        "source_annotation_audit": read_json(batch / "validation.json") if (batch / "validation.json").exists() else None,
        "limitations": ["结构落图与语义复核分开；本次未重新逐题标注。", "旧索引草稿与本批未批准提案仍为draft，不作为已发布正式知识库。", "同题跨来源语义去重未执行；不按短文本或时间戳误合并。", "未实现TG；非题目和待上下文记录仅归档，不自动制成追问链。"],
    }
    # Write only after every graph check succeeds. Never overwrite historic data.
    out.mkdir(parents=True)
    save_jsonl(out / "nodes.jsonl", sorted(graph.nodes.values(), key=lambda n: n["id"]))
    save_jsonl(out / "edges.jsonl", sorted(graph.edges.values(), key=lambda e: e["id"]))
    for prefix, node_set, edges in (("mg", mg_nodes, mg_edges), ("kg", kg_nodes, kg_edges)):
        save_jsonl(out / f"{prefix}_nodes.jsonl", (graph.nodes[nid] for nid in sorted(node_set)))
        save_jsonl(out / f"{prefix}_edges.jsonl", sorted(edges, key=lambda e: e["id"]))
    save_jsonl(out / "source_records.jsonl", archived)
    save_jsonl(out / "excluded_records.jsonl", (row for row in archived if row["record_status"] != "labeled"))
    save_jsonl(out / "graph_issues.jsonl", issues)
    save_json(out / "entity_redirects.json", dict(sorted(aliases.items())))
    save_json(out / "mapping_report.json", report)
    save_json(out / "graph_manifest.json", {
        "schema_version": 2, "graph_built": True, "build_kind": "offline_materialization_with_drafts",
        "corpus_id": corpus, "source_batch": str(batch.resolve()),
        "registry_version": manifest["registry_version"], "scene_registry_version": manifest["scene_registry_version"],
        "input_sha256": inputs,
        "output_sha256": {path.name: sha256(path) for path in sorted(out.iterdir()) if path.is_file()},
        "production_ready": False, "new_semantic_annotations_created": 0,
    })
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX)
    args = parser.parse_args()
    report = build(args.batch, args.out, index_dir=args.index_dir)
    print(json.dumps({k: v for k, v in report.items() if k not in {"source_annotation_audit"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
