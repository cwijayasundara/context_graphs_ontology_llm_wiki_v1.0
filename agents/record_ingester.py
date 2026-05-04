"""Manifest-driven record ingester.

Where the LLM ingestor handles documents (PDF/Word/PPT/HTML) by reading prose
and extracting typed entities, this module handles **records** — CSV, XLSX,
and (eventually) DB extracts and API JSON. Records are higher-precision
than prose: one row often *is* one entity, and we don't want an LLM guessing
column semantics.

Each record source ships a sibling manifest (YAML) declaring how columns map
to ontology Object Types. The ingester:

  1. validates the mapping against ontology/object_types.yaml + link_types.yaml
     up front (fail fast — no rows touched if the mapping is wrong);
  2. computes a content hash over the canonical record set (sorted rows) so
     re-ingest is a no-op when the source bytes are equivalent;
  3. writes one wiki/entities/ page per row with citations like
     `raw/records/foo.csv#row=42`;
  4. writes the source page through the existing wiki contract;
  5. recompiles the graph (idempotent — skip if nothing changed).

CLI:
    python agents/record_ingester.py ingest raw/records/customers.csv
    python agents/record_ingester.py ingest raw/records/customers.csv --force
    python agents/record_ingester.py validate raw/records/customers.csv
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))

import yaml

from _lib import RAW, WIKI, load_ontology
from compile_graph import compile_graph
from logging_config import configure_logging, get_logger

log = get_logger("record_ingester")


# --------------------------------------------------------------------------
# Manifest schema (validated up front; fail fast).
# --------------------------------------------------------------------------

REQUIRED_TOP_LEVEL = {"source_class", "mapping"}
REQUIRED_MAPPING_KEYS = {"target_type", "identity"}
REQUIRED_IDENTITY_KEYS = {"column", "slug"}


class ManifestError(ValueError):
    """Raised when a manifest is invalid against the ontology or schema."""


def _manifest_path_for(raw_path: Path) -> Path:
    sib = raw_path.with_suffix(raw_path.suffix + ".manifest.yaml")
    if sib.exists():
        return sib
    sib2 = raw_path.with_suffix(".manifest.yaml")
    if sib2.exists():
        return sib2
    raise ManifestError(
        f"no manifest for {raw_path}; expected {sib.name} or {sib2.name}"
    )


def load_manifest(raw_path: Path) -> dict[str, Any]:
    mpath = _manifest_path_for(raw_path)
    manifest = yaml.safe_load(mpath.read_text()) or {}
    missing = REQUIRED_TOP_LEVEL - set(manifest.keys())
    if missing:
        raise ManifestError(f"{mpath} missing required keys: {sorted(missing)}")
    mapping = manifest["mapping"]
    missing = REQUIRED_MAPPING_KEYS - set(mapping.keys())
    if missing:
        raise ManifestError(f"{mpath}.mapping missing keys: {sorted(missing)}")
    missing = REQUIRED_IDENTITY_KEYS - set(mapping["identity"].keys())
    if missing:
        raise ManifestError(f"{mpath}.mapping.identity missing keys: {sorted(missing)}")
    return manifest


def validate_against_ontology(manifest: dict[str, Any]) -> None:
    """Check the manifest's target_type and link_types exist in the ontology."""
    ontology = load_ontology()
    valid_types = {o["id"] for o in ontology["object_types"]}
    valid_link_types = {l["id"] for l in ontology["link_types"]}

    target = manifest["mapping"]["target_type"]
    if target not in valid_types:
        raise ManifestError(
            f"target_type {target!r} not in ontology; valid: {sorted(valid_types)}"
        )
    for link in manifest["mapping"].get("links", []):
        if link.get("target_type") not in valid_types:
            raise ManifestError(
                f"link.target_type {link.get('target_type')!r} not in ontology"
            )
        if link.get("link_type") not in valid_link_types:
            raise ManifestError(
                f"link.link_type {link.get('link_type')!r} not in ontology"
            )


# --------------------------------------------------------------------------
# Row reading: CSV and XLSX, both yield list[dict[str, str]] uniformly.
# --------------------------------------------------------------------------

