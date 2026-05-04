# Context Graphs

A layered knowledge system for agentic LLMs. Three patterns fused into one stack:

- **Karpathy LLM Wiki** — canonical, LLM-maintained markdown.
- **TrustGraph Context Graph** — derived property graph with provenance.
- **Palantir Ontology** — typed Object/Link/Action types with a governed write surface.

The DeepAgent (Kimi K2.6 by default) drives the loop:
**ingest** raw sources → wiki, **compile** wiki → graph, **ask** with citations,
**lint** for drift, **invoke** typed actions through audited adapters.

```
raw/  ──ingestor──▶  wiki/  ──compile_graph──▶  graph/  ──researcher──▶  cited answers
                       ▲                                                      │
                       └────────────── synthesis filed back ──────────────────┘
```

## Architecture

Six layers, each with one owner and one mutability rule. **Wiki is canonical; everything else flows from it.**

| Layer | Path        | Owner                 | Rule |
|------:|-------------|-----------------------|------|
| L0    | `raw/`      | humans                | immutable; LLM reads only |
| L0.5  | `parsed/`   | parser cache          | derived from `raw/`; never hand-edit |
| L1    | `wiki/`     | LLM via `ingestor`    | edit only through typed `upsert_*` tools |
| L2    | `graph/`    | `compile_graph.py`    | regenerated; never hand-edit Kuzu |
| L3    | `ontology/` | humans                | the schema contract; edit first, back-fill wiki second |
| L4    | `agents/`   | code                  | the DeepAgent + tools + action server |

Every wiki page carries YAML frontmatter (`id`, `type`, `sources[]`, `confidence`, `updated`, optional `links[]`). Every claim cites a `raw/` path or another wiki id. The full agent contract is in [`CLAUDE.md`](./CLAUDE.md).

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # then add your API key(s)
```

`kuzu` is optional. Without it, the graph still compiles to `graph/snapshots/graph.jsonl` (typed nodes/edges, ontology classes/properties, provenance, retrieval traces) and queries fall back to BM25 over the wiki.

## Configure

### LLM provider (`.env`)

| `LLM_PROVIDER`       | Default model                                          | Required key                  |
|----------------------|--------------------------------------------------------|-------------------------------|
| `moonshot` (default) | `kimi-k2.6`                                            | `MOONSHOT_API_KEY`            |
| `openai`             | `gpt-5.2`                                              | `OPENAI_API_KEY`              |
| `gemini`             | `gemini-3-pro-preview`                                 | `GEMINI_API_KEY`              |
| `openrouter`         | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`   | `OPENROUTER_API_KEY`          |
| `nvidia`             | `nvidia/nemotron-nano-3`                               | `NVIDIA_API_KEY`              |
| `deepseek`           | `deepseek-v4`                                          | `DEEPSEEK_API_KEY`            |

Override per run: `--llm-provider gemini --llm-model gemini-3-pro-preview`.

### Document parser

Two paths, depending on whether the source is **prose** (a document) or **records** (rows).

**Document path** — chosen by file extension. Word, PowerPoint, and HTML route to dedicated parsers regardless of `DOCUMENT_PARSER_PROVIDER`; everything else uses the configured PDF/text provider:

| Format               | Parser                              | Output                                                       |
|----------------------|-------------------------------------|--------------------------------------------------------------|
| `.pdf`               | `liteparse` / `landingai` / `nemotron` (env) | markdown + page chunks + grounding                  |
| `.docx`              | `python-docx` (auto)                | markdown + heading-based chunks + tables                     |
| `.pptx`              | `python-pptx` (auto)                | markdown per slide + slide grounding + speaker notes         |
| `.html` / `.htm`     | `trafilatura` (auto)                | clean article markdown + URL/depth/parent provenance         |
| `.txt`, `.md`, `.csv`| `liteparse` passthrough             | as-is                                                        |

`DOCUMENT_PARSER_PROVIDER` controls the PDF/HTML provider:

| Provider              | Best for                                   | Setup                                                                       |
|-----------------------|--------------------------------------------|-----------------------------------------------------------------------------|
| `liteparse` (default) | Local PDFs, OCR, layout, bounding boxes    | `npm install -g @llamaindex/liteparse` + `pip install -r requirements.txt`  |
| `landingai`           | Tables, visual grounding, confidence spans | `LANDINGAI_API_KEY`                                                         |
| `nemotron`            | NVIDIA Nemotron Parse VLM                  | `pip install paper-qa-nemotron` + `NVIDIA_API_KEY`                          |

