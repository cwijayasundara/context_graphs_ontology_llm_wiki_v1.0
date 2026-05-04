"""Conformance: every wiki page validates against the ontology."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agents"))

from _lib import iter_wiki_pages, load_ontology, parse_page  # noqa: E402


def test_every_page_has_frontmatter():
    for p in iter_wiki_pages():
        fm, _ = parse_page(p)
        assert fm, f"{p} missing frontmatter"


def test_every_page_has_known_type():
    ont = load_ontology()
    valid = {o["id"] for o in ont["object_types"]}
    for p in iter_wiki_pages():
        fm, _ = parse_page(p)
        assert fm.get("type") in valid, f"{p} has unknown type {fm.get('type')!r}"


def test_every_page_has_sources():
    for p in iter_wiki_pages():
        fm, _ = parse_page(p)
        assert fm.get("sources"), f"{p} has no sources[]"


def test_links_use_known_types():
    ont = load_ontology()
    valid = {l["id"] for l in ont["link_types"]}
    for p in iter_wiki_pages():
        fm, _ = parse_page(p)
        for link in (fm.get("links") or []):
            assert link.get("type") in valid, f"{p} uses unknown link type {link.get('type')!r}"


def test_action_functions_exist():
    sys.path.insert(0, str(ROOT))
    from ontology.functions import REGISTRY
    ont = load_ontology()
    for a in ont["action_types"]:
        assert a["function"] in REGISTRY, f"action {a['id']} -> missing function {a['function']}"