def read_rows(raw_path: Path) -> list[dict[str, str]]:
    suffix = raw_path.suffix.lower()
    if suffix == ".csv":
        with raw_path.open(encoding="utf-8-sig", newline="") as f:
            return [
                {k: ("" if v is None else str(v).strip()) for k, v in row.items()}
                for row in csv.DictReader(f)
            ]
    if suffix in {".xlsx", ".xlsm"}:
        try:
            import openpyxl
        except ImportError as exc:
            raise RuntimeError(
                "Install openpyxl for Excel record ingest: pip install openpyxl"
            ) from exc
        wb = openpyxl.load_workbook(raw_path, data_only=True, read_only=True)
        ws = wb.active
        rows = ws.iter_rows(values_only=True)
        try:
            header = [str(c).strip() if c is not None else "" for c in next(rows)]
        except StopIteration:
            return []
        return [
            {
                header[i]: ("" if cell is None else str(cell).strip())
                for i, cell in enumerate(row)
                if i < len(header)
            }
            for row in rows
            if any(c is not None and str(c).strip() for c in row)
        ]
    raise ValueError(f"unsupported record format {suffix!r}; expected .csv, .xlsx, .xlsm")


# --------------------------------------------------------------------------
# Identity: build a stable wiki id from a row using the manifest slug template.
# --------------------------------------------------------------------------

_SLUG_RE = re.compile(r"\{([a-zA-Z0-9_]+)(?:\|([a-zA-Z0-9_]+))?\}")


def _slug_token(value: str, transform: str | None) -> str:
    s = value.strip()
    if not s:
        return ""
    if transform == "slug" or transform is None:
        return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    if transform == "email_local":
        return re.sub(r"[^a-z0-9]+", "_", s.split("@", 1)[0].lower()).strip("_")
    if transform == "lower":
        return s.lower()
    if transform == "raw":
        return s
    raise ManifestError(f"unknown slug transform {transform!r}")


def render_id(template: str, row: dict[str, str]) -> str:
    def repl(m: re.Match) -> str:
        col, transform = m.group(1), m.group(2)
        if col not in row:
            raise ManifestError(f"slug template references missing column {col!r}")
        return _slug_token(row[col], transform)

    rendered = _SLUG_RE.sub(repl, template)
    return rendered.strip("_") or "row"


# --------------------------------------------------------------------------
# Content hash: sorted canonical CSV-style serialization. Stable across row
# reorderings; changes only when row contents actually change.
# --------------------------------------------------------------------------

def canonical_content_hash(rows: list[dict[str, str]]) -> str:
    if not rows:
        return hashlib.sha256(b"").hexdigest()
    columns = sorted({k for row in rows for k in row.keys()})
    canonical = []
    for row in rows:
        canonical.append("".join(f"{c}={row.get(c, '')}" for c in columns))
    canonical.sort()
    return hashlib.sha256("".join(canonical).encode()).hexdigest()


# --------------------------------------------------------------------------
# Page writers (use the same wiki contract as the LLM ingestor's upsert tools).
# --------------------------------------------------------------------------

def _frontmatter_block(fm: dict[str, Any]) -> str:
    return "---\n" + "\n".join(f"{k}: {json.dumps(v)}" for k, v in fm.items()) + "\n---\n"


def _write_entity_page(rel_dir: str, fm: dict[str, Any], title: str, body: str) -> Path:
    path = WIKI / rel_dir / f"{fm['id']}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{_frontmatter_block(fm)}\n# {title}\n\n{body}\n")
    return path


def _append_log(line: str) -> None:
    log_path = WIKI / "log.md"
    if not log_path.exists():
        log_path.write_text("# Log\n\n")
    with log_path.open("a") as f:
        f.write(f"- {dt.datetime.now(dt.timezone.utc).isoformat()} — {line}\n")


# --------------------------------------------------------------------------
# Idempotency: the source page records the content_hash from last successful
# ingest. Skip when it matches the new hash.
# --------------------------------------------------------------------------

def _existing_source(raw_rel: str) -> tuple[Path, dict[str, Any]] | None:
    sources_dir = WIKI / "sources"
    if not sources_dir.exists():
        return None
    for page in sources_dir.glob("*.md"):
        text = page.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        try:
            fm_text, _ = text[4:].split("\n---", 1)
            fm = yaml.safe_load(fm_text) or {}
        except Exception:
            continue
        if fm.get("raw_path") == raw_rel:
            return page, fm
    return None


# --------------------------------------------------------------------------
# Mapping: row -> entity. Honors manifest required/optional/links.
# --------------------------------------------------------------------------

