"""Wiki health check. Looks for orphans, missing frontmatter, unknown types,
broken link targets, stale pages, unsupported claims, AND extraction
completeness gaps (numeric line items present in the parsed source but
absent from the wiki).
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import sys
from pathlib import Path

from _lib import iter_wiki_pages, load_ontology, parse_page


STALE_DAYS = 180
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")

# --------------------------------------------------------------------------
# Completeness checker — surfaces values present in the parsed source but
# absent from the wiki. This is the answer to "did the LLM ingestor lose
# information?" — converts silent extraction loss into visible lint warnings.
#
# Strategy: scan parsed/<source>/document.md for known numeric patterns
# ($X.X billion / $X,XXX million / X.X% / X bps / $X.X). For each, check
# whether the value (or its scaled form) appears in any wiki page that
# cites this source. Misses become coverage_gap issues.
# --------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
PARSED = ROOT / "parsed"
WIKI = ROOT / "wiki"

# Patterns we consider "load-bearing" numeric claims worth carrying into the wiki
_NUMERIC_PATTERNS = [
    # $X.XB / $X.X billion
    (re.compile(r"\$\s*(\d{1,3}(?:[,.]\d{1,3})*(?:\.\d+)?)\s*(?:billion|B\b|bn\b)", re.IGNORECASE),
     "usd_billion"),
    # $X,XXX million / $X.X million
    (re.compile(r"\$\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:million|M\b|mn\b)", re.IGNORECASE),
     "usd_million"),
    # $X,XXX (in tables, no unit suffix — use minimum 4-digit threshold to avoid noise)
    (re.compile(r"\$\s*(\d{1,3}(?:,\d{3})+(?:\.\d+)?)"),
     "usd_table"),
    # X.X% (likely a margin or growth number)
    (re.compile(r"(?<![A-Za-z0-9])(\d{1,3}(?:\.\d+)?)\s*%"),
     "percent"),
]

# Pages can cite the value as $6.794B, 6.794, 6,794, 6794, etc. Check all forms.
def _value_variants(raw: str, kind: str) -> set[str]:
    s = raw.replace(",", "")
    out: set[str] = set()
    try:
        f = float(s)
    except ValueError:
        return out
    out.add(s)
    out.add(raw)
    if kind == "usd_million":
        # $6,794M → also accept $6.794B and $6.8B
        b = f / 1000.0
        out.update({f"{b:.3f}", f"{b:.2f}", f"{b:.1f}"})
    elif kind == "usd_billion":
        # $6.794B → also accept $6794M
        m = f * 1000.0
        out.update({f"{int(m)}", f"{int(round(m, -2))}", f"{m:.0f}"})
    elif kind == "percent":
        out.add(f"{f:.1f}")
        out.add(f"{f:.2f}")
        if f.is_integer():
            out.add(str(int(f)))
    elif kind == "usd_table":
        b = f / 1000.0
        out.update({f"{b:.3f}", f"{b:.2f}", f"{b:.1f}"})
    return {v for v in out if v}


def _wiki_text_by_source(source_path: str) -> str:
    """Concatenate body + frontmatter of every wiki page that cites the
    given source. We search in this concatenation for numeric values."""
    blobs: list[str] = []
    for p in iter_wiki_pages():
        fm, body = parse_page(p)
        if not fm:
            continue
        sources = fm.get("sources") or []
        if any(source_path in str(s) for s in sources):
            blobs.append(json.dumps(fm, default=str))
            blobs.append(body or "")
    return "\n".join(blobs)


def _extract_source_numerics(parsed_md: str, max_per_kind: int = 200) -> list[dict]:
    """Return a list of {value_raw, kind, line_no, context_snippet} from the
    parsed document. Bounded per kind to avoid quadratic blowup on big tables."""
    found: list[dict] = []
    seen_per_kind = collections.Counter()
    for line_no, line in enumerate(parsed_md.splitlines(), start=1):
        for pattern, kind in _NUMERIC_PATTERNS:
            for m in pattern.finditer(line):
                if seen_per_kind[kind] >= max_per_kind:
                    continue
                seen_per_kind[kind] += 1
                snippet = line.strip()[:160]
                found.append({
                    "value_raw": m.group(1),
                    "kind": kind,
                    "line_no": line_no,
                    "context": snippet,
                })
    return found


def check_extraction_completeness(*, max_gaps_per_source: int = 25) -> list[dict]:
    """For every parsed source, list numeric values present in the source but
    not findable in any wiki page citing that source."""
    gaps: list[dict] = []
    if not PARSED.exists():
        return gaps
    for source_dir in sorted(PARSED.rglob("document.md")):
        # parsed/raw/docs/Foo/document.md → raw_path = raw/docs/Foo.<ext>
        rel_dir = source_dir.parent.relative_to(PARSED)
        # Find the raw file (look for matching raw/<rel_dir>.{pdf,html,docx,...})
        candidates = list((ROOT / rel_dir.parent).glob(f"{rel_dir.name}.*"))
        raw_candidates = [c for c in candidates if c.suffix.lower()
                          in {".pdf", ".html", ".htm", ".docx", ".pptx", ".xlsx", ".csv", ".md", ".txt"}]
        if not raw_candidates:
            continue
        raw_path = str(raw_candidates[0].relative_to(ROOT))
        parsed_md = source_dir.read_text(encoding="utf-8", errors="replace")
        wiki_text = _wiki_text_by_source(raw_path)
        if not wiki_text.strip():
            continue
        numerics = _extract_source_numerics(parsed_md)
        missing: list[dict] = []
        for entry in numerics:
            variants = _value_variants(entry["value_raw"], entry["kind"])
            # Some forms are too short to search safely (e.g., "5" matching everywhere).
            # Require value length >= 3 chars to count as a real signal.
            variants = {v for v in variants if len(v) >= 3}
            if not variants:
                continue
            if any(v in wiki_text for v in variants):
                continue
            missing.append(entry)
            if len(missing) >= max_gaps_per_source:
                break
        if missing:
            gaps.append({
                "source": raw_path,
                "missing_numeric_count": len(missing),
                "first_missing": missing[:5],
            })
    return gaps


def lint() -> dict:
    ont = load_ontology()
    obj_types = {o["id"] for o in ont["object_types"]}
    link_types = {l["id"] for l in ont["link_types"]}

    issues: list[dict] = []
    inbound = collections.Counter()
    pages: list[tuple] = []

    for p in iter_wiki_pages():
        fm, body = parse_page(p)
        pages.append((p, fm))
        if not fm:
            issues.append({"page": str(p), "kind": "missing_frontmatter"})
            continue
        if fm.get("type") not in obj_types:
            issues.append({"page": str(p), "kind": "unknown_type", "value": fm.get("type")})
        if not fm.get("sources"):
            issues.append({"page": str(p), "kind": "no_sources"})
        if "updated" in fm:
            try:
                d = dt.date.fromisoformat(str(fm["updated"]))
                if (dt.date.today() - d).days > STALE_DAYS:
                    issues.append({"page": str(p), "kind": "stale", "updated": str(d)})
            except ValueError:
                issues.append({"page": str(p), "kind": "bad_date"})
        for link in (fm.get("links") or []):
            if link.get("type") not in link_types:
                issues.append({"page": str(p), "kind": "unknown_link_type",
                               "value": link.get("type")})
            inbound[link.get("to")] += 1
        if fm.get("type") == "Source":
            for target in _WIKILINK_RE.findall(body):
                inbound[target] += 1

    ids_present = {fm.get("id") for _p, fm in pages if fm.get("id")}
    for p, fm in pages:
        for link in (fm.get("links") or []):
            tgt = link.get("to")
            if tgt and tgt not in ids_present:
                issues.append({"page": str(p), "kind": "broken_link", "target": tgt})

    for p, fm in pages:
        pid = fm.get("id")
        action_sourced = any(str(source).startswith("action:") for source in fm.get("sources", []))
        if pid and inbound[pid] == 0 and fm.get("type") != "Source" and not action_sourced:
            issues.append({"page": str(p), "kind": "orphan", "id": pid})

    # Extraction completeness — surfaces numeric values present in the parsed
    # source but absent from every wiki page citing it. Skipped under --fast
    # because it scans every parsed/<source>/document.md.
    completeness_gaps: list[dict] = []
    if _COMPLETENESS_ENABLED:
        completeness_gaps = check_extraction_completeness()
        for gap in completeness_gaps:
            issues.append({
                "kind": "extraction_completeness_gap",
                "source": gap["source"],
                "missing_numeric_count": gap["missing_numeric_count"],
                "examples": [
                    f"line {m['line_no']}: {m['kind']}={m['value_raw']!r} — {m['context'][:100]}"
                    for m in gap["first_missing"]
                ],
            })

    return {
        "page_count": len(pages),
        "issue_count": len(issues),
        "issues": issues,
        "extraction_gaps_per_source": len(completeness_gaps),
    }


# Module-level toggle so --fast can disable the (more expensive) completeness scan.
_COMPLETENESS_ENABLED = True


def main() -> int:
    global _COMPLETENESS_ENABLED
    parser = argparse.ArgumentParser()
    parser.add_argument("--fast", action="store_true",
                        help="Skip the extraction-completeness scan (faster but less thorough).")
    parser.add_argument("--no-completeness", action="store_true",
                        help="Same as --fast for the completeness check.")
    args = parser.parse_args()
    if args.fast or args.no_completeness:
        _COMPLETENESS_ENABLED = False
    result = lint()
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["issue_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
