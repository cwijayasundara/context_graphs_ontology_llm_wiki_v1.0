"""Build a SQLite metadata and FTS index over wiki pages and parsed chunks."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from _lib import ROOT, iter_wiki_pages, parse_page
from logging_config import configure_logging, get_logger

KB = ROOT / "kb"
DEFAULT_DB = KB / "index.sqlite"
PARSED = ROOT / "parsed"
log = get_logger("build_kb_index")


def build_index(db_path: Path = DEFAULT_DB) -> dict:
    configure_logging()
    log.info("kb_index.start db=%s", db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    with sqlite3.connect(db_path) as conn:
        _create_schema(conn)
        counts = _index_wiki(conn)
        counts["chunks"] = _index_chunks(conn)
        conn.commit()
    result = {"db": str(db_path), **counts}
    log.info("kb_index.done sources=%s pages=%s links=%s chunks=%s",
             result["sources"], result["pages"], result["links"], result["chunks"])
    return result


def search_index(
    query: str,
    *,
    db_path: Path = DEFAULT_DB,
    source_ids: list[str] | None = None,
    types: list[str] | None = None,
    tags: list[str] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    if not db_path.exists():
        build_index(db_path=db_path)
    configure_logging()
    log.info("kb_index.search query=%r source_ids=%s types=%s tags=%s limit=%s",
             query, source_ids, types, tags, limit)
    where = ["content_fts match ?"]
    params: list[Any] = [_fts_query(query)]
    if source_ids:
        where.append("source_id in (%s)" % ",".join("?" for _ in source_ids))
        params.extend(source_ids)
    if types:
        where.append("(kind = 'chunk' or coalesce(type, '') in (%s))" % ",".join("?" for _ in types))
        params.extend(types)
    if tags:
        for tag in tags:
            where.append("coalesce(tags, '') like ?")
            params.append(f"%{tag}%")
    params.append(limit)
    sql = f"""
        select kind, item_id, source_id, type, path, title, text, rank
        from content_fts
        where {" and ".join(where)}
        order by rank
        limit ?
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
    results = [dict(row) for row in rows]
    log.info("kb_index.search_done results=%s", len(results))
    return results


def list_sources(*, db_path: Path = DEFAULT_DB) -> list[dict[str, Any]]:
    if not db_path.exists():
        build_index(db_path=db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            select
                s.*,
                count(distinct ps.page_id) as page_count,
                count(distinct c.chunk_id) as chunk_count
            from sources s
            left join page_sources ps on ps.source_id = s.id
            left join chunks c on c.source_id = s.id
            group by s.id
            order by coalesce(s.published_at, s.updated, ''), s.id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table sources (
            id text primary key,
            title text,
            raw_path text,
            source_class text,
            published_at text,
            period text,
            fiscal_year text,
            tags text,
            confidence real,
            updated text,
            path text
        );
        create table pages (
            id text primary key,
            type text not null,
            title text,
            path text not null,
            source_ids text,
            confidence real,
            updated text,
            tags text,
            body text
        );
        create table page_sources (
            page_id text not null,
            source_id text not null
        );
        create table links (
            from_id text not null,
            to_id text not null,
            type text not null
        );
        create table chunks (
            source_id text not null,
            chunk_id text not null,
            page_num integer,
            chunk_type text,
            text text,
            metadata text,
            primary key (source_id, chunk_id)
        );
        create virtual table content_fts using fts5(
            kind,
            item_id,
            source_id,
            type,
            path,
            title,
            text,
            tags,
            tokenize='porter'
        );
        """
    )


def _index_wiki(conn: sqlite3.Connection) -> dict:
    sources = pages = links = 0
    raw_to_source_id: dict[str, str] = {}
    page_records: list[tuple[Path, dict, str]] = []
    for path in iter_wiki_pages():
        fm, body = parse_page(path)
        if not fm.get("id"):
            continue
        page_records.append((path, fm, body))
        if fm.get("type") == "Source":
            raw_path = fm.get("raw_path") or (fm.get("sources") or [""])[0]
            source_id = fm["id"]
            raw_to_source_id[raw_path] = source_id
            conn.execute(
                """
                insert into sources values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    _title(fm["id"], body),
                    raw_path,
                    fm.get("source_class"),
                    fm.get("published_at"),
                    fm.get("period"),
                    str(fm.get("fiscal_year", "")),
                    _json_list(fm.get("tags")),
                    fm.get("confidence"),
                    str(fm.get("updated", "")),
                    str(path.relative_to(ROOT)),
                ),
            )
            sources += 1

    for path, fm, body in page_records:
        page_id = fm["id"]
        source_ids = [_source_id_for(raw, raw_to_source_id) for raw in (fm.get("sources") or [])]
        source_ids = [sid for sid in source_ids if sid]
        conn.execute(
            "insert into pages values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                page_id,
                fm.get("type"),
                _title(page_id, body),
                str(path.relative_to(ROOT)),
                json.dumps(source_ids),
                fm.get("confidence"),
                str(fm.get("updated", "")),
                _json_list(fm.get("tags")),
                body,
            ),
        )
        conn.execute(
            "insert into content_fts values (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "page",
                page_id,
                source_ids[0] if source_ids else "",
                fm.get("type"),
                str(path.relative_to(ROOT)),
                _title(page_id, body),
                body,
                _json_list(fm.get("tags")),
            ),
        )
        for source_id in source_ids:
            conn.execute("insert into page_sources values (?, ?)", (page_id, source_id))
        for link in fm.get("links") or []:
            conn.execute(
                "insert into links values (?, ?, ?)",
                (page_id, link.get("to"), link.get("type")),
            )
            links += 1
        pages += 1
    return {"sources": sources, "pages": pages, "links": links}


