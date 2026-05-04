from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))

import ingest_agent  # noqa: E402


def test_standalone_ingest_writes_real_source_summary(tmp_path, monkeypatch):
    raw_root = tmp_path / "raw"
    wiki_root = tmp_path / "wiki"
    raw_doc = raw_root / "docs" / "customer_note.md"
    raw_doc.parent.mkdir(parents=True)
    raw_doc.write_text(
        "# Customer note\n\nACME is on SLA Tier 2. Response time is 4 business hours.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ingest_agent, "RAW", raw_root)
    monkeypatch.setattr(ingest_agent, "WIKI", wiki_root)
    monkeypatch.setattr(ingest_agent, "compile_graph", lambda: {"nodes": 1, "errors": []})

    result = ingest_agent.ingest(raw_doc)

    source_page = Path(result["source_page"])
    text = source_page.read_text(encoding="utf-8")
    assert result["compile"] == {"nodes": 1, "errors": []}
    assert "_Stub summary._" not in text
    assert "ACME is on SLA Tier 2" in text
    assert "raw/docs/customer_note.md" in text
    assert "chunks:" in text
