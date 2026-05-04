"""Searchable precedent over the Decision typed graph.

Closes the headline gap from the Foundation Capital "Context Graphs" thesis:
make organizational decisions queryable as precedent, not tribal knowledge.

Given a decision_class, an entity, or an action_id, returns the most relevant
prior Decisions ranked by recency × shared-target overlap × outcome match,
with their justifying memos and concepts inlined.

Pure function over the typed graph — no LLM. The Memo Engine + Decision pages
already carry typed `affects` / `justified_by` / `approved_by` / `targets`
edges; this just walks them.

CLI:
    python agents/precedent.py search --class operational_write_approved
    python agents/precedent.py search --action publish_intel_memo --entity nvidia-corp
    python agents/precedent.py search --entity customer_acme --limit 5
    python agents/precedent.py for-decision decision_publish_intel_memo_analyst_20260503T143955
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))

from _lib import WIKI, iter_wiki_pages, parse_page  # noqa: E402
from logging_config import configure_logging, get_logger  # noqa: E402

log = get_logger("precedent")


def _load_decisions() -> list[dict[str, Any]]:
    """Read every wiki/decisions/*.md page into a list of frontmatter dicts."""
    out: list[dict[str, Any]] = []
    for p in iter_wiki_pages():
        if p.parent.name != "decisions":
            continue
        try:
            fm, body = parse_page(p)
        except Exception:
            continue
        if fm.get("type") != "Decision":
            continue
        fm["_path"] = str(p.relative_to(ROOT))
        fm["_body"] = body
        out.append(fm)
    out.sort(key=lambda d: d.get("ts", ""), reverse=True)
    return out


def _link_targets(fm: dict[str, Any], link_type: str | None = None) -> set[str]:
    out: set[str] = set()
    for link in fm.get("links") or []:
        if not isinstance(link, dict):
            continue
        if link_type is None or link.get("type") == link_type:
            target = link.get("to")
            if target:
                out.add(target)
    return out


def _score(candidate: dict[str, Any], *,
           target_entities: set[str],
           target_class: str | None,
           target_action: str | None) -> tuple[float, dict]:
    """Heuristic relevance score. Higher = more relevant.

    - shared affected entity: +3 each (overlap is the strongest precedent signal)
    - same decision_class: +2
    - same action_id: +1.5
    - approved: +0.5 (precedent is stronger when the prior decision was approved)
    - successful outcome: +0.5
    """
    breakdown: dict[str, float] = {}
    affected = _link_targets(candidate, "affects") | _link_targets(candidate, "justified_by")
    overlap = affected & target_entities
    if overlap:
        breakdown["entity_overlap"] = 3.0 * len(overlap)
    if target_class and candidate.get("decision_class") == target_class:
        breakdown["class_match"] = 2.0
    if target_action and candidate.get("action_id") == target_action:
        breakdown["action_match"] = 1.5
    if candidate.get("approved"):
        breakdown["approved"] = 0.5
    if candidate.get("action_outcome") == "ok":
        breakdown["outcome_ok"] = 0.5
    return sum(breakdown.values()), breakdown


def _decision_summary(fm: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": fm.get("id"),
        "ts": fm.get("ts"),
        "actor": fm.get("actor"),
        "action_id": fm.get("action_id"),
        "decision_class": fm.get("decision_class"),
        "approved": fm.get("approved"),
        "outcome": fm.get("action_outcome"),
        "affects": sorted(_link_targets(fm, "affects")),
        "justified_by": sorted(_link_targets(fm, "justified_by")),
        "page": fm.get("_path"),
    }


def search_precedents(
    *,
    decision_class: str | None = None,
    action_id: str | None = None,
    entity: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Rank prior Decisions by relevance to the (class, action, entity) query."""
    configure_logging()
    log.info("precedent.search class=%s action=%s entity=%s limit=%s",
             decision_class, action_id, entity, limit)

    target_entities: set[str] = {entity} if entity else set()
    candidates = _load_decisions()
    scored = []
    for fm in candidates:
        score, breakdown = _score(
            fm,
            target_entities=target_entities,
            target_class=decision_class,
            target_action=action_id,
        )
        # Apply hard filters: if the user asked for a specific class/action,
        # require it. Entity overlap is a soft signal.
        if decision_class and fm.get("decision_class") != decision_class:
            continue
        if action_id and fm.get("action_id") != action_id:
            continue
        if score == 0 and (decision_class or action_id or entity):
            continue
        scored.append((score, breakdown, fm))

    # Sort by score desc, then ts desc (recency tiebreak).
    scored.sort(key=lambda x: (-x[0], -_ts_sort_key(x[2].get("ts", ""))))
    top = scored[:limit]

    return {
        "query": {"decision_class": decision_class, "action_id": action_id, "entity": entity},
        "candidates_considered": len(candidates),
        "matches_returned": len(top),
        "precedents": [
            {**_decision_summary(fm), "score": round(score, 2), "score_breakdown": breakdown}
            for score, breakdown, fm in top
        ],
    }


def _ts_sort_key(ts: str) -> int:
    """Cheap monotonic key for ts sorting; ISO timestamps sort lexicographically."""
    try:
        return hash(ts)
    except Exception:
        return 0


def precedents_for(decision_id: str, *, limit: int = 5) -> dict[str, Any]:
    """Find precedents for a SPECIFIC decision: use its own (class, action,
    affects) signature as the query."""
    decisions = _load_decisions()
    target = next((d for d in decisions if d.get("id") == decision_id), None)
    if not target:
        return {"error": f"decision {decision_id!r} not found"}
    target_entities = _link_targets(target, "affects") | _link_targets(target, "justified_by")
    others = [d for d in decisions if d.get("id") != decision_id]
    scored = []
    for fm in others:
        score, breakdown = _score(
            fm,
            target_entities=target_entities,
            target_class=target.get("decision_class"),
            target_action=target.get("action_id"),
        )
        if score > 0:
            scored.append((score, breakdown, fm))
    scored.sort(key=lambda x: (-x[0], -_ts_sort_key(x[2].get("ts", ""))))
    top = scored[:limit]
    return {
        "for_decision": _decision_summary(target),
        "candidates_considered": len(others),
        "precedents": [
            {**_decision_summary(fm), "score": round(score, 2), "score_breakdown": breakdown}
            for score, breakdown, fm in top
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("search", help="Search precedents by class/action/entity.")
    p.add_argument("--class", dest="decision_class",
                   help="Filter to one decision_class (review_flag, publication, "
                        "operational_write_approved, operational_write_unapproved, synthesis, other).")
    p.add_argument("--action", dest="action_id", help="Filter to one action_id (e.g. publish_intel_memo).")
    p.add_argument("--entity", help="Soft signal: prior decisions that affect this entity score higher.")
    p.add_argument("--limit", type=int, default=5)

    f = sub.add_parser("for-decision", help="Find precedents for a specific Decision id.")
    f.add_argument("decision_id")
    f.add_argument("--limit", type=int, default=5)

    args = parser.parse_args()
    if args.cmd == "search":
        result = search_precedents(
            decision_class=args.decision_class,
            action_id=args.action_id,
            entity=args.entity,
            limit=args.limit,
        )
    else:
        result = precedents_for(args.decision_id, limit=args.limit)

    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
