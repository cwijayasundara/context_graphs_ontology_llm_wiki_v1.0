"""Reconstruct the state-of-world at the moment a Decision was made.

Every Decision page records the wiki + ontology fingerprints at decision time
(via _wiki_fingerprint / _ontology_fingerprint in ontology/functions/actions.py).
This tool walks the existing artifacts and produces a replay report:

  - The ontology version then in effect (object/link/action type counts;
    matches the recorded fingerprint or flags drift)
  - Which wiki pages existed and were live at decision time (frontmatter
    `updated <= decision.ts`); newer pages are excluded from the replay view
  - Which sources had been ingested by then (their `ingested_at` <= ts)
  - Which Memos were live (and thus could have informed the decision)
  - Which prior Decisions were already on the books

The output is the answer to the regulator question "what did you know when you
made this call?" For complete byte-for-byte replay you'd need git, but this
gives logical replayability against the typed knowledge layer — which is what
matters for compliance use cases.

CLI:
    python agents/decision_replay.py replay <decision_id>
    python agents/decision_replay.py replay <decision_id> --include-stale-context
    python agents/decision_replay.py list                # show all replayable decisions
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents"))

from _lib import WIKI, iter_wiki_pages, load_ontology, parse_page  # noqa: E402
from logging_config import configure_logging, get_logger  # noqa: E402

log = get_logger("decision_replay")


def _load_decision(decision_id: str) -> dict[str, Any]:
    page = WIKI / "decisions" / f"{decision_id}.md"
    if not page.exists():
        raise FileNotFoundError(f"no Decision page for {decision_id!r} at {page}")
    fm, body = parse_page(page)
    fm["_path"] = str(page.relative_to(ROOT))
    fm["_body"] = body
    return fm


def _list_decisions() -> list[dict[str, Any]]:
    out = []
    decisions_dir = WIKI / "decisions"
    if not decisions_dir.exists():
        return out
    for p in sorted(decisions_dir.glob("*.md")):
        try:
            fm, _ = parse_page(p)
        except Exception:
            continue
        if fm.get("type") == "Decision":
            out.append({
                "id": fm.get("id"),
                "ts": fm.get("ts"),
                "actor": fm.get("actor"),
                "action_id": fm.get("action_id"),
                "decision_class": fm.get("decision_class"),
                "approved": fm.get("approved"),
                "outcome": fm.get("action_outcome"),
            })
    out.sort(key=lambda d: d.get("ts", ""), reverse=True)
    return out


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        # tolerate both date-only ("2026-05-03") and full ISO timestamps
        if "T" in ts:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _page_was_live_at(fm: dict[str, Any], cutoff: datetime) -> bool:
    """Was the underlying fact captured by `cutoff`?

    Prefer semantic event time (ts / ingested_at / generated_at) over the
    observation time (updated). Backfilled decisions have `updated` = today
    but `ts` = when the action actually happened — for replay we want the
    latter."""
    candidates = [fm.get("ts"), fm.get("ingested_at"), fm.get("generated_at"), fm.get("updated")]
    for raw in candidates:
        if not raw:
            continue
        parsed = _parse_iso(str(raw))
        if parsed is None:
            continue
        return parsed <= cutoff
    # If we can't determine a timestamp, default to "live" rather than dropping
    # the page from the replay. The user can opt-out via --strict.
    return True


def replay(decision_id: str, *, strict: bool = False) -> dict[str, Any]:
    """Build a replay report. `strict=True` excludes pages with no parseable
    timestamp; default behavior includes them (safer for replay completeness)."""
    configure_logging()
    log.info("decision_replay.start id=%s strict=%s", decision_id, strict)

    decision = _load_decision(decision_id)
    cutoff = _parse_iso(str(decision.get("ts", "")))
    if cutoff is None:
        return {"error": f"decision {decision_id!r} has no parseable ts"}

    recorded_wiki_fp = decision.get("wiki_fingerprint", "")
    recorded_ont_fp = decision.get("ontology_fingerprint", "")

    live_pages: dict[str, list[dict]] = {
        "entities": [], "concepts": [], "sources": [],
        "memos": [], "decisions": [], "synthesis": [], "other": [],
    }

    for p in iter_wiki_pages():
        try:
            fm, _ = parse_page(p)
        except Exception:
            continue
        if not fm:
            continue
        live = _page_was_live_at(fm, cutoff)
        if strict and live and not any(fm.get(k) for k in ("updated", "ingested_at", "ts", "generated_at")):
            continue
        if not live:
            continue
        bucket = p.parent.name if p.parent.name in live_pages else "other"
        live_pages[bucket].append({
            "id": fm.get("id"),
            "type": fm.get("type"),
            "updated": fm.get("updated") or fm.get("ts") or fm.get("ingested_at"),
            "confidence": fm.get("confidence"),
            "path": str(p.relative_to(ROOT)),
        })

    # Sort each bucket by recency (newest live page first; nearest in time to
    # the decision is most likely to have informed it).
    for bucket in live_pages:
        live_pages[bucket].sort(key=lambda d: str(d.get("updated") or ""), reverse=True)

    # Ontology version then in effect (we can't reconstruct old ontology
    # contents — only flag drift). The fingerprint match is the proof that the
    # current ontology bytes are the same as at decision time.
    ontology = load_ontology()
    current_ont_fp = ""
    try:
        from ontology.functions.actions import _ontology_fingerprint
        current_ont_fp = _ontology_fingerprint()
    except Exception:
        pass
    ontology_drifted = bool(recorded_ont_fp and current_ont_fp and recorded_ont_fp != current_ont_fp)

    # Wiki fingerprint drift — wiki has changed since the decision, which is
    # expected. We only flag it as drift if the recorded fingerprint is missing
    # (Decision was written before fingerprinting was wired).
    wiki_fingerprint_recorded = bool(recorded_wiki_fp)

    # Prior decisions on the books at cutoff
    prior_decisions = [
        d for d in _list_decisions()
        if d.get("id") != decision_id and (_parse_iso(d.get("ts", "")) or cutoff) <= cutoff
    ]

    return {
        "decision": {
            "id": decision_id,
            "ts": decision.get("ts"),
            "actor": decision.get("actor"),
            "action_id": decision.get("action_id"),
            "decision_class": decision.get("decision_class"),
            "approved": decision.get("approved"),
            "outcome": decision.get("action_outcome"),
            "scopes": decision.get("scopes"),
            "page": decision.get("_path"),
        },
        "ontology_at_decision_time": {
            "fingerprint_recorded": recorded_ont_fp[:16] + "..." if recorded_ont_fp else None,
            "fingerprint_current": current_ont_fp[:16] + "..." if current_ont_fp else None,
            "drifted": ontology_drifted,
            "current_object_types": [o["id"] for o in ontology["object_types"]],
            "current_link_types": [l["id"] for l in ontology["link_types"]],
            "current_action_types": [a["id"] for a in ontology["action_types"]],
        },
        "wiki_at_decision_time": {
            "wiki_fingerprint_recorded": bool(wiki_fingerprint_recorded),
            "live_page_counts": {k: len(v) for k, v in live_pages.items()},
            "live_pages": live_pages,
        },
        "prior_decisions": prior_decisions[:20],
        "prior_decision_count": len(prior_decisions),
        "replay_method": (
            "Logical replay against typed knowledge layer. For byte-for-byte "
            "replay use git: `git log --until=" + str(decision.get("ts", "")) + " wiki/`"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("replay", help="Reconstruct state-of-world for a Decision.")
    r.add_argument("decision_id")
    r.add_argument("--strict", action="store_true",
                   help="Exclude pages with no parseable timestamp (default: include).")
    sub.add_parser("list", help="List all replayable Decisions, newest first.")
    args = parser.parse_args()

    if args.cmd == "list":
        print(json.dumps(_list_decisions(), indent=2, default=str))
        return 0

    result = replay(args.decision_id, strict=args.strict)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
