"""Runtime adapter tests without application dependencies or paid model calls."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile


BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The adapter itself only needs settings attributes. Keep these tests
        # runnable in the standard-library graph-test environment.
        cls.config = types.ModuleType("app.config")
        cls.config.settings = types.SimpleNamespace(
            graph_snapshot_path="docs/graph-demo/mgkg-9000-v3.zip",
            graph_include_drafts=False, graph_max_projects=3,
            graph_max_scene_seeds=2, graph_max_concept_seeds=6,
            graph_seed_catalog_chars=512000,
            graph_kg_candidate_limit=300, graph_mg_candidate_limit=200,
            graph_final_limit=100, graph_kg_final_quota=60,
            graph_mg_final_quota=40, graph_max_depth=2,
        )
        spec = importlib.util.spec_from_file_location(
            "graph_runtime_under_test", BACKEND / "app/services/graph_retrieval_runtime.py"
        )
        cls.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"app.config": cls.config}):
            spec.loader.exec_module(cls.module)

    def test_default_path_is_repository_relative(self):
        self.assertEqual(
            self.module._snapshot_path(),
            BACKEND.parent / "docs/graph-demo/mgkg-9000-v3.zip",
        )

    def test_zip_loads_only_expected_members(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "graph.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("graph/nodes.jsonl", json.dumps({
                    "id": "concept:redis", "node_type": "Concept", "name": "Redis"
                }) + "\n")
                output.writestr("graph/edges.jsonl", "")
                output.writestr("../../unrelated", "ignored")
            graph = self.module._load_snapshot(archive, False)
            self.assertEqual(list(graph.nodes), ["concept:redis"])
            self.assertFalse((Path(temp) / "unrelated").exists())

    def test_hit_preserves_source_and_graph_provenance(self):
        hit = self.module.GraphRetrievalRuntime._to_hit({
            "question_id": "q1", "canonical_question_id": "canonical:q1",
            "question": "Redis缓存穿透如何处理？", "answer": "布隆过滤器",
            "roles": ["java_backend"], "source_file": "repo/file",
            "channels": ["kg", "mg"], "paths": [{"kind": "scene_direct"}],
            "direct_scene": True,
            "original_tags": {"category": "bagu", "business_scene": ["shop"]},
        })
        self.assertEqual(hit["category"], "bagu")
        self.assertEqual(hit["graph_canonical_question_id"], "canonical:q1")
        self.assertEqual(hit["source_file"], "repo/file")
        self.assertTrue(hit["graph_direct_scene"])

    def test_project_input_is_bounded_and_ignores_invalid_rows(self):
        projects = self.module.GraphRetrievalRuntime._projects({
            "projects": [{"name": str(i)} for i in range(5)] + ["bad"]
        })
        self.assertEqual(len(projects), 3)


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        RuntimeTests.setUpClass.__func__(cls)

    def build_runtime(self, *, broken_ranking=False):
        from app.services.graph_retrieval import GraphIndex, GraphRetriever
        from app.services.graph_seed_resolver import GraphSeedResolver
        nodes = [
            {"id": "scene:shop", "name": "商户服务", "node_type": "Scene"},
            {"id": "concept:agent", "name": "智能体", "node_type": "Concept"},
            {"id": "concept:tools", "name": "工具调用", "node_type": "Concept"},
        ]
        edges = [{"src_id": "concept:agent", "relation": "HAS_SUBTOPIC", "dst_id": "concept:tools"}]
        for index in range(18):
            qid = f"q{index}"
            role = "java_backend" if index == 17 else "agent_dev"
            nodes.append({"id": qid, "node_type": "Question", "name": f"智能体工具执行失败后第{index}种恢复措施如何设计？",
                          "properties": {"roles": [role], "answer": str(index), "original_tags": {"category": "bagu"}}})
            edges.append({"src_id": qid, "relation": "TESTS", "dst_id": "concept:tools"})
            if index < 8:
                edges.append({"src_id": "scene:shop", "relation": "HAS_QUESTION", "dst_id": qid})
        class Model:
            def __init__(self): self.calls = []
            def chat_json(self, system, user):
                self.calls.append((system, user))
                if "目录：" in user:
                    return {"scenes": [{"id": "scene:shop", "evidence": "商户", "reason": "服务商户"}],
                            "concepts": [{"id": "concept:tools", "evidence": "工具", "reason": "工具调用"}]}
                payload = json.loads(user)
                if broken_ranking: return {"ranking": ["fake"]}
                return {"ranking": [row["id"] for row in reversed(payload["candidates"])]}
        runtime = self.module.GraphRetrievalRuntime.__new__(self.module.GraphRetrievalRuntime)
        runtime.llm = Model(); runtime.snapshot = Path("test.zip"); runtime.include_drafts = False
        runtime.graph = GraphIndex(nodes, edges); runtime.retriever = GraphRetriever(runtime.graph)
        runtime.resolver = GraphSeedResolver(runtime.graph)
        self.module.settings.graph_rerank_enabled = True
        self.module.settings.graph_rerank_shortlist = 30
        return runtime

    def test_real_pipeline_keeps_both_routes_and_all_projects(self):
        runtime = self.build_runtime()
        result = runtime.retrieve_projects({"projects": [{"name": "商户工具甲"}, {"name": "商户工具乙"}]},
                                          roles=["agent_dev"], target_role="Agent开发", material_limit=8)
        self.assertEqual(len(result["hits"]), 8)
        self.assertEqual([h["graph_project_id"] for h in result["hits"][:2]], ["p1", "p2"])
        ids = [h["graph_question_id"] for h in result["hits"]]
        self.assertEqual(len(set(ids)), 8)
        self.assertNotIn("q17", ids)
        for project in ("p1", "p2"):
            rows = [h for h in result["hits"] if h["graph_project_id"] == project]
            self.assertEqual({h["graph_assigned_lane"] for h in rows}, {"kg", "mg"})
            self.assertTrue(any(h["graph_direct_scene"] for h in rows))
        self.assertTrue(all(m["rerank_status"] == "llm" for m in result["projects"]))
        self.assertTrue(all(m["rerank_ms"] >= 0 for m in result["projects"]))
        # Reranker gets raw text, not graph score/labels/source paths.
        for system, user in runtime.llm.calls:
            if "重排器" in system:
                payload = json.loads(user)
                self.assertNotIn("roles", payload["candidates"][0])
                self.assertNotIn("graph_score", user)

    def test_bad_ranking_keeps_rule_candidates(self):
        runtime = self.build_runtime(broken_ranking=True)
        result = runtime.retrieve_projects({"projects": [{"name": "商户工具甲"}]}, roles=["agent_dev"], material_limit=4)
        self.assertEqual(len(result["hits"]), 4)
        self.assertEqual(result["projects"][0]["rerank_status"], "rules_fallback")
        self.assertEqual(result["projects"][0]["rerank_error"], "ValueError")

    def test_leaf_bagu_scope_excludes_project_history_and_other_roles(self):
        runtime = self.build_runtime()
        hits = runtime.retrieve_bagu(domain_concept_ids=["concept:tools"], count=50,
                                    roles=["agent_dev"], exclude_question_ids=["q0"],
                                    asked_norms=["智能体工具执行失败后第1种恢复措施如何设计？"], seed=42)
        ids = {h["graph_question_id"] for h in hits}
        self.assertEqual(len(ids), 15)
        self.assertFalse(ids & {"q0", "q1", "q17"})

    def test_rerank_rejects_duplicates_missing_and_foreign_ids(self):
        from app.services.graph_reranker import rerank
        rows = [{"question": "甲？"}, {"question": "乙？"}]
        for ranking in (["C001", "C001"], ["C001"], ["C001", "invented"], [1, "C002"]):
            class Model:
                def chat_json(self, system, user): return {"ranking": ranking}
            with self.subTest(ranking=ranking), self.assertRaises(ValueError):
                rerank(rows, Model(), project_text="示例")


if __name__ == "__main__":
    unittest.main()
