"""GraphRAG query: BM25 over wiki + 1-hop expansion + deterministic synthesis.

Returns a structured, ontology-labeled answer with citations and can append a
query-time retrieval trace under graph/retrieval_traces.jsonl.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import math
import re
import sys
from pathlib import Path

from _lib import GRAPH, ROOT, iter_wiki_pages, load_ontology, parse_page
from build_kb_index import search_index
from logging_config import configure_logging, get_logger

_TOK = re.compile(r"[a-zA-Z][a-zA-Z0-9_]+")
log = get_logger("query_agent")


def _tokenize(s: str) -> list[str]:
    return [t.lower() for t in _TOK.findall(s)]


_BM25_CACHE: tuple[tuple, dict, dict, int] | None = None


def _wiki_fingerprint() -> tuple:
    out = []
    for p in sorted(iter_wiki_pages()):
        try:
            st = p.stat()
            out.append((str(p), st.st_mtime_ns, st.st_size))
        except FileNotFoundError:
            continue
    return tuple(out)


def _bm25_index() -> tuple[dict, dict, int]:
    """Cached BM25 index over the wiki. Rebuilds only when wiki changes."""
    global _BM25_CACHE
    fp = _wiki_fingerprint()
    if _BM25_CACHE is not None and _BM25_CACHE[0] == fp:
        return _BM25_CACHE[1], _BM25_CACHE[2], _BM25_CACHE[3]
    docs: dict[str, list[str]] = {}
    for p in iter_wiki_pages():
        _fm, body = parse_page(p)
        docs[str(p)] = _tokenize(body)
    df: dict[str, int] = collections.Counter()
    for toks in docs.values():
        for t in set(toks):
            df[t] += 1
    _BM25_CACHE = (fp, docs, df, len(docs))
    return docs, df, len(docs)


def _bm25_score(query: list[str], doc: list[str], df: dict, n: int,
                k1: float = 1.5, b: float = 0.75, avgdl: float = 200) -> float:
    tf = collections.Counter(doc)
    score = 0.0
    dl = max(1, len(doc))
    for q in query:
        if q not in tf:
            continue
        idf = math.log(1 + (n - df.get(q, 0) + 0.5) / (df.get(q, 0) + 0.5))
        score += idf * (tf[q] * (k1 + 1)) / (tf[q] + k1 * (1 - b + b * dl / avgdl))
    return score


def _expand(seed_paths: list[str], hops: int = 1) -> list[str]:
    pages = {Path(p): parse_page(Path(p)) for p in iter_wiki_pages()}
    by_id = {fm.get("id"): str(p) for p, (fm, _) in pages.items() if fm.get("id")}
    out = set(seed_paths)
    frontier = set(seed_paths)
    for _ in range(max(0, hops)):
        next_frontier = set()
        for seed in frontier:
            fm, _body = pages.get(Path(seed), ({}, ""))
            for link in (fm.get("links") or []):
                target = by_id.get(link.get("to"))
                if target and target not in out:
                    out.add(target)
                    next_frontier.add(target)
        frontier = next_frontier
    return list(out)


def _ontology_labels() -> tuple[dict[str, str], dict[str, str]]:
    ontology = load_ontology()
    classes = {item["id"]: item.get("description", "") for item in ontology["object_types"]}
    properties = {item["id"]: item.get("description", item["id"]) for item in ontology["link_types"]}
    return classes, properties


def _first_sentences(body: str, limit: int = 2) -> str:
    text = re.sub(r"\s+", " ", body).strip()
    text = re.sub(r"^#\s+[^.?!]+(?:\s+|$)", "", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(s for s in sentences[:limit] if s)[:700]


def _rel_path(path: str) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return path


def _synthesize(
    question: str,
    contexts: list[tuple[str, dict, str]],
    evidence_rows: list[dict] | None = None,
) -> str:
    class_labels, property_labels = _ontology_labels()
    lines = ["# Answer", "", f"**Question:** {question}", ""]
    if not contexts:
        lines.extend([
            "The wiki did not contain matching context for this question.",
            "",
            "**Citations:** none",
        ])
        return "\n".join(lines)

    lines.append("**Grounded findings:**")
    for row in (evidence_rows or [])[:5]:
        text = _first_sentences(row.get("text", ""), limit=2)
        if not text:
            continue
        source = row.get("source_id") or "unknown source"
        lines.append(
            f"- `{row.get('kind')}` evidence from `{source}` says: {text}"
            f" Citation: `{source}`."
        )
    for path, fm, body in contexts[:8]:
        page_id = fm.get("id", Path(path).stem)
        page_type = fm.get("type", "Unknown")
        type_label = class_labels.get(page_type, page_type)
        sources = ", ".join(fm.get("sources") or ["no source listed"])
        summary = _first_sentences(body)
        link_bits = []
        for link in fm.get("links") or []:
            link_bits.append(
                f"{property_labels.get(link.get('type'), link.get('type'))}: [[{link.get('to')}]]"
            )
        link_text = f" Links: {'; '.join(link_bits)}." if link_bits else ""
        lines.append(
            f"- `[[{page_id}]]` ({page_type}: {type_label}) says: {summary}"
            f"{link_text} Citation: `{sources}`."
        )

    lines.extend(["", "**Context pages:**"])
    for path, fm, _body in contexts[:8]:
        lines.append(f"- `{fm.get('id', Path(path).stem)}` at `{_rel_path(path)}`")
    return "\n".join(lines)


def _record_retrieval_trace(result: dict, contexts: list[tuple[str, dict, str]]) -> str:
    GRAPH.mkdir(parents=True, exist_ok=True)
    trace_path = GRAPH / "retrieval_traces.jsonl"
    trace = {
        "kind": "retrieval_trace",
        "trace_id": f"trace_{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "question": result["question"],
        "seed_paths": [_rel_path(path) for path in result["seed_paths"]],
        "expanded_paths": [_rel_path(path) for path in result["expanded_paths"]],
        "grounding_ids": [fm.get("id") for _path, fm, _body in contexts if fm.get("id")],
    }
    with trace_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(trace, sort_keys=True) + "\n")
    return str(trace_path)


def ask(
    question: str,
    top_k: int = 5,
    *,
    source_ids: list[str] | None = None,
    types: list[str] | None = None,
    tags: list[str] | None = None,
    record_trace: bool = True,
) -> dict:
    configure_logging()
    log.info("query.start question=%r top_k=%s source_ids=%s types=%s tags=%s",
             question, top_k, source_ids, types, tags)
    docs, df, n = _bm25_index()
    q_toks = _tokenize(question)
    avgdl = sum(len(d) for d in docs.values()) / max(1, len(docs))
    if source_ids or types or tags:
        seeds, evidence_rows = _filtered_seed_paths(
            question,
            top_k,
            source_ids=source_ids,
            types=types,
            tags=tags,
        )
    else:
        scored = sorted(
            ((path, _bm25_score(q_toks, toks, df, n, avgdl=avgdl)) for path, toks in docs.items()),
            key=lambda x: x[1], reverse=True,
        )
        seeds = [p for p, s in scored[:top_k] if s > 0]
        evidence_rows = []
    expanded = _expand(seeds, hops=1)
    contexts = []
    for p in expanded:
        fm, body = parse_page(Path(p))
        contexts.append((p, fm, body))
    result = {
        "question": question,
        "seed_paths": seeds,
        "expanded_paths": expanded,
        "answer_markdown": _synthesize(question, contexts, evidence_rows),
    }
    if record_trace:
        result["retrieval_trace_path"] = _record_retrieval_trace(result, contexts)
    log.info("query.done seeds=%s expanded=%s trace=%s",
             len(result["seed_paths"]), len(result["expanded_paths"]),
             result.get("retrieval_trace_path"))
    return result


def _filtered_seed_paths(
    question: str,
    top_k: int,
    *,
    source_ids: list[str] | None,
    types: list[str] | None,
    tags: list[str] | None,
) -> tuple[list[str], list[dict]]:
    rows = search_index(
        question,
        source_ids=source_ids,
        types=types,
        tags=tags,
        limit=max(top_k * 3, top_k),
    )
    by_id = _page_path_by_id()
    paths: list[str] = []
    seen = set()
    for row in rows:
        if row["kind"] == "page":
            path = str((ROOT / row["path"]).resolve())
        elif row["kind"] == "chunk" and row.get("source_id") in by_id:
            path = by_id[row["source_id"]]
        else:
            continue
        if path not in seen:
            paths.append(path)
            seen.add(path)
        if len(paths) >= top_k:
            break
    return paths, rows


def _page_path_by_id() -> dict[str, str]:
    out = {}
    for path in iter_wiki_pages():
        fm, _body = parse_page(path)
        if fm.get("id"):
            out[fm["id"]] = str(path.resolve())
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("question", nargs="+")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--source-id", action="append", dest="source_ids")
    parser.add_argument("--type", action="append", dest="types")
    parser.add_argument("--tag", action="append", dest="tags")
    args = parser.parse_args()
    print(json.dumps(
        ask(
            " ".join(args.question),
            top_k=args.top_k,
            source_ids=args.source_ids,
            types=args.types,
            tags=args.tags,
        ),
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
