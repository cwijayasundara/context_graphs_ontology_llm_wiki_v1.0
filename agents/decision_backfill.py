"""One-shot migrator: walk graph/audit.jsonl and write a Decision wiki page
for every historical action invocation that doesn't already have one.

Idempotent: if a wiki/decisions/<id>.md already exists for a given audit row's
(ts, action, actor) triple, it's skipped. Safe to re-run.

This is what closes the gap surfaced by the Foundation Capital "Context Graphs"
analysis: every decision becomes a first-class typed graph node so it can be
queried, joined, and replayed alongside the rest of the typed wiki.

Usage:
    python agents/decision_backfill.py
    python agents/decision_backfill.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents"))

from _lib import WIKI  # noqa: E402
from logging_config import configure_logging, get_logger  # noqa: E402
from ontology.functions.actions import _decision_id, _write_decision_page  # noqa: E402

log = get_logger("decision_backfill")
AUDIT_LOG = ROOT / "graph" / "audit.jsonl"


def backfill(dry_run: bool = False) -> dict:
    configure_logging()
    if not AUDIT_LOG.exists():
        return {"audit_rows": 0, "written": 0, "skipped_existing": 0}

    written: list[str] = []
    skipped: list[str] = []
    rows = 0
    for line in AUDIT_LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        rows += 1
        ts = row.get("ts", "")
        actor = row.get("actor", "system")
        action = row.get("action", "unknown")
        if not ts:
            continue
        decision_id = _decision_id(ts, action, actor)
        page = WIKI / "decisions" / f"{decision_id}.md"
        if page.exists():
            skipped.append(decision_id)
            continue
        if dry_run:
            written.append(decision_id)
            continue
        _write_decision_page(
            ts=ts, actor=actor, action=action,
            inputs=row.get("inputs") or {},
            result=row.get("result") or {},
            scopes=row.get("scopes") or [],
            approved=bool(row.get("approved", False)),
        )
        written.append(decision_id)
        log.info("decision_backfill.wrote id=%s", decision_id)

    return {
        "audit_rows": rows,
        "written": len(written),
        "skipped_existing": len(skipped),
        "first_few_written": written[:5],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be written without touching wiki/decisions/.")
    args = parser.parse_args()
    result = backfill(dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
