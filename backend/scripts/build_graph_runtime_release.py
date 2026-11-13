#!/usr/bin/env python3
"""Build an active-only runtime snapshot; never promote draft semantics."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.graph_retrieval import GraphIndex


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def jsonl(rows):
    return b"".join((json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode() for row in rows)


def build_release(source: Path, out: Path, approvals: Path, *, audit_out: Path | None = None):
    upstream = json.loads((source / "graph_manifest.json").read_text())
    for name, digest in upstream["output_sha256"].items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"upstream checksum mismatch: {name}")
    for required in ("nodes.jsonl", "edges.jsonl"):
        if required not in upstream["output_sha256"]:
            raise ValueError(f"upstream manifest does not cover {required}")
    def rows(name):
        with (source / name).open(encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]
    nodes, edges = rows("nodes.jsonl"), rows("edges.jsonl")
    # Validate the complete structure before selecting the runtime view.
    GraphIndex(nodes, edges, include_drafts=True)
    by_id = {n["id"]: n for n in nodes}
    active = {nid for nid, n in by_id.items() if n.get("state") == "active"}
    published_edges = []; removed_navigation = 0
    structural_parents = {e["src_id"] for e in edges if e["relation"] == "HAS_SUBTOPIC"}
    original_linked = set(); published_linked = set()
    for e in edges:
        if e["relation"] in {"TESTS", "REQUIRES", "HAS_QUESTION"}:
            original_linked.update(nid for nid in (e["src_id"], e["dst_id"]) if by_id[nid]["node_type"] == "Question")
        if e.get("state") != "active" or e["src_id"] not in active or e["dst_id"] not in active:
            continue
        if e["relation"] in {"TESTS", "REQUIRES", "INVOLVES"} and by_id[e["dst_id"]].get("properties", {}).get("kind") == "navigation":
            removed_navigation += 1
            continue
        published_edges.append(deepcopy(e))
        if e["relation"] in {"TESTS", "REQUIRES", "HAS_QUESTION"}:
            published_linked.update(nid for nid in (e["src_id"], e["dst_id"]) if by_id[nid]["node_type"] == "Question")
    approved = {}
    approval_rows = json.loads(approvals.read_text())["questions"]
    by_sample = {n.get("properties", {}).get("sample_id"): n for n in nodes if n["node_type"] == "Question"}
    for item in approval_rows:
        n = by_sample.get(item["sample_id"])
        if not n or n["name"] != item["question"] or n["id"] not in active or item["kind"] != "behavioral":
            raise ValueError(f"general question approval does not match: {item['sample_id']}")
        if n["id"] in original_linked or n["id"] in approved:
            raise ValueError("general approvals must be unique, graph-independent questions")
        approved[n["id"]] = item["kind"]
    published_nodes = []; routes = []
    for node in nodes:
        nid = node["id"]
        if node["node_type"] == "Question":
            route = ("graph" if nid in published_linked else "general_behavioral" if nid in approved
                     else "held_unlinked" if nid not in original_linked else "held_semantic_edges")
            routes.append({"sample_id": node["properties"]["sample_id"], "question_id": nid, "route": route})
            if nid not in published_linked and nid not in approved:
                continue
        if nid not in active:
            continue
        item = deepcopy(node)
        if nid in structural_parents:
            # Removing draft children must not turn a real parent into a BAGU leaf.
            item.setdefault("properties", {})["structural_has_children"] = True
        if nid in approved:
            item.setdefault("properties", {})["general_pool_kind"] = approved[nid]
        published_nodes.append(item)
    graph = GraphIndex(published_nodes, published_edges)
    report = json.loads((source / "mapping_report.json").read_text())
    manifest = {
        "schema_version": 1, "release_kind": "active_only_graph_with_reviewed_general_pool",
        "runtime_ready": True, "semantic_review_complete": False,
        "source_production_ready": upstream.get("production_ready"),
        "source_graph_manifest_sha256": hashlib.sha256((source / "graph_manifest.json").read_bytes()).hexdigest(),
        "general_approvals_sha256": hashlib.sha256(approvals.read_bytes()).hexdigest(),
        "source_records": report["source_total_records"], "source_question_count": report["status_counts"]["labeled"],
        "question_review_stages": dict(Counter(n.get("properties", {}).get("review_stage", "unknown")
                                               for n in nodes if n["node_type"] == "Question")),
        "node_count": len(published_nodes), "edge_count": len(published_edges),
        "node_types": dict(Counter(n["node_type"] for n in published_nodes)),
        "question_routes": dict(Counter(r["route"] for r in routes)),
        "removed_active_navigation_edges": removed_navigation,
        "bagu_leaf_question_count": len(graph.bagu_pool(nid for nid, n in graph.nodes.items() if n["node_type"] == "Concept")[1]),
        "limits": ["仅发布active关系；initial标注未自动变成review。", "无边题逐条登记去向；未经确认的不自动用作HR或技术题。", "draft子节点被移除时保留父节点非叶子属性。"],
    }
    payload = {"nodes.jsonl": jsonl(published_nodes), "edges.jsonl": jsonl(published_edges)}
    manifest["output_sha256"] = {name: hashlib.sha256(raw).hexdigest() for name, raw in payload.items()}
    payload["runtime_manifest.json"] = encode(manifest)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Refuse accidental overwrites; a release name identifies immutable bytes.
    with zipfile.ZipFile(out, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, raw in sorted(payload.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 13, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, raw, compresslevel=9)
    if audit_out is not None:
        audit_out.parent.mkdir(parents=True, exist_ok=True)
        audit_out.write_bytes(jsonl(routes))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--approvals", type=Path, default=Path(__file__).resolve().parents[1] / "graph/general-question-approvals.json")
    parser.add_argument("--audit-out", type=Path)
    args = parser.parse_args()
    print(json.dumps(build_release(args.source, args.out, args.approvals, audit_out=args.audit_out), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
