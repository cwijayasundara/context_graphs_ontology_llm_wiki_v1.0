"""Domain tools exposed to the DeepAgent. These enforce the ontology contract:
agents cannot freely edit markdown — they invoke typed tools that write valid
frontmatter, validate against ontology/*.yaml, and emit audit rows for actions.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents"))

from _lib import GRAPH, RAW, WIKI, iter_wiki_pages, load_ontology, parse_page  # noqa: E402
from compile_graph import compile_graph as _compile_graph  # noqa: E402
from document_parser import parse_document  # noqa: E402
from lint_agent import lint as _lint  # noqa: E402
from build_kb_index import list_sources as _list_indexed_sources  # noqa: E402
from logging_config import get_logger  # noqa: E402

log = get_logger("tools")


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s.lower()).strip("_")[:60]


def _write_page(rel_dir: str, fm: dict, title: str, body: str) -> str:
    path = WIKI / rel_dir / f"{fm['id']}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_lines = "\n".join(f"{k}: {json.dumps(v)}" for k, v in fm.items())
    path.write_text(f"---\n{fm_lines}\n---\n\n# {title}\n\n{body}\n")
    return str(path.relative_to(ROOT))


def _append_log(line: str) -> None:
    log = WIKI / "log.md"
    if not log.exists():
        log.write_text("# Log\n\n")
    with log.open("a") as f:
        f.write(f"- {dt.datetime.now(dt.timezone.utc).isoformat()} — {line}\n")


@tool
def list_raw_files() -> list[str]:
    """List every file under raw/ (immutable source material). Returns repo-relative paths."""
    return [str(p.relative_to(ROOT)) for p in RAW.rglob("*") if p.is_file()]


@tool
def read_raw_file(path: str) -> str:
    """Read an immutable raw source by repo-relative path (must be under raw/).
    Use for ingestion. Never modify raw/."""
    full = (ROOT / path).resolve()
    if not str(full).startswith(str(RAW.resolve())):
        raise ValueError("read_raw_file is restricted to paths under raw/")
    if not full.exists():
        raise FileNotFoundError(path)
    return full.read_text(errors="replace")


@tool
def read_parsed_document(path: str, provider: str | None = None, force: bool = False) -> dict:
    """Parse and read a raw document into canonical structured content.

    Use this for PDFs, images, spreadsheets, and other layout-heavy documents.
    Returns markdown, chunks, metadata, grounding, and parser warnings. Parsed
    artifacts are cached under parsed/<raw-relative-path-without-extension>/.
    Set provider to local, landingai, or nemotron to override DOCUMENT_PARSER_PROVIDER.
    """
    log.info("tool.read_parsed_document path=%s provider=%s force=%s", path, provider, force)
    parsed = parse_document(path, provider=provider, force=force)
    log.info("tool.read_parsed_document_done path=%s chunks=%s warnings=%s",
             path, len(parsed.chunks), len(parsed.warnings))
    return parsed.to_dict()


@tool
def is_source_ingested(raw_path: str) -> dict:
    """Check whether a raw/ document already has a wiki/sources/*.md page.

    Returns {ingested, source_page, source_id, ingested_at, raw_changed_since_ingest}.
    Call this FIRST in any ingest workflow. If `ingested` is True and
    `raw_changed_since_ingest` is False, do NOT re-parse or re-upsert; report the
    existing source page and stop unless the user explicitly asked for a re-ingest.
    """
    full = (ROOT / raw_path).resolve()
    raw_under_repo = str(full).startswith(str(RAW.resolve()))
    rel = raw_path
    if raw_under_repo:
        rel = str(Path("raw") / full.relative_to(RAW.resolve()))
    sources_dir = WIKI / "sources"
    if sources_dir.exists():
        for page in sources_dir.glob("*.md"):
            try:
                fm, _ = parse_page(page)
            except Exception:
                continue
            page_raw = fm.get("raw_path")
            page_sources = fm.get("sources") or []
            if page_raw == rel or rel in page_sources or page_raw == raw_path:
                raw_changed = False
                if full.exists():
                    raw_changed = full.stat().st_mtime > page.stat().st_mtime
                return {
                    "ingested": True,
                    "source_page": str(page.relative_to(ROOT)),
                    "source_id": fm.get("id"),
                    "ingested_at": fm.get("ingested_at"),
                    "raw_changed_since_ingest": raw_changed,
                }
    return {"ingested": False, "raw_path": rel}


@tool
def list_sources() -> list[dict]:
    """List indexed source documents with metadata, page counts, and chunk counts.
    Builds kb/index.sqlite if it does not exist."""
    return _list_indexed_sources()


@tool
def list_wiki_pages() -> list[dict]:
    """List wiki pages with their id, type, and path."""
    out = []
    for p in iter_wiki_pages():
        fm, _ = parse_page(p)
        out.append({"path": str(p.relative_to(ROOT)),
                    "id": fm.get("id"), "type": fm.get("type")})
    return out


@tool
def read_wiki_page(page_id: str) -> dict:
    """Read a wiki page by its id. Returns frontmatter and body."""
    for p in iter_wiki_pages():
        fm, body = parse_page(p)
        if fm.get("id") == page_id:
            return {"path": str(p.relative_to(ROOT)), "frontmatter": fm, "body": body}
    raise KeyError(f"no wiki page with id {page_id!r}")


@tool
def get_ontology() -> dict:
    """Return the current ontology: object_types, link_types, action_types."""
    return load_ontology()


@tool
def upsert_entity(*, id: str, type: str, name: str, sources: list[str],
                   confidence: float = 0.9, body: str = "",
                   links: list[dict] | None = None,
                   extra: dict | None = None) -> str:
    """Create or update a wiki/entities/<id>.md page. Validates the type and link types
    against the ontology. `links` items must be {to, type}. Returns the relative path.
    """
    ont = load_ontology()
    valid_types = {o["id"] for o in ont["object_types"]}
    if type not in valid_types:
        raise ValueError(f"unknown Object Type {type!r}; valid: {sorted(valid_types)}")
    valid_link_types = {l["id"] for l in ont["link_types"]}
    for link in links or []:
        if link.get("type") not in valid_link_types:
            raise ValueError(f"unknown Link Type {link.get('type')!r}")
    if not sources:
        raise ValueError("sources[] must be non-empty (every claim cites a source)")
    fm: dict[str, Any] = {
        "id": id, "type": type,
        "sources": sources, "confidence": confidence,
        "updated": dt.date.today().isoformat(),
    }
    if links:
        fm["links"] = links
    if extra:
        fm.update(extra)
    rel = _write_page("entities", fm, name, body or f"No body supplied for {name}.")
    log.info("tool.upsert_entity id=%s type=%s sources=%s links=%s", id, type, len(sources), len(links or []))
    _append_log(f"upsert entity {id} -> {rel}")
    return rel


@tool
def upsert_concept(*, id: str, name: str, sources: list[str],
                    confidence: float = 0.9, body: str = "",
                    domain: str | None = None,
                    links: list[dict] | None = None) -> str:
    """Create or update a wiki/concepts/<id>.md page (type: Concept)."""
    ont = load_ontology()
    valid_link_types = {l["id"] for l in ont["link_types"]}
    for link in links or []:
        if link.get("type") not in valid_link_types:
            raise ValueError(f"unknown Link Type {link.get('type')!r}")
    if not sources:
        raise ValueError("sources[] must be non-empty")
    fm: dict[str, Any] = {
        "id": id, "type": "Concept",
        "sources": sources, "confidence": confidence,
        "updated": dt.date.today().isoformat(),
    }
    if domain:
        fm["domain"] = domain
    if links:
        fm["links"] = links
    rel = _write_page("concepts", fm, name, body or f"No body supplied for {name}.")
    log.info("tool.upsert_concept id=%s sources=%s links=%s", id, len(sources), len(links or []))
    _append_log(f"upsert concept {id} -> {rel}")
    return rel


@tool
def upsert_source(*, raw_path: str, summary: str,
                   touched_pages: list[str] | None = None,
                   source_class: str = "document",
                   confidence: float = 1.0) -> str:
    """Record an ingested raw source as wiki/sources/<id>.md. `touched_pages` is the
    list of wiki page ids this source informed."""
    src_id = "src_" + _slug(Path(raw_path).stem)
    fm = {
        "id": src_id, "type": "Source",
        "sources": [raw_path], "confidence": confidence,
        "updated": dt.date.today().isoformat(),
        "raw_path": raw_path, "ingested_at": dt.date.today().isoformat(),
        "source_class": source_class,
    }
    body = summary
    if touched_pages:
        body += "\n\nTouched pages: " + ", ".join(f"[[{p}]]" for p in touched_pages)
    rel = _write_page("sources", fm, Path(raw_path).name, body)
    log.info("tool.upsert_source raw_path=%s source_id=%s touched=%s", raw_path, src_id, len(touched_pages or []))
    _append_log(f"ingest source {raw_path} -> {rel}")
    return rel


@tool
def compile_graph(force: bool = False) -> dict:
    """Rebuild graph/ from wiki/. Idempotent: skips when wiki + ontology are
    unchanged since the last successful compile (returns {skipped: true, ...}).
    Pass force=True only when you need to bypass the fingerprint cache."""
    log.info("tool.compile_graph force=%s", force)
    return _compile_graph(force=force)


@tool
def lint_wiki() -> dict:
    """Run wiki health check (orphans, broken links, stale pages, missing sources).
    Returns the issue list."""
    return _lint()


@tool
def list_actions() -> list[dict]:
    """List the typed Action Types the agent can invoke."""
    ont = load_ontology()
    return [
        {
            "id": a["id"],
            "description": a.get("description", ""),
            "inputs": a.get("inputs", {}),
            "scope": a["scope"],
            "requires_approval": a.get("requires_approval", False),
        }
        for a in ont["action_types"]
    ]


@tool
def invoke_action(*, action_id: str, actor: str, scopes: list[str],
                   inputs: dict, approved: bool = False) -> dict:
    """Invoke a typed Action Type. Validates scope, approval, and input schema.
    The ONLY write path to audited local action adapters or explicitly configured integrations."""
    sys.path.insert(0, str(ROOT / "agents"))
    from action_server import invoke as _invoke
    return _invoke(action_id, actor=actor,
                   actor_scopes=set(scopes) | {"any_authenticated"},
                   inputs=inputs, approved=approved)


def _record_graph_search_trace(query_terms: list[str], seeds: list[str],
                                expanded: list[str], grounding_ids: list[str]) -> str:
    GRAPH.mkdir(parents=True, exist_ok=True)
    trace_path = GRAPH / "retrieval_traces.jsonl"
    now = dt.datetime.now(dt.timezone.utc)
    trace = {
        "kind": "retrieval_trace",
        "trace_id": f"trace_{now.strftime('%Y%m%d%H%M%S%f')}",
        "timestamp": now.isoformat(),
        "source": "graph_search",
        "question": " ".join(query_terms),
        "query_terms": list(query_terms),
        "seed_paths": [str(Path(p).relative_to(ROOT)) for p in seeds],
        "expanded_paths": [str(Path(p).relative_to(ROOT)) for p in expanded],
        "grounding_ids": grounding_ids,
    }
    with trace_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(trace, sort_keys=True) + "\n")
    return str(trace_path)


@tool
def graph_search(query_terms: list[str], top_k: int = 5,
                 source_ids: list[str] | None = None,
                 types: list[str] | None = None,
                 tags: list[str] | None = None,
                 snippet_chars: int = 240,
                 expand_hops: int = 1) -> list[dict]:
    """Search wiki pages, optionally filtered by source ids, ontology types, or tags.
    Filtered searches use the SQLite KB index; unfiltered searches use BM25 over wiki pages.
    Results are expanded by `expand_hops` graph links and returned with frontmatter.
    Tune `snippet_chars` (default 240) and `expand_hops` (default 1, set 0 to skip expansion)
    to control payload size; smaller payloads = faster LLM synthesis."""
    sys.path.insert(0, str(ROOT / "agents"))
    log.info("tool.graph_search terms=%s top_k=%s source_ids=%s types=%s tags=%s",
             query_terms, top_k, source_ids, types, tags)
    from query_agent import _bm25_index, _bm25_score, _expand, _tokenize
    if source_ids or types or tags:
        from query_agent import _filtered_seed_paths
        seeds, _evidence_rows = _filtered_seed_paths(
            " ".join(query_terms),
            top_k,
            source_ids=source_ids,
            types=types,
            tags=tags,
        )
    else:
        docs, df, n = _bm25_index()
        q_toks = [t.lower() for t in query_terms for t in _tokenize(t)]
        avgdl = sum(len(d) for d in docs.values()) / max(1, len(docs))
        scored = sorted(
            ((path, _bm25_score(q_toks, toks, df, n, avgdl=avgdl)) for path, toks in docs.items()),
            key=lambda x: x[1], reverse=True,
        )
        seeds = [p for p, s in scored[:top_k] if s > 0]
    expanded = _expand(seeds, hops=max(0, expand_hops))
    out = []
    grounding_ids: list[str] = []
    snippet_limit = max(80, snippet_chars)
    for p in expanded:
        fm, body = parse_page(Path(p))
        if fm.get("id"):
            grounding_ids.append(fm["id"])
        out.append({"path": str(Path(p).relative_to(ROOT)),
                    "frontmatter": fm,
                    "snippet": body[:snippet_limit]})
    trace_path = _record_graph_search_trace(query_terms, seeds, expanded, grounding_ids)
    log.info("tool.graph_search_done seeds=%s expanded=%s trace=%s",
             len(seeds), len(out), trace_path)
    return out


ALL_TOOLS = [
    list_raw_files, read_raw_file, read_parsed_document,
    is_source_ingested,
    list_sources, list_wiki_pages, read_wiki_page, get_ontology,
    upsert_entity, upsert_concept, upsert_source,
    compile_graph, lint_wiki,
    list_actions, invoke_action,
    graph_search,
]
