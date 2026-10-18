"""
Prompt corpus derived from real-world conversational datasets (WildChat & developer traces).
Supplies realistic prompt previews for visual telemetry and node click inspection.
"""

import random
from typing import List, Dict
from .models import WorkloadType

PROMPT_CORPUS: Dict[WorkloadType, List[str]] = {
    WorkloadType.TEXT_CHAT: [
        "Explain the fundamental difference between speculative decoding and standard autoregressive sampling.",
        "How can we minimize KV-cache memory footprint on NVIDIA H100 GPUs during long multi-turn sessions?",
        "Can you compare Kubernetes HPA versus KEDA for scaling GPU inference worker pods?",
        "Explain the trade-offs between PagedAttention and vLLM continuous batching in high-concurrency setups.",
        "What are the best practices for handling multi-tenant rate limits in cloud AI gateways?",
        "Provide a high-level overview of distributed tensor parallelism across multiple SXM5 nodes.",
        "How does flash-attention reduce memory bandwidth bottlenecks in transformer architectures?",
        "Write a concise guide comparing quantized 4-bit AWQ with FP8 inference precision.",
        "What metrics should an AI data center monitor to anticipate thermal throttling on GPU racks?",
        "Explain how token bucket algorithms differ from leaky bucket in request rate limiters.",
    ],
    WorkloadType.CODE_GEN: [
        "Write an asynchronous Python asyncio queue worker with retry logic and exponential backoff.",
        "Implement a custom PyTorch CUDA kernel hook for fused RoPE (Rotary Positional Embedding).",
        "Generate a Rust gRPC client to stream inference tokens with zero-copy serialization.",
        "Create a FastAPI endpoint that handles streaming Server-Sent Events (SSE) for LLM tokens.",
        "Write a Triton server client script in C++ sending concurrent inference batches.",
        "Implement a Redis-backed token bucket rate limiter in Go with atomic pipeline executions.",
        "Write a Prometheus custom exporter in Python to track GPU memory fragmentation metrics.",
        "Generate a SQL schema and indexing strategy for storing 50 million inference audit logs.",
        "Implement an LRU cache with TTL in TypeScript for caching embedding vectors.",
        "Write a Dockerfile and Kubernetes deployment manifest for vLLM with Ray cluster support.",
    ],
    WorkloadType.RAG_QA: [
        "Based on the 48-page quarterly financial filing, identify all GPU capital expenditures.",
        "According to the attached ISO-27001 audit report, list unresolved high-severity access control findings.",
        "Query the corporate knowledge base to extract SLA compensation clauses for 99.9% uptime tiers.",
        "From the technical whitepaper, summarize Section 4 regarding cross-datacenter failover latency.",
        "Extract all FDA regulatory citations regarding algorithmic transparency from the clinical study PDF.",
        "Using the customer contract archive, compare renewal penalty provisions across Tier-1 enterprise clients.",
        "Synthesize recommendations from three engineering post-mortems on database deadlocks.",
        "Extract API breaking changes between v2.4 and v3.0 documented in the developer changelog.",
        "Cross-reference employee onboarding compliance logs against the mandatory cybersecurity checklist.",
        "Analyze 200 customer support transcripts to identify the top 5 unresolved onboarding bugs.",
    ],
    WorkloadType.SUMMARIZATION: [
        "Generate a 3-paragraph executive briefing of the 120-page Federal Trade Commission AI guidelines.",
        "Summarize the annual data center sustainability report, highlighting PUE and water consumption.",
        "Provide an analytical summary of the earnings conference call transcript, noting analyst sentiment.",
        "Condense the multi-author research paper on state-space models (Mamba) into key theoretical contributions.",
        "Produce a bullet-point executive digest of the quarterly cyber-threat intelligence report.",
        "Summarize the comprehensive legal deposition transcript regarding proprietary algorithmic models.",
        "Summarize the server telemetry logs recorded during yesterday's 14:00 UTC network degradation event.",
        "Condense the 80-page EU AI Act regulatory impact assessment for enterprise software architects.",
        "Create an executive summary comparing cloud pricing models across AWS, Azure, and GCP for H100 clusters.",
        "Synthesize customer feedback surveys collected across 10,000 enterprise software trial users.",
    ],
}


def get_random_prompt(workload_type: WorkloadType) -> str:
    """Returns a realistic prompt preview snippet matching the workload type."""
    corpus = PROMPT_CORPUS.get(workload_type, PROMPT_CORPUS[WorkloadType.TEXT_CHAT])
    return random.choice(corpus)
