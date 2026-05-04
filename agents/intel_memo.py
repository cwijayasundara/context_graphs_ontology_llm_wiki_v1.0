"""Entity Intelligence Memo Engine.

Produces a typed, audited memo about a target entity by combining
ontology-typed graph traversal, provenance audit, contradiction detection,
derived-metric rollup, and coverage-gap analysis. The deterministic core
runs WITHOUT an LLM; the LLM is only invoked to draft final prose around
already-extracted structured findings.

This is the architectural contrast to RAG: structure first, prose last.
Standard RAG cannot:

  - Traverse typed edges (no edge schema in a vector index).
  - Detect cross-page contradictions structurally (no entity coreference).
  - Audit freshness against ingest timestamps (no provenance graph).
  - Roll up derived metrics across a sub-graph (no aggregation primitive).
  - Identify coverage gaps relative to an ontology (no schema).
  - Write back through governed Action Types (no audit surface).

CLI:
    python agents/intel_memo.py memo nvidia-corp --actor analyst --hops 2
    python agents/intel_memo.py memo nvidia-corp --actor analyst --no-llm
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))
sys.path.insert(0, str(ROOT))

from _lib import GRAPH, WIKI, iter_wiki_pages, load_ontology, parse_page  # noqa: E402
from action_server import invoke as invoke_action  # noqa: E402
from logging_config import configure_logging, get_logger  # noqa: E402

log = get_logger("intel_memo")


# --------------------------------------------------------------------------
# Graph index — typed nodes, typed edges, source provenance.
# --------------------------------------------------------------------------

def build_graph_index() -> dict[str, Any]:
    """Walk wiki/ once. Return id->page index, id->type, id->sources, edge list."""
    pages: dict[str, dict] = {}
    edges: list[dict] = []
    for path in iter_wiki_pages():
        fm, body = parse_page(path)
        page_id = fm.get("id")
        if not page_id:
            continue
        pages[page_id] = {
            "id": page_id,
            "type": fm.get("type"),
            "path": str(path.relative_to(ROOT)),
            "sources": list(fm.get("sources") or []),
            "confidence": float(fm.get("confidence", 0.5)),
            "updated": str(fm.get("updated", "")),
            "body": body,
            "frontmatter": fm,
        }
        for link in fm.get("links") or []:
            if not isinstance(link, dict) or "to" not in link:
                continue
            edges.append({
                "from": page_id,
                "to": link["to"],
                "type": link.get("type"),
            })
    out_adj: dict[str, list[dict]] = defaultdict(list)
    in_adj: dict[str, list[dict]] = defaultdict(list)
    for edge in edges:
        out_adj[edge["from"]].append(edge)
        in_adj[edge["to"]].append(edge)
    return {"pages": pages, "edges": edges, "out_adj": out_adj, "in_adj": in_adj}


def traverse(graph: dict, seed: str, hops: int) -> dict[str, int]:
    """Bidirectional BFS from seed. Returns {page_id: hop_distance}."""
    if seed not in graph["pages"]:
        return {}
    visited: dict[str, int] = {seed: 0}
    frontier = [seed]
    for depth in range(1, max(0, hops) + 1):
        next_frontier: list[str] = []
        for node in frontier:
            neighbors = (
                [e["to"] for e in graph["out_adj"].get(node, [])]
                + [e["from"] for e in graph["in_adj"].get(node, [])]
            )
            for n in neighbors:
                if n not in visited and n in graph["pages"]:
                    visited[n] = depth
                    next_frontier.append(n)
        frontier = next_frontier
    return visited


# --------------------------------------------------------------------------
# Coverage analysis — counts touched pages per ontology Object Type.
# --------------------------------------------------------------------------

def coverage_report(graph: dict, touched: dict[str, int]) -> dict[str, Any]:
    ontology = load_ontology()
    expected_types = {o["id"] for o in ontology["object_types"]}
    counts: dict[str, int] = {t: 0 for t in expected_types}
    by_type: dict[str, list[str]] = defaultdict(list)
    for pid in touched:
        ptype = graph["pages"][pid].get("type")
        if ptype in counts:
            counts[ptype] += 1
            by_type[ptype].append(pid)
    gaps = sorted([t for t, c in counts.items() if c == 0])
    return {"counts": counts, "by_type": dict(by_type), "gaps": gaps}


# --------------------------------------------------------------------------
# Provenance audit — every claim → source → ingest timestamp + confidence.
# --------------------------------------------------------------------------

def provenance_chain(graph: dict, touched: dict[str, int]) -> list[dict]:
    chain = []
    source_pages = {pid for pid, p in graph["pages"].items() if p.get("type") == "Source"}
    for pid in sorted(touched, key=lambda x: (touched[x], x)):
        page = graph["pages"][pid]
        for src in page["sources"]:
            ingested_at = None
            source_class = None
            source_page_id = None
            for sid in source_pages:
                spage = graph["pages"][sid]
                if spage["frontmatter"].get("raw_path") == src or src in spage["sources"]:
                    ingested_at = spage["frontmatter"].get("ingested_at")
                    source_class = spage["frontmatter"].get("source_class")
                    source_page_id = sid
                    break
            chain.append({
                "claim_page": pid,
                "claim_type": page.get("type"),
                "claim_confidence": page["confidence"],
                "claim_updated": page["updated"],
                "raw_source": src,
                "source_page": source_page_id,
                "source_class": source_class,
                "ingested_at": ingested_at,
            })
    return chain


# --------------------------------------------------------------------------
# Freshness — page.updated < source.ingested_at means stale derivation.
# --------------------------------------------------------------------------

def freshness_warnings(graph: dict, chain: list[dict]) -> list[dict]:
    warnings = []
    for row in chain:
        if not row["ingested_at"] or not row["claim_updated"]:
            continue
        if row["claim_updated"] < row["ingested_at"][:10]:
            warnings.append({
                "page": row["claim_page"],
                "claim_updated": row["claim_updated"],
                "source_ingested_at": row["ingested_at"],
                "raw_source": row["raw_source"],
                "severity": "stale_derivation",
            })
    return warnings


# --------------------------------------------------------------------------
# Contradiction detection — extract numeric/percent claims and cluster
# them by topic. Multiple distinct values for the same topic = contradiction.
# --------------------------------------------------------------------------

_PCT_RE = re.compile(r"\b(\d{1,3}(?:\.\d+)?)\s*%")
_USD_BIL_RE = re.compile(r"\$(\d+(?:\.\d+)?)\s*(?:billion|B|bn)\b", re.IGNORECASE)
_USD_MIL_RE = re.compile(r"\$(\d+(?:\.\d+)?)\s*(?:million|M|mn)\b", re.IGNORECASE)


def _extract_claims(text: str) -> list[dict]:
    out = []
    for m in _PCT_RE.finditer(text):
        ctx = text[max(0, m.start() - 80): m.end() + 40].lower()
        kind = "gross_margin" if "gross margin" in ctx else (
            "operating_margin" if "operating margin" in ctx else "percent")
        out.append({"kind": kind, "value": float(m.group(1)), "unit": "%", "context": ctx.strip()})
    for m in _USD_BIL_RE.finditer(text):
        ctx = text[max(0, m.start() - 80): m.end() + 40].lower()
        kind = ("revenue" if "revenue" in ctx else
                "net_income" if "net income" in ctx else
                "operating_income" if "operating income" in ctx else "usd_billion")
        out.append({"kind": kind, "value": float(m.group(1)), "unit": "USD_B", "context": ctx.strip()})
    for m in _USD_MIL_RE.finditer(text):
        ctx = text[max(0, m.start() - 80): m.end() + 40].lower()
        out.append({"kind": "usd_million", "value": float(m.group(1)), "unit": "USD_M",
                    "context": ctx.strip()})
    return out


_SEGMENT_HINTS = (
    ("data_center", ("data center", "datacenter")),
    ("gaming", ("gaming",)),
    ("automotive", ("automotive",)),
    ("professional_visualization", ("professional visualization", "proviz")),
    ("nvlink", ("nvlink",)),
    ("balance_sheet", ("balance sheet", "total assets", "current assets", "cash/cash equivalents", "marketable securities")),
    ("shareholder_returns", ("share repurchase", "dividend", "shareholder")),
    ("partnership", ("partnership", "collaboration", "investment in", "licensing")),
)


def _segment_of(context: str) -> str:
    for seg, hints in _SEGMENT_HINTS:
        for h in hints:
            if h in context:
                return seg
    return "company_wide"


def _period_of(context: str) -> str:
    if "q4 fy2026" in context or "q4 fiscal 2026" in context:
        return "q4_fy2026"
    if "q1 fy2027" in context or "q1 fiscal 2027" in context:
        return "q1_fy2027"
    if "fy2025" in context or "fiscal 2025" in context:
        return "fy2025"
    if "fy2026" in context or "fiscal 2026" in context or "fiscal year 2026" in context:
        return "fy2026"
    return "unspecified"


def contradictions_report(graph: dict, touched: dict[str, int]) -> list[dict]:
    """Group numeric claims by (kind, period, segment). Flag clusters with
    >1 distinct value as contradictions.

    Segment dimension prevents false positives from disaggregated subtotals:
    $62.3B Data Center revenue and $68.1B company-wide revenue land in
    different buckets so they no longer collide as 'two values for Q4 revenue'.
    Period dimension separates Q4 from full-year claims.
    """
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for pid in touched:
        page = graph["pages"][pid]
        if page["type"] not in {"Concept", "Customer"}:
            continue
        for claim in _extract_claims(page["body"]):
            ctx = claim["context"]
            key = (claim["kind"], _period_of(ctx), _segment_of(ctx))
            grouped[key].append({**claim, "page": pid})
    flagged = []
    for (kind, period, segment), claims in grouped.items():
        # Skip noise: only meaningful kinds and segments where a single canonical
        # value should exist.
        if kind in {"percent", "usd_billion", "usd_million"}:
            # These are too ambiguous without further context; only fire when
            # constrained to a known segment AND a known period.
            if segment == "company_wide" or period == "unspecified":
                continue
        distinct = sorted({(c["value"], c["unit"]) for c in claims})
        if len(distinct) > 1:
            flagged.append({
                "kind": kind, "period": period, "segment": segment,
                "distinct_values": [{"value": v, "unit": u} for v, u in distinct],
                "claims": claims,
                "pages": sorted({c["page"] for c in claims}),
            })
    return flagged


# --------------------------------------------------------------------------
# Derived-metric rollup — aggregate numeric facts across the touched subgraph.
# --------------------------------------------------------------------------

def metric_rollup(graph: dict, touched: dict[str, int]) -> dict[str, Any]:
    revenues_b: list[tuple[str, float]] = []
    margins_pct: list[tuple[str, float]] = []
    for pid in touched:
        page = graph["pages"][pid]
        for claim in _extract_claims(page["body"]):
            if claim["kind"] == "revenue":
                revenues_b.append((pid, claim["value"]))
            elif claim["kind"] == "gross_margin":
                margins_pct.append((pid, claim["value"]))
    return {
        "revenue_claims_usd_b": revenues_b,
        "gross_margin_claims_pct": margins_pct,
        "max_revenue_usd_b": max((v for _, v in revenues_b), default=None),
        "min_revenue_usd_b": min((v for _, v in revenues_b), default=None),
        "max_gross_margin_pct": max((v for _, v in margins_pct), default=None),
        "min_gross_margin_pct": min((v for _, v in margins_pct), default=None),
    }


# --------------------------------------------------------------------------
# Memo orchestrator — assemble everything into a reasoning trace + draft body.
# --------------------------------------------------------------------------

def build_memo(target: str, hops: int = 2) -> dict[str, Any]:
    graph = build_graph_index()
    if target not in graph["pages"]:
        raise KeyError(f"target entity {target!r} not in wiki")
    touched = traverse(graph, target, hops=hops)
    coverage = coverage_report(graph, touched)
    chain = provenance_chain(graph, touched)
    freshness = freshness_warnings(graph, chain)
    contradictions = contradictions_report(graph, touched)
    metrics = metric_rollup(graph, touched)

    cited_ids = sorted(touched.keys())
    flagged_ids = sorted(
        {w["page"] for w in freshness}
        | {pid for c in contradictions for pid in c["pages"]}
    )

    return {
        "target_entity": target,
        "target_type": graph["pages"][target].get("type"),
        "hops": hops,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "touched": touched,
        "coverage": coverage,
        "provenance_chain": chain,
        "freshness_warnings": freshness,
        "contradictions": contradictions,
        "metrics": metrics,
        "cites": cited_ids,
        "flagged": flagged_ids,
    }


def draft_memo_body(trace: dict[str, Any], graph: dict | None = None) -> str:
    g = graph or build_graph_index()
    target = trace["target_entity"]
    target_page = g["pages"].get(target, {})
    cov = trace["coverage"]
    lines = [
        f"**Target:** [[{target}]] (type: `{trace['target_type']}`)  ",
        f"**Traversal:** {trace['hops']}-hop, {len(trace['touched'])} pages reached  ",
        f"**Generated:** {trace['generated_at']}",
        "",
        "## Coverage by Object Type",
        "",
    ]
    for type_name, count in sorted(cov["counts"].items()):
        examples = cov["by_type"].get(type_name, [])[:3]
        ex = ", ".join(f"[[{e}]]" for e in examples) if examples else "_none_"
        lines.append(f"- **{type_name}**: {count} — {ex}")
    if cov["gaps"]:
        lines.extend(["", f"**Gaps:** {', '.join(cov['gaps'])} — no pages of these types in the {trace['hops']}-hop neighborhood."])

    lines.extend(["", "## Derived Metrics"])
    metrics = trace["metrics"]
    if metrics["max_revenue_usd_b"] is not None:
        lines.append(f"- Revenue range across cited pages: ${metrics['min_revenue_usd_b']:.1f}B – ${metrics['max_revenue_usd_b']:.1f}B")
    if metrics["max_gross_margin_pct"] is not None:
        lines.append(f"- Gross margin range across cited pages: {metrics['min_gross_margin_pct']:.1f}% – {metrics['max_gross_margin_pct']:.1f}%")

    if trace["contradictions"]:
        lines.extend(["", "## Contradictions Detected"])
        for c in trace["contradictions"]:
            vals = ", ".join(f"{v['value']}{v['unit']}" for v in c["distinct_values"])
            pages = ", ".join(f"[[{p}]]" for p in c["pages"])
            lines.append(f"- **{c['kind']} / {c['period']} / {c.get('segment','?')}** — distinct values seen: {vals}; pages: {pages}")
    else:
        lines.extend(["", "## Contradictions Detected", "_None._"])

    if trace["freshness_warnings"]:
        lines.extend(["", "## Freshness Warnings"])
        for w in trace["freshness_warnings"]:
            lines.append(f"- [[{w['page']}]] last updated {w['claim_updated']} but source `{w['raw_source']}` ingested {w['source_ingested_at']}")
    else:
        lines.extend(["", "## Freshness Warnings", "_All cited pages are at least as new as their sources._"])

    lines.extend(["", "## Provenance Chain (first 10 entries)"])
    for row in trace["provenance_chain"][:10]:
        lines.append(
            f"- [[{row['claim_page']}]] (`{row['claim_type']}`, conf={row['claim_confidence']:.2f}) "
            f"← `{row['raw_source']}` (class={row['source_class'] or 'n/a'}, ingested={row['ingested_at'] or 'n/a'})"
        )
    if len(trace["provenance_chain"]) > 10:
        lines.append(f"- _… and {len(trace['provenance_chain']) - 10} more provenance rows in the trace artifact._")

    lines.extend(["", "## Cited Pages", ""])
    for pid in trace["cites"]:
        page = g["pages"][pid]
        marker = " ⚠" if pid in trace["flagged"] else ""
        lines.append(f"- [[{pid}]] ({page.get('type')}){marker}")

    body = "\n".join(lines)
    if target_page.get("body"):
        body += f"\n\n## Target Snapshot\n\n{target_page['body'][:600]}"
    return body


def publish(target: str, *, actor: str, hops: int = 2,
            scopes: set[str] | None = None) -> dict[str, Any]:
    """Build the memo and write it through the audited Action Type."""
    configure_logging()
    log.info("intel_memo.build target=%s hops=%s actor=%s", target, hops, actor)
    trace = build_memo(target, hops=hops)
    body = draft_memo_body(trace)
    title = f"Intel Memo: {target}"

    flag_results = []
    for fid in trace["flagged"]:
        reason = "contradiction" if any(fid in c["pages"] for c in trace["contradictions"]) else "stale"
        detail = f"flagged by intel memo {title!r}; hops={hops}"
        flag_results.append(invoke_action(
            "flag_concept_review",
            actor=actor,
            actor_scopes=(scopes or set()) | {"any_authenticated"},
            inputs={"concept_id": fid, "reason": reason, "detail": detail},
        ))

    publish_result = invoke_action(
        "publish_intel_memo",
        actor=actor,
        actor_scopes=(scopes or set()) | {"any_authenticated"},
        inputs={
            "title": title,
            "target_entity": target,
            "body_markdown": body,
            "cites": trace["cites"],
            "flagged": trace["flagged"],
            "reasoning_trace": trace,
        },
    )
    log.info("intel_memo.published memo=%s flagged=%s", publish_result.get("memo_id"), len(flag_results))
    return {"publish": publish_result, "flagged": flag_results, "trace_summary": {
        "touched": len(trace["touched"]),
        "contradictions": len(trace["contradictions"]),
        "freshness_warnings": len(trace["freshness_warnings"]),
        "coverage_gaps": trace["coverage"]["gaps"],
    }}


def _query_memo_subgraph(memo_id: str | None, link_type: str) -> list[dict]:
    """Run a typed Kuzu query over the memo subgraph. Returns rows as dicts."""
    import kuzu  # local import; kuzu is optional

    conn = kuzu.Connection(kuzu.Database(str(GRAPH / "kuzu.db")))
    if memo_id:
        cypher = (
            "MATCH (m:Entity {type:'Memo', id:$mid})-"
            "[:Link {type:$lt}]->(c:Entity) "
            "RETURN m.id AS memo, c.id AS target, c.type AS target_type"
        )
        res = conn.execute(cypher, {"mid": memo_id, "lt": link_type})
    else:
        cypher = (
            "MATCH (m:Entity {type:'Memo'})-"
            "[:Link {type:$lt}]->(c:Entity) "
            "RETURN m.id AS memo, c.id AS target, c.type AS target_type"
        )
        res = conn.execute(cypher, {"lt": link_type})
    rows = []
    while res.has_next():
        memo, target, target_type = res.get_next()
        rows.append({"memo": memo, "target": target, "target_type": target_type})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("memo", help="Build and publish an intel memo for an entity.")
    p.add_argument("target", help="Wiki id of the target entity (e.g. nvidia-corp).")
    p.add_argument("--actor", required=True)
    p.add_argument("--hops", type=int, default=2)
    p.add_argument("--scopes", default="any_authenticated")
    p.add_argument("--dry-run", action="store_true",
                   help="Build trace + draft body, print, but do not invoke actions.")

    q = sub.add_parser("query", help="Run a typed Kuzu query over the memo subgraph.")
    q.add_argument("--memo-id", help="Restrict to one memo id; omit for all memos.")
    q.add_argument("--link", default="flags_concept",
                   choices=["flags_concept", "cites_evidence", "targets"],
                   help="Which typed edge to traverse (default: flags_concept).")

    args = parser.parse_args()

    if args.cmd == "query":
        rows = _query_memo_subgraph(args.memo_id, args.link)
        print(json.dumps(rows, indent=2))
        return 0

    if args.cmd != "memo":
        parser.error("unknown command")

    scopes = {s.strip() for s in args.scopes.split(",") if s.strip()}
    if args.dry_run:
        trace = build_memo(args.target, hops=args.hops)
        graph = build_graph_index()
        body = draft_memo_body(trace, graph=graph)
        summary = {
            "touched": len(trace["touched"]),
            "contradictions": len(trace["contradictions"]),
            "freshness_warnings": len(trace["freshness_warnings"]),
            "coverage_gaps": trace["coverage"]["gaps"],
            "cites": len(trace["cites"]),
            "flagged": len(trace["flagged"]),
        }
        print(json.dumps({"summary": summary}, indent=2))
        print("\n--- DRAFT MEMO ---\n")
        print(body)
        return 0

    result = publish(args.target, actor=args.actor, hops=args.hops, scopes=scopes)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
