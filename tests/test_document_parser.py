from __future__ import annotations

import json
from pathlib import Path

import pytest

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))

from document_parser import (  # noqa: E402
    LandingAIParser,
    LiteParseParser,
    NemotronParser,
    ParsedDocument,
    get_parser,
    write_parsed_artifacts,
)


def test_liteparse_parser_reads_plain_text_document(tmp_path):
    raw = tmp_path / "memo.txt"
    raw.write_text("First paragraph.\n\nSecond paragraph.\n", encoding="utf-8")

    parsed = LiteParseParser().parse(raw, raw_path="raw/docs/memo.txt")

    assert parsed.raw_path == "raw/docs/memo.txt"
    assert parsed.provider == "liteparse"
    assert parsed.markdown == "First paragraph.\n\nSecond paragraph."
    assert parsed.chunks[0]["type"] == "text"
    assert parsed.chunks[0]["markdown"] == parsed.markdown
    assert parsed.metadata["extension"] == ".txt"


def test_liteparse_parser_maps_pdf_pages_and_text_items():
    class FakeResult:
        text = "Revenue grew 73%"
        pages = [
            {
                "pageNum": 1,
                "width": 612,
                "height": 792,
                "text": "Revenue grew 73%",
                "textItems": [
                    {"text": "Revenue", "x": 72, "y": 200, "width": 48, "height": 12},
                    {"text": "grew 73%", "x": 124, "y": 200, "width": 60, "height": 12},
                ],
            }
        ]

    class FakeLiteParseClient:
        def parse(self, path, **kwargs):
            assert path == "/tmp/report.pdf"
            assert kwargs["ocr_enabled"] is True
            assert kwargs["password"] == "secret"
            return FakeResult()

    parsed = LiteParseParser(
        client=FakeLiteParseClient(),
        ocr_enabled=True,
        password="secret",
    ).parse(Path("/tmp/report.pdf"), raw_path="raw/docs/report.pdf")

    assert parsed.provider == "liteparse"
    assert parsed.markdown == "Revenue grew 73%"
    assert parsed.metadata["page_count"] == 1
    assert parsed.chunks[0]["grounding"]["page"] == 1
    assert parsed.chunks[0]["grounding"]["text_items"][0]["box"]["left"] == 72


def test_write_parsed_artifacts_writes_canonical_json_and_markdown(tmp_path):
    parsed = ParsedDocument(
        raw_path="raw/docs/memo.txt",
        provider="local",
        markdown="hello",
        chunks=[{"id": "chunk-1", "type": "text", "markdown": "hello", "grounding": {"page": 0}}],
        metadata={"page_count": 1},
        grounding={"chunk-1": {"page": 0}},
        warnings=[],
    )

    out_dir = write_parsed_artifacts(parsed, parsed_root=tmp_path)

    assert (out_dir / "document.md").read_text(encoding="utf-8") == "hello\n"
    data = json.loads((out_dir / "document.json").read_text(encoding="utf-8"))
    assert data["raw_path"] == "raw/docs/memo.txt"
    assert data["chunks"][0]["id"] == "chunk-1"


def test_landing_ai_parser_maps_chunks_grounding_and_confidence(tmp_path):
    raw = tmp_path / "filing.pdf"
    raw.write_bytes(b"%PDF-1.7")

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "markdown": "# Filing\n\n| A | B |",
                "chunks": [
                    {
                        "id": "c1",
                        "type": "table",
                        "markdown": "| A | B |",
                        "grounding": {"page": 0},
                    }
                ],
                "metadata": {"page_count": 1, "job_id": "job-1"},
                "grounding": {
                    "c1": {
                        "page": 0,
                        "type": "chunkTable",
                        "confidence": 0.91,
                        "low_confidence_spans": [],
                    }
                },
            }

    class FakeClient:
        def __init__(self):
            self.calls = []

        def post(self, url, headers=None, files=None, data=None, timeout=None):
            self.calls.append((url, headers, files, data, timeout))
            return FakeResponse()

    client = FakeClient()
    parser = LandingAIParser(api_key="key", client=client)

    parsed = parser.parse(raw, raw_path="raw/docs/filing.pdf")

    assert parsed.provider == "landingai"
    assert parsed.markdown.startswith("# Filing")
    assert parsed.chunks[0]["grounding"]["confidence"] == 0.91
    assert parsed.metadata["job_id"] == "job-1"
    assert client.calls[0][0] == "https://api.va.landing.ai/v1/ade/parse"
    assert client.calls[0][3]["model"] == "dpt-2-latest"


def test_nemotron_parser_maps_page_results(tmp_path):
    raw = tmp_path / "filing.pdf"
    raw.write_bytes(b"%PDF-1.7")

    async def fake_parse_pdf_to_pages(path):
        assert path == raw
        return [
            {"text": "Page one", "metadata": {"page": 0}},
            {"text": "Page two", "metadata": {"page": 1}},
        ]

    parser = NemotronParser(parse_pdf_to_pages=fake_parse_pdf_to_pages)

    parsed = parser.parse(raw, raw_path="raw/docs/filing.pdf")

    assert parsed.provider == "nemotron"
    assert parsed.markdown == "Page one\n\n---\n\nPage two"
    assert [chunk["grounding"]["page"] for chunk in parsed.chunks] == [0, 1]


def test_get_parser_requires_provider_keys(monkeypatch):
    monkeypatch.setenv("DOCUMENT_PARSER_PROVIDER", "landingai")
    monkeypatch.delenv("LANDINGAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="LANDINGAI_API_KEY"):
        get_parser()
