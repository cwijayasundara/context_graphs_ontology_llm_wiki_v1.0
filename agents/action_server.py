"""MCP-style action server. Each Action Type in ontology/action_types.yaml is
exposed as a tool. Scopes are enforced; inputs are validated; every call is audited.

Run as a plain CLI for local testing:
    python agents/action_server.py list
    python agents/action_server.py invoke create_customer --actor alice \
        --inputs '{"name":"Acme","region":"NA"}'

To plug into Claude/Codex/etc., wrap each entry in REGISTRY as an MCP tool.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ontology.functions import REGISTRY as FUNCTIONS  # noqa: E402

from _lib import load_ontology  # noqa: E402


class PermissionError_(Exception):
    pass


class ApprovalRequired(Exception):
    pass


def _check_scope(actor_scopes: set[str], required: str) -> None:
    if required == "any_authenticated":
        return
    if required not in actor_scopes:
        raise PermissionError_(f"actor lacks scope {required!r}")


def _validate_inputs(spec: dict, inputs: dict) -> dict:
    out = {}
    for key, schema in spec.items():
        if key in inputs:
            value = inputs[key]
        elif schema.get("required", False):
            raise ValueError(f"missing required input: {key}")
        else:
            value = schema.get("default")
            if value is None:
                continue
        if schema["type"] == "enum" and value not in schema["values"]:
            raise ValueError(f"{key}={value!r} not in {schema['values']}")
        out[key] = value
    return out


def list_actions() -> list[dict]:
    ont = load_ontology()
    return [{"id": a["id"], "scope": a["scope"],
             "requires_approval": a.get("requires_approval", False),
             "description": a.get("description", "")}
            for a in ont["action_types"]]


def invoke(action_id: str, *, actor: str, actor_scopes: set[str],
           inputs: dict, approved: bool = False) -> dict:
    ont = load_ontology()
    spec = next((a for a in ont["action_types"] if a["id"] == action_id), None)
    if not spec:
        raise KeyError(f"unknown action: {action_id}")

    _check_scope(actor_scopes, spec["scope"])
    if spec.get("requires_approval") and not approved:
        raise ApprovalRequired(f"{action_id} requires approval; pass --approved")

    validated = _validate_inputs(spec.get("inputs", {}), inputs)
    fn = FUNCTIONS[spec["function"]]
    # Stash invocation metadata so the action handler's _audit() can write a
    # complete Decision wiki page (scopes + approval came in via the server,
    # not via the action's input schema).
    import os
    os.environ["_DECISION_SCOPES"] = ",".join(sorted(actor_scopes))
    os.environ["_DECISION_APPROVED"] = "1" if approved else "0"
    try:
        return fn(actor=actor, **validated)
    finally:
        os.environ.pop("_DECISION_SCOPES", None)
        os.environ.pop("_DECISION_APPROVED", None)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p_inv = sub.add_parser("invoke")
    p_inv.add_argument("action_id")
    p_inv.add_argument("--actor", required=True)
    p_inv.add_argument("--scopes", default="any_authenticated",
                       help="comma-separated, e.g. sales_ops,procurement_admin")
    p_inv.add_argument("--inputs", default="{}", help="JSON dict")
    p_inv.add_argument("--approved", action="store_true")
    args = parser.parse_args()

    if args.cmd == "list":
        print(json.dumps(list_actions(), indent=2))
        return 0

    scopes = {s.strip() for s in args.scopes.split(",") if s.strip()} | {"any_authenticated"}
    try:
        result = invoke(args.action_id, actor=args.actor, actor_scopes=scopes,
                        inputs=json.loads(args.inputs), approved=args.approved)
    except (PermissionError_, ApprovalRequired, ValueError, KeyError) as e:
        print(json.dumps({"error": type(e).__name__, "message": str(e)}, indent=2))
        return 2
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
