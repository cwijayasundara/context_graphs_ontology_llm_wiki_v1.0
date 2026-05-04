---
id: "memo_intel_memo__nvidia_corp"
type: "Memo"
title: "Intel Memo: nvidia-corp"
target_entity: "nvidia-corp"
generated_at: "2026-05-04T06:45:48.677588+00:00"
hops: 2
claim_count: 37
contradictions_count: 4
freshness_warnings_count: 0
sources: ["agentic_ai", "ai_enterprise", "ai_reasoning", "ampere-gpu", "blackwell-gpu", "blackwell_ultra", "bluefield_3", "capital-return", "connectx_8", "cuda_x", "data_center_revenue", "free-cash-flow", "fy26", "fy27", "gaap", "gb200", "gb300", "gb300_nvl72", "gross-margin", "hgx_b300_nvl16", "hopper-gpu", "infiniband", "llama_nemotron", "networking_segment", "non-gaap-measures", "non_gaap", "nvidia", "nvidia-corp", "nvlink", "physical_ai", "q1-fy27-outlook", "q4_fy26", "quantum_x800", "quarterly_revenue_trend", "revenue_by_markets", "spectrum-x", "test_time_scaling"]
confidence: 0.9
updated: "2026-05-04"
links: [{"to": "nvidia-corp", "type": "targets"}, {"to": "agentic_ai", "type": "cites_evidence"}, {"to": "ai_enterprise", "type": "cites_evidence"}, {"to": "ai_reasoning", "type": "cites_evidence"}, {"to": "ampere-gpu", "type": "cites_evidence"}, {"to": "blackwell-gpu", "type": "cites_evidence"}, {"to": "blackwell_ultra", "type": "cites_evidence"}, {"to": "bluefield_3", "type": "cites_evidence"}, {"to": "capital-return", "type": "cites_evidence"}, {"to": "connectx_8", "type": "cites_evidence"}, {"to": "cuda_x", "type": "cites_evidence"}, {"to": "data_center_revenue", "type": "cites_evidence"}, {"to": "free-cash-flow", "type": "cites_evidence"}, {"to": "fy26", "type": "cites_evidence"}, {"to": "fy27", "type": "cites_evidence"}, {"to": "gaap", "type": "cites_evidence"}, {"to": "gb200", "type": "cites_evidence"}, {"to": "gb300", "type": "cites_evidence"}, {"to": "gb300_nvl72", "type": "cites_evidence"}, {"to": "gross-margin", "type": "cites_evidence"}, {"to": "hgx_b300_nvl16", "type": "cites_evidence"}, {"to": "hopper-gpu", "type": "cites_evidence"}, {"to": "infiniband", "type": "cites_evidence"}, {"to": "llama_nemotron", "type": "cites_evidence"}, {"to": "networking_segment", "type": "cites_evidence"}, {"to": "non-gaap-measures", "type": "cites_evidence"}, {"to": "non_gaap", "type": "cites_evidence"}, {"to": "nvidia", "type": "cites_evidence"}, {"to": "nvidia-corp", "type": "cites_evidence"}, {"to": "nvlink", "type": "cites_evidence"}, {"to": "physical_ai", "type": "cites_evidence"}, {"to": "q1-fy27-outlook", "type": "cites_evidence"}, {"to": "q4_fy26", "type": "cites_evidence"}, {"to": "quantum_x800", "type": "cites_evidence"}, {"to": "quarterly_revenue_trend", "type": "cites_evidence"}, {"to": "revenue_by_markets", "type": "cites_evidence"}, {"to": "spectrum-x", "type": "cites_evidence"}, {"to": "test_time_scaling", "type": "cites_evidence"}, {"to": "data_center_revenue", "type": "flags_concept"}, {"to": "fy26", "type": "flags_concept"}, {"to": "gaap", "type": "flags_concept"}, {"to": "gross-margin", "type": "flags_concept"}, {"to": "networking_segment", "type": "flags_concept"}, {"to": "non_gaap", "type": "flags_concept"}, {"to": "nvidia-corp", "type": "flags_concept"}, {"to": "q1-fy27-outlook", "type": "flags_concept"}, {"to": "q4_fy26", "type": "flags_concept"}]
---

# Intel Memo: nvidia-corp

**Target:** [[nvidia-corp]] (type: `Customer`)  
**Traversal:** 2-hop, 37 pages reached  
**Generated:** 2026-05-04T06:45:48.605186+00:00

## Coverage by Object Type

- **Concept**: 20 — [[q1-fy27-outlook]], [[fy26]], [[non-gaap-measures]]
- **Customer**: 2 — [[nvidia-corp]], [[nvidia]]
- **Decision**: 0 — _none_
- **Memo**: 0 — _none_
- **Person**: 0 — _none_
- **Product**: 15 — [[blackwell-gpu]], [[blackwell_ultra]], [[hopper-gpu]]
- **Source**: 0 — _none_

**Gaps:** Decision, Memo, Person, Source — no pages of these types in the 2-hop neighborhood.

## Derived Metrics
- Revenue range across cited pages: $3.0B – $215.9B
- Gross margin range across cited pages: 2.0% – 75.2%

