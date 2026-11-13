"""Publication boundaries: drafts, hidden children, checksums, and explicit routes."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.services.graph_retrieval import GraphIndex, GraphRetriever, ProjectQuery
from app.services.graph_snapshot import read_snapshot

SPEC = importlib.util.spec_from_file_location("runtime_release_builder", BACKEND / "scripts/build_graph_runtime_release.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def node(nid, node_type="Concept", state="active", **props):
    return {"id": nid, "node_type": node_type, "state": state, "name": nid, "properties": props}


def edge(src, rel, dst, state="active"):
    return {"src_id": src, "relation": rel, "dst_id": dst, "state": state}


class RuntimeReleaseTests(unittest.TestCase):
    def fixture(self, root):
        source = root / "source"; source.mkdir()
        nodes = [node("parent"), node("leaf"), node("draft", state="draft"),
                 node("nav", kind="navigation"),
                 node("q", "Question", sample_id="F1", original_tags={"category": "bagu"}),
                 node("parentq", "Question", sample_id="F2", original_tags={"category": "bagu"}),
                 node("held", "Question", sample_id="F3"), node("navq", "Question", sample_id="F4"),
                 node("hr", "Question", sample_id="F5"), node("unknown", "Question", sample_id="F6")]
        edges = [edge("parent", "HAS_SUBTOPIC", "draft", "draft"),
                 edge("q", "TESTS", "leaf"), edge("parentq", "TESTS", "parent"),
                 edge("held", "TESTS", "draft", "draft"), edge("navq", "TESTS", "nav")]
        report = {"source_total_records": 6, "status_counts": {"labeled": 6}}
        payload = {"nodes.jsonl": builder.jsonl(nodes), "edges.jsonl": builder.jsonl(edges),
                   "mapping_report.json": builder.encode(report)}
        for name, raw in payload.items(): (source / name).write_bytes(raw)
        (source / "graph_manifest.json").write_bytes(builder.encode({
            "production_ready": False,
            "output_sha256": {name: hashlib.sha256(raw).hexdigest() for name, raw in payload.items()},
        }))
        approvals = root / "approvals.json"
        approvals.write_text(json.dumps({"questions": [{"sample_id": "F5", "question": "hr", "kind": "behavioral"}]}))
        return source, approvals

    def test_release_excludes_drafts_navigation_and_unapproved_orphans_without_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source, approvals = self.fixture(root)
            before = {f.name: f.read_bytes() for f in source.iterdir()}
            report = builder.build_release(source, root / "runtime.zip", approvals, audit_out=root / "routes.jsonl")
            nodes, edges, manifest = read_snapshot(root / "runtime.zip", require_release=True)
            graph = GraphIndex(nodes, edges)
            self.assertNotIn("draft", graph.nodes)
            self.assertNotIn("held", graph.nodes)
            self.assertNotIn("navq", graph.nodes)
            self.assertNotIn("unknown", graph.nodes)
            self.assertEqual(graph.general_question_ids, ("hr",))
            self.assertFalse(graph.is_leaf("parent"))
            self.assertEqual(set(graph.bagu_pool(["parent", "leaf"])[1]), {"q"})
            self.assertEqual(report["removed_active_navigation_edges"], 1)
            self.assertFalse(manifest["semantic_review_complete"])
            self.assertEqual({f.name: f.read_bytes() for f in source.iterdir()}, before)
            routes = {r["sample_id"]: r["route"] for r in map(json.loads, (root / "routes.jsonl").read_text().splitlines())}
            self.assertEqual(routes["F3"], "held_semantic_edges")
            self.assertEqual(routes["F6"], "held_unlinked")

    def test_corrupted_release_and_unverified_production_snapshots_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source, approvals = self.fixture(root)
            with self.assertRaisesRegex(ValueError, "verified runtime release"):
                read_snapshot(source, require_release=True)
            builder.build_release(source, root / "runtime.zip", approvals)
            with zipfile.ZipFile(root / "runtime.zip") as archive:
                payload = {name: archive.read(name) for name in archive.namelist()}
            payload["nodes.jsonl"] += b"\n"
            with zipfile.ZipFile(root / "corrupt.zip", "w") as archive:
                for name, raw in payload.items(): archive.writestr(name, raw)
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                read_snapshot(root / "corrupt.zip", require_release=True)

    def test_upstream_corruption_or_mismatched_approval_prevents_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source, approvals = self.fixture(root)
            approvals.write_text(json.dumps({"questions": [{"sample_id": "F5", "question": "changed", "kind": "behavioral"}]}))
            with self.assertRaisesRegex(ValueError, "approval does not match"):
                builder.build_release(source, root / "runtime.zip", approvals)
            with (source / "nodes.jsonl").open("a") as handle: handle.write("\n")
            with self.assertRaisesRegex(ValueError, "upstream checksum mismatch"):
                builder.build_release(source, root / "runtime.zip", approvals)
            self.assertFalse((root / "runtime.zip").exists())

    def test_non_active_states_are_not_recalled_even_in_draft_experiments(self):
        nodes = [node("active"), node("retired", state="retired"),
                 node("q", "Question"), node("oldq", "Question", state="retired")]
        edges = [edge("q", "TESTS", "active", "retired"), edge("q", "TESTS", "retired"),
                 edge("oldq", "TESTS", "active")]
        for drafts in (False, True):
            graph = GraphIndex(deepcopy(nodes), deepcopy(edges), include_drafts=drafts)
            self.assertFalse(graph.eligible("retired"))
            self.assertEqual(graph.neighbors("active", "TESTS", reverse=True), [])


class PackagedReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        nodes, edges, cls.manifest = read_snapshot(BACKEND / "graph/mgkg-45033-active-v1.zip", require_release=True)
        cls.graph = GraphIndex(nodes, edges)

    def test_bundled_release_covers_full_source_but_never_promotes_pending_semantics(self):
        self.assertEqual(self.manifest["source_records"], 45033)
        self.assertFalse(self.manifest["source_production_ready"])
        self.assertFalse(self.manifest["semantic_review_complete"])
        self.assertTrue(all(n["state"] == "active" for n in self.graph.nodes.values()))
        self.assertTrue(all(state == "active" for state in self.graph.edge_states.values()))
        self.assertEqual(len(self.graph.general_question_ids), 8)
        self.assertGreater(self.manifest["question_routes"]["held_semantic_edges"], 0)
        self.assertTrue(any(n["properties"].get("companies") or n["properties"].get("company")
                            for n in self.graph.nodes.values() if n["node_type"] == "Question"))

    def test_real_seeds_return_unique_bounded_active_paths_and_separate_bagu_pool(self):
        retriever = GraphRetriever(self.graph)
        for concept in ("concept:agent", "concept:rag", "concept:redis", "concept:mysql", "concept:java"):
            with self.subTest(concept=concept):
                result = retriever.project_retrieve(ProjectQuery(concept_ids=(concept,)), seed=42)
                questions = result["questions"]
                self.assertTrue(questions)
                self.assertLessEqual(len(questions), 100)
                self.assertLessEqual(len(result["candidates"]), 500)
                identities = {q["canonical_question_id"] for q in questions}
                self.assertEqual(len(identities), len(questions))
                for question in questions:
                    for path in question["paths"]:
                        self.assertLessEqual(path["concept_depth"], 2)
                        self.assertTrue(all(step["state"] == "active" for step in path["steps"]))
                bagu = retriever.bagu_retrieve(domain_concept_ids=[concept], count=5, seed=42,
                                                exclude_question_ids=identities)
                self.assertTrue(bagu["questions"])
                self.assertFalse(identities & {q["canonical_question_id"] for q in bagu["questions"]})
                self.assertTrue(all(self.graph.is_leaf(leaf) for q in bagu["questions"] for leaf in q["leaf_concept_ids"]))

    def test_real_scene_and_concept_both_contribute_without_general_questions(self):
        out = GraphRetriever(self.graph).project_retrieve(ProjectQuery(
            scene_ids=("scene:candidate:proposed.scene.customer_service",), concept_ids=("concept:rag",)), seed=42)
        self.assertTrue(any(q["direct_scene"] for q in out["questions"]))
        self.assertTrue(any("mg" in q["channels"] for q in out["questions"]))
        self.assertFalse({q["question_id"] for q in out["questions"]} & set(self.graph.general_question_ids))


if __name__ == "__main__":
    unittest.main()
