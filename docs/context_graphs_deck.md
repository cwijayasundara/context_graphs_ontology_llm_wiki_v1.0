# Context Graphs — Pitch Deck

> **Format:** 10 slides, Google Slides–friendly markdown.
> Each slide is delimited by `---`. Bullets are tight (≤7 per slide). The
> **Speaker notes** block at the bottom of each slide should be pasted into the
> Slides "Notes" pane. To render: paste into Marp / Slidev / Pandoc, or
> manually copy each `##` block into a new slide in Google Slides.

---

## Slide 1 — Title

# Context Graphs
### Typed Knowledge for Enterprise AI Agents
*Karpathy LLM Wiki + TrustGraph Context Graph + Palantir Ontology, fused into one stack*

**Audience:** CTO / CIO / Head of AI Platform
**Date:** May 2026

**Speaker notes:**
> One-line framing: most enterprises today have either (a) a pile of vector-indexed PDFs they call "RAG" or (b) a hand-curated knowledge graph nobody trusts. We propose a third architecture that combines the best of three industry patterns and produces something neither RAG nor a graph alone can deliver: an auditable, typed, governable substrate for agentic LLMs.

---

## Slide 2 — Executive Summary

**The shift:** Enterprise AI moved from "answer-the-question" to "do-the-work." Agents now propose actions on real systems. RAG alone can't survive that bar.

**The proposal:** A **layered context architecture** that treats the wiki as canonical, the graph as derived, the ontology as the schema contract, and the action server as the only mutation surface.

**Three numbers that matter:**
- **86% vs 32%** — GraphRAG vs vector RAG on multi-hop questions (Diffbot KG-LM benchmark)
- **63%** — LinkedIn ticket-resolution time reduction with knowledge-graph-augmented retrieval (40h → 15h)
- **85%** — share of enterprises projected to run hybrid (vector + graph) retrieval by end of 2026 (Gartner / industry surveys)

**Business outcome:** Faster time-to-answer, regulator-grade provenance, governed agentic write-back. The *same* substrate powers Q&A, compliance reports, decision memos, and operational automation.

**Speaker notes:**
> The deck has one job: convince the exec that "RAG over our SharePoint" is not the right mental model for the next 3 years, and that this fused architecture is. The numbers are real and load-bearing. Mention: the gap is widest exactly where enterprise queries live — schema-bound, multi-entity, time-bounded.

---

## Slide 3 — Why Vector RAG Alone Hits a Wall

| Capability the business asks for             | Vector RAG | Why it fails |
|-----------------------------------------------|:----------:|--------------|
| "Find every contract that touches GDPR"       | ❌         | No type system; cosine similarity is not a filter |
| "Compare Q4 numbers across our 3 reports"     | ❌         | No cross-document aggregation; no entity coreference |
| "Which decisions still depend on this retracted source?" | ❌ | No provenance graph; chunks have no lineage |
| "Why did the agent take this action?"         | ❌         | No reasoning trace; embedding scores are not citations |
| "Is this fact still true as of last quarter?" | ❌         | No temporal model |

**Concrete benchmark:** On schema-bound enterprise questions (KPIs, aggregations, strategic-planning entities), **vector RAG drops to 0% accuracy** while GraphRAG sustains 90%+ (Diffbot 2025; FalkorDB SDK 2025).

**Where vector RAG still wins:** ~80% of *simple semantic lookups* — keep it as the recall layer.

**Speaker notes:**
> Don't disparage RAG — most enterprises started there for good reason. The point is that the *next* class of asks (structured, multi-hop, audited, time-bounded) needs a different substrate. The 80/15/5 split (simple lookup / structured reasoning / agentic) is roughly the consensus production pattern in 2026.

---

## Slide 4 — The Three-Pattern Fusion

```
 ┌────────────────────────┐    ┌────────────────────────┐    ┌────────────────────────┐
 │  Karpathy LLM Wiki     │    │  TrustGraph Context    │    │  Palantir Ontology     │
 │  (canonical knowledge) │    │  Graph (derived view)  │    │  (schema + actions)    │
 ├────────────────────────┤    ├────────────────────────┤    ├────────────────────────┤
 │ Markdown + frontmatter │    │ Typed nodes + edges    │    │ Object / Link / Action │
 │ LLM-maintained         │    │ 4-level provenance     │    │ Scoped, audited writes │
 │ Quality gate at write  │    │ Reasoning traces       │    │ Digital twin of org    │
 │ Compounds over time    │    │ Hallucination ↓        │    │ Semantic + kinetic     │
 └─────────┬──────────────┘    └──────────┬─────────────┘    └──────────┬─────────────┘
           │                              │                              │
           └──────────────┬───────────────┴──────────────┬───────────────┘
                          ▼                              ▼
              ┌────────────────────────────────────────────────────┐
              │   Context Graphs — one stack, three contracts      │
              │   Wiki canonical · Graph derived · Ontology gates  │
              └────────────────────────────────────────────────────┘
```