def _row_to_entity(
    row: dict[str, str],
    manifest: dict[str, Any],
    raw_rel: str,
    row_idx: int,
) -> tuple[dict[str, Any], list[Path]] | None:
    """Returns (entity_frontmatter, secondary_pages_to_write) or None to skip."""
    mapping = manifest["mapping"]
    target_type = mapping["target_type"]
    identity = mapping["identity"]
    id_value = render_id(identity["slug"], row)
    if not id_value or id_value == "row":
        return None

    extra: dict[str, Any] = {}
    for key, spec in (mapping.get("required") or {}).items():
        col = spec["column"]
        val = row.get(col, "").strip()
        if not val:
            raise ManifestError(
                f"row {row_idx}: required field {key!r} (column {col!r}) is empty"
            )
        if spec.get("validate_against") and val not in spec["validate_against"]:
            raise ManifestError(
                f"row {row_idx}: {key}={val!r} not in {spec['validate_against']}"
            )
        extra[key] = val

    for key, spec in (mapping.get("optional") or {}).items():
        col = spec["column"]
        val = row.get(col, "").strip() or spec.get("default")
        if val:
            if spec.get("validate_against") and val not in spec["validate_against"]:
                raise ManifestError(
                    f"row {row_idx}: {key}={val!r} not in {spec['validate_against']}"
                )
            extra[key] = val

    citation = f"{raw_rel}#row={row_idx}"
    fm: dict[str, Any] = {
        "id": id_value,
        "type": target_type,
        "sources": [citation],
        "confidence": float(manifest.get("default_confidence", 0.95)),
        "updated": dt.date.today().isoformat(),
    }
    fm.update({k: v for k, v in extra.items() if k not in fm})

    secondary_pages: list[dict[str, Any]] = []
    links: list[dict[str, str]] = []
    for link_spec in mapping.get("links", []):
        sub_id_template = link_spec["identity"]["slug"]
        # If the slug references a column that's empty, skip the link cleanly.
        try:
            sub_id = render_id(sub_id_template, row)
        except ManifestError:
            continue
        if not sub_id or sub_id == "row":
            continue

        link_type = link_spec["link_type"]
        direction = link_spec.get("direction", "from_self")
        sub_type = link_spec["target_type"]

        if direction == "from_self":
            links.append({"to": sub_id, "type": link_type})
        # We always materialize the linked entity as its own page so the
        # graph has both endpoints typed. For "from_other" direction the
        # outbound link lives on the *other* page.
        sub_extra: dict[str, Any] = {}
        for key, spec in (link_spec.get("required") or {}).items():
            col = spec["column"]
            val = row.get(col, "").strip()
            if not val:
                raise ManifestError(
                    f"row {row_idx}: required link field {key!r} empty"
                )
            sub_extra[key] = val
        for key, spec in (link_spec.get("optional") or {}).items():
            val = row.get(spec["column"], "").strip() or spec.get("default")
            if val:
                sub_extra[key] = val
        sub_fm: dict[str, Any] = {
            "id": sub_id,
            "type": sub_type,
            "sources": [citation],
            "confidence": float(link_spec.get("confidence", manifest.get("default_confidence", 0.95))),
            "updated": dt.date.today().isoformat(),
        }
        sub_fm.update({k: v for k, v in sub_extra.items() if k not in sub_fm})
        if direction == "from_other":
            sub_fm["links"] = [{"to": id_value, "type": link_type}]
        secondary_pages.append(sub_fm)

    if links:
        fm["links"] = links

    return fm, secondary_pages


# --------------------------------------------------------------------------
# Orchestrator.
# --------------------------------------------------------------------------

def _render_body(fm: dict[str, Any], manifest: dict[str, Any]) -> str:
    target_type = manifest["mapping"]["target_type"]
    name_field = manifest["mapping"].get("name_field")
    title = fm.get(name_field) if name_field else fm.get("name") or fm["id"]
    lines = [f"_{target_type} record imported from `{fm['sources'][0]}`._\n"]
    skip = {"id", "type", "sources", "confidence", "updated", "links"}
    for k, v in fm.items():
        if k in skip:
            continue
        lines.append(f"- **{k}**: {v}")
    return "\n".join(lines)


