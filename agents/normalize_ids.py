"""Detect and merge duplicate wiki ids that differ only in slug shape.

The LLM ingestor coins slugs ad-hoc per run, so the same concept often appears
with multiple ids: nvidia_corp / nvidia-corp / NvidiaCorp. After a multi-source
ingest these duplicates pollute the typed graph (two nodes for the same thing),
break entity overlap in precedent search, and make Cypher queries miss results.

This tool walks wiki/, groups pages whose ids normalize to the same canonical
form, picks a winner per group using a deterministic priority, merges sources
and frontmatter from the loser pages, rewrites every `links: [{to: <loser>}]`
reference across the rest of the wiki, then deletes the loser pages.

Winner selection priority (first match wins):
  1. Page in wiki/entities/ over wiki/concepts/ (typed Object > generic Concept).
  2. Larger body (more content already extracted).
  3. Higher confidence in frontmatter.
  4. Lexically smallest id (deterministic tiebreak).

Idempotent: re-running on a clean wiki is a no-op.
Reversible: --dry-run prints the plan without touching files.

CLI:
    python agents/normalize_ids.py audit          # report duplicates only
    python agents/normalize_ids.py merge --dry-run
    python agents/normalize_ids.py merge          # actually merge + rewrite
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))

import yaml

from _lib import WIKI, parse_page  # noqa: E402
from logging_config import configure_logging, get_logger  # noqa: E402

log = get_logger("normalize_ids")


def _canonical(stem: str) -> str:
    """Collapse separators to underscores; lowercase. nvidia_corp == nvidia-corp."""
    return re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_")


def _all_pages() -> list[Path]:
    out = []
    for p in WIKI.rglob("*.md"):
        if p.name in {"index.md", "log.md"}:
            continue
        out.append(p)
    return out


def _winner_priority(page: Path, fm: dict, body: str) -> tuple:
    """Lower tuple = higher priority. See module docstring."""
    in_entities = 0 if page.parent.name == "entities" else 1
    body_neg = -len(body)               # bigger body wins
    conf_neg = -float(fm.get("confidence", 0.0))
    return (in_entities, body_neg, conf_neg, fm.get("id", ""))


def detect_duplicates() -> dict[str, list[tuple[Path, dict, str]]]:
    """Group pages by canonical id. Returns only groups with >1 member."""
    groups: dict[str, list[tuple[Path, dict, str]]] = defaultdict(list)
    for p in _all_pages():
        try:
            fm, body = parse_page(p)
        except Exception:
            continue
        page_id = fm.get("id") or p.stem
        groups[_canonical(page_id)].append((p, fm, body))
    return {k: sorted(v, key=lambda x: _winner_priority(x[0], x[1], x[2]))
            for k, v in groups.items() if len(v) > 1}


def _format_fm(fm: dict) -> str:
    return "---\n" + "\n".join(f"{k}: {json.dumps(v)}" for k, v in fm.items()) + "\n---\n"


def _merge_frontmatter(winner_fm: dict, loser_fms: list[dict]) -> dict:
    """Union sources + links from losers into winner. Winner's primitive
    fields (type, name, confidence, etc.) win. Loser links become new typed
    edges if the (to, type) pair isn't already on the winner."""
    out = dict(winner_fm)
    sources = list(out.get("sources") or [])
    seen_sources = set(sources)
    for fm in loser_fms:
        for s in fm.get("sources") or []:
            if s not in seen_sources:
                sources.append(s)
                seen_sources.add(s)
    if sources:
        out["sources"] = sources

    links = list(out.get("links") or [])
    seen_links = {(l.get("to"), l.get("type")) for l in links if isinstance(l, dict)}
    for fm in loser_fms:
        for link in fm.get("links") or []:
            if not isinstance(link, dict):
                continue
            sig = (link.get("to"), link.get("type"))
            if sig not in seen_links:
                links.append(link)
                seen_links.add(sig)
    if links:
        out["links"] = links
    return out