**Why fuse and not pick one?**
- **Wiki alone** = no typed query, no governed write
- **Graph alone** = brittle to maintain, no human-readable source of truth
- **Ontology alone** = schema without data is paper

**Speaker notes:**
> Each pattern is real and shipping. Karpathy's LLM Wiki gist (Apr 2026, ~50k+ stars) — quality gate before storage > retrieval improvements. TrustGraph — "Context Operating System for AI"; PROV-O reasoning traces. Palantir Foundry/AIP — Ontology System; "digital twin of the organization." Our contribution: fuse them so the wiki is canonical, the graph is regenerable, and the ontology is the contract.

---

## Slide 5 — Architecture: Six Layers, One Mutability Rule

| Layer | Path        | Owner                  | Mutability                                    |
|------:|-------------|------------------------|------------------------------------------------|
| L0    | `raw/`      | humans / source pulls  | immutable; LLM reads only                      |
| L0.5  | `parsed/`   | parser cache           | derived from L0; never hand-edited             |
| L1    | `wiki/`     | LLM via typed tools    | the canonical knowledge layer                  |
| L2    | `graph/`    | `compile_graph.py`     | regenerated from L1; never hand-edited         |
| L3    | `ontology/` | humans                 | the schema contract; edit *first*, back-fill L1 |
| L4    | `agents/`   | code                   | DeepAgent + tools + governed action server     |

**One rule that makes the rest safe:** **L1 is canonical. Everything below regenerates from it.** Lose the graph? Recompile. Bad parse? Re-parse. Bad LLM extraction? Re-ingest with provenance preserved.

**Frontmatter every wiki page carries:** `id`, `type`, `sources[]`, `confidence`, `updated`, `links[]`. Every claim cites a `raw/` path or another wiki id. **No floating facts.**

**Speaker notes:**
> The mutability rule is the architectural insight. RAG systems collapse into chaos because there's no canonical layer — the index *is* the source of truth, and rebuilding it is expensive. Here the wiki is plain markdown in git. Auditable, diffable, mergeable, and small enough to read end-to-end. Everything else is regenerable infrastructure.

---

## Slide 6 — What This Stack Gives You That RAG Cannot

| Capability                              | How it works                                                       |
|-----------------------------------------|--------------------------------------------------------------------|
| **Multi-hop typed traversal**           | Bidirectional BFS over typed edges in Kuzu/snapshot                |
| **Coverage-gap analysis**               | Count touched pages by Object Type; surface missing types          |
| **Provenance audit chain**              | Claim → wiki page → raw source → ingest timestamp + parser confidence |
| **Cross-page contradiction detection**  | Cluster numeric claims by `(metric, period, segment)`; flag mismatches |
| **Freshness signals**                   | `page.updated` vs `source.ingested_at`; bitemporal-ready          |
| **Derived-metric rollup**               | Aggregate facts across the touched subgraph                        |
| **Governed typed write-back**           | Action Types validate scope + schema + approval; emit audit row   |
| **Reasoning-trace artifact**            | Full machine-replayable derivation per memo (`graph/memos/*.json`) |
| **Typed downstream queries**            | Cypher over Kuzu — real query language, not cosine                 |

**Reference application in this repo:** *Entity Intelligence Memo Engine* — runs all nine capabilities end-to-end with no LLM in the deterministic core; LLM is optional polish.

**Speaker notes:**
> This is the slide where finance/compliance/ops people lean in. Each row is a real business capability they've been buying point solutions for. We deliver them on one substrate. The Memo Engine is not a toy — it's the demonstration that the architecture composes.

---

## Slide 7 — Industry Validation

