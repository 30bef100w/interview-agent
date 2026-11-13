#!/usr/bin/env python3
"""Deployment preflight: verify the effective configured graph without any LLM call."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import settings
from app.services.graph_retrieval_runtime import GraphRetrievalRuntime


def main():
    if not settings.graph_retrieval_enabled:
        print(json.dumps({"graph_enabled": False, "backend": "legacy"}))
        return
    if settings.graph_include_drafts:
        raise ValueError("deployment requires GRAPH_INCLUDE_DRAFTS=false")
    started = time.perf_counter()
    runtime = GraphRetrievalRuntime(None)
    if not getattr(runtime.graph, "runtime_manifest", None):
        raise ValueError("deployment requires runtime_manifest.json")
    print(json.dumps({
        "graph_enabled": True, "snapshot": str(runtime.snapshot),
        "include_drafts": runtime.include_drafts, "node_count": len(runtime.graph.nodes),
        "edge_count": len(runtime.graph.edge_states),
        "general_pool_count": len(runtime.graph.general_question_ids),
        "seed_catalog_chars": len(runtime.resolver.catalog),
        "load_ms": round((time.perf_counter() - started) * 1000, 2),
        "release": runtime.graph.runtime_manifest,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
