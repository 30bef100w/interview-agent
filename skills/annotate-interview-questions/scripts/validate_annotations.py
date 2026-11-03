#!/usr/bin/env python3
"""Validate offline annotation structure/references; never infer semantic labels."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys


def require(condition, message):
    if not condition:
        raise ValueError(message)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_lines(path):
    values = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            value = json.loads(line)
            require(isinstance(value, dict), f"{path}:{number}: expected object")
            values.append(value)
    return values


def evidence(value, location):
    require(isinstance(value, dict), f"{location}: evidence must be object")
    require(all(nonempty(value.get(k)) for k in ("locator", "quote")),
            f"{location}: evidence requires locator and quote")


def unique_strings(values, location):
    require(isinstance(values, list) and all(nonempty(x) for x in values),
            f"{location}: expected string array")
    require(len(values) == len(set(values)), f"{location}: duplicate IDs")
    return values


def check_dag(parents):
    colors = {}

    def visit(node):
        require(colors.get(node) != 1, f"hierarchy cycle at {node}")
        if colors.get(node) == 2:
            return
        colors[node] = 1
        for parent in parents[node]:
            require(parent in parents, f"{node}: unknown parent {parent}")
            visit(parent)
        colors[node] = 2

    for node in parents:
        visit(node)


def validate(args):
    registry = read_json(args.registry)
    require(isinstance(registry, list), "registry must be a list of concept objects")
    concepts, parents = set(), {}
    for node in registry:
        require(isinstance(node, dict) and nonempty(node.get("id")), "invalid registry entry")
        node_id = node["id"]
        require(node_id not in concepts, f"duplicate registry ID: {node_id}")
        concepts.add(node_id)
        parents[node_id] = unique_strings(node.get("parents", []), f"{node_id}.parents")
    scenes = {n["id"] for n in read_lines(args.scene_nodes) if n.get("node_type") == "Scene"}

    proposals = read_lines(args.proposals) if args.proposals else []
    proposed_ids = set()
    for node in proposals:
        kind, node_id = node.get("node_type"), node.get("id")
        require(kind in {"Concept", "Scene"}, "proposal type must be Concept or Scene")
        prefix = "new:concept:" if kind == "Concept" else "new:scene:"
        require(nonempty(node_id) and node_id.startswith(prefix) and len(node_id) > len(prefix),
                f"proposal ID must start with {prefix}")
        require(node_id not in concepts | scenes | proposed_ids, f"duplicate proposal: {node_id}")
        proposed_ids.add(node_id)
        require(all(nonempty(node.get(k)) for k in ("name", "definition")),
                f"{node_id}: Chinese name and definition required")
        unique_strings(node.get("aliases"), f"{node_id}.aliases")
        ps = unique_strings(node.get("parents"), f"{node_id}.parents")
        evidence(node.get("evidence"), node_id)
        if kind == "Concept":
            require(ps, f"{node_id}: concept proposal needs explicit parent")
            concepts.add(node_id)
            parents[node_id] = ps
        else:
            require(not ps, f"{node_id}: scene entry must not add forced hierarchy")
            scenes.add(node_id)
    check_dag(parents)

    manifest = read_json(args.manifest)
    require(isinstance(manifest, dict), "manifest must be object")
    require(manifest.get("schema_version") == "1.0.0", "manifest schema_version must be 1.0.0")
    for key in ("corpus_id", "registry_version", "source_file", "source_sha256"):
        require(nonempty(manifest.get(key)), f"manifest.{key} required")
    sha = manifest["source_sha256"]
    require(len(sha) == 64 and all(c in "0123456789abcdef" for c in sha), "invalid source_sha256")
    planned = unique_strings(manifest.get("planned_sample_ids"), "manifest.planned_sample_ids")
    completed = unique_strings(manifest.get("completed_sample_ids"), "manifest.completed_sample_ids")
    require(planned, "empty planned scope")
    require(set(completed) <= set(planned), "completed IDs outside planned scope")

    rows = read_lines(args.annotations)
    ids, seen_ids, status_counts, stage_counts, proposal_refs = [], set(), Counter(), Counter(), 0
    required = {"schema_version", "corpus_id", "sample_id", "registry_version", "source_locator",
                "record_status", "review_stage", "normalized_question", "context_refs", "reason",
                "tests", "requires", "scenes", "scene_concept_links"}
    for row in rows:
        require(required <= row.keys(), f"annotation missing fields: {sorted(required - row.keys())}")
        sid = row["sample_id"]
        require(nonempty(sid), "sample_id must be nonempty string")
        require(sid not in seen_ids, f"duplicate annotation: {sid}")
        seen_ids.add(sid)
        ids.append(sid)
        require(row["schema_version"] == "1.0.0", f"{sid}: wrong schema version")
        for key in ("corpus_id", "registry_version"):
            require(row[key] == manifest[key], f"{sid}: {key} differs from manifest")
        require(nonempty(row["source_locator"]) and nonempty(row["reason"]),
                f"{sid}: source_locator and reason required")
        require(row["record_status"] in {"labeled", "needs_context", "not_question"},
                f"{sid}: invalid record_status")
        require(row["review_stage"] in {"initial", "review"}, f"{sid}: invalid review_stage")
        require(row["normalized_question"] is None or nonempty(row["normalized_question"]),
                f"{sid}: normalized_question must be null or nonempty string")
        require(isinstance(row["context_refs"], list), f"{sid}: context_refs must be array")
        for ref in row["context_refs"]:
            evidence(ref, f"{sid}.context_refs")
        require(row["normalized_question"] is None or row["context_refs"],
                f"{sid}: normalized question needs supporting context_refs")
        for key in ("tests", "requires", "scenes", "scene_concept_links"):
            items = row[key]
            require(isinstance(items, list), f"{sid}.{key}: expected array")
            require(row["record_status"] == "labeled" or not items,
                    f"{sid}: unresolved/non-question record must not emit graph relations")
            seen = set()
            for item in items:
                require(isinstance(item, dict), f"{sid}.{key}: relation must be object")
                fields = ["scene_id"] if key == "scenes" else ["concept_id"]
                if key == "scene_concept_links":
                    fields = ["scene_id", "concept_id"]
                refs = tuple(item.get(f) for f in fields)
                require(all(nonempty(x) for x in refs), f"{sid}.{key}: missing endpoint")
                require(refs not in seen, f"{sid}.{key}: duplicate relation {refs}")
                seen.add(refs)
                for field, ref in zip(fields, refs):
                    require(ref in (scenes if field == "scene_id" else concepts),
                            f"{sid}.{key}: unknown {field} {ref}")
                    proposal_refs += int(ref in proposed_ids)
                allowed = {"question", "source_context"}
                if key in {"tests", "requires"}:
                    allowed.add("answer_clarification")
                require(item.get("basis") in allowed, f"{sid}.{key}: unsupported evidence basis")
                evidence(item.get("evidence"), f"{sid}.{key}")
                require(nonempty(item.get("reason")), f"{sid}.{key}: reason required")
        status_counts[row["record_status"]] += 1
        stage_counts[row["review_stage"]] += 1

    require(ids == completed, "annotation order/IDs differ from completed_sample_ids")
    completed_set = set(completed)
    require(ids == [sid for sid in planned if sid in completed_set], "annotations are not in planned order")
    require(args.allow_partial or ids == planned, "planned scope is incomplete; use --allow-partial for checkpoint")
    require(dict(status_counts) == manifest.get("status_counts"), "manifest status_counts mismatch")
    require(dict(stage_counts) == manifest.get("review_stage_counts"), "manifest review_stage_counts mismatch")
    require(type(manifest.get("proposal_count")) is int and manifest["proposal_count"] == len(proposals),
            "manifest proposal_count mismatch")
    return {"valid": True, "completed": len(ids), "planned": len(planned),
            "status_counts": dict(status_counts), "proposal_count": len(proposals),
            "proposal_reference_count": proposal_refs,
            "semantic_accuracy_checked": False, "source_quotes_checked": False,
            "note": "结构校验通过；不应用索引变更，不批准新节点，不执行建图。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("annotations", "registry", "scene-nodes", "manifest"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--proposals", type=Path)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    try:
        result = validate(args)
    except (ValueError, OSError, KeyError, TypeError, RecursionError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
