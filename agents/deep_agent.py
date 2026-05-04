"""DeepAgent orchestrator over the context-graphs system, powered by Kimi (Moonshot).

Sub-agents:
  - ingestor   : read a raw/ source and write wiki pages (entities, concepts, source summary)
  - researcher : answer questions using graph_search + reading wiki pages
  - linter     : run lint and propose fixes (does not auto-apply)
  - operator   : invoke typed Actions through the governed action surface

CLI:
  python agents/deep_agent.py ingest raw/docs/foo.pdf
  python agents/deep_agent.py ask "What SLA is ACME on?"
  python agents/deep_agent.py lint
  python agents/deep_agent.py invoke create_customer --actor alice --scopes sales_ops \\
      --inputs '{"name":"Globex","region":"EU"}'
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))

from llm import get_llm
from logging_config import configure_logging, get_logger
from tools import (
    ALL_TOOLS,
    compile_graph,
    graph_search,
    invoke_action,
    is_source_ingested,
    list_actions,
    list_raw_files,
    list_sources,
    list_wiki_pages,
    read_parsed_document,
    lint_wiki,
    read_raw_file,
    read_wiki_page,
    upsert_concept,
    upsert_entity,
    upsert_source,
    get_ontology,
)

log = get_logger("deep_agent")

TOP_INSTRUCTIONS = """\
You orchestrate a layered domain-context system (Karpathy LLM Wiki + TrustGraph context graph + Palantir-style ontology).

Hard rules:
1. raw/ is immutable. Read documents with read_parsed_document when structure matters,
   or read_raw_file for plain text; never write under raw/.
2. wiki/ is canonical. Use upsert_entity / upsert_concept / upsert_source; never freehand markdown.
3. graph/ is derived. Call compile_graph after wiki changes.
4. Every claim cites a source (raw/ path or another wiki id) — sources[] is mandatory.
5. State changes go through invoke_action only; local adapters are audited and external integrations must be explicit.
6. Validate Object Type and Link Type names against get_ontology() before writing.

Delegate to sub-agents:
  - ingestor for raw->wiki compilation
  - researcher for answering questions from the wiki
  - linter for health checks
  - operator for typed Action invocation
Use the task tool to dispatch.
"""

INGESTOR_PROMPT = """\
You ingest a raw source into the wiki. Your goal is ZERO information loss
relative to the parsed source. Information that's in the source but not in
the wiki is a defect — not an acceptable trade-off.

Workflow:
0. ALWAYS start with is_source_ingested(path). If it returns
   {{"ingested": true, "raw_changed_since_ingest": false}}, STOP IMMEDIATELY:
   do not call read_parsed_document, do not parse, do not upsert anything,
   do not compile_graph. Report the existing source_page and exit.
   Only proceed when the source is not yet ingested, the raw file changed since
   ingest, or the user explicitly asked to re-ingest / force.
1. For PDFs, images, spreadsheets, or layout-heavy files, call read_parsed_document(path)
   to get markdown, chunks, tables, grounding, confidence, and parser warnings.
   read_parsed_document is cached under parsed/; do not pass force=True unless
   the user asked for a re-parse.
   Use read_raw_file(path) only for plain text-like files.
2. get_ontology() to learn valid Object Types and Link Types.