def _rewrite_link_references(loser_id: str, winner_id: str, all_pages: list[Path]) -> int:
    """Rewrite every {"to": loser_id} in any other page's links[] to winner_id.
    Returns the count of rewrites."""
    count = 0
    for p in all_pages:
        try:
            fm, body = parse_page(p)
        except Exception:
            continue
        links = fm.get("links") or []
        if not links:
            continue
        changed = False
        new_links = []
        seen = set()
        for link in links:
            if isinstance(link, dict) and link.get("to") == loser_id:
                link = {**link, "to": winner_id}
                changed = True
            sig = (link.get("to"), link.get("type")) if isinstance(link, dict) else None
            if sig and sig in seen:
                # dedup any new collision the rewrite created
                continue
            if sig:
                seen.add(sig)
            new_links.append(link)
        if changed:
            fm["links"] = new_links
            p.write_text(_format_fm(fm) + "\n" + body, encoding="utf-8")
            count += 1
    return count


def _merge_body(winner_body: str, loser_bodies: list[str]) -> str:
    """Append loser bodies under a clear separator so no information is lost."""
    extras = [b.strip() for b in loser_bodies if b.strip()]
    if not extras:
        return winner_body
    return winner_body.rstrip() + "\n\n" + "\n\n".join(
        f"<!-- merged from duplicate id -->\n{b}" for b in extras
    ) + "\n"


def merge(*, dry_run: bool = False) -> dict[str, Any]:
    configure_logging()
    log.info("normalize_ids.merge dry_run=%s", dry_run)

    duplicates = detect_duplicates()
    if not duplicates:
        return {"groups_found": 0, "merges": [], "link_rewrites": 0}

    all_pages = _all_pages()
    plan = []
    total_rewrites = 0

    for canonical, members in sorted(duplicates.items()):
        winner_path, winner_fm, winner_body = members[0]
        losers = members[1:]
        loser_summary = [
            {"id": fm.get("id"), "path": str(p.relative_to(ROOT)),
             "type": fm.get("type"), "body_chars": len(body)}
            for p, fm, body in losers
        ]

        # Plan the merge
        merged_fm = _merge_frontmatter(winner_fm, [fm for _, fm, _ in losers])
        merged_body = _merge_body(winner_body, [b for _, _, b in losers])

        # Apply unless dry-run
        rewrites_for_this_group = 0
        if not dry_run:
            winner_path.write_text(_format_fm(merged_fm) + "\n" + merged_body, encoding="utf-8")
            for loser_path, loser_fm, _ in losers:
                loser_id = loser_fm.get("id")
                winner_id = merged_fm.get("id")
                if loser_id and winner_id and loser_id != winner_id:
                    rewrites_for_this_group += _rewrite_link_references(
                        loser_id, winner_id, all_pages
                    )
                # Don't delete the winner if a loser path happens to equal it
                if loser_path.resolve() != winner_path.resolve():
                    loser_path.unlink()
            total_rewrites += rewrites_for_this_group

        plan.append({
            "canonical_form": canonical,
            "winner": {
                "id": winner_fm.get("id"),
                "path": str(winner_path.relative_to(ROOT)),
                "type": winner_fm.get("type"),
                "body_chars": len(winner_body),
            },
            "merged_losers": loser_summary,
            "link_rewrites": rewrites_for_this_group,
        })

    return {
        "groups_found": len(duplicates),
        "merges": plan,
        "link_rewrites": total_rewrites,
        "dry_run": dry_run,
    }


def audit() -> dict[str, Any]:
    duplicates = detect_duplicates()
    return {
        "duplicate_groups": len(duplicates),
        "groups": {
            canonical: [
                {"id": fm.get("id"), "type": fm.get("type"),
                 "path": str(p.relative_to(ROOT)), "body_chars": len(body)}
                for p, fm, body in members
            ]
            for canonical, members in sorted(duplicates.items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("audit", help="Report duplicate ids without modifying anything.")
    m = sub.add_parser("merge", help="Merge duplicates: pick winner, union sources/links, rewrite refs, delete losers.")
    m.add_argument("--dry-run", action="store_true",
                   help="Print the merge plan without touching files.")
    args = parser.parse_args()

    if args.cmd == "audit":
        result = audit()
    else:
        result = merge(dry_run=args.dry_run)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