Parsed artifacts cache under `parsed/` (regenerable; gitignored).

**Web pull** — `agents/source_pull/web.py` fetches a seed URL and follows in-content links (nav/footer/aside chrome filtered out) up to `--depth` levels deep, saving each page as `raw/web/<host>/<slug>.html` with a companion `<slug>.meta.json` carrying URL, fetched_at, parent_url, depth, and content_hash. The companion is what `WebParser` reads at parse time, so URL provenance survives all the way into wiki citations.

```bash
python agents/source_pull/web.py crawl https://example.com/blog/X --depth 2 --max-pages 30
python agents/source_pull/web.py crawl https://example.com/about --depth 0      # single page
python agents/source_pull/web.py crawl https://example.com/X --allow-external   # cross-domain
```

Polite-by-default: same-domain only (override with `--allow-external`), 1s delay between requests (`--delay`), per-crawl page budget (`--max-pages 30`), per-host file layout under `raw/web/<host>/`. Re-runs are idempotent: pages with unchanged content_hash are skipped, so scheduling the same crawl daily is safe and cheap. After pulling, the LLM ingestor takes over (`python agents/deep_agent.py ingest raw/web/<host>/<slug>.html`).

**Record path** — Excel and CSV bypass the LLM entirely. Each record source ships a sibling YAML manifest declaring how columns map to ontology types; `agents/record_ingester.py` validates the mapping against the ontology, computes a content hash for idempotent re-ingest, and writes one typed wiki page per row plus secondary entities for linked persons/products.

```bash
python agents/record_ingester.py validate raw/records/customers_q1_2026.csv
python agents/record_ingester.py ingest   raw/records/customers_q1_2026.csv [--force]
```

Manifest convention: `<source>.csv` paired with `<source>.csv.manifest.yaml` (or `<source>.manifest.yaml`). See `raw/records/customers_q1_2026.manifest.yaml` for a worked example. Required keys: `source_class`, `mapping.target_type`, `mapping.identity.{column,slug}`. Re-ingest is a no-op when the canonical sorted-row hash is unchanged.

## Use

The DeepAgent (`agents/deep_agent.py`) is the LLM-driven entry point. Four scoped sub-agents — `ingestor`, `researcher`, `linter`, `operator`. The same operations are also exposed as deterministic CLIs that need no API key.

| Goal                  | LLM-driven (DeepAgent)                                                          | Deterministic (no API key)                                          |
|-----------------------|---------------------------------------------------------------------------------|---------------------------------------------------------------------|
| Pull web pages        | —                                                                               | `python agents/source_pull/web.py crawl <url> --depth 2`            |
| Ingest a document     | `python agents/deep_agent.py ingest raw/docs/X.{pdf,docx,pptx,html}`            | `python agents/ingest_agent.py ingest raw/docs/X.md`                |
| Ingest a record table | —                                                                               | `python agents/record_ingester.py ingest raw/records/X.{csv,xlsx}`  |
| Compile graph         | (auto-invoked by ingestor)                                                      | `python agents/compile_graph.py [--force]`                          |
| Ask a question        | `python agents/deep_agent.py ask "What is X?"`                                  | `python agents/query_agent.py "What is X?"`                         |
| Lint the wiki         | `python agents/deep_agent.py lint`                                              | `python agents/lint_agent.py`                                       |
| Invoke an action      | `python agents/deep_agent.py invoke <id> --actor X --scopes Y --inputs '{...}'` | `python agents/action_server.py invoke <id> ...`                    |
| Build the KB index    | —                                                                               | `python agents/build_kb_index.py`                                   |
| Visualize the graph   | —                                                                               | `python agents/visualize_graph.py`                                  |
| Generate intel memo   | —                                                                               | `python agents/intel_memo.py memo <entity_id> --actor X`            |
| Search precedents     | —                                                                               | `python agents/precedent.py search --class <class> --entity <id>`   |
| Replay a decision     | —                                                                               | `python agents/decision_replay.py replay <decision_id>`             |
| Backfill decisions    | —                                                                               | `python agents/decision_backfill.py` (one-shot, idempotent)         |

### Information loss is a defect