def ingest(raw_path: Path, *, force: bool = False) -> dict[str, Any]:
    configure_logging()
    log.info("record_ingest.start raw_path=%s force=%s", raw_path, force)
    if not raw_path.exists():
        raise FileNotFoundError(raw_path)
    manifest = load_manifest(raw_path)
    validate_against_ontology(manifest)

    raw_resolved = raw_path.resolve()
    raw_root_resolved = RAW.resolve()
    if raw_root_resolved in raw_resolved.parents:
        rel = str(Path("raw") / raw_resolved.relative_to(raw_root_resolved))
    else:
        rel = str(raw_resolved)
    rows = read_rows(raw_path)
    new_hash = canonical_content_hash(rows)

    existing = _existing_source(rel)
    if existing is not None and not force:
        _, fm_old = existing
        if fm_old.get("content_hash") == new_hash:
            log.info("record_ingest.skip_unchanged raw_path=%s rows=%s", raw_path, len(rows))
            return {
                "skipped": True,
                "reason": "content hash unchanged since last ingest",
                "raw_path": rel,
                "rows": len(rows),
                "content_hash": new_hash,
                "hint": "pass --force to re-ingest",
            }

    target_type = manifest["mapping"]["target_type"]
    sub_dir = "entities"  # Customers, Persons, Products land in entities/
    written: list[Path] = []
    secondary_seen: dict[str, dict[str, Any]] = {}

    for idx, row in enumerate(rows, start=1):
        result = _row_to_entity(row, manifest, rel, idx)
        if result is None:
            continue
        fm, secondary = result
        body = _render_body(fm, manifest)
        title = fm.get(manifest["mapping"].get("name_field", "name"), fm["id"])
        written.append(_write_entity_page(sub_dir, fm, title, body))
        for sub_fm in secondary:
            existing_sub = secondary_seen.get(sub_fm["id"])
            if existing_sub:
                # Merge sources + links across rows that reference the same secondary entity.
                existing_sub["sources"] = sorted(set(existing_sub["sources"]) | set(sub_fm["sources"]))
                if "links" in sub_fm:
                    existing_sub.setdefault("links", [])
                    for link in sub_fm["links"]:
                        if link not in existing_sub["links"]:
                            existing_sub["links"].append(link)
            else:
                secondary_seen[sub_fm["id"]] = dict(sub_fm)

    for sub_fm in secondary_seen.values():
        body = _render_body(sub_fm, {"mapping": {"target_type": sub_fm["type"]}})
        title = sub_fm.get("name") or sub_fm["id"]
        written.append(_write_entity_page(sub_dir, sub_fm, title, body))

    # Source page (records the content_hash for next-run idempotency).
    src_id = "src_" + render_id("{stem|slug}", {"stem": raw_path.stem})
    src_fm = {
        "id": src_id,
        "type": "Source",
        "sources": [rel],
        "confidence": 1.0,
        "updated": dt.date.today().isoformat(),
        "raw_path": rel,
        "ingested_at": dt.date.today().isoformat(),
        "source_class": manifest["source_class"],
        "content_hash": new_hash,
        "manifest_path": str(_manifest_path_for(raw_path).relative_to(ROOT)),
        "row_count": len(rows),
        "target_type": target_type,
    }
    src_body = (
        f"Record source ingested from `{rel}` via manifest "
        f"`{src_fm['manifest_path']}`.\n\n"
        f"- Rows: {len(rows)}\n"
        f"- Target type: {target_type}\n"
        f"- Content hash: `{new_hash[:16]}...`\n\n"
        f"Touched pages: " + ", ".join(f"[[{p.stem}]]" for p in written[:30])
        + (f"\n\n_…and {len(written) - 30} more._" if len(written) > 30 else "")
    )
    _write_entity_page("sources", src_fm, raw_path.name, src_body)
    _append_log(f"record-ingest {rel} -> {len(written)} entity pages (hash {new_hash[:8]})")

    log.info("record_ingest.done raw_path=%s rows=%s pages=%s", raw_path, len(rows), len(written))
    compile_result = compile_graph()
    return {
        "raw_path": rel,
        "rows": len(rows),
        "pages_written": len(written),
        "primary_pages": len(rows),
        "secondary_pages": len(secondary_seen),
        "content_hash": new_hash,
        "source_page": str((WIKI / "sources" / f"{src_id}.md").relative_to(ROOT)),
        "compile": {
            "errors": compile_result.get("errors", []),
            "skipped": compile_result.get("skipped", False),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest", help="Ingest a record source per its manifest.")
    p.add_argument("path", type=Path)
    p.add_argument("--force", action="store_true",
                   help="Re-ingest even if content hash is unchanged.")
    v = sub.add_parser("validate", help="Validate manifest against the ontology without writing.")
    v.add_argument("path", type=Path)
    args = parser.parse_args()

    raw_path = args.path.resolve()
    if args.cmd == "validate":
        manifest = load_manifest(raw_path)
        validate_against_ontology(manifest)
        rows = read_rows(raw_path)
        out = {
            "manifest": str(_manifest_path_for(raw_path).relative_to(ROOT)),
            "target_type": manifest["mapping"]["target_type"],
            "rows": len(rows),
            "columns": sorted({k for row in rows for k in row.keys()}),
            "ok": True,
        }
        print(json.dumps(out, indent=2))
        return 0

    result = ingest(raw_path, force=args.force)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