## Contradictions Detected
- **revenue / unspecified / data_center** — distinct values seen: 3.0USD_B, 11.0USD_B, 32.6USD_B, 35.6USD_B, 51.3USD_B, 62.3USD_B, 68.1USD_B; pages: [[data_center_revenue]], [[networking_segment]], [[nvidia-corp]]
- **revenue / fy2026 / company_wide** — distinct values seen: 68.1USD_B, 215.9USD_B; pages: [[fy26]], [[nvidia-corp]], [[q4_fy26]]
- **gross_margin / unspecified / company_wide** — distinct values seen: 2.0%, 20.0%, 65.0%, 71.1%, 71.3%, 73.0%, 73.5%, 74.9%, 75.0%, 75.2%; pages: [[fy26]], [[gaap]], [[gross-margin]], [[non_gaap]], [[q1-fy27-outlook]], [[q4_fy26]]
- **revenue / unspecified / company_wide** — distinct values seen: 31.4USD_B, 78.0USD_B; pages: [[networking_segment]], [[q1-fy27-outlook]]

## Freshness Warnings
_All cited pages are at least as new as their sources._

## Provenance Chain (first 10 entries)
- [[nvidia-corp]] (`Customer`, conf=0.95) ← `raw/docs/NVDA-F4Q26-Quarterly-Presentation.pdf` (class=document, ingested=2026-05-04)
- [[nvidia-corp]] (`Customer`, conf=0.95) ← `raw/docs/Q4FY26-CFO-Commentary.pdf` (class=document, ingested=2026-05-04)
- [[ampere-gpu]] (`Product`, conf=0.92) ← `raw/docs/NVDA-F4Q26-Quarterly-Presentation.pdf` (class=document, ingested=2026-05-04)
- [[blackwell-gpu]] (`Product`, conf=0.92) ← `raw/docs/NVDA-F4Q26-Quarterly-Presentation.pdf` (class=document, ingested=2026-05-04)
- [[blackwell_ultra]] (`Product`, conf=0.95) ← `raw/web/nvidianews.nvidia.com/news_nvidia_blackwell_ultra_ai_factory_platform_paves_way_for_age_of_ai_reasoning.html` (class=press_release, ingested=2026-05-04)
- [[blackwell_ultra]] (`Product`, conf=0.95) ← `raw/docs/NVDA-F4Q26-Quarterly-Presentation.pdf` (class=document, ingested=2026-05-04)
- [[capital-return]] (`Concept`, conf=0.94) ← `raw/docs/NVDA-F4Q26-Quarterly-Presentation.pdf` (class=document, ingested=2026-05-04)
- [[data_center_revenue]] (`Concept`, conf=0.95) ← `raw/docs/Rev_by_Mkt_Qtrly_Trend_Q426.pdf` (class=document, ingested=2026-05-04)
- [[data_center_revenue]] (`Concept`, conf=0.95) ← `raw/docs/NVDA-F4Q26-Quarterly-Presentation.pdf` (class=document, ingested=2026-05-04)
- [[free-cash-flow]] (`Concept`, conf=0.94) ← `raw/docs/NVDA-F4Q26-Quarterly-Presentation.pdf` (class=document, ingested=2026-05-04)
- _… and 35 more provenance rows in the trace artifact._

## Cited Pages

- [[agentic_ai]] (Concept)
- [[ai_enterprise]] (Product)
- [[ai_reasoning]] (Concept)
- [[ampere-gpu]] (Product)
- [[blackwell-gpu]] (Product)
- [[blackwell_ultra]] (Product)
- [[bluefield_3]] (Product)
- [[capital-return]] (Concept)
- [[connectx_8]] (Product)
- [[cuda_x]] (Product)
- [[data_center_revenue]] (Concept) ⚠
- [[free-cash-flow]] (Concept)
- [[fy26]] (Concept) ⚠
- [[fy27]] (Concept)
- [[gaap]] (Concept) ⚠
- [[gb200]] (Concept)
- [[gb300]] (Concept)
- [[gb300_nvl72]] (Product)
- [[gross-margin]] (Concept) ⚠
- [[hgx_b300_nvl16]] (Product)
- [[hopper-gpu]] (Product)
- [[infiniband]] (Product)
- [[llama_nemotron]] (Product)
- [[networking_segment]] (Concept) ⚠
- [[non-gaap-measures]] (Concept)
- [[non_gaap]] (Concept) ⚠
- [[nvidia]] (Customer)
- [[nvidia-corp]] (Customer) ⚠
- [[nvlink]] (Product)
- [[physical_ai]] (Concept)
- [[q1-fy27-outlook]] (Concept) ⚠
- [[q4_fy26]] (Concept) ⚠
- [[quantum_x800]] (Product)
- [[quarterly_revenue_trend]] (Concept)
- [[revenue_by_markets]] (Concept)
- [[spectrum-x]] (Product)
- [[test_time_scaling]] (Concept)

## Target Snapshot

# NVIDIA Corporation

NVIDIA Corporation is a leading technology company specializing in GPU-accelerated computing and AI infrastructure. According to the Q4 FY26 investor presentation, NVIDIA reported record quarterly revenue of $68.1B (+73% YoY), with Data Center revenue up nearly 13x since the emergence of ChatGPT. The company is described as the world's largest networking business and the most performant, lowest cost/token inference provider with the largest installed base. NVIDIA infrastructure is in high demand, with even Hopper and much of the six-year-old Ampere-based products sold out
