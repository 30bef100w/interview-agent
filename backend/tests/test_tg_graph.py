"""TG 节点复用、真实顺序边和有界正向召回。"""
import tempfile
from pathlib import Path

from app.services.tg_graph import TraceGraphStore


def test_ingest_reuses_probe_and_retrieve_follows_observed_direction():
    with tempfile.TemporaryDirectory() as temp:
        store = TraceGraphStore(Path(temp) / "tg.json")
        chain = {
            "project": "黑马点评",
            "chains": [
                {"intent": "缓存击穿", "problem": "怎么处理热点 Key？", "when": "提到热点数据"},
                {"intent": "分布式锁", "problem": "如何避免重复重建？", "when": "提到加锁"},
            ],
        }
        first = store.ingest_chain(chain, scene_anchor_ids=["scene:local-life"], concept_anchor_ids=["concept:redis"], company_scope="meituan")
        second = store.ingest_chain(chain, scene_anchor_ids=["scene:local-life"], concept_anchor_ids=["concept:redis"], company_scope="meituan")
        assert [x["probe_id"] for x in first["nodes"]] == [x["probe_id"] for x in second["nodes"]]
        store.record_trigger(first["nodes"][0]["probe_id"], session_id=1)
        store.record_trigger(first["nodes"][1]["probe_id"], session_id=1, previous_probe_id=first["nodes"][0]["probe_id"])
        result = store.retrieve(concept_anchor_ids=["concept:redis"], company_scope="meituan", max_depth=2, max_nodes=5)
        assert [node["intent"] for node in result["nodes"]] == ["缓存击穿", "分布式锁"]
        assert result["paths"][-1]["path"] == [first["nodes"][0]["probe_id"], first["nodes"][1]["probe_id"]]


def test_trigger_and_presentation_are_idempotent_per_session_and_stats_are_auditable():
    with tempfile.TemporaryDirectory() as temp:
        store = TraceGraphStore(Path(temp) / "tg.json")
        chain = {"project": "项目", "chains": [{"intent": "缓存", "problem": "怎么查？", "when": "提到缓存"}]}
        node = store.ingest_chain(chain, concept_anchor_ids=["concept:redis"])["nodes"][0]
        probe_id = node["probe_id"]
        assert store.record_trigger(probe_id, session_id=7)
        assert store.record_trigger(probe_id, session_id=7)
        store.retrieve(concept_anchor_ids=["concept:redis"], session_id=7)
        store.retrieve(concept_anchor_ids=["concept:redis"], session_id=7)
        stats = store.stats()
        assert stats["total_hits"] == 1
        assert stats["total_presented"] == 1
        assert stats["observed_edges"] == 0
