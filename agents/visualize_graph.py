"""Render graph/snapshots/graph.jsonl as an interactive graph and GraphML.

The graph compiler owns the canonical export. This module is a viewer/exporter:
it reads the JSONL snapshot, keeps ontology/provenance metadata, and writes
static artifacts that are easy to inspect locally.
"""
from __future__ import annotations

import argparse
import dataclasses
import html
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = ROOT / "graph" / "snapshots" / "graph.jsonl"
DEFAULT_HTML = ROOT / "graph" / "graph.html"
DEFAULT_GRAPHML = ROOT / "graph" / "graph.graphml"


@dataclasses.dataclass
class GraphView:
    nodes: dict[str, dict[str, Any]]
    edges: list[dict[str, Any]]
    ontology_classes: dict[str, dict[str, Any]]
    ontology_properties: dict[str, dict[str, Any]]
    provenance: dict[str, list[str]]

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)


def load_graph(snapshot: Path = DEFAULT_SNAPSHOT) -> GraphView:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    ontology_classes: dict[str, dict[str, Any]] = {}
    ontology_properties: dict[str, dict[str, Any]] = {}
    provenance: dict[str, list[str]] = {}

    for line in snapshot.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        kind = record.get("kind")
        if kind == "node":
            nodes[record["id"]] = record
        elif kind == "edge":
            edges.append({
                "from": record["from"],
                "to": record["to"],
                "label": record.get("ontology_property") or record.get("type", ""),
                **record,
            })
        elif kind == "ontology_class":
            ontology_classes[record["id"]] = record
        elif kind == "ontology_property":
            ontology_properties[record["id"]] = record
        elif kind == "provenance":
            provenance.setdefault(record["entity_id"], []).append(record["source"])

    return GraphView(
        nodes=nodes,
        edges=edges,
        ontology_classes=ontology_classes,
        ontology_properties=ontology_properties,
        provenance=provenance,
    )


def export_html(graph: GraphView, out: Path = DEFAULT_HTML) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    nodes = [_html_node(node_id, record, graph.provenance.get(node_id, []))
             for node_id, record in sorted(graph.nodes.items())]
    edges = [_html_edge(edge) for edge in graph.edges
             if edge.get("from") in graph.nodes and edge.get("to") in graph.nodes]
    legend = _legend(graph)
    page = _html_page(nodes, edges, legend, graph)
    out.write_text(page, encoding="utf-8")
    return out


def export_graphml(graph: GraphView, out: Path = DEFAULT_GRAPHML) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    graphml = ET.Element("graphml", xmlns="http://graphml.graphdrawing.org/xmlns")
    ET.SubElement(graphml, "key", id="type", **{"for": "node"}, attr_name="type", attr_type="string")
    ET.SubElement(graphml, "key", id="path", **{"for": "node"}, attr_name="path", attr_type="string")
    ET.SubElement(graphml, "key", id="sources", **{"for": "node"}, attr_name="sources", attr_type="string")
    ET.SubElement(graphml, "key", id="label", **{"for": "edge"}, attr_name="label", attr_type="string")
    graph_el = ET.SubElement(graphml, "graph", id="context_graph", edgedefault="directed")

    for node_id, record in sorted(graph.nodes.items()):
        node_el = ET.SubElement(graph_el, "node", id=node_id)
        _data(node_el, "type", str(record.get("ontology_class") or record.get("type", "")))
        _data(node_el, "path", str(record.get("path", "")))
        _data(node_el, "sources", ", ".join(record.get("sources") or []))

    for idx, edge in enumerate(graph.edges):
        if edge.get("from") not in graph.nodes or edge.get("to") not in graph.nodes:
            continue
        edge_el = ET.SubElement(
            graph_el,
            "edge",
            id=f"e{idx}",
            source=edge["from"],
            target=edge["to"],
        )
        _data(edge_el, "label", str(edge.get("label", "")))

    ET.indent(graphml)
    ET.ElementTree(graphml).write(out, encoding="utf-8", xml_declaration=True)
    return out