3. EXTRACTION COMPLETENESS — this is the most important step.

   a. PROSE ENTITIES: identify every Customer / Person / Product / Concept the
      source mentions. Prefer page/chunk/cell-level evidence in citations.

   b. NUMERIC LINE ITEMS: for any source containing financial / statistical
      tables (10-K, 10-Q, 8-K, earnings release, CFO commentary, market
      reports, KPI dashboards), you MUST upsert a Concept page for each
      distinct numeric line item present in the tables, including:
        - revenue (per period, per segment, per market)
        - gross profit / gross margin (GAAP and non-GAAP, per period)
        - operating expenses (GAAP and non-GAAP, per period)
        - operating income (GAAP and non-GAAP, per period)
        - net income (GAAP and non-GAAP, per period)
        - diluted EPS (GAAP and non-GAAP, per period)
        - cash from operations / free cash flow
        - balance-sheet items (total assets, cash & equivalents, etc.)
        - shareholder returns (repurchases, dividends)
        - segment / market revenue breakdowns
        - guidance / outlook line items (per future period)
      For each, the Concept page MUST include the actual dollar / percent /
      ratio value, the period it applies to (e.g. "Q4 FY26"), the GAAP/non-GAAP
      flag where relevant, and a citation to the parsed source line/cell.
      DO NOT collapse multiple line items into one summary page — one Concept
      per (metric, period, basis). The graph will dedup via id slugs.

   c. EVERY NAMED PARTY: every Customer / Person / Product named in the source
      MUST have its own wiki page. Do NOT reference an entity in another
      page's `links` without also upserting the page for the entity itself.

   d. EVERY ANNOUNCED RELATIONSHIP: when the source describes a partnership,
      collaboration, supplier relationship, or similar between named parties,
      materialize it as typed links between BOTH parties (not just prose in
      the body).

4. For each upsert_entity(...) or upsert_concept(...): set `sources=[raw_path]`,
   confidence calibrated to source class (sec-filing: 0.99; press release: 0.95;
   marketing: 0.7), and `links` to other ids you created.

5. upsert_source(raw_path=..., summary=..., touched_pages=[...]).

6. compile_graph() to rebuild graph/.

7. Return a brief report listing pages touched and (importantly) any line
   items you SAW IN THE SOURCE BUT DID NOT EXTRACT. Honesty about gaps beats
   silent omission.

Task: {description}
"""

RESEARCHER_PROMPT = """\
You answer a domain question using the wiki + derived graph.

Be efficient — every extra tool call adds seconds of latency.

Workflow:
1. ONE call to graph_search. Default arguments:
     top_k=5, expand_hops=0, snippet_chars=240
   Pick 4–6 strong terms (nouns, named entities, qualifiers). Do NOT issue
   multiple redundant searches with rephrased terms — the BM25 index is the same.
   Bump top_k to 10 or expand_hops to 1 ONLY for cross-cutting / multi-entity
   questions where one page clearly cannot contain the answer.
2. Only call graph_search a second time if the first returned 0 results, or if
   the answer plainly requires a different topic. Never make more than 2 search
   calls.
3. read_wiki_page(id) only when you need the FULL body of a specific page
   beyond the snippet returned by graph_search. Skip it for simple lookups
   the snippets already cover.
4. Synthesize a concise answer with INLINE CITATIONS to wiki ids and raw/ paths.
5. If a clear contradiction or gap exists, surface it.
6. Never invent facts. If the wiki doesn't say it, say so.

Question: {description}
"""

LINTER_PROMPT = """\
You audit the wiki for health issues.

Workflow:
1. lint_wiki() to get issues.
2. For each issue, propose a concrete fix (which tool call would you run, with what args).
3. DO NOT auto-apply fixes. Return a markdown report.

Task: {description}
"""

OPERATOR_PROMPT = """\
You invoke typed Action Types on behalf of a user.

Workflow:
1. list_actions() to see available verbs.
2. Match the user's request to an action id; verify the user's scopes cover it.
3. If requires_approval is true, surface that and STOP — do not pass approved=True without explicit confirmation.
4. invoke_action(action_id=..., actor=..., scopes=[...], inputs={...}, approved=False).
5. Return the result and the audit row reference.

