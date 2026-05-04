from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))

from build_kb_index import build_index, list_sources, search_index  # noqa: E402


def test_build_index_records_sources_pages_links_and_chunks(tmp_path):
    db_path = tmp_path / "index.sqlite"

    result = build_index(db_path=db_path)

    assert result["sources"] >= 1
    assert result["pages"] >= 1
    assert result["chunks"] >= 1
    with sqlite3.connect(db_path) as conn:
        source = conn.execute(
            "select id, raw_path, source_class from sources where id = ?",
            ("src_nvidia_8_k_2026",),
        ).fetchone()
        page = conn.execute(
            "select id, type from pages where id = ?",
            ("nvidia-q4-fy2026-results",),
        ).fetchone()
        chunk = conn.execute(
            "select source_id, chunk_id, page_num from chunks where source_id = ? limit 1",
            ("src_nvidia_8_k_2026",),
        ).fetchone()

    assert source[0] == "src_nvidia_8_k_2026"
    assert source[1] == "raw/docs/nvidia_8_k_2026.pdf"
    assert source[2]
    assert page == ("nvidia-q4-fy2026-results", "Concept")
    assert chunk[0] == "src_nvidia_8_k_2026"
    assert chunk[1]


def test_search_index_filters_by_source_and_type(tmp_path):
    db_path = tmp_path / "index.sqlite"
    build_index(db_path=db_path)

    results = search_index(
        "gross margin fiscal 2026",
        db_path=db_path,
        source_ids=["src_nvidia_8_k_2026"],
        types=["Source", "Concept"],
        limit=10,
    )

    assert results
    assert {item["source_id"] for item in results} == {"src_nvidia_8_k_2026"}
    assert all(item["kind"] in {"page", "chunk"} for item in results)
    assert any("gross" in item["text"].lower() for item in results)


def test_list_sources_returns_document_metadata(tmp_path):
    db_path = tmp_path / "index.sqlite"
    build_index(db_path=db_path)

    sources = list_sources(db_path=db_path)

    nvidia = next(item for item in sources if item["id"] == "src_nvidia_8_k_2026")
    assert nvidia["raw_path"] == "raw/docs/nvidia_8_k_2026.pdf"
    assert nvidia["source_class"]
    assert nvidia["page_count"] >= 1
    assert nvidia["chunk_count"] >= 1
