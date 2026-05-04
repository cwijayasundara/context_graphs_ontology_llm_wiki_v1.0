"""Compile wiki/ -> graph/kuzu.db. Wiki is canonical; graph is fully regenerated.

Also writes a .jsonl snapshot for git-diffable review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path

from _lib import GRAPH, ONTOLOGY, WIKI, iter_wiki_pages, load_ontology, parse_page
from logging_config import configure_logging, get_logger
from update_index import update_index


_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
_FINGERPRINT_PATH = GRAPH / ".compile.fingerprint"
log = get_logger("compile_graph")


def _input_fingerprint() -> str:
    """Hash every wiki page + ontology file by path + mtime + size.

    Cheap (no file reads) and stable: any wiki edit, ontology edit, page rename,
    or page deletion changes the fingerprint, which is enough to know the graph
    is stale. We never tie this to graph/ outputs — only to inputs.
    """
    h = hashlib.sha256()
    inputs: list[Path] = sorted(iter_wiki_pages())
    if ONTOLOGY.exists():
        inputs.extend(sorted(ONTOLOGY.glob("*.yaml")))
    for p in inputs:
        try:
            st = p.stat()
        except FileNotFoundError:
            continue
        rel = str(p.relative_to(GRAPH.parent)) if GRAPH.parent in p.parents else str(p)
        h.update(f"{rel}|{st.st_mtime_ns}|{st.st_size}\n".encode())
    return h.hexdigest()


def _outputs_present() -> bool:
    snap = GRAPH / "snapshots" / "graph.jsonl"
    if not snap.exists() or snap.stat().st_size == 0:
        return False
    db = GRAPH / "kuzu.db"
    try:
        import kuzu  # noqa: F401
        return db.exists()
    except ImportError:
        return True


def compile_graph(*, force: bool = False) -> dict:
    with _compile_lock():
        if not force:
            cached = _try_skip()
            if cached is not None:
                return cached
        result = _compile_graph_unlocked()
        if not result.get("errors"):
            _FINGERPRINT_PATH.parent.mkdir(parents=True, exist_ok=True)
            _FINGERPRINT_PATH.write_text(_input_fingerprint())
        return result


def _try_skip() -> dict | None:
    if not _FINGERPRINT_PATH.exists() or not _outputs_present():
        return None
    if _FINGERPRINT_PATH.read_text().strip() != _input_fingerprint():
        return None
    snap = GRAPH / "snapshots" / "graph.jsonl"
    nodes = edges = provenance = ontology_classes = ontology_properties = 0
    with snap.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                kind = json.loads(line).get("kind")
            except json.JSONDecodeError:
                continue
            if kind == "node":
                nodes += 1
            elif kind == "edge":
                edges += 1
            elif kind == "provenance":
                provenance += 1
            elif kind == "ontology_class":
                ontology_classes += 1
            elif kind == "ontology_property":
                ontology_properties += 1
    backend = "kuzu" if (GRAPH / "kuzu.db").exists() else "jsonl-only (install kuzu for graph queries)"
    log.info("compile_graph.skip_unchanged nodes=%s edges=%s backend=%s", nodes, edges, backend)
    return {
        "skipped": True,
        "reason": "wiki + ontology unchanged since last successful compile",
        "nodes": nodes, "edges": edges,
        "ontology_classes": ontology_classes,
        "ontology_properties": ontology_properties,
        "provenance_records": provenance,
        "errors": [], "backend": backend, "snapshot": str(snap),
        "hint": "run `python agents/compile_graph.py --force` (or pass force=True from Python) to recompile anyway",
    }


def _compile_graph_unlocked() -> dict:
    configure_logging()
    log.info("compile_graph.start")
    update_index()
    ontology = load_ontology()
    valid_object_types = {o["id"] for o in ontology["object_types"]}
    valid_link_types = {l["id"] for l in ontology["link_types"]}
    link_specs = {l["id"]: l for l in ontology["link_types"]}

    nodes: list[dict] = []
    edges: list[dict] = []
    provenance: list[dict] = []
    errors: list[str] = []
    page_types: dict[str, str] = {}

    for path in iter_wiki_pages():
        fm, body = parse_page(path)
        if not fm:
            errors.append(f"missing frontmatter: {path}")
            continue
        type_ = fm.get("type")
        id_ = fm.get("id")
        if type_ not in valid_object_types:
            errors.append(f"unknown Object Type {type_!r} in {path}")
            continue
        if not id_:
            errors.append(f"missing id in {path}")
            continue
        page_types[id_] = type_
        nodes.append({
            "id": id_,
            "type": type_,
            "ontology_class": type_,
            "path": str(path),
            "sources": fm.get("sources", []),
            "confidence": fm.get("confidence", 0.5),
            "updated": str(fm.get("updated", "")),
        })
        for source in fm.get("sources", []) or []:
            provenance.append({
                "entity_id": id_,
                "source": source,
                "path": str(path),
                "confidence": fm.get("confidence", 0.5),
            })
        for link in fm.get("links", []) or []:
            ltype = link.get("type")
            if ltype not in valid_link_types:
                errors.append(f"unknown Link Type {ltype!r} in {path}")
                continue
            edges.append({"from": id_, "to": link["to"], "type": ltype,
                          "ontology_property": ltype, "source_page": id_})
        if type_ == "Source" and "mentions" in valid_link_types:
            for target in _WIKILINK_RE.findall(body):
                edges.append({"from": id_, "to": target, "type": "mentions",
                              "ontology_property": "mentions", "source_page": id_})

    for edge in edges:
        spec = link_specs.get(edge["type"])
        if not spec:
            continue
        from_type = page_types.get(edge["from"])
        to_type = page_types.get(edge["to"])
        if from_type and not _type_allowed(from_type, spec.get("from")):
            errors.append(
                f"Link {edge['type']!r} from {edge['from']} has type {from_type!r}; "
                f"expected {_as_list(spec.get('from'))}"
            )
        if to_type and not _type_allowed(to_type, spec.get("to")):
            errors.append(
                f"Link {edge['type']!r} to {edge['to']} has type {to_type!r}; "
                f"expected {_as_list(spec.get('to'))}"
            )

    GRAPH.mkdir(parents=True, exist_ok=True)
    snap = GRAPH / "snapshots" / "graph.jsonl"
    snap.parent.mkdir(parents=True, exist_ok=True)
    with snap.open("w") as f:
        for item in ontology["object_types"]:
            f.write(json.dumps({"kind": "ontology_class", **item}) + "\n")
        for item in ontology["link_types"]:
            record = {"kind": "ontology_property", **item}
            record["from"] = _as_list(record.get("from"))
            record["to"] = _as_list(record.get("to"))
            f.write(json.dumps(record) + "\n")
        for n in nodes:
            f.write(json.dumps({"kind": "node", **n}) + "\n")
        for e in edges:
            f.write(json.dumps({"kind": "edge", **e}) + "\n")
        for p in provenance:
            f.write(json.dumps({"kind": "provenance", **p}) + "\n")
        trace_path = GRAPH / "retrieval_traces.jsonl"
        if trace_path.exists():
            for line in trace_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    f.write(line.rstrip() + "\n")

    try:
        import kuzu  # type: ignore

        db_path = GRAPH / "kuzu.db"
        if db_path.exists():
            shutil.rmtree(db_path) if db_path.is_dir() else db_path.unlink()
        db = kuzu.Database(str(db_path))
        conn = kuzu.Connection(db)
        conn.execute(
            "CREATE NODE TABLE Entity(id STRING, type STRING, path STRING, "
            "confidence DOUBLE, updated STRING, PRIMARY KEY(id))"
        )
        conn.execute("CREATE REL TABLE Link(FROM Entity TO Entity, type STRING)")
        for n in nodes:
            conn.execute(
                "CREATE (:Entity {id: $id, type: $t, path: $p, confidence: $c, updated: $u})",
                {"id": n["id"], "t": n["type"], "p": n["path"],
                 "c": float(n["confidence"]), "u": n["updated"]},
            )
        existing = {n["id"] for n in nodes}
        for e in edges:
            if e["from"] in existing and e["to"] in existing:
                conn.execute(
                    "MATCH (a:Entity {id: $f}), (b:Entity {id: $t}) "
                    "CREATE (a)-[:Link {type: $lt}]->(b)",
                    {"f": e["from"], "t": e["to"], "lt": e["type"]},
                )
        backend = "kuzu"
        log.info("compile_graph.kuzu_rebuilt db=%s", db_path)
    except ImportError:
        backend = "jsonl-only (install kuzu for graph queries)"
        log.info("compile_graph.kuzu_unavailable")

    result = {"nodes": len(nodes), "edges": len(edges),
              "ontology_classes": len(ontology["object_types"]),
              "ontology_properties": len(ontology["link_types"]),
              "provenance_records": len(provenance),
              "errors": errors, "backend": backend, "snapshot": str(snap)}
    log.info("compile_graph.done nodes=%s edges=%s provenance=%s errors=%s backend=%s",
             result["nodes"], result["edges"], result["provenance_records"],
             len(errors), backend)
    return result


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _type_allowed(actual: str, expected) -> bool:
    values = _as_list(expected)
    return not values or actual in values


@contextmanager
def _compile_lock():
    GRAPH.mkdir(parents=True, exist_ok=True)
    lock_path = GRAPH / ".compile.lock"
    with lock_path.open("w") as lock:
        try:
            import fcntl

            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
        except ImportError:
            yield


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="Recompile even if wiki + ontology are unchanged.")
    args = parser.parse_args()
    result = compile_graph(force=args.force)
    print(json.dumps(result, indent=2))
    sys.exit(1 if result["errors"] else 0)
