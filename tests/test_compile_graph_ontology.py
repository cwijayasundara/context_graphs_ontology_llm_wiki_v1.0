from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))

from compile_graph import compile_graph  # noqa: E402


def _snapshot_records() -> list[dict]:
    snapshot = ROOT / "graph" / "snapshots" / "graph.jsonl"
    return [json.loads(line) for line in snapshot.read_text(encoding="utf-8").splitlines()]


def test_compile_graph_emits_ontology_and_provenance_records():
    result = compile_graph()
    records = _snapshot_records()

    assert result["errors"] == []
    assert {
        "kind": "ontology_class",
        "id": "Customer",
        "description": "A buying organization or individual.",
        "required_properties": ["name"],
        "optional_properties": ["region", "tier", "industry", "primary_contact"],
        "identity_property": "name",
    } in records
    assert any(
        record["kind"] == "ontology_property"
        and record["id"] == "has_sla"
        and record["from"] == ["Customer"]
        and record["to"] == ["Concept"]
        for record in records
    )
    assert any(
        record["kind"] == "node"
        and record["id"] == "nvidia-q4-fy2026-results"
        and record["ontology_class"] == "Concept"
        for record in records
    )
    assert any(
        record["kind"] == "provenance"
        and record["entity_id"] == "nvidia-q4-fy2026-results"
        and record["source"] == "raw/docs/nvidia_8_k_2026.pdf"
        for record in records
    )
