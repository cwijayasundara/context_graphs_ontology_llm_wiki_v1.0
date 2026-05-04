---
id: "kv_cache"
type: "Concept"
sources: ["raw/web/nvidianews.nvidia.com/news_nvidia_dynamo_open_source_library_accelerates_and_scales_ai_reasoning_models.html"]
confidence: 0.9
updated: "2026-05-04"
links: [{"to": "nvidia_dynamo", "type": "mentions"}, {"to": "ai_reasoning_models", "type": "mentions"}]
---

# KV cache

KV cache (Key-Value cache) is the knowledge that inference systems hold in memory from serving prior requests. NVIDIA Dynamo maps the KV cache across potentially thousands of GPUs and routes new inference requests to the GPUs that have the best knowledge match, avoiding costly recomputations and freeing up GPUs to respond to new incoming requests.