Task: {description}
"""


def _build_agent(*, llm_provider: str | None = None, llm_model: str | None = None):
    from deepagents import create_deep_agent
    from langchain.agents.middleware import (
        ModelCallLimitMiddleware,
        ModelRetryMiddleware,
        ToolRetryMiddleware,
    )

    subagents = [
        {
            "name": "ingestor",
            "description": "Compile a raw/ source into wiki pages (entities, concepts, source).",
            "system_prompt": INGESTOR_PROMPT,
            "tools": [is_source_ingested, read_parsed_document, read_raw_file,
                      list_raw_files, get_ontology,
                      upsert_entity, upsert_concept, upsert_source,
                      compile_graph, list_wiki_pages],
        },
        {
            "name": "researcher",
            "description": "Answer questions from the wiki with citations.",
            "system_prompt": RESEARCHER_PROMPT,
            "tools": [graph_search, read_wiki_page, list_sources, list_wiki_pages, get_ontology],
        },
        {
            "name": "linter",
            "description": "Audit the wiki and propose fixes (read-only).",
            "system_prompt": LINTER_PROMPT,
            "tools": [lint_wiki, list_wiki_pages, read_wiki_page],
        },
        {
            "name": "operator",
            "description": "Invoke typed Action Types (the only write surface).",
            "system_prompt": OPERATOR_PROMPT,
            "tools": [list_actions, invoke_action, get_ontology],
        },
    ]

    log.info("deep_agent.build provider=%s model=%s", llm_provider, llm_model)
    return create_deep_agent(
        model=get_llm(provider=llm_provider, model=llm_model),
        tools=ALL_TOOLS,
        subagents=subagents,
        system_prompt=TOP_INSTRUCTIONS,
        middleware=[
            ModelCallLimitMiddleware(run_limit=40),
            ModelRetryMiddleware(max_retries=2),
            ToolRetryMiddleware(max_retries=2),
        ],
    )


def _append_query_log(question: str, answer: str) -> None:
    """Append a one-line query record to wiki/log.md (per CLAUDE.md spec)."""
    from _lib import WIKI

    log_path = WIKI / "log.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if not log_path.exists():
        log_path.write_text("# Log\n\n")
    snippet = " ".join(answer.split())[:160]
    line = f"query \"{question.strip()[:200]}\" -> {snippet}"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"- {dt.datetime.now(dt.timezone.utc).isoformat()} — {line}\n")


def _run(prompt: str, *, llm_provider: str | None = None, llm_model: str | None = None) -> str:
    configure_logging()
    log.info("deep_agent.run_start provider=%s model=%s prompt_chars=%s",
             llm_provider, llm_model, len(prompt))
    agent = _build_agent(llm_provider=llm_provider, llm_model=llm_model)
    result = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    msgs = result.get("messages", [])
    log.info("deep_agent.run_done messages=%s", len(msgs))
    return msgs[-1].content if msgs else json.dumps(result, default=str)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--llm-provider",
        choices=["openai", "gemini", "moonshot", "openrouter", "nvidia", "deepseek"],
        help="Override LLM_PROVIDER for this run.",
    )
    parser.add_argument("--llm-model", help="Override the provider's default model for this run.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ing = sub.add_parser("ingest")
    p_ing.add_argument("path")

    p_ask = sub.add_parser("ask")
    p_ask.add_argument("question", nargs="+")

    sub.add_parser("lint")

    p_inv = sub.add_parser("invoke")
    p_inv.add_argument("action_id")
    p_inv.add_argument("--actor", required=True)
    p_inv.add_argument("--scopes", default="any_authenticated")
    p_inv.add_argument("--inputs", default="{}")
    p_inv.add_argument("--approved", action="store_true")

    p_chat = sub.add_parser("chat")
    p_chat.add_argument("message", nargs="+")

    args = parser.parse_args()

    question_for_log: str | None = None
    if args.cmd == "ingest":
        prompt = f"Ingest the source at path '{args.path}' into the wiki. Use the ingestor sub-agent."
    elif args.cmd == "ask":
        question_for_log = " ".join(args.question)
        prompt = f"Answer this question using the researcher sub-agent: {question_for_log}"
    elif args.cmd == "lint":
        prompt = "Audit the wiki using the linter sub-agent and report issues with proposed fixes."
    elif args.cmd == "invoke":
        prompt = (
            f"Invoke action '{args.action_id}' as actor '{args.actor}' with scopes "
            f"{args.scopes!r}, inputs {args.inputs}, approved={args.approved}. "
            "Use the operator sub-agent."
        )
    else:
        question_for_log = " ".join(args.message)
        prompt = question_for_log

    answer = _run(prompt, llm_provider=args.llm_provider, llm_model=args.llm_model)
    print(answer)
    if question_for_log:
        _append_query_log(question_for_log, answer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