| Org / pattern             | What they ship                                                       | Public signal                                                                     |
|---------------------------|----------------------------------------------------------------------|-----------------------------------------------------------------------------------|
| **Palantir** (Foundry + AIP) | Ontology = "digital twin of the organization"; semantic + kinetic   | AIP Document Intelligence GA Feb 2026; Ontology positioned as the OS layer        |
| **Microsoft** (GraphRAG)     | Hierarchical community summaries over LLM-extracted KG              | 3.4× QA accuracy gain; productized in Microsoft Discovery (Azure)                 |
| **TrustGraph** (open source) | "Context Operating System"; 4-level provenance; PROV-O reasoning traces | Open-source Context Graphs; portable context cores                                |
| **Karpathy** (LLM Wiki)      | Canonical markdown maintained by the LLM; "compounds over time"     | Apr 2026 gist; Obsidian, Claude Code, DAIR.AI all built variants in <60 days     |
| **LinkedIn**                 | GraphRAG over support-ticket + customer KG                          | **40h → 15h ticket resolution time** (-63%)                                       |
| **Uber / Airbnb / Netflix**  | Knowledge-graph-backed feature stores + discovery                   | Hybrid (vector + graph) is the dominant ML-platform pattern                       |

**Industry direction (2026):** Hybrid retrieval = default. Pure-vector RAG is a 2024 pattern.

**Speaker notes:**
> The thesis isn't "we invented this." The thesis is: the three patterns we fuse are independently validated by Microsoft, Palantir, the Karpathy/Obsidian community, TrustGraph, and the FAANG ML platforms. Our specific contribution is: the *layered, regenerable, ontology-gated* architecture that makes them composable in one repo with one team owning it.

---

## Slide 8 — Three Enterprise Use Cases On The Same Stack

### Use case A — **Compliance & Audit** (regulated industries)

> *"For every claim in our quarterly disclosure, show the source, ingest timestamp, parser confidence, and ontology version."*

- Provenance chain produces a regulator-grade derivation per claim
- Linter flags stale derivations and contradicting concepts before filing
- Audit log proves who invoked which write, when, with which approval

### Use case B — **Decision-Support Memos** (finance, M&A, BD)

> *"Build a 2-hop intelligence memo on Acme Corp: cited evidence, contradictions, freshness, derived metrics."*

- Deterministic Memo Engine runs in seconds with no LLM
- Output is a typed `Memo` wiki page + machine-replayable JSON trace
- Runs nightly; alerts on net-new contradictions

### Use case C — **Governed Agentic Operations** (sales, support, ops)

> *"Let agents propose actions — but only ones the ontology allows, with audit trails."*

- Action Types are the only write surface (`create_customer`, `escalate_ticket`, `flag_concept_review`)
- Scope + approval gates enforced server-side
- Action server emits one audit row per call; agent cannot bypass it

**Speaker notes:**
> Pick the use case that matches the audience. For a CIO of a bank: A. For a CFO/strategy lead: B. For a CRO/COO: C. They all run on the same wiki + graph + ontology. That's the multiplier — one platform investment, multiple business outcomes.

---

## Slide 9 — 90-Day Adoption Roadmap

```
Day 0 ─────── Day 30 ──────── Day 60 ──────── Day 90 ──────────────▶
  │             │                │                │
  │             │                │                └─ Use case in
  │             │                │                   production
  │             │                │
  │             │                └─ First Memo Engine run on
  │             │                   target entity (no LLM in core)
  │             │
  │             └─ First 5 sources ingested (PDF, Word, web, CSV)
  │                Ontology v0 with 5 Object / 5 Link / 3 Action types
  │
  └─ Stand up the layered repo (wiki/, graph/, ontology/, agents/)
     Pick provider stack (Kuzu + Kimi or GPT + LiteParse + trafilatura)
```

**Complexity controls (the 8-tier ladder, adopted on demand):**

| Tier | Adopt when… |
|------|-------------|
| 1. Query-side filters (`link_types`, `min_confidence`, `updated_after`) | Day 1 — half a day's work |
| 2. Domain partitioning (`domain:` per Object Type) | At ~3+ source classes |
| 3. Hierarchical synthesis rollups | At ~500+ pages |
| 4. Centrality & importance ranking (PageRank in snapshot) | At ~1k+ nodes |
| 5. Edge weights & confidence pruning | Returns get noisy |
| 6. Bitemporal (`valid_from`/`valid_to`) | Temporal contradictions become recurring |
| 7. Ontology versioning + deprecation | Schema starts sprawling |
| 8. Tenancy (multi-overlay, shared raw) | Multi-BU rollout |

**Speaker notes:**
> The goal is to ship a real use case in 90 days, not to build the whole platform first. Tier-1 controls handle the first ~6 months. The ladder is your scaling story for the exec — we know how to scale this *because we know what to add at each break point.* That's the credibility lever.

---

## Slide 10 — Call to Action, Risks, KPIs

### What we're asking for
- **Sponsor + use case:** one named exec, one bounded business problem, 90-day pilot
- **Two engineers + one domain SME** for the pilot
- **Read access** to one document set + one record table (CSV/SQL extract)

