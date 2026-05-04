"""Audited local adapters for Action Types.

These functions intentionally write only to the local wiki/audit log. External
CRM/ERP integrations should be added as explicit adapters with their own tests
and configuration instead of being implied by these local actions.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]
WIKI = ROOT / "wiki"
AUDIT_LOG = ROOT / "graph" / "audit.jsonl"
LOCAL_ADAPTER = "local_wiki"


def _audit(actor: str, action: str, inputs: dict, result: dict,
           *, scopes: list[str] | None = None, approved: bool | None = None) -> str:
    """Append the audit row AND write a typed Decision wiki page so every
    Action invocation becomes a first-class queryable graph node, not just a
    line in audit.jsonl. Returns the Decision id."""
    import os
    if scopes is None:
        scopes_env = os.environ.get("_DECISION_SCOPES", "")
        scopes = [s for s in scopes_env.split(",") if s] if scopes_env else []
    if approved is None:
        approved = os.environ.get("_DECISION_APPROVED", "0") == "1"
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_LOG.open("a") as f:
        f.write(json.dumps({
            "ts": ts, "actor": actor, "action": action,
            "adapter": LOCAL_ADAPTER, "external_write": False,
            "inputs": inputs, "result": result,
            "scopes": list(scopes or []), "approved": approved,
        }) + "\n")
    return _write_decision_page(ts=ts, actor=actor, action=action, inputs=inputs,
                                 result=result, scopes=list(scopes or []), approved=approved)


def _decision_id(ts: str, action: str, actor: str) -> str:
    safe_ts = ts.replace(":", "").replace("-", "").replace(".", "").replace("+", "_")
    safe_actor = "".join(c if c.isalnum() else "_" for c in actor.lower())
    return f"decision_{action}_{safe_actor}_{safe_ts[:18]}"


def _wiki_fingerprint() -> str:
    """Hash all wiki page mtimes+sizes (cheap, stable). Records what state of
    the wiki was live at decision time — the basis for replay."""
    try:
        items = []
        for p in sorted((WIKI).rglob("*.md")):
            st = p.stat()
            items.append(f"{p.relative_to(WIKI)}|{st.st_mtime_ns}|{st.st_size}")
        return hashlib.sha256("\n".join(items).encode()).hexdigest()
    except Exception:
        return ""


def _ontology_fingerprint() -> str:
    items = []
    for name in ("object_types.yaml", "link_types.yaml", "action_types.yaml"):
        p = ROOT / "ontology" / name
        if p.exists():
            st = p.stat()
            items.append(f"{name}|{st.st_mtime_ns}|{st.st_size}")
    return hashlib.sha256("\n".join(items).encode()).hexdigest() if items else ""


_AFFECTING_INPUT_KEYS = (
    "target_entity", "concept_id", "supplier_id", "customer_id",
    "actor", "page_id", "entity_id", "name",
)


def _decision_links(action: str, inputs: dict) -> list[dict]:
    """Best-effort: derive 'affects' / 'justified_by' typed links from common
    input keys. Conservative — only writes a link when the input value looks
    like a plausible wiki id."""
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for key in _AFFECTING_INPUT_KEYS:
        val = inputs.get(key)
        if not val or not isinstance(val, str):
            continue
        if not val.replace("_", "").replace("-", "").isalnum():
            continue
        link_type = "affects" if key not in {"actor"} else "approved_by"
        sig = (val, link_type)
        if sig in seen:
            continue
        seen.add(sig)
        out.append({"to": val, "type": link_type})
    for cite in inputs.get("cites") or []:
        if isinstance(cite, str) and (cite, "justified_by") not in seen:
            out.append({"to": cite, "type": "justified_by"})
            seen.add((cite, "justified_by"))
    for flagged in inputs.get("flagged") or []:
        if isinstance(flagged, str) and (flagged, "affects") not in seen:
            out.append({"to": flagged, "type": "affects"})
            seen.add((flagged, "affects"))
    return out


def _classify(action: str, inputs: dict, approved: bool) -> str:
    """Lightweight decision classification for precedent search."""
    if action.startswith("flag_"):
        return "review_flag"
    if action.startswith("publish_"):
        return "publication"
    if action.startswith("create_") or action.startswith("trigger_"):
        return "operational_write" + ("_approved" if approved else "_unapproved")
    if action.startswith("file_") or action.startswith("run_"):
        return "synthesis"
    return "other"


def _write_decision_page(*, ts: str, actor: str, action: str, inputs: dict,
                         result: dict, scopes: list[str], approved: bool) -> str:
    """Write wiki/decisions/<id>.md. Returns the Decision id."""
    decision_id = _decision_id(ts, action, actor)
    decision_class = _classify(action, inputs, approved)
    inputs_summary = json.dumps({k: inputs[k] for k in list(inputs)[:5]}, default=str)[:300]
    result_summary = json.dumps({k: result[k] for k in list(result)[:5]}, default=str)[:300]
    action_outcome = "ok" if isinstance(result, dict) and not result.get("error") else "error"

    fm = {
        "id": decision_id,
        "type": "Decision",
        "sources": [f"action:{action}", f"actor:{actor}"],
        "confidence": 0.99,
        "updated": dt.date.today().isoformat(),
        "ts": ts,
        "actor": actor,
        "action_id": action,
        "scopes": scopes,
        "approved": approved,
        "decision_class": decision_class,
        "action_outcome": action_outcome,
        "inputs_summary": inputs_summary,
        "result_summary": result_summary,
        "wiki_fingerprint": _wiki_fingerprint(),
        "ontology_fingerprint": _ontology_fingerprint(),
    }
    links = _decision_links(action, inputs)
    if links:
        fm["links"] = links

    page = WIKI / "decisions" / f"{decision_id}.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    body = (
        f"_Decision auto-recorded by the action server._\n\n"
        f"- **Action:** `{action}`\n"
        f"- **Actor:** {actor}\n"
        f"- **Scopes:** {', '.join(scopes) if scopes else '_none_'}\n"
        f"- **Approved:** {approved}\n"
        f"- **Class:** {decision_class}\n"
        f"- **Outcome:** {action_outcome}\n\n"
        f"## Inputs\n\n```json\n{inputs_summary}\n```\n\n"
        f"## Result\n\n```json\n{result_summary}\n```\n"
    )
    fm_block = "---\n" + "\n".join(f"{k}: {json.dumps(v)}" for k, v in fm.items()) + "\n---\n"
    page.write_text(f"{fm_block}\n# {action} @ {ts}\n\n{body}\n")
    return decision_id


def _upsert_entity(type_: str, id_: str, name: str, sources: list[str], extra: dict) -> None:
    path = WIKI / "entities" / f"{id_}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    frontmatter = {
        "id": id_,
        "type": type_,
        "sources": sources,
        "confidence": 0.99,
        "updated": today,
        **extra,
    }
    body = path.read_text().split("---", 2)[-1] if path.exists() else f"\n# {name}\n"
    fm = "---\n" + "\n".join(f"{k}: {json.dumps(v)}" for k, v in frontmatter.items()) + "\n---"
    path.write_text(f"{fm}\n{body}")


def create_customer(*, actor: str, name: str, region: str, tier: str = "t3") -> dict:
    cid = f"customer_{name.lower().replace(' ', '_')}"
    result = {
        "id": cid,
        "name": name,
        "region": region,
        "tier": tier,
        "adapter": LOCAL_ADAPTER,
        "external_write": False,
    }
    _upsert_entity("Customer", cid, name, sources=[f"action:{actor}"],
                   extra={"region": region, "tier": tier})
    _audit(actor, "create_customer", {"name": name, "region": region, "tier": tier}, result)
    return result


def trigger_purchase_order(*, actor: str, supplier_id: str, amount_usd: float,
                            line_items: list[str]) -> dict:
    po_id = f"po_{uuid.uuid4().hex[:8]}"
    result = {"po_id": po_id, "supplier_id": supplier_id,
              "amount_usd": amount_usd, "line_items": line_items, "status": "queued",
              "adapter": LOCAL_ADAPTER, "external_write": False}
    _audit(actor, "trigger_purchase_order",
           {"supplier_id": supplier_id, "amount_usd": amount_usd, "line_items": line_items},
           result)
    return result


def run_allocation_scenario(*, actor: str, plant_id: str, horizon_days: int) -> dict:
    score = round(min(1.0, horizon_days / 365.0), 3)
    result = {"plant_id": plant_id, "horizon_days": horizon_days, "score": score,
              "adapter": LOCAL_ADAPTER, "external_write": False}
    _audit(actor, "run_allocation_scenario",
           {"plant_id": plant_id, "horizon_days": horizon_days}, result)
    return result


def file_synthesis(*, actor: str, title: str, body_markdown: str, cites: list[str]) -> dict:
    slug = title.lower().replace(" ", "_")[:60]
    path = WIKI / "synthesis" / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    fm = (
        "---\n"
        f"id: synthesis_{slug}\n"
        "type: Concept\n"
        f"sources: {json.dumps(cites)}\n"
        "confidence: 0.85\n"
        f"updated: {today}\n"
        "---\n"
    )
    path.write_text(f"{fm}\n# {title}\n\n{body_markdown}\n")
    result = {"path": str(path.relative_to(ROOT))}
    result.update({"adapter": LOCAL_ADAPTER, "external_write": False})
    _audit(actor, "file_synthesis", {"title": title, "cites": cites}, result)
    return result


def publish_intel_memo(*, actor: str, title: str, target_entity: str,
                       body_markdown: str, cites: list[str],
                       reasoning_trace: dict, flagged: list[str] | None = None) -> dict:
    """Write a typed Memo wiki page + reasoning-trace artifact + audit row.

    Memo is an Object Type. Citations become typed `cites_evidence` links.
    Flagged ids become typed `flags_concept` links. The reasoning trace is
    written as JSON under graph/memos/ for downstream replay/audit.
    """
    flagged = list(flagged or [])
    slug = "".join(c if c.isalnum() else "_" for c in title.lower()).strip("_")[:60]
    memo_id = f"memo_{slug}"
    today = dt.date.today().isoformat()
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    links: list[dict] = [{"to": target_entity, "type": "targets"}]
    for cite in cites:
        links.append({"to": cite, "type": "cites_evidence"})
    for fid in flagged:
        links.append({"to": fid, "type": "flags_concept"})

    frontmatter = {
        "id": memo_id,
        "type": "Memo",
        "title": title,
        "target_entity": target_entity,
        "generated_at": now,
        "hops": reasoning_trace.get("hops"),
        "claim_count": len(cites),
        "contradictions_count": len(reasoning_trace.get("contradictions", [])),
        "freshness_warnings_count": len(reasoning_trace.get("freshness_warnings", [])),
        "sources": cites,
        "confidence": 0.9,
        "updated": today,
        "links": links,
    }
    fm_block = "---\n" + "\n".join(f"{k}: {json.dumps(v)}" for k, v in frontmatter.items()) + "\n---\n"

    page = WIKI / "memos" / f"{memo_id}.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(f"{fm_block}\n# {title}\n\n{body_markdown}\n")

    trace_path = ROOT / "graph" / "memos" / f"{memo_id}.json"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text(json.dumps(reasoning_trace, indent=2, sort_keys=True, default=str))

    result = {
        "memo_id": memo_id,
        "page": str(page.relative_to(ROOT)),
        "trace": str(trace_path.relative_to(ROOT)),
        "links_written": len(links),
        "adapter": LOCAL_ADAPTER,
        "external_write": False,
    }
    _audit(actor, "publish_intel_memo",
           {"title": title, "target_entity": target_entity,
            "cites": cites, "flagged": flagged}, result)
    return result


def flag_concept_review(*, actor: str, concept_id: str, reason: str, detail: str) -> dict:
    """Append to graph/review_queue.jsonl. Idempotent on (concept_id, reason)."""
    queue_path = ROOT / "graph" / "review_queue.jsonl"
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    existing: set[tuple[str, str]] = set()
    if queue_path.exists():
        for line in queue_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            existing.add((row.get("concept_id", ""), row.get("reason", "")))

    duplicate = (concept_id, reason) in existing
    if not duplicate:
        with queue_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
                "actor": actor,
                "concept_id": concept_id,
                "reason": reason,
                "detail": detail,
            }) + "\n")

    result = {
        "concept_id": concept_id,
        "reason": reason,
        "detail": detail,
        "queue": str(queue_path.relative_to(ROOT)),
        "duplicate": duplicate,
        "adapter": LOCAL_ADAPTER,
        "external_write": False,
    }
    _audit(actor, "flag_concept_review",
           {"concept_id": concept_id, "reason": reason, "detail": detail}, result)
    return result
