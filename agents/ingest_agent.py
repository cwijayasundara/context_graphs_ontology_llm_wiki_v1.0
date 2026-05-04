"""Deterministic ingest raw/ -> wiki/ for local and CI workflows.

Two modes:
  bootstrap-ontology  — propose ontology drafts from seed docs (interactive)
  ingest <path>       — compile a single raw artifact into wiki pages

The DeepAgent ingestor remains the richer LLM path for extracting many typed
pages. This module is the production-safe deterministic path: it records the
source with a grounded summary, chunk inventory, index/log updates, and graph
recompilation without emitting placeholder content.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys

from _lib import RAW, WIKI, load_ontology, parse_page
from compile_graph import compile_graph
from logging_config import configure_logging, get_logger

log = get_logger("ingest_agent")


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s.lower()).strip("_")[:60]


def _append_log(line: str) -> None:
    log = WIKI / "log.md"
    log.parent.mkdir(parents=True, exist_ok=True)
    if not log.exists():
        log.write_text("# Log\n\n")
    with log.open("a") as f:
        f.write(f"- {dt.datetime.now(dt.timezone.utc).isoformat()} — {line}\n")


def _repo_raw_path(raw_path: pathlib.Path) -> str:
    try:
        return str(pathlib.Path("raw") / raw_path.relative_to(RAW))
    except ValueError:
        return str(raw_path)


def _read_markdown(raw_path: pathlib.Path) -> tuple[str, list[dict]]:
    text = raw_path.read_text(encoding="utf-8", errors="replace").strip()
    parts = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks = [
        {"id": f"chunk-{idx + 1}", "chars": len(part), "preview": part[:180]}
        for idx, part in enumerate(parts[:20])
    ]
    return text, chunks


def _summary(markdown: str, chunks: list[dict]) -> str:
    title = ""
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped:
            title = stripped.lstrip("#").strip()
            break
    sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", markdown).strip())
    takeaways = [s for s in sentences if s][:5]
    lines = []
    if title:
        lines.append(f"Summary: {title}")
    if takeaways:
        lines.append("")
        lines.append("Key takeaways:")
        lines.extend(f"- {item}" for item in takeaways)
    lines.append("")
    lines.append("chunks:")
    for chunk in chunks:
        lines.append(f"- {chunk['id']}: {chunk['chars']} chars — {chunk['preview']}")
    return "\n".join(lines).strip() + "\n"


def _existing_source_page(rel: str) -> pathlib.Path | None:
    """Return the wiki/sources/*.md page already recording `rel`, or None."""
    sources_dir = WIKI / "sources"
    if not sources_dir.exists():
        return None
    for page in sources_dir.glob("*.md"):
        try:
            fm, _ = parse_page(page)
        except Exception:
            continue
        if fm.get("raw_path") == rel or rel in (fm.get("sources") or []):
            return page
    return None


def _raw_newer_than_page(raw_path: pathlib.Path, page: pathlib.Path) -> bool:
    """True if the raw file has been touched since the source page was written."""
    try:
        return raw_path.stat().st_mtime > page.stat().st_mtime
    except FileNotFoundError:
        return True


def ingest(raw_path: pathlib.Path, *, force: bool = False) -> dict:
    configure_logging()
    log.info("ingest.start raw_path=%s force=%s", raw_path, force)
    if not raw_path.exists():
        log.error("ingest.not_found raw_path=%s", raw_path)
        return {"error": f"not found: {raw_path}"}
    rel = _repo_raw_path(raw_path)
    existing = _existing_source_page(rel)
    if existing is not None and not force and not _raw_newer_than_page(raw_path, existing):
        log.info("ingest.skip_already_ingested raw_path=%s existing=%s", raw_path, existing)
        return {
            "skipped": True,
            "reason": "already ingested; raw file unchanged since source page was written",
            "source_page": str(existing),
            "raw_path": rel,
            "hint": "pass force=True to re-ingest",
        }
    src_id = _slug(raw_path.stem)
    src_page = WIKI / "sources" / f"{src_id}.md"
    src_page.parent.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    markdown, chunks = _read_markdown(raw_path)
    fm = (
        "---\n"
        f"id: {src_id}\n"
        "type: Source\n"
        f"sources: [\"{rel}\"]\n"
        "confidence: 1.0\n"
        f"updated: {today}\n"
        f"raw_path: {rel}\n"
        f"ingested_at: {today}\n"
        "source_class: document\n"
        "---\n"
    )
    body = f"# {raw_path.name}\n\n{_summary(markdown, chunks)}"
    src_page.write_text(fm + body, encoding="utf-8")

    _append_log(f"ingest {rel} -> wiki/sources/{src_id}.md")
    compile_result = compile_graph()
    result = {"source_page": str(src_page), "chunks": len(chunks), "compile": compile_result}
    log.info("ingest.done source_page=%s chunks=%s compile_errors=%s",
             src_page, len(chunks), len(compile_result.get("errors", [])))
    return result


def bootstrap_ontology(seed_dir: pathlib.Path) -> dict:
    ont = load_ontology()
    return {
        "current_object_types": [o["id"] for o in ont["object_types"]],
        "current_link_types": [l["id"] for l in ont["link_types"]],
        "current_action_types": [a["id"] for a in ont["action_types"]],
        "seed_files": [str(p) for p in seed_dir.rglob("*") if p.is_file()],
        "next": "Have your LLM read seed_files and propose edits to ontology/*.yaml",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_ing = sub.add_parser("ingest")
    p_ing.add_argument("path", type=pathlib.Path)
    p_ing.add_argument("--force", action="store_true",
                       help="Re-ingest even if a source page already covers this raw_path.")
    p_boot = sub.add_parser("bootstrap-ontology")
    p_boot.add_argument("--raw", type=pathlib.Path, default=RAW)
    args = parser.parse_args()

    if args.cmd == "ingest":
        result = ingest(args.path, force=args.force)
    else:
        result = bootstrap_ontology(args.raw)

    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
