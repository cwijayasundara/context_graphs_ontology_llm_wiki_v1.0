from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))

from update_index import build_index_markdown  # noqa: E402


def _page(path: Path, frontmatter: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}\n---\n\n{body}\n", encoding="utf-8")


def test_build_index_groups_pages_by_type(tmp_path):
    wiki = tmp_path / "wiki"
    _page(
        wiki / "entities" / "acme.md",
        'id: "customer_acme"\ntype: "Customer"\nsources: ["raw/docs/acme.pdf"]\nconfidence: 0.9\nupdated: "2026-05-03"',
        "# ACME Corp\n\nACME is a seed customer.",
    )
    _page(
        wiki / "concepts" / "sla.md",
        'id: "sla_tier_2"\ntype: "Concept"\nsources: ["raw/docs/sla.md"]\nconfidence: 1.0\nupdated: "2026-05-03"',
        "# SLA Tier 2\n\nSupport response policy.",
    )

    markdown = build_index_markdown(wiki)

    assert "## Customers" in markdown
    assert "- [[customer_acme|ACME Corp]] - ACME is a seed customer." in markdown
    assert "## Concepts" in markdown
    assert "- [[sla_tier_2|SLA Tier 2]] - Support response policy." in markdown


def test_build_index_omits_index_and_log(tmp_path):
    wiki = tmp_path / "wiki"
    (wiki / "index.md").parent.mkdir(parents=True)
    (wiki / "index.md").write_text("# Old index\n", encoding="utf-8")
    (wiki / "log.md").write_text("# Log\n", encoding="utf-8")

    markdown = build_index_markdown(wiki)

    assert "Old index" not in markdown
    assert "Log" not in markdown