The ingestor prompt enforces "ZERO information loss relative to the parsed source." For any source containing financial / statistical tables, the LLM ingestor must upsert one Concept page per distinct numeric line item present in the tables — not one summary page that omits the figures. See `INGESTOR_PROMPT` in `agents/deep_agent.py` for the current contract (per-period, per-segment, per-basis enumeration; explicit gap reporting at the end of every ingest).

`agents/lint_agent.py` ships a **completeness checker** that scans every parsed source for numeric values (`$X.XB`, `$X,XXX million`, `X.X%`) and verifies each appears in at least one wiki page citing that source. Misses become `extraction_completeness_gap` lint issues with the offending line numbers and contexts. This converts silent extraction loss into visible, actionable lint warnings.

```bash
# Default lint includes the completeness scan (slower but more thorough)
python agents/lint_agent.py

# Skip the scan if you just want a fast structural check
python agents/lint_agent.py --fast
```

For numeric-table-heavy sources (10-K, 10-Q, 8-K, CFO commentary), set `DOCUMENT_PARSER_PROVIDER=landingai` so the parser preserves table cell IDs and confidence scores. The default LiteParse is fine for prose; LandingAI is the right choice when financial tables matter and you need cell-level grounding.

### Idempotency

- **Document ingest** — `is_source_ingested(path)` is called first; skips if the source page exists and the raw file is unchanged. Force with `--force`.
- **Record ingest** — content hash over canonical sorted rows; re-ingest is a no-op when bytes are equivalent (handles re-dumps where mtime changed but data didn't).
- **Web crawl** — content hash per fetched page; re-crawls fetch nothing when remote pages haven't changed, making daily/hourly schedules cheap.
- **Parse** — `parsed/<raw-relative>` is cached; reuses unless `force=True`.
- **Compile graph** — fingerprints all wiki pages + ontology files (`mtime_ns`+`size`); skips when unchanged. Force with `--force`.

## Ingestion guide — end to end

The goal of ingestion is to turn raw bytes into typed wiki pages with cited claims, then compile the graph. Three paths exist, one per source shape. Pick the path by source type; the rest of the loop is the same.

```
                ┌────────────────────────────────────┐
   PDF / DOCX / │ deep_agent ingest                  │  ─►  wiki/sources/<id>.md
   PPTX / TXT / │  (LLM extracts entities/concepts   │      wiki/entities/*
   MD           │   via typed upsert_* tools)        │      wiki/concepts/*
                └────────────────────────────────────┘
                ┌────────────────────────────────────┐
   URL          │ source_pull/web crawl              │  ─►  raw/web/<host>/<slug>.html
   (web page)   │  (depth-limited BFS, polite,       │       + <slug>.meta.json
                │   content-hash idempotent)         │
                │ deep_agent ingest <fetched HTML>   │  ─►  wiki/sources/* + entities/concepts
                └────────────────────────────────────┘
                ┌────────────────────────────────────┐
   CSV / XLSX   │ record_ingester ingest             │  ─►  one wiki/entities/<id>.md per row
                │  (manifest-driven, no LLM)         │       + linked Person/Product entities
                └────────────────────────────────────┘
                                  │
                                  ▼
                  python agents/compile_graph.py     ─►  graph/kuzu.db
                                                         graph/snapshots/graph.jsonl
```

### Path A — PDFs, Word, PowerPoint (LLM ingestor)

For unstructured prose where the LLM has to identify entities and concepts.

```bash
cp /path/to/quarterly_report.pdf raw/docs/
python agents/deep_agent.py ingest raw/docs/quarterly_report.pdf
```

What happens, in order:

1. **`is_source_ingested(path)` check.** If the source page already exists and the raw file is unchanged, the ingestor stops immediately and reports the existing page. No re-parsing, no re-upserting.
2. **Parse via the appropriate provider.** Extension auto-routing picks `LiteParse` (PDF), `python-docx` (.docx), `python-pptx` (.pptx), or `trafilatura` (.html). Result is cached under `parsed/<raw-relative>/document.{json,md}`.
3. **LLM ingestor sub-agent runs.** It reads the parsed markdown + chunks, calls `get_ontology()` to learn valid types, then writes typed pages via `upsert_entity` / `upsert_concept` / `upsert_source`. Every claim cites the raw path.
4. **`compile_graph()` is invoked automatically.** Cached if wiki + ontology haven't changed since last compile.

Override the LLM provider per run if needed:

```bash
python agents/deep_agent.py --llm-provider openai --llm-model gpt-5.2 \
    ingest raw/docs/quarterly_report.pdf
```

### Path B — Web pages (crawl, then ingest)

Two-step. First fetch and save HTML; then ingest the saved file like any other document.

```bash
# Single page
python agents/source_pull/web.py crawl \
    https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-first-quarter-fiscal-2026 \
    --depth 0 --max-pages 1

# Page + 1-hop in-content links (most common for press hubs / blog indexes)
python agents/source_pull/web.py crawl <seed_url> --depth 1 --max-pages 10 --delay 1.0

# Section walk: page + children + grandchildren (capped)
python agents/source_pull/web.py crawl <seed_url> --depth 2 --max-pages 30 --delay 1.0

# Cross-domain follow-on (use with tight --max-pages)
python agents/source_pull/web.py crawl <seed_url> --depth 1 --max-pages 8 --allow-external
```

**What the crawler does:**

- Same-domain only by default (override with `--allow-external`).
- Filters chrome (`<nav>`, `<footer>`, `<aside>`, classes containing `menu` / `cookie` / `share` / `related`) before following links.
- Saves HTML to `raw/web/<host>/<slug>.html` plus a sibling `<slug>.meta.json` with URL / fetched_at / parent_url / depth / content_hash.
- Skips `mailto:` / `javascript:` / fragments / non-HTML content types.
- Enforces `--max-pages` budget and `--delay` between requests (politeness).
- Re-runs are idempotent: pages whose content hash matches the sidecar are not re-written.

**Then ingest the fetched HTML:**

```bash
# One page
python agents/deep_agent.py ingest raw/web/nvidianews.nvidia.com/<slug>.html

# Whole batch (zsh / bash)
for f in raw/web/nvidianews.nvidia.com/*.html; do
  python agents/deep_agent.py ingest "$f"
done
```

The `WebParser` reads the `.meta.json` sidecar so URL / fetched_at / parent_url / depth survive into wiki citations as first-class metadata.

### Path C — CSV and XLSX (record ingester, no LLM)

For row-oriented data where each row is (or augments) a typed entity. The LLM doesn't guess column semantics — you declare them in a manifest.

```bash
# 1. Drop the file plus a sibling manifest into raw/records/
ls raw/records/
#   customers_q1_2026.csv
#   customers_q1_2026.manifest.yaml      # or customers_q1_2026.csv.manifest.yaml

# 2. Validate the manifest against the ontology BEFORE touching any rows
python agents/record_ingester.py validate raw/records/customers_q1_2026.csv

# 3. Ingest
python agents/record_ingester.py ingest raw/records/customers_q1_2026.csv

# 4. Re-run safely — no-op when content hash unchanged. Force a rebuild:
python agents/record_ingester.py ingest raw/records/customers_q1_2026.csv --force
```

Minimal manifest shape (full example: `raw/records/customers_q1_2026.manifest.yaml`):

```yaml
source_class: csv                     # or xlsx
default_confidence: 0.95

mapping:
  target_type: Customer               # must exist in ontology/object_types.yaml
  identity:
    column: customer_id
    slug: "customer_{customer_id|slug}"
  required:
    name:    { column: legal_name }
    region:  { column: hq_region, validate_against: [NA, EU, APAC, LATAM] }
  optional:
    tier:    { column: account_tier, default: t3 }
  links:                              # optional: auto-create linked entities
    - target_type: Person
      identity:
        column: primary_contact_email
        slug: "person_{primary_contact_email|email_local}"
      link_type: works_at             # must exist in ontology/link_types.yaml
      direction: from_other           # link lives on the Person side
      required:
        name:  { column: primary_contact_name }
        email: { column: primary_contact_email }

refresh:
  policy: manual_drop                 # or scheduled_pull
```

Slug template tokens supported: `{column}`, `{column|slug}`, `{column|email_local}`, `{column|lower}`, `{column|raw}`. Citations are written as `raw/records/<file>.csv#row=<n>` so every claim ties back to a specific row. Re-ingest is dedup-safe at the row level via `content_hash` over the sorted canonical row set.

**When NOT to use the record path.** Some files arrive as `.xls`/`.xlsx` but are not row-oriented data — e.g., SEC filings rendered as Excel workbooks where each sheet is a pre-formatted paragraph table, EDGAR exports, or financial statements with merged cells and multi-row headers. These belong on the **document path**: convert to PDF first (or use the original PDF if available) and run `deep_agent ingest` so the LLM extracts entities and concepts from the prose. The record path expects "one row = one entity"; if your file doesn't fit that shape, don't force it.

### After every ingest path

The same three commands close the loop, regardless of how the data got in:

```bash
# Compile graph (idempotent — skips when wiki + ontology fingerprint unchanged)
python agents/compile_graph.py

# Health check the wiki
python agents/lint_agent.py

# Ask a question with cited answer
python agents/deep_agent.py ask "What did the source say about X?"

# Generate an Intel Memo on a target entity (deterministic core, no LLM)
python agents/intel_memo.py memo <entity_id> --actor analyst --hops 2 --dry-run
```

### Worked example — building NVIDIA's context from public sources

The repo's bundled NVIDIA build was assembled with the runbook below. It produced **306 typed wiki pages, 1100 typed graph edges, 0 ontology errors, 0 lint issues** from 13 sources (3 PDFs + 10 HTML press releases) in roughly 90 minutes wall clock. Two cleanup steps are intentionally part of the runbook — they reflect *what actually happens* on a multi-source ingest, not idealized happy-path mechanics.

#### 1. Drop the source files

```bash
# Quarterly PDFs (already in raw/docs/ in the bundled build)
cp ~/Downloads/NVDA-F4Q26-Quarterly-Presentation.pdf raw/docs/
cp ~/Downloads/Q4FY26-CFO-Commentary.pdf            raw/docs/
cp ~/Downloads/Rev_by_Mkt_Qtrly_Trend_Q426.pdf      raw/docs/
```

> **Tip — files that look like records but aren't.** SEC filings rendered as `.xls`/`.xlsx` workbooks (where each sheet is a paragraph table, not row-oriented data) belong on the **document path**, not the record path. Move them to `raw/docs/` (convert to PDF if needed) instead of `raw/records/`. We set such files aside under `raw/records/skipped/` in this build.

#### 2. Crawl one entry-point URL with depth-1 link following

```bash
python agents/source_pull/web.py crawl \
    https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-first-quarter-fiscal-2026 \
    --depth 1 --max-pages 10 --delay 1.0
```

Result: 10 HTML pages saved to `raw/web/nvidianews.nvidia.com/<slug>.html` plus `<slug>.meta.json` sidecars carrying URL + fetched_at + parent_url + depth + content_hash. Same-domain only by default; in-content links only (nav/footer/aside chrome filtered).

#### 3. Ingest each source through the LLM ingestor

```bash
for f in raw/docs/*.pdf raw/web/nvidianews.nvidia.com/*.html; do
  python agents/deep_agent.py ingest "$f"
done
```

> **Expect early-skips that are actually correct.** The LLM ingestor reading source N often also writes source pages for adjacent sources it sees referenced inside N. When the for-loop reaches source N+1, `is_source_ingested()` correctly reports it's already done and the ingestor exits in <1s. This is `is_source_ingested` working as designed — don't `--force` past it. After the full batch, every source has a typed page and most entities/concepts have been extracted.

> **Run this in the background for long batches** — see `agents/source_pull/web.py` and `agents/deep_agent.py ingest` invocations in the chat-history examples for how to launch under `nohup` / `&` and track progress.

#### 4. Normalize duplicate ids (this step is REQUIRED, not optional)

The LLM coins slugs ad-hoc per ingest. The same concept frequently appears with multiple ids: `nvidia_corp` / `nvidia-corp` / `NvidiaCorp`. After our 13-source NVIDIA ingest there were **12 duplicate-id groups**. Two consequences:

- The typed graph has two nodes for the same thing → entity overlap in precedent search misses results.
- `kb/index.sqlite` build fails with `UNIQUE constraint failed: pages.id`.

Fix is one command:

```bash
python agents/normalize_ids.py audit                # report duplicates only
python agents/normalize_ids.py merge --dry-run      # print the merge plan
python agents/normalize_ids.py merge                # actually merge
```

Winner selection per group: entity > concept; larger body wins ties; higher confidence; lex-smallest id as final tiebreak. Sources and links are unioned from the loser pages onto the winner; every `links: [{to: <loser>}]` in OTHER pages is rewritten to point at the winner; loser pages are deleted. Idempotent — safe to re-run.

#### 5. Recompile the graph and ABSORB ontology widening

```bash
python agents/compile_graph.py --force
```

The first compile after a multi-source LLM ingest typically reports ontology violations — the LLM produces edge shapes the original ontology was authored without contemplating (e.g., `Product part_of Concept`, `operates_in from Product`, `mentions from Person`). Read the error output, then widen the relevant `from`/`to` lists in `ontology/link_types.yaml` to admit the legitimate shapes. Examples we adopted in this build:

```yaml
- id: operates_in
  from: [Customer, Product, Person]                 # was: Customer
  to:   [Customer, Concept, Product, Person]        # was: [Customer, Concept]

- id: owns
  from: [Person, Customer, Product]                 # was: Person

- id: derived_from
  from: [Customer, Concept, Person, Product]
  to:   [Customer, Concept, Source, Product, Person]   # widened on .to

- id: mentions
  from: [Source, Customer, Product, Concept, Person]   # widened to include Person

- id: part_of
  from: [Product, Person, Concept, Customer]
  to:   [Customer, Product, Concept]                # widened to include Concept

- id: targets
  from: [Memo, Product]                             # was: Memo
```

Re-run `python agents/compile_graph.py --force` until errors hit 0. **Ontology-first edits are part of the discipline** — when the schema is too narrow for legitimate usage, widen it. When the LLM produces something semantically wrong (e.g., a backwards `owns` edge), fix the wiki instead.

#### 6. Build the kb FTS index

```bash
python agents/build_kb_index.py
```

This succeeds cleanly only after the duplicate-id normalizer has run. Output: 13 sources, 295 pages, 34 chunks, 652 typed links, 307 page→source provenance rows.

#### 7. Lint and validate

```bash
python agents/lint_agent.py            # exits non-zero on issues
```

If lint reports issues, fix them at the source (re-ingest with corrections, or hand-edit the wiki page). Don't paper over them at compile-time.

#### 8. Validate end-to-end with an Intel Memo

```bash
# Dry-run prints the structured findings + draft body, invokes no actions
python agents/intel_memo.py memo nvidia-corp --actor analyst --hops 2 --dry-run

# Real publish: writes wiki/memos/, graph/memos/, audit row, Decision page,
#   review-queue rows for each flagged concept
python agents/intel_memo.py memo nvidia-corp --actor analyst --hops 2
```

A successful publish emits **one Memo wiki page + one publish_intel_memo Decision page + N flag_concept_review Decision pages** (one per concept the contradiction detector flagged for human review). The 2-hop NVIDIA memo on this build surfaced 4 numeric contradictions and 9 flagged concepts.

#### Final state — what 13 sources produced

| Layer | Result |
|---|---|
| `wiki/` | 306 typed pages: 94 Product + 87 Customer + 79 Concept + 22 Person + 13 Source + 10 Decision + 1 Memo. Frontmatter validity: 306/306. |
| `graph/` | 306 nodes, 1100 typed edges, 364 provenance records, 16 ontology properties, 7 ontology classes, **0 errors**. |
| `kb/index.sqlite` | 13 sources, 295 pages, 34 chunks, 652 typed links indexed for FTS. |
| `ontology/` | Widened to 16 link types over the run. 0 violations after widening. |
| `graph/audit.jsonl` | 10 audited Action invocations (1 publish + 9 flag_concept_review). |
| `graph/review_queue.jsonl` | 9 concepts queued for human review (idempotent on `(concept_id, reason)`). |
| `graph/memos/*.json` | 1 machine-replayable reasoning trace. |
| Lint | 0 issues. |
| Wall clock | ~90 minutes total (13 LLM ingests serially; can be parallelized). |

#### Querying the result

```bash
# Cited natural-language answer
python agents/deep_agent.py ask "What did NVIDIA report for Q4 FY26 revenue and gross margin?"

# Filtered FTS query against kb/
python agents/query_agent.py --type Source \
    "What were the partnerships announced alongside Q1 FY26?"

# Typed Cypher over the graph
python -c "
import kuzu
c = kuzu.Connection(kuzu.Database('graph/kuzu.db'))
res = c.execute(\"MATCH (p:Entity {type:'Product'})-[:Link {type:'part_of'}]->(c:Entity {id:'nvidia-corp'}) RETURN p.id\")
while res.has_next(): print(res.get_next())
"

# Searchable precedent across decisions
python agents/precedent.py search --class review_flag --entity nvidia-corp

# Replay a decision (state-of-world reconstruction)
python agents/decision_replay.py list
python agents/decision_replay.py replay <decision_id>

# Visualize
python agents/visualize_graph.py    # writes graph/graph.html + graph/graph.graphml
```

#### Lessons from this build (read before doing your own)

1. **Plan for ~25–30 entities and ~5–10 concepts per substantive press release.** That sets the order of magnitude for wiki growth from web ingest.
2. **The LLM ingestor will produce duplicate ids on multi-source runs.** Run `normalize_ids.py merge` before `build_kb_index.py` — the merge isn't optional.
3. **Expect to widen the ontology.** A first multi-source ingest typically surfaces 5–10 legitimate edge shapes the schema didn't anticipate. This is normal and signals the ontology is being shaped by real data, not designed in a vacuum.
4. **`is_source_ingested` early-exits are correct, not bugs.** Don't `--force` past them on the same batch.
5. **Files that arrive as `.xls` aren't always tabular data.** SEC filings rendered as Excel workbooks belong on the document path. Move them to `raw/docs/` or convert to PDF.
6. **The compile cache is your "is this stable?" oracle.** `python agents/compile_graph.py` returning `skipped: True` proves the wiki + ontology haven't drifted since the last successful build.

## Outputs

| Path                              | What it is                                                     |
|-----------------------------------|----------------------------------------------------------------|
| `wiki/sources/<id>.md`            | One per ingested raw artifact; summary + touched pages         |
| `wiki/entities/<id>.md`           | Typed Object instances (Customer, Person, Product, …)          |
| `wiki/concepts/<id>.md`           | Domain ideas, policies, metrics, partnerships                  |
| `wiki/synthesis/<id>.md`          | Reusable cross-cutting answers, filed back from queries        |
| `wiki/memos/<id>.md`              | Entity Intelligence Memos (see below)                          |
| `wiki/index.md`                   | Auto-regenerated catalog by ontology type                      |
| `wiki/log.md`                     | Append-only record of ingests, queries, lint passes            |
| `graph/kuzu.db`                   | Kuzu property graph (when installed)                           |
| `graph/snapshots/graph.jsonl`     | JSONL snapshot: ontology + nodes + edges + provenance + traces |
| `graph/retrieval_traces.jsonl`    | One row per query (seeds, expanded, grounding)                 |
| `graph/audit.jsonl`               | One row per Action Type invocation                             |
| `graph/review_queue.jsonl`        | Idempotent flagged-concept queue                               |
| `graph/memos/<id>.json`           | Machine-replayable reasoning trace per memo                    |
| `kb/index.sqlite`                 | FTS + metadata index for filtered search                       |

## Application: Entity Intelligence Memo Engine

A complete app that exercises every layer end-to-end and demonstrates capabilities standard or agentic RAG **cannot** match. The deterministic core runs without an LLM.

```
target → traverse(typed BFS) → coverage gaps → provenance chain → freshness check
       → contradiction detection → metric rollup → typed Memo + reasoning trace
       → publish_intel_memo (audited) + flag_concept_review (idempotent)
```

| Capability                          | Why RAG can't do it                                       |
|-------------------------------------|-----------------------------------------------------------|
| Multi-hop typed traversal           | Vector index has no edge schema                           |
| Coverage gap analysis               | RAG has no notion of which Object Types should be present |
| Provenance audit chain              | RAG returns chunks, not lineage to ingest timestamps      |
| Cross-page contradiction detection  | RAG returns contradictory snippets, can't cluster them    |
| Freshness signals                   | RAG has no temporal model                                 |
| Derived-metric rollup               | Aggregation across documents needs typed nodes            |
| Governed typed write-back           | Every write is scope-checked, schema-validated, audited   |
| Reasoning-trace artifact            | Full machine-replayable derivation per memo               |
| Typed Cypher downstream queries     | Ontology gives a real query language; vectors give cosine |

### Run it

```bash
python agents/intel_memo.py memo nvidia-corp --actor analyst --hops 2 --dry-run   # preview
python agents/intel_memo.py memo nvidia-corp --actor analyst --hops 2             # publish
python agents/compile_graph.py                                                    # pick up the new typed edges
python agents/intel_memo.py query --link flags_concept                            # typed Cypher query
python agents/intel_memo.py query --link cites_evidence --memo-id memo_intel_memo__nvidia_corp
```

| Flag        | Default              | Effect                                                |
|-------------|----------------------|-------------------------------------------------------|
| `--actor`   | required             | Identity recorded in every audit row                  |
| `--hops`    | `2`                  | Bidirectional BFS depth from the target entity        |
| `--scopes`  | `any_authenticated`  | Comma-separated scopes for action invocation          |
| `--dry-run` | off                  | Print trace + draft body; invoke no actions           |

## Decisions as first-class graph nodes

Every Action invocation through the action server now writes a typed **`Decision`** wiki page (in addition to the `audit.jsonl` row). This closes the gap surfaced by the [Foundation Capital "Context Graphs" thesis](https://foundationcapital.com/ideas/context-graphs-ais-trillion-dollar-opportunity): organizational decisions become *searchable precedent*, not tribal knowledge.

| Concept | Where it lives | What you get |
|---------|----------------|--------------|
| `Decision` Object Type | `ontology/object_types.yaml` | Frontmatter records `ts`, `actor`, `scopes`, `approved`, `decision_class`, plus `wiki_fingerprint` + `ontology_fingerprint` for replay |
| `triggered_by` / `justified_by` / `approved_by` / `affects` / `precedes` link types | `ontology/link_types.yaml` | Typed edges from a Decision into the rest of the graph |
| Auto-write on every invocation | `ontology/functions/actions.py:_audit` | Every action writes both an audit row AND a typed Decision page |
| **Searchable precedent** | `agents/precedent.py` | "Show prior decisions of class X that affected entity Y" — ranked by entity-overlap × class match × outcome |
| **State-of-world replay** | `agents/decision_replay.py` | Reconstruct what was knowable at decision time; flag ontology drift since |
| **Backfill historical decisions** | `agents/decision_backfill.py` | Walk `audit.jsonl` and create one Decision page per row (idempotent) |

```bash
# Search prior decisions
python agents/precedent.py search --class operational_write_approved --limit 5
python agents/precedent.py search --entity nvidia-corp --limit 5
python agents/precedent.py for-decision <decision_id>           # auto-derives signature

# Replay state-of-world at decision time + check for ontology drift
python agents/decision_replay.py list                           # all decisions, newest first
python agents/decision_replay.py replay <decision_id>           # full replay report

# Migrate historical audit rows into typed Decision pages (one-shot)
python agents/decision_backfill.py
```

The Decision subgraph is queryable via typed Cypher just like everything else — for example, "every decision justified by the NVIDIA Q4 memo":

```bash
python <<'PY'
import kuzu
conn = kuzu.Connection(kuzu.Database("graph/kuzu.db"))
res = conn.execute(
    "MATCH (d:Entity {type:'Decision'})-[:Link {type:'justified_by'}]->(m:Entity {type:'Memo'}) "
    "RETURN d.id, m.id"
)
while res.has_next(): print(res.get_next())
PY
```

## Editing the ontology

The ontology is the contract. Add types **first**, then back-fill wiki pages.

| File                              | Edit when you need…                                    |
|-----------------------------------|--------------------------------------------------------|
| `ontology/object_types.yaml`      | a new Object Type (e.g. `Customer`, `Memo`)            |
| `ontology/link_types.yaml`        | a new edge predicate (e.g. `part_of`, `cites_evidence`) |
| `ontology/action_types.yaml`      | a new governed write verb + its `function:` registration |
| `ontology/functions/actions.py`   | the Python implementation of an Action Type            |

After editing, run `python agents/compile_graph.py --force` to revalidate wiki pages against the new schema. `pytest tests/` runs ontology conformance + retrieval evals.

## Hard rules

1. **Never modify `raw/`.**
2. **Wiki is canonical; graph is derived.** If they disagree, wiki wins — rebuild the graph.
3. **Every wiki page needs frontmatter** with `id`, `type`, `sources[]`, `confidence`, `updated`.
4. **Every claim cites a source.** No floating facts.
5. **Writes go through Action Types only.** The action server validates, scopes, and audits every call.
6. **Lint before merge.** `python agents/lint_agent.py` exits non-zero on issues.

See [`CLAUDE.md`](./CLAUDE.md) for the full agent contract and page conventions.

## When to add a vector DB

Not yet. SQLite FTS5 + ontology metadata filters cover document/source/type/date/tag-filtered retrieval today. Add a vector store only when you see semantic recall failures keyword search can't fix — and keep the same shape:

```
SQLite filters → vector/BM25 seed → graph expansion → wiki pages → cited answer
```

The vector layer is for recall, not for source of truth. Source of truth stays `raw/` → `parsed/` → `wiki/` → `ontology/` → derived `graph/`.
