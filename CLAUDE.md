# Context Graphs — Agent Instructions

This repo is a **layered domain-context system** for agentic LLMs. It consolidates three patterns:
Karpathy's LLM Wiki (canonical markdown), TrustGraph Context Graphs (derived property graph with provenance),
and Palantir Ontology (typed Object/Link/Action types with governed write-back).

## Layered model (read top-down)

```
L4  agents/                 — DeepAgents (Kimi via Moonshot) + governed action server
L3  ontology/               — Object/Link/Action types (the schema; hand-curated)
L2  graph/                  — derived property graph (Kuzu); REGENERATED, never hand-edited
L1  wiki/                   — canonical markdown, LLM-maintained, git-versioned
L0.5 parsed/                — derived parser cache; regenerate from raw/, never hand-edit
L0  raw/                    — immutable source material; LLM reads, never modifies
```

## Agents (DeepAgents stack)

`agents/deep_agent.py` is the orchestrator. Sub-agents:
- **ingestor**  — raw → wiki compilation (typed `upsert_*` tools, never freehand markdown)
- **researcher** — answers questions via `graph_search` + reading wiki pages, with citations
- **linter**    — read-only audit; proposes fixes, never auto-applies
- **operator**  — invokes typed Action Types through the governed surface

LLM: pluggable provider via `LLM_PROVIDER` env (`openai` | `gemini` | `moonshot` | `openrouter` | `nvidia` | `deepseek`).
All values come from `.env` (auto-loaded by `agents/_lib.py` via python-dotenv).
- OpenAI: `OPENAI_API_KEY`, `OPENAI_MODEL` (default `gpt-5.2`).
- Gemini: `GEMINI_API_KEY` or `GOOGLE_API_KEY`, `GEMINI_MODEL` (default `gemini-3-pro-preview`).
- Moonshot/Kimi K2.6: `MOONSHOT_API_KEY`, `KIMI_MODEL` (default `kimi-k2.6`).
- OpenRouter/Nemotron: `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` (default `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`).
- NVIDIA/Nemotron (direct): `NVIDIA_API_KEY`, `NVIDIA_BASE_URL` (default `https://integrate.api.nvidia.com/v1`), `NVIDIA_MODEL` (default `nvidia/nemotron-nano-3`).
- DeepSeek V4: `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL` (default `deepseek-v4`).
See `agents/llm.py` and `.env.example`.

## The compile loop

```
raw/  ──ingest_agent──▶  wiki/  ──compile_graph──▶  graph/  ──query_agent──▶  answers
                          ▲                                                      │
                          └──────────── synthesis filed back ────────────────────┘
```

## Hard rules (do not violate)

1. **Never modify `raw/`.** It is the immutable source. Read only.
2. **`wiki/` is canonical. `graph/` is derived.** If they disagree, wiki wins. Rebuild the graph; never hand-edit Kuzu.
3. **Every wiki page MUST have YAML frontmatter** with at least: `id`, `type`, `sources[]`, `confidence`, `updated`.
4. **Every claim MUST cite a source** — either a `raw/` file path or another wiki page. No floating facts.
5. **Writes to operational systems go through Action Types only.** Never write directly. The action server enforces scopes and emits audit rows.
6. **The ontology is the contract.** New entity/link/action kinds require updating `ontology/*.yaml` first, then back-filling.
7. **Lint before merge.** Run `python agents/lint_agent.py` before declaring work done. Address contradictions, orphans, stale claims.

## Page conventions

### `wiki/entities/<id>.md` — instances of an Object Type
```yaml
---
id: customer_acme
type: Customer            # must match an Object Type id in ontology/object_types.yaml
sources:
  - raw/docs/acme_msa_2025.pdf
  - https://acme.example.com/about
confidence: 0.95
updated: 2026-05-02
links:
  - {to: region_na, type: operates_in}
  - {to: tier_2,    type: has_sla}
---
# ACME Corp
Prose description of the entity. Use [[wiki-links]] to other pages liberally.
```

### `wiki/concepts/<id>.md` — ideas/frameworks/policies
Same frontmatter shape, `type: Concept` (or a domain-specific concept type defined in ontology).

### `wiki/sources/<id>.md` — one summary per ingested source
Frontmatter must include `raw_path` and `ingested_at`. Body = key takeaways + what wiki pages were touched.

### `wiki/synthesis/<id>.md` — cross-cutting analysis
Long-form answers/findings filed back from query sessions. Higher prose, still cites.

### `wiki/index.md`
Catalog organized by Object Type. Updated on every ingest. Do not let it grow stale.

### `wiki/log.md`
Append-only chronological record of ingests, queries, and lint passes. Never rewrite history.

## When the user asks you to ingest

0. **Check first, work second.** Call `is_source_ingested(path)` before doing
   anything else. If it returns `ingested=true` and `raw_changed_since_ingest=false`,
   STOP — report the existing `wiki/sources/<id>.md` page and exit. Do not
   re-parse, do not re-upsert, do not recompile. Only proceed if the source is
   new, the raw file is newer than the source page, or the user explicitly asked
   to re-ingest. (`parsed/` is also cached on a per-file basis, so even when you
   do proceed, `read_parsed_document` will reuse the cached parse unless you
   pass `force=True`.)
1. For PDFs, images, spreadsheets, and layout-heavy documents, read the source
   with `read_parsed_document` so extraction uses structured Markdown, chunks,
   tables, grounding, metadata, and confidence/warning signals. Use
   `read_raw_file` only for plain text-like files.
2. Discuss key takeaways with the user (briefly).
3. Write `wiki/sources/<source_id>.md` summary.
4. Update or create affected `wiki/entities/*.md` and `wiki/concepts/*.md` (typically 5–15 pages).
5. Update `wiki/index.md`.
6. Append to `wiki/log.md`.
7. Run `python agents/compile_graph.py` to rebuild affected subgraph.
8. Run `python agents/lint_agent.py --fast` and report any new issues.

## When the user asks a question

1. Read `wiki/index.md` first.
2. Use `query_agent` (GraphRAG over `graph/` + read relevant `wiki/*.md`).
3. Answer with **inline citations** to wiki pages and/or `raw/` paths.
4. If the answer is non-trivial and likely useful again, offer to file it as `wiki/synthesis/*.md`.

## When proposing a write to operational systems

Never write directly. List the matching Action Type from `ontology/action_types.yaml` and propose calling it
through the MCP action server. If no Action Type fits, **stop and propose adding one to the ontology** — do not improvise.
