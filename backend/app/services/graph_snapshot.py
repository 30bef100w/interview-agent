"""Read immutable graph releases without extracting ZIP members to disk."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile


def read_snapshot(path: Path, *, require_release: bool = False):
    def decode(raw):
        return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]

    def read_files(read, names):
        raw = {name: read(name) for name in ("nodes.jsonl", "edges.jsonl")}
        manifest = json.loads(read("runtime_manifest.json")) if "runtime_manifest.json" in names else None
        if manifest is not None:
            if manifest.get("schema_version") != 1 or manifest.get("runtime_ready") is not True:
                raise ValueError("graph release is not runtime ready")
            for name, content in raw.items():
                if hashlib.sha256(content).hexdigest() != manifest.get("output_sha256", {}).get(name):
                    raise ValueError(f"graph release checksum mismatch: {name}")
        elif require_release:
            raise ValueError("production graph requires a verified runtime release")
        nodes, edges = decode(raw["nodes.jsonl"]), decode(raw["edges.jsonl"])
        if manifest is not None:
            if any(row.get("state") != "active" for row in nodes + edges):
                raise ValueError("runtime release must contain only active nodes and edges")
            by_id = {row["id"]: row for row in nodes}
            for edge in edges:
                if edge["relation"] in {"TESTS", "REQUIRES", "INVOLVES"}:
                    if by_id.get(edge["dst_id"], {}).get("properties", {}).get("kind") == "navigation":
                        raise ValueError("runtime release contains a navigation target")
            if manifest.get("node_count") != len(nodes) or manifest.get("edge_count") != len(edges):
                raise ValueError("runtime release counts do not match")
        return nodes, edges, manifest

    if path.is_dir():
        return read_files(lambda name: (path / name).read_bytes(), {p.name for p in path.iterdir()})
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        members = [name for name in names if name == "nodes.jsonl" or name.endswith("/nodes.jsonl")]
        if len(members) != 1 or len(names) != len(set(names)):
            raise ValueError("graph snapshot must contain exactly one nodes.jsonl and unique members")
        prefix = members[0][:-len("nodes.jsonl")]
        return read_files(lambda name: archive.read(prefix + name),
                          {name[len(prefix):] for name in names if name.startswith(prefix)})
