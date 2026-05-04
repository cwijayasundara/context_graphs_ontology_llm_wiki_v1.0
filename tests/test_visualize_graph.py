from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))

from visualize_graph import export_graphml, export_html, load_graph  # noqa: E402


def _write_snapshot(path: Path) -> None:
    records = [
        {"kind": "ontology_class", "id": "Customer"},
        {"kind": "ontology_property", "id": "has_sla", "from": ["Customer"], "to": ["Concept"]},
        {
            "kind": "node",
            "id": "customer_acme",
            "type": "Customer",
            "ontology_class": "Customer",
            "path": "wiki/entities/customer_acme.md",
            "sources": ["raw/docs/acme_msa_2025.pdf"],
        },
        {
            "kind": "node",
            "id": "sla_tier_2",
            "type": "Concept",
            "ontology_class": "Concept",
            "path": "wiki/concepts/sla_tier_2.md",
            "sources": ["raw/docs/sla_policy.md"],
        },
        {
            "kind": "edge",
            "from": "customer_acme",
            "to": "sla_tier_2",
            "type": "has_sla",
            "ontology_property": "has_sla",
        },
        {
            "kind": "provenance",
            "entity_id": "customer_acme",
            "source": "raw/docs/acme_msa_2025.pdf",
        },
    ]
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")


def test_load_graph_keeps_typed_nodes_edges_and_provenance(tmp_path):
    snapshot = tmp_path / "graph.jsonl"
    _write_snapshot(snapshot)

    graph = load_graph(snapshot)

    assert graph.node_count == 2
    assert graph.edge_count == 1
    assert graph.nodes["customer_acme"]["ontology_class"] == "Customer"
    assert graph.edges[0]["label"] == "has_sla"
    assert graph.provenance["customer_acme"] == ["raw/docs/acme_msa_2025.pdf"]


def test_export_html_writes_interactive_vis_network_page(tmp_path):
    snapshot = tmp_path / "graph.jsonl"
    out = tmp_path / "graph.html"
    _write_snapshot(snapshot)

    graph = load_graph(snapshot)
    export_html(graph, out)

    html = out.read_text(encoding="utf-8")
    assert "vis-network" in html
    assert "customer_acme" in html
    assert "sla_tier_2" in html
    assert "has_sla" in html
    assert "raw/docs/acme_msa_2025.pdf" in html


def test_export_graphml_writes_graphml_nodes_and_edges(tmp_path):
    snapshot = tmp_path / "graph.jsonl"
    out = tmp_path / "graph.graphml"
    _write_snapshot(snapshot)

    graph = load_graph(snapshot)
    export_graphml(graph, out)

    xml = out.read_text(encoding="utf-8")
    assert "<graphml" in xml
    assert 'id="customer_acme"' in xml
    assert 'source="customer_acme" target="sla_tier_2"' in xml
