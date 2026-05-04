"""Smoke test: query agent finds the seed entity."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agents"))

from query_agent import ask  # noqa: E402


def test_query_finds_seed_financial_concept():
    result = ask("What is the Gross margin for Q4 Fiscal 2026?", record_trace=False)
    paths = " ".join(result["expanded_paths"])
    assert "nvidia-q4-fy2026-results" in paths
    assert "nvidia-corp" in paths


def test_query_synthesizes_cited_answer_without_stub_text():
    result = ask("What is the Gross margin for Q4 Fiscal 2026?", record_trace=False)

    answer = result["answer_markdown"]

    assert "stub" not in answer.lower()
    assert "nvidia-q4-fy2026-results" in answer
    assert "raw/docs/nvidia_8_k_2026.pdf" in answer
    assert "Gross margin 75.0%" in answer


def test_query_filters_to_selected_source():
    result = ask(
        "Gross margin Fiscal 2026",
        source_ids=["src_nvidia_8_k_2026"],
        types=["Source", "Concept"],
        record_trace=False,
    )

    assert result["seed_paths"]
    assert all("acme" not in path for path in result["seed_paths"])
    assert "raw/docs/nvidia_8_k_2026.pdf" in result["answer_markdown"]
