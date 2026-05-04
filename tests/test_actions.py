from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ontology.functions import actions  # noqa: E402


def test_local_action_adapter_marks_results_and_audit_as_local(tmp_path, monkeypatch):
    monkeypatch.setattr(actions, "WIKI", tmp_path / "wiki")
    monkeypatch.setattr(actions, "AUDIT_LOG", tmp_path / "graph" / "audit.jsonl")

    result = actions.create_customer(actor="alice", name="Globex", region="EU")

    audit = json.loads(actions.AUDIT_LOG.read_text(encoding="utf-8").splitlines()[0])
    assert result["adapter"] == "local_wiki"
    assert result["external_write"] is False
    assert audit["adapter"] == "local_wiki"
    assert audit["external_write"] is False