def _data(parent: ET.Element, key: str, value: str) -> None:
    item = ET.SubElement(parent, "data", key=key)
    item.text = value


def _html_node(node_id: str, record: dict[str, Any], provenance: list[str]) -> dict[str, Any]:
    node_type = record.get("ontology_class") or record.get("type", "Unknown")
    sources = record.get("sources") or []
    title = [
        f"<strong>{html.escape(node_id)}</strong>",
        f"Type: {html.escape(str(node_type))}",
        f"Path: {html.escape(str(record.get('path', '')))}",
    ]
    if sources:
        title.append("Sources: " + html.escape(", ".join(sources)))
    if provenance:
        title.append("Provenance: " + html.escape(", ".join(provenance)))
    return {
        "id": node_id,
        "label": node_id,
        "group": node_type,
        "title": "<br>".join(title),
        "shape": "dot",
        "value": max(8, len(sources) + len(provenance) + 8),
    }


def _html_edge(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "from": edge["from"],
        "to": edge["to"],
        "label": edge.get("label", ""),
        "arrows": "to",
        "title": html.escape(str(edge.get("label", ""))),
    }


def _legend(graph: GraphView) -> str:
    groups = sorted({record.get("ontology_class") or record.get("type", "Unknown")
                     for record in graph.nodes.values()})
    return "".join(f"<span class='pill'>{html.escape(str(group))}</span>" for group in groups)


def _html_page(nodes: list[dict[str, Any]], edges: list[dict[str, Any]],
               legend: str, graph: GraphView) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Context Graph</title>
  <script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
  <style>
    html, body {{ height: 100%; margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    #toolbar {{ height: 56px; display: flex; align-items: center; gap: 16px; padding: 0 16px; border-bottom: 1px solid #d7dce2; background: #f8fafc; }}
    #graph {{ height: calc(100% - 57px); }}
    .stat {{ font-size: 13px; color: #334155; }}
    .pill {{ display: inline-block; padding: 3px 8px; margin-right: 6px; border: 1px solid #cbd5e1; border-radius: 999px; font-size: 12px; background: white; }}
  </style>
</head>
<body>
  <div id="toolbar">
    <strong>Context Graph</strong>
    <span class="stat">{graph.node_count} nodes</span>
    <span class="stat">{graph.edge_count} edges</span>
    <span>{legend}</span>
  </div>
  <div id="graph"></div>
  <script>
    const nodes = new vis.DataSet({json.dumps(nodes)});
    const edges = new vis.DataSet({json.dumps(edges)});
    const container = document.getElementById("graph");
    const data = {{ nodes, edges }};
    const options = {{
      nodes: {{ font: {{ size: 14 }}, borderWidth: 1 }},
      edges: {{ font: {{ align: "middle", size: 11 }}, smooth: {{ type: "dynamic" }} }},
      groups: {{
        Customer: {{ color: {{ background: "#dbeafe", border: "#2563eb" }} }},
        Product: {{ color: {{ background: "#dcfce7", border: "#16a34a" }} }},
        Person: {{ color: {{ background: "#fef3c7", border: "#d97706" }} }},
        Concept: {{ color: {{ background: "#f3e8ff", border: "#9333ea" }} }},
        Source: {{ color: {{ background: "#fee2e2", border: "#dc2626" }} }}
      }},
      physics: {{ stabilization: true, barnesHut: {{ gravitationalConstant: -6000, springLength: 180 }} }},
      interaction: {{ hover: true, navigationButtons: true, keyboard: true }}
    }};
    new vis.Network(container, data, options);
  </script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--graphml", type=Path, default=DEFAULT_GRAPHML)
    parser.add_argument("--no-html", action="store_true")
    parser.add_argument("--no-graphml", action="store_true")
    args = parser.parse_args()

    graph = load_graph(args.snapshot)
    outputs = {}
    if not args.no_html:
        outputs["html"] = str(export_html(graph, args.html))
    if not args.no_graphml:
        outputs["graphml"] = str(export_graphml(graph, args.graphml))
    print(json.dumps({"nodes": graph.node_count, "edges": graph.edge_count, **outputs}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
