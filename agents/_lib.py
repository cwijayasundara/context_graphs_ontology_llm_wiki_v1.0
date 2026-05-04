"""Shared helpers: ontology loader, frontmatter parser, wiki walker.

Also loads the project .env on import so every agent entry point picks up
provider keys without needing shell exports.
"""
from __future__ import annotations

import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology"
WIKI = ROOT / "wiki"
RAW = ROOT / "raw"
GRAPH = ROOT / "graph"

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


_ONTOLOGY_CACHE: dict | None = None
_ONTOLOGY_FP: tuple | None = None
_PAGE_CACHE: dict[str, tuple[float, int, dict, str]] = {}


def _ontology_fingerprint() -> tuple:
    out = []
    for name in ("object_types.yaml", "link_types.yaml", "action_types.yaml"):
        p = ONTOLOGY / name
        try:
            st = p.stat()
            out.append((name, st.st_mtime_ns, st.st_size))
        except FileNotFoundError:
            out.append((name, 0, 0))
    return tuple(out)


def load_ontology() -> dict:
    global _ONTOLOGY_CACHE, _ONTOLOGY_FP
    fp = _ontology_fingerprint()
    if _ONTOLOGY_CACHE is not None and _ONTOLOGY_FP == fp:
        return _ONTOLOGY_CACHE
    _ONTOLOGY_CACHE = {
        "object_types": yaml.safe_load((ONTOLOGY / "object_types.yaml").read_text()),
        "link_types": yaml.safe_load((ONTOLOGY / "link_types.yaml").read_text()),
        "action_types": yaml.safe_load((ONTOLOGY / "action_types.yaml").read_text()),
    }
    _ONTOLOGY_FP = fp
    return _ONTOLOGY_CACHE


def parse_page(path: pathlib.Path) -> tuple[dict, str]:
    """Memoized wiki page read; cache invalidates on mtime or size change."""
    key = str(path)
    try:
        st = path.stat()
    except FileNotFoundError:
        _PAGE_CACHE.pop(key, None)
        raise
    cached = _PAGE_CACHE.get(key)
    if cached and cached[0] == st.st_mtime_ns and cached[1] == st.st_size:
        return cached[2], cached[3]
    text = path.read_text()
    m = _FM_RE.match(text)
    if not m:
        _PAGE_CACHE[key] = (st.st_mtime_ns, st.st_size, {}, text)
        return {}, text
    fm = yaml.safe_load(m.group(1)) or {}
    body = m.group(2)
    _PAGE_CACHE[key] = (st.st_mtime_ns, st.st_size, fm, body)
    return fm, body


def iter_wiki_pages():
    for p in WIKI.rglob("*.md"):
        if p.name in {"index.md", "log.md"}:
            continue
        yield p


def page_id(path: pathlib.Path) -> str:
    return path.stem