def _index_chunks(conn: sqlite3.Connection) -> int:
    count = 0
    for parsed_json in PARSED.rglob("document.json"):
        payload = json.loads(parsed_json.read_text(encoding="utf-8"))
        raw_path = payload.get("raw_path", "")
        source_id = _source_id_from_raw(raw_path)
        for idx, chunk in enumerate(payload.get("chunks") or []):
            text = chunk.get("markdown") or ""
            if not text.strip():
                continue
            chunk_id = chunk.get("id") or f"chunk-{idx + 1}"
            grounding = chunk.get("grounding") or {}
            conn.execute(
                "insert or replace into chunks values (?, ?, ?, ?, ?, ?)",
                (
                    source_id,
                    chunk_id,
                    grounding.get("page"),
                    chunk.get("type"),
                    text,
                    json.dumps({"grounding": grounding}, sort_keys=True),
                ),
            )
            conn.execute(
                "insert into content_fts values (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "chunk",
                    chunk_id,
                    source_id,
                    "Chunk",
                    str(parsed_json.relative_to(ROOT)),
                    chunk_id,
                    text,
                    "",
                ),
            )
            count += 1
    return count


def _source_id_for(raw_path: str, raw_to_source_id: dict[str, str]) -> str:
    return raw_to_source_id.get(raw_path) or _source_id_from_raw(raw_path)


def _source_id_from_raw(raw_path: str) -> str:
    stem = Path(raw_path).stem
    slug = "".join(c if c.isalnum() else "_" for c in stem.lower()).strip("_")[:60]
    return f"src_{slug}"


def _title(page_id: str, body: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return page_id.replace("_", " ").title()


def _json_list(value: Any) -> str:
    if not value:
        return "[]"
    return json.dumps(value if isinstance(value, list) else [value])


def _fts_query(query: str) -> str:
    terms = [term.replace('"', "") for term in query.split() if term.strip()]
    return " OR ".join(terms) if terms else query


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--search")
    parser.add_argument("--list-sources", action="store_true")
    parser.add_argument("--source-id", action="append", dest="source_ids")
    parser.add_argument("--type", action="append", dest="types")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    if args.list_sources:
        print(json.dumps({"sources": list_sources(db_path=args.db)}, indent=2))
    elif args.search:
        results = search_index(
            args.search,
            db_path=args.db,
            source_ids=args.source_ids,
            types=args.types,
            limit=args.limit,
        )
        print(json.dumps({"results": results}, indent=2))
    else:
        print(json.dumps(build_index(db_path=args.db), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
