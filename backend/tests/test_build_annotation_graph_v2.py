"""Contract tests for the deterministic MG/KG materializer."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build_annotation_graph_v2.py"
SPEC = importlib.util.spec_from_file_location("annotation_graph_v2", SCRIPT)
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class AnnotationGraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.batch = self.root / "batch"
        self.index = self.root / "index"
        self.batch.mkdir()
        self.index.mkdir()
        self.registry = [
            {"id": "nav", "name": "目录", "kind": "navigation", "parents": []},
            {"id": "redis", "name": "Redis", "parents": ["nav"]},
            {"id": "cache", "name": "缓存", "parents": ["nav"]},
            {"id": "draft", "name": "候选知识", "parents": ["redis"]},
        ]
        self.dump(self.index / "registry.json", self.registry)
        self.lines(self.index / "nodes.jsonl", [
            {"id": "concept:" + n["id"], "node_type": "Concept",
             "state": "draft" if n["id"] == "draft" else "active"} for n in self.registry
        ])
        self.dump(self.index / "aliases.json", [{"source": "old.redis", "target": "redis"}])
        self.lines(self.index / "edges.jsonl", [])
        self.samples = [
            {"sample_id": "S0001", "question": "两个项目怎么分别处理？", "answer": "原答案", "company": "企业甲", "roles": ["后端"]},
            {"sample_id": "S0002", "question": "网页标题"},
            {"sample_id": "S0003", "question": "这部分怎么做？"},
            {"sample_id": "S0004", "question": "范围以外"},
        ]
        self.lines(self.root / "source.jsonl", self.samples)
        self.dump(self.batch / "scene_registry.json", {
            "registry_version": "scene.v1", "scenes": [
                {"id": "scene:a", "name": "项目甲", "definition": "甲项目", "tag_policy": "reuse"},
                {"id": "scene:b", "name": "项目乙", "definition": "乙项目", "tag_policy": "reuse"},
                {"id": "scene:old", "name": "甲日志模块", "definition": "历史模块", "tag_policy": "redirect", "redirect_to": "scene:a"},
            ],
        })
        self.proposals = [{"id": "new:concept:redis.extra", "node_type": "Concept", "name": "新知识",
                           "definition": "新知识范围", "parents": ["redis"], "evidence": {"locator": "q:1", "quote": "处理"}}]
        self.changes = [{"operation": "merge", "source_id": "new:concept:alias", "target_id": "new:concept:redis.extra",
                         "reason": "语义等价", "evidence": {"locator": "q:1", "quote": "处理"}},
                        {"operation": "add_parent", "target_id": "draft", "parent_id": "cache",
                         "reason": "明确跨父", "evidence": {"locator": "q:1", "quote": "处理"}}]
        self.annotations = []
        for sid, status in (("S0001", "labeled"), ("S0002", "not_question"), ("S0003", "needs_context")):
            self.annotations.append({
                "schema_version": "1.0.0", "sample_id": sid, "corpus_id": "corpus-a", "registry_version": "index.v1",
                "source_locator": f"source.jsonl:{int(sid[1:])}", "record_status": status,
                "review_stage": "review", "review_scope": "full" if status == "labeled" else "status_only",
                "reason": "测试标注", "context_refs": [], "tests": [], "requires": [], "scenes": [], "scene_concept_links": [],
            })
        self.annotations[0].update(
            tests=[self.rel(concept_id="old.redis"), self.rel(concept_id="redis"), self.rel(concept_id="new:concept:alias")],
            requires=[self.rel(concept_id="cache")],
            scenes=[self.rel(scene_id="scene:old"), self.rel(scene_id="scene:b")],
            scene_concept_links=[self.rel(scene_id="scene:a", concept_id="redis")],
        )

    def rel(self, **kwargs):
        return {**kwargs, "basis": "question", "evidence": {"locator": "q:1", "quote": "处理"}, "reason": "明确依据"}

    def dump(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def lines(self, path, rows):
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    def prepare(self):
        self.lines(self.batch / "annotations.jsonl", self.annotations)
        self.lines(self.batch / "node_proposals.jsonl", self.proposals)
        self.lines(self.batch / "index_changes.jsonl", self.changes)
        self.manifest = {
            "source_file": "source.jsonl", "source_sha256": builder.sha256(self.root / "source.jsonl"),
            "scene_registry_version": "scene.v1", "scene_registry_sha256": builder.sha256(self.batch / "scene_registry.json"),
            "corpus_id": "corpus-a", "registry_version": "index.v1",
            "planned_sample_ids": [a["sample_id"] for a in self.annotations],
            "completed_sample_ids": [a["sample_id"] for a in self.annotations],
            "status_counts": {"labeled": 1, "not_question": 1, "needs_context": 1},
        }
        self.dump(self.batch / "manifest.json", self.manifest)

    def build(self, name="out"):
        out = self.root / name
        report = builder.build(self.batch, out, index_dir=self.index, root=self.root)
        return out, report, list(builder.read_jsonl(out / "nodes.jsonl")), list(builder.read_jsonl(out / "edges.jsonl"))

    def test_shared_entities_directed_relations_no_scene_cartesian_product(self):
        self.prepare()
        out, report, nodes, edges = self.build()
        qid = "question:corpus-a:S0001"
        triples = {(e["src_id"], e["relation"], e["dst_id"]) for e in edges}
        self.assertIn((qid, "REQUIRES", "concept:cache"), triples)
        self.assertIn(("scene:a", "INVOLVES", "concept:redis"), triples)
        self.assertNotIn(("scene:b", "INVOLVES", "concept:redis"), triples)
        self.assertNotIn(("scene:a", "INVOLVES", "concept:cache"), triples)
        self.assertNotIn((qid, "TESTS", "concept:nav"), triples)
        self.assertNotIn("scene:old", {n["id"] for n in nodes})
        mg = {n["id"]: n for n in builder.read_jsonl(out / "mg_nodes.jsonl")}
        kg = {n["id"]: n for n in builder.read_jsonl(out / "kg_nodes.jsonl")}
        self.assertEqual(mg[qid], kg[qid])
        self.assertEqual(mg["concept:redis"], kg["concept:redis"])
        self.assertEqual(report["source_records_outside_scope"], 1)
        self.assertEqual(len(list(builder.read_jsonl(out / "source_records.jsonl"))), 3)
        self.assertEqual(len(list(builder.read_jsonl(out / "excluded_records.jsonl"))), 2)
        question = mg[qid]
        self.assertEqual(question["properties"]["company"], "企业甲")
        self.assertEqual(question["properties"]["answer"], "原答案")
        self.assertEqual(sum(n["node_type"] == "Question" for n in nodes), 1)
        self.assertFalse(any(n["node_type"] == "Company" for n in nodes))

    def test_alias_merge_dedup_and_draft_state(self):
        self.prepare()
        _, _, nodes, edges = self.build()
        self.assertNotIn("concept:old.redis", {n["id"] for n in nodes})
        self.assertNotIn("concept:new:concept:alias", {n["id"] for n in nodes})
        target = next(n for n in nodes if n["id"] == "concept:new:concept:redis.extra")
        self.assertEqual(target["state"], "draft")
        tests = [e for e in edges if e["relation"] == "TESTS"]
        self.assertEqual(len(tests), 2)
        self.assertEqual(next(e for e in tests if e["dst_id"] == target["id"])["state"], "draft")
        self.assertTrue(any(e["src_id"] == "concept:cache" and e["dst_id"] == "concept:draft" for e in edges))

    def test_unknown_reference_fails_before_output(self):
        self.annotations[0]["tests"].append(self.rel(concept_id="missing"))
        self.prepare()
        with self.assertRaisesRegex(ValueError, "unregistered concept"):
            self.build()
        self.assertFalse((self.root / "out").exists())

    def test_source_hash_mismatch_rejected(self):
        self.prepare()
        with (self.root / "source.jsonl").open("a") as handle:
            handle.write("\n")
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            self.build()

    def test_excluded_relationship_and_duplicate_annotation_rejected(self):
        self.annotations[1]["tests"] = [self.rel(concept_id="redis")]
        self.prepare()
        with self.assertRaisesRegex(ValueError, "excluded annotation"):
            self.build()
        self.annotations[1]["tests"] = []
        self.annotations.append(self.annotations[0])
        self.prepare()
        with self.assertRaisesRegex(ValueError, "duplicate annotation"):
            self.build()

    def test_missing_source_and_cross_corpus_rejected(self):
        self.annotations[0]["sample_id"] = "S9999"
        self.prepare()
        with self.assertRaisesRegex(ValueError, "missing source"):
            self.build()
        self.annotations[0]["sample_id"] = "S0001"
        self.annotations[0]["corpus_id"] = "different-corpus"
        self.prepare()
        with self.assertRaisesRegex(ValueError, "corpus/registry mismatch"):
            self.build()

    def test_cycles_and_missing_explicit_parent_rejected(self):
        self.changes.append({"operation": "add_parent", "target_id": "nav", "parent_id": "redis"})
        self.prepare()
        with self.assertRaisesRegex(ValueError, "hierarchy cycle"):
            self.build()
        self.changes.pop()
        self.proposals[0]["parents"] = ["unknown.parent"]
        self.prepare()
        with self.assertRaisesRegex(ValueError, "unknown endpoint"):
            self.build()

    def test_scene_link_requires_attachment_and_scene_evidence(self):
        self.annotations[0]["scene_concept_links"][0]["scene_id"] = "scene:missing"
        self.prepare()
        with self.assertRaisesRegex(ValueError, "no explicit scene attachment"):
            self.build()
        self.annotations[0]["scene_concept_links"][0]["scene_id"] = "scene:a"
        self.annotations[0]["scenes"][0]["basis"] = "answer_clarification"
        self.prepare()
        with self.assertRaisesRegex(ValueError, "answer-only evidence"):
            self.build()

    def test_navigation_tags_remain_draft_with_issue(self):
        self.annotations[0]["tests"].append(self.rel(concept_id="nav"))
        self.prepare()
        _, report, _, edges = self.build()
        self.assertEqual(report["issues"]["navigation_target_edges"], 1)
        edge = next(e for e in edges if e["relation"] == "TESTS" and e["dst_id"] == "concept:nav")
        self.assertEqual(edge["state"], "draft")

    def test_output_reproducible_and_no_overwrite(self):
        self.prepare()
        first, _, _, _ = self.build("one")
        second, _, _, _ = self.build("two")
        for path in first.iterdir():
            self.assertEqual(path.read_bytes(), (second / path.name).read_bytes(), path.name)
        with self.assertRaises(FileExistsError):
            self.build("one")

    def test_alias_cycle_rejected(self):
        self.changes.extend([
            {"operation": "merge", "source_id": "cycle.a", "target_id": "cycle.b"},
            {"operation": "merge", "source_id": "cycle.b", "target_id": "cycle.a"},
        ])
        self.prepare()
        with self.assertRaisesRegex(ValueError, "alias cycle"):
            self.build()

    def test_context_review_entry_is_not_an_active_scene(self):
        self.prepare()
        path = self.batch / "scene_registry.json"
        catalog = builder.read_json(path)
        catalog["scenes"].append({"id": "scene:mixed", "name": "待分流入口", "definition": "旧混合入口", "tag_policy": "context_review"})
        self.dump(path, catalog)
        self.manifest["scene_registry_sha256"] = builder.sha256(path)
        self.dump(self.batch / "manifest.json", self.manifest)
        _, _, nodes, _ = self.build()
        self.assertNotIn("scene:mixed", {node["id"] for node in nodes})

    def test_detail_profiles_are_metadata_without_new_edges_or_approval(self):
        self.prepare()
        _, _, baseline_nodes, baseline_edges = self.build("before")
        profile_path = self.root / "backend/data/knowledge_node_profiles_v01.json"
        profile_path.parent.mkdir(parents=True)
        self.dump(profile_path, {"concepts": {
            "draft": {"introduction": "候选知识点解释", "key_questions": ["如何理解？"]},
            "new:concept:redis.extra": {"introduction": "新知识解释"},
        }})
        scene_path = self.batch / "scene_registry.json"
        catalog = builder.read_json(scene_path)
        catalog["scenes"][0]["detail_profile"] = {
            "introduction": "完整业务说明", "interview_focus": ["不应自动创建的知识点"]}
        self.dump(scene_path, catalog)
        self.prepare()
        out, report, nodes, edges = self.build("after")
        self.assertEqual(baseline_edges, edges)
        self.assertEqual([(n["id"], n["state"]) for n in baseline_nodes], [(n["id"], n["state"]) for n in nodes])
        self.assertEqual(report["nodes_with_detail_profiles"], {"Concept": 2, "Scene": 1})
        by_id = {n["id"]: n for n in nodes}
        self.assertEqual(by_id["concept:draft"]["properties"]["detail_profile"]["introduction"], "候选知识点解释")
        self.assertEqual(by_id["scene:a"]["properties"]["detail_profile"]["introduction"], "完整业务说明")
        manifest = builder.read_json(out / "graph_manifest.json")
        self.assertEqual(manifest["input_sha256"][str(profile_path.resolve())], builder.sha256(profile_path))


if __name__ == "__main__":
    unittest.main()