### Risks & mitigations
| Risk | Mitigation |
|------|------------|
| LLM ingestion produces ontology violations | Linter blocks merge; ontology-first edits; deterministic record path bypasses LLM entirely |
| Graph complexity overwhelms users | 8-tier ladder above; domain partitioning + memo rollups |
| Vendor lock-in (LLM provider) | Pluggable: 6 providers wired today (`openai`, `gemini`, `kimi`, `nemotron`, `openrouter`, `deepseek`) |
| Hallucinated citations | "No floating facts" rule enforced by `upsert_*` tools; lint flags missing sources |
| Bitemporal complexity | Optional Tier-6; not required day 1 |

### KPIs to track
- **Time-to-answer** for the pilot use case (baseline → 90-day)
- **Citation rate** on agent answers (% with grounded source link)
- **Lint clean-rate** at merge (% pages passing all checks)
- **Action-server audit completeness** (100% target)
- **% queries served by graph traversal** vs raw vector (target shift toward graph at month 3)

### Decision asks
1. Approve the 90-day pilot scope on the named use case
2. Designate the executive sponsor + SME
3. Schedule month-2 review against KPIs

**Speaker notes:**
> Close on the ask, not the technology. Three resources, one named use case, one sponsor. If the room doesn't have a named use case yet, do not leave without scheduling the workshop to find one — the platform without a business outcome is a vanity project. Every metric on the KPI list is observable in this repo today (linter, audit log, retrieval traces, memo trace artifacts). Nothing on this slide is aspirational — it's all instrumented.

---

## Appendix — Sources & Further Reading

**Industry references**
- [Palantir Foundry Ontology overview](https://www.palantir.com/docs/foundry/ontology/overview)
- [Palantir AIP architecture](https://www.palantir.com/docs/foundry/architecture-center/aip-architecture)
- [Palantir Feb 2026 announcements (AIP Document Intelligence GA)](https://www.palantir.com/docs/foundry/announcements/2026-02)
- [Microsoft GraphRAG project page](https://www.microsoft.com/en-us/research/project/graphrag/)
- [Microsoft Research: GraphRAG on narrative private data](https://www.microsoft.com/en-us/research/blog/graphrag-unlocking-llm-discovery-on-narrative-private-data/)
- [GraphRAG on GitHub (microsoft/graphrag)](https://github.com/microsoft/graphrag)
- [TrustGraph — Context Operating System for AI](https://trustgraph.ai/)
- [TrustGraph: Ontologies and Context Graphs](https://trustgraph.ai/guides/key-concepts/ontologies-and-context-graphs/)
- [TrustGraph open-source repo](https://github.com/trustgraph-ai/trustgraph)
- [Karpathy's original LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- [VentureBeat coverage of LLM Wiki](https://venturebeat.com/data/karpathy-shares-llm-knowledge-base-architecture-that-bypasses-rag-with-an)

**Benchmarks & comparative research**
- [GraphRAG vs Vector RAG accuracy benchmark — FalkorDB / Diffbot KG-LM](https://www.falkordb.com/blog/graphrag-accuracy-diffbot-falkordb/)
- [GraphRAG vs Vector RAG side-by-side — Meilisearch](https://www.meilisearch.com/blog/graph-rag-vs-vector-rag)
- [Systematic eval: RAG vs GraphRAG (arXiv 2502.11371)](https://arxiv.org/html/2502.11371v3)
- [Knowledge Graph–Enhanced RAG for Enterprise (Lund Univ. master's thesis 2026)](http://lup.lub.lu.se/student-papers/record/9223345/file/9223346.pdf)
- [LinkedIn / Uber / Airbnb / Netflix knowledge-graph patterns (Neo4j)](https://neo4j.com/news/how-linkedin-uber-lyft-airbnb-and-netflix-are-solving-data-management-and-discovery-for-machine-learning-solutions/)
- [Hybrid RAG enterprise adoption forecast 2026](https://lumenalta.com/insights/9-llm-enterprise-applications-advancements-in-2026-for-cios-and-ctos)

**This repo**
- `CLAUDE.md` — full agent contract
- `agents/intel_memo.py` — reference application: Entity Intelligence Memo Engine
- `agents/document_parser.py` — multi-format parsers (PDF, Word, PPT, HTML)
- `agents/source_pull/web.py` — depth-limited web crawler
- `agents/record_ingester.py` — manifest-driven CSV/Excel ingest
- `ontology/` — Object / Link / Action type contracts
