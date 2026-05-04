---
id: "disaggregated_serving"
type: "Concept"
sources: ["raw/web/nvidianews.nvidia.com/news_nvidia_dynamo_open_source_library_accelerates_and_scales_ai_reasoning_models.html"]
confidence: 0.9
updated: "2026-05-04"
links: [{"to": "nvidia_dynamo", "type": "mentions"}, {"to": "ai_reasoning_models", "type": "mentions"}, {"to": "nvidia_llama_nemotron", "type": "mentions"}]
---

# Disaggregated serving

Disaggregated serving is an inference architecture technique that assigns the different computational phases of large language models (LLMs) — including building an understanding of the user query and then generating the best response — to different GPUs. This allows each phase to be optimized independently for its specific needs and ensures maximum GPU resource utilization. NVIDIA Dynamo supports disaggregated serving as a core feature. It is particularly well-suited for reasoning models like the NVIDIA Llama Nemotron model family.
