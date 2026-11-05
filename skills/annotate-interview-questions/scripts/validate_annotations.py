#!/usr/bin/env python3
"""Validate offline annotation structure/references; never infer semantic labels."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
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


def ancestor_map(parents):
    cache = {}

    def ancestors(node, active=None):
        if node in cache:
            return cache[node]
        active = set() if active is None else active
        require(node not in active, f"hierarchy cycle at {node}")
        result = set()
        for parent in parents.get(node, []):
            result.add(parent)
            result.update(ancestors(parent, active | {node}))
        cache[node] = result
        return result

    for node in parents:
        ancestors(node)
    return cache


def load_scene_registry(path):
    catalog = read_json(path)
    require(isinstance(catalog, dict) and nonempty(catalog.get("registry_version")),
            "scene registry_version required")
    require(isinstance(catalog.get("scenes"), list), "scene registry.scenes must be array")
    by_id, identities = {}, {}
    for scene in catalog["scenes"]:
        require(isinstance(scene, dict), "scene definition must be object")
        sid = scene.get("id")
        require(nonempty(sid) and sid.startswith("scene:"), "invalid scene ID")
        require(sid not in by_id, f"duplicate scene ID: {sid}")
        require(all(nonempty(scene.get(k)) for k in ("name", "definition")),
                f"{sid}: scene name/definition required")
        for field in ("aliases", "match_when", "exclude_when"):
            values = unique_strings(scene.get(field), f"{sid}.{field}")
            require(field == "aliases" or values, f"{sid}.{field} must explain matching boundary")
        require(scene.get("tag_policy") in {"reuse", "broad_only", "redirect", "module_only", "context_review"},
                f"{sid}: invalid tag_policy")
        if scene["tag_policy"] in {"reuse", "broad_only"}:
            for name in [scene["name"], *scene["aliases"]]:
                name = name.strip().casefold()
                require(name not in identities, f"{sid}: duplicate scene name/alias: {name}")
                identities[name] = sid
        by_id[sid] = scene
    for sid, scene in by_id.items():
        target = scene.get("redirect_to")
        if scene["tag_policy"] == "redirect":
            require(target in by_id and target != sid, f"{sid}: invalid redirect target")
            require(by_id[target]["tag_policy"] in {"reuse", "broad_only"},
                    f"{sid}: redirect must target reusable scene; chain/cycle not allowed")
        else:
            require(target is None, f"{sid}: non-redirect entry must not redirect")
        for rule in scene.get("resolution_rules", []):
            if "target_id" in rule:
                require(rule["target_id"] in by_id and
                        by_id[rule["target_id"]]["tag_policy"] in {"reuse", "broad_only"},
                        f"{sid}: invalid contextual target")
    return {sid for sid, scene in by_id.items() if scene["tag_policy"] in {"reuse", "broad_only"}}, catalog["registry_version"]


def check_regressions(path, manifest, rows):
    """Check curated required/forbidden edges in one immutable corpus."""
    cases = read_json(path)
    require(cases.get("schema_version") == "1.0.0", "invalid regression schema")
    for field in ("corpus_id", "source_sha256"):
        require(nonempty(cases.get(field)) and cases[field] == manifest[field],
                f"regression {field} differs from manifest; do not apply cases to another corpus")
    require(isinstance(cases.get("cases"), list), "regression cases must be array")
    reviewed = {r["sample_id"]: r for r in rows if r["review_stage"] == "review"}
    seen, violations, checked = set(), [], 0
    for case in cases["cases"]:
        sid = case.get("sample_id")
        require(nonempty(sid) and sid not in seen, "invalid/duplicate regression sample_id")
        seen.add(sid)
        require(nonempty(case.get("reason")), f"{sid}: regression reason required")
        forbidden_tests = unique_strings(case.get("forbidden_tests", []), f"{sid}.forbidden_tests")
        forbidden_scenes = unique_strings(case.get("forbidden_scenes", []), f"{sid}.forbidden_scenes")
        required_tests = unique_strings(case.get("required_tests", []), f"{sid}.required_tests")
        required_scenes = unique_strings(case.get("required_scenes", []), f"{sid}.required_scenes")
        require(not (set(required_tests) & set(forbidden_tests)) and
                not (set(required_scenes) & set(forbidden_scenes)),
                f"{sid}: contradictory required/forbidden relations")
        links = case.get("forbidden_scene_concept_links", [])
        require(isinstance(links, list), f"{sid}: forbidden links must be array")
        require(all(isinstance(link, dict) and nonempty(link.get("scene_id")) and
                    nonempty(link.get("concept_id")) for link in links), f"{sid}: invalid forbidden link")
        forbidden_links = {(link["scene_id"], link["concept_id"]) for link in links}
        require(len(forbidden_links) == len(links), f"{sid}: duplicate forbidden links")
        if sid not in reviewed:
            continue
        checked += 1
        row = reviewed[sid]
        actual_tests = {r["concept_id"] for r in row["tests"]}
        actual_scenes = {r["scene_id"] for r in row["scenes"]}
        bad_tests = sorted(set(forbidden_tests) & actual_tests)
        bad_scenes = sorted(set(forbidden_scenes) & actual_scenes)
        missing_tests = sorted(set(required_tests) - actual_tests)
        missing_scenes = sorted(set(required_scenes) - actual_scenes)
        bad_links = sorted(forbidden_links & {(r["scene_id"], r["concept_id"])
                                             for r in row["scene_concept_links"]})
        if bad_tests or bad_scenes or bad_links or missing_tests or missing_scenes:
            violations.append({"sample_id": sid, "tests": bad_tests, "scenes": bad_scenes,
                               "scene_concept_links": bad_links,
                               "missing_tests": missing_tests, "missing_scenes": missing_scenes,
                               "reason": case["reason"]})
    require(not violations, "known semantic regressions: " + json.dumps(violations, ensure_ascii=False))
    return {"cases_checked": checked, "cases_total": len(seen),
            "note": "仅检查固定案例的必需/禁用关系，不代表完成语义审核。"}


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
    scene_version = None
    if getattr(args, "scene_registry", None):
        scenes, scene_version = load_scene_registry(args.scene_registry)
    else:
        require(getattr(args, "scene_nodes", None), "provide scene registry or legacy scene nodes")
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
            for field in ("match_when", "exclude_when"):
                require(unique_strings(node.get(field), f"{node_id}.{field}"),
                        f"{node_id}: scene proposal needs matching boundaries")
            scenes.add(node_id)
    check_dag(parents)
    ancestors_by_id = ancestor_map(parents)

    manifest = read_json(args.manifest)
    require(isinstance(manifest, dict), "manifest must be object")
    if scene_version and "scene_registry_version" in manifest:
        require(manifest["scene_registry_version"] == scene_version, "scene registry version differs from manifest")
    if scene_version and "scene_registry_sha256" in manifest:
        require(manifest["scene_registry_sha256"] == hashlib.sha256(Path(args.scene_registry).read_bytes()).hexdigest(),
                "scene registry hash differs from manifest")
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
    reviewed_ids, full_reviewed_ids, scope_counts = [], [], Counter()
    ancestor_overlap_count, ancestor_overlap_examples = 0, []
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
        scope = row.get("review_scope")
        if scope is not None:
            require(scope in {"full", "concept_only", "scene_only", "status_only"},
                    f"{sid}: invalid review_scope")
            require(row["review_stage"] == "review", f"{sid}: initial record cannot declare review_scope")
        if row["review_stage"] == "review":
            reviewed_ids.append(sid)
            scope_counts[scope or "unspecified"] += 1
            if scope == "full":
                full_reviewed_ids.append(sid)
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
        if row["record_status"] == "labeled":
            concept_ids = {item["concept_id"] for item in row["tests"]}
            overlaps = []
            for concept_id in concept_ids:
                overlaps.extend((parent, concept_id)
                                for parent in ancestors_by_id.get(concept_id, set())
                                if parent in concept_ids)
            ancestor_overlap_count += len(overlaps)
            if overlaps and len(ancestor_overlap_examples) < 20:
                ancestor_overlap_examples.append({"sample_id": sid, "pairs": sorted(overlaps)})
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
    for field, actual in (("reviewed_sample_ids", reviewed_ids),
                          ("full_reviewed_sample_ids", full_reviewed_ids)):
        if field in manifest:
            require(unique_strings(manifest[field], f"manifest.{field}") == actual,
                    f"manifest {field} mismatch")
    if "review_scope_counts" in manifest:
        require(manifest["review_scope_counts"] == dict(scope_counts), "manifest review_scope_counts mismatch")
    if getattr(args, "require_reviewed", False):
        require(ids == planned and len(reviewed_ids) == len(planned),
                "review incomplete: all planned records must declare review_stage=review")
        for row in rows:
            if row["record_status"] == "labeled":
                require(row.get("review_scope") == "full",
                        f"{row['sample_id']}: labeled record requires review_scope=full")
            else:
                require(row.get("review_scope") in {"status_only", "full"},
                        f"{row['sample_id']}: unresolved/non-question record requires status_only or full review")
    regression = None
    if getattr(args, "regression_cases", None):
        regression = check_regressions(args.regression_cases, manifest, rows)
    return {"valid": True, "completed": len(ids), "planned": len(planned),
            "completed_means": "文件已有输出记录数，不代表AI已完整复核数量。",
            "reviewed_count": len(reviewed_ids), "initial_count": stage_counts.get("initial", 0),
            "full_review_count": len(full_reviewed_ids), "review_scope_counts": dict(scope_counts),
            "ancestor_overlap_count": ancestor_overlap_count,
            "ancestor_overlap_examples": ancestor_overlap_examples,
            "status_counts": dict(status_counts), "proposal_count": len(proposals),
            "proposal_reference_count": proposal_refs,
            "semantic_accuracy_checked": False, "source_quotes_checked": False,
            "scene_registry_version": scene_version,
            "regression_checks": regression,
            "note": "结构校验通过；不应用索引变更，不批准新节点，不执行建图。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("annotations", "registry", "manifest"):
        parser.add_argument("--" + name, required=True, type=Path)
    scene_input = parser.add_mutually_exclusive_group(required=True)
    scene_input.add_argument("--scene-registry", type=Path)
    scene_input.add_argument("--scene-nodes", type=Path, help="legacy snapshots without scene definitions")
    parser.add_argument("--proposals", type=Path)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--require-reviewed", action="store_true",
                        help="require review of all planned records; labeled records need full review, others may use status_only")
    parser.add_argument("--regression-cases", type=Path,
                        help="curated required/forbidden edges for an exact corpus and source hash")
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
