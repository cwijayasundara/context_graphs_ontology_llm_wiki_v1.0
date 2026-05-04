"""Generate wiki/index.md from the current wiki pages."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

from _lib import WIKI, parse_page


_HEADINGS = {
    "Customer": "Customers",
    "Product": "Products",
    "Person": "People",
    "Concept": "Concepts",
    "Source": "Sources",
}
_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
_TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)


def _iter_pages(wiki_root: Path):
    for path in sorted(wiki_root.rglob("*.md")):
        if path.name in {"index.md", "log.md"}:
            continue
        yield path


def _parse_page(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    match = _FM_RE.match(text)
    if not match:
        return {}, text
    return yaml.safe_load(match.group(1)) or {}, match.group(2)


def _title(page_id: str, body: str) -> str:
    if match := _TITLE_RE.search(body):
        return match.group(1).strip()
    return page_id.replace("_", " ").title()


def _summary(body: str) -> str:
    lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("```") or stripped.startswith("---"):
            continue
        lines.append(stripped)
    if not lines:
        return ""
    text = " ".join(lines)
    return text[:157].rstrip() + "..." if len(text) > 160 else text


def build_index_markdown(wiki_root: Path = WIKI) -> str:
    groups: dict[str, list[tuple[str, str, str]]] = {}
    for path in _iter_pages(wiki_root):
        fm, body = _parse_page(path)
        page_id = fm.get("id")
        page_type = fm.get("type")
        if not page_id or not page_type:
            continue
        groups.setdefault(page_type, []).append((page_id, _title(page_id, body), _summary(body)))

    lines = [
        "# Wiki Index",
        "",
        "_Generated from wiki pages. Do not edit by hand; run `python agents/update_index.py`._",
        "",
    ]
    ordered_types = list(_HEADINGS)
    ordered_types.extend(sorted(t for t in groups if t not in _HEADINGS))
    for page_type in ordered_types:
        heading = _HEADINGS.get(page_type, page_type)
        lines.extend([f"## {heading}", ""])
        entries = sorted(groups.get(page_type, []), key=lambda item: item[1].lower())
        if entries:
            for page_id, title, summary in entries:
                suffix = f" - {summary}" if summary else ""
                lines.append(f"- [[{page_id}|{title}]]{suffix}")
        else:
            lines.append("- (none yet)")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def update_index(wiki_root: Path = WIKI) -> Path:
    path = wiki_root / "index.md"
    path.write_text(build_index_markdown(wiki_root), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wiki", type=Path, default=WIKI)
    args = parser.parse_args()
    print(update_index(args.wiki))
    return 0


if __name__ == "__main__":
    sys.exit(main())
