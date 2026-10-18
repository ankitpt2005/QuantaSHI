"""
QuantaSHI - Part 1: User Interface AI Agent (Autonomous Workload Generator Agent).
Replaces manual static prompt scripting with generative AI agent personas that dynamically
synthesize realistic prompt payloads, token demands, priorities, and deadline SLOs.
"""

from __future__ import annotations
import json
import uuid
import time
import random
from typing import Dict, List, Optional, Any

from ai_agent_client import call_llm
from .models import InferenceRequest, WorkloadType, PriorityLevel


USER_PERSONAS = [
    {
        "role": "Senior Cloud Architect",
        "description": "Designs multi-region distributed systems and microservices pipelines.",
        "preferred_workload": WorkloadType.CODE_GEN,
    },
    {
        "role": "Financial Quantitative Analyst",
        "description": "Performs options pricing, risk simulations, and market sentiment extraction.",
        "preferred_workload": WorkloadType.RAG_QA,
    },
    {
        "role": "Enterprise Data Scientist",
        "description": "Summarizes long-context research publications and business intelligence reports.",
        "preferred_workload": WorkloadType.SUMMARIZATION,
    },
    {
        "role": "Real-time Customer Support Specialist",
        "description": "Handles live interactive user dialogues with low-latency responsiveness.",
        "preferred_workload": WorkloadType.TEXT_CHAT,
    },
    {
        "role": "Security Compliance Auditor",
        "description": "Extracts regulatory vulnerabilities from audit logs and source code.",
        "preferred_workload": WorkloadType.RAG_QA,
    },
]


class UserWorkloadAgent:
    """
    Dedicated AI Agent for Part 1: Users (Workload Generation).
    Synthesizes contextual inference traffic instead of relying on manual hardcoded templates.
    """

    def __init__(self, model: str = "openai/gpt-4o-mini"):
        self.model = model
        self.agent_name = "UserWorkloadAgent"
        self.history: List[Dict[str, Any]] = []

    def generate_dynamic_request(
        self,
        user_id: Optional[str] = None,
        persona: Optional[Dict[str, Any]] = None,
        workload_type: Optional[WorkloadType] = None,
        arrival_timestamp: Optional[float] = None,
    ) -> InferenceRequest:
        """
        Uses LLM agent to dynamically generate an authentic AI inference request.
        Falls back to intelligent local synthesis if LLM is unreachable.
        """
        if persona is None:
            persona = random.choice(USER_PERSONAS)
        if user_id is None:
            user_id = f"usr_{random.randint(1, 100):03d}"
        if workload_type is None:
            workload_type = persona.get("preferred_workload", random.choice(list(WorkloadType)))
        if arrival_timestamp is None:
            arrival_timestamp = time.time()

        system_prompt = (
            f"You are an autonomous AI Agent simulating an enterprise user: {persona['role']} "
            f"({persona['description']}). Generate a realistic AI inference query for workload '{workload_type.value}'.\n"
            "Return a strictly valid JSON object with the following keys:\n"
            "- prompt: realistic 1-2 sentence prompt query\n"
            "- context_tokens: integer prompt token count (between 64 and 2048)\n"
            "- max_output_tokens: integer expected output tokens (between 32 and 512)\n"
            "- priority: integer (0=P0_CRITICAL, 1=P1_INTERACTIVE, 2=P2_BATCH)\n"
            "- deadline_slo_ms: integer turnaround deadline in ms (between 400 and 4000)\n"
            "- reasoning: short 1-sentence rationale for these parameters\n"
            "Respond ONLY with valid JSON. No markdown ticks or commentary."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Generate request for persona: {persona['role']}"},
        ]

        llm_res = call_llm(
            messages=messages,
            model=self.model,
            temperature=0.7,
            max_tokens=300,
        )

        payload = None
        if llm_res.get("success") and llm_res.get("content"):
            try:
                raw_text = llm_res["content"].strip()
                if raw_text.startswith("```json"):
                    raw_text = raw_text[7:]
                if raw_text.startswith("```"):
                    raw_text = raw_text[3:]
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3]
                payload = json.loads(raw_text.strip())
            except Exception:
                payload = None

        if not payload:
            # Deterministic fallback if API is unreachable
            payload = self._fallback_synthesis(persona, workload_type)

        priority_val = payload.get("priority", 1)
        if priority_val == 0:
            pri = PriorityLevel.P0_CRITICAL
        elif priority_val == 2:
            pri = PriorityLevel.P2_BATCH
        else:
            pri = PriorityLevel.P1_INTERACTIVE

        req = InferenceRequest(
            request_id=f"req_{uuid.uuid4().hex[:8]}",
            user_id=user_id,
            arrival_timestamp=arrival_timestamp,
            workload_type=workload_type,
            context_tokens=int(payload.get("context_tokens", 256)),
            max_output_tokens=int(payload.get("max_output_tokens", 128)),
            priority_level=pri,
            deadline_slo_ms=float(payload.get("deadline_slo_ms", 1500.0)),
            prompt_preview=str(payload.get("prompt", "Simulated enterprise query")),
        )

        self.history.append({
            "request_id": req.request_id,
            "user_id": req.user_id,
            "persona": persona["role"],
            "prompt": req.prompt_preview,
            "reasoning": payload.get("reasoning", "Synthesized via AI Persona Agent"),
            "timestamp": arrival_timestamp,
        })
        if len(self.history) > 50:
            self.history.pop(0)

        return req

    def _fallback_synthesis(self, persona: Dict[str, Any], workload_type: WorkloadType) -> Dict[str, Any]:
        """Provides rich agent synthesis when LLM gateway is offline."""
        if workload_type == WorkloadType.CODE_GEN:
            return {
                "prompt": f"[{persona['role']}] Implement an asynchronous zero-copy buffer ring in Rust for network ingestion.",
                "context_tokens": 384,
                "max_output_tokens": 196,
                "priority": 0,
                "deadline_slo_ms": 1200.0,
                "reasoning": "High-throughput system implementation requiring low latency.",
            }
        elif workload_type == WorkloadType.RAG_QA:
            return {
                "prompt": f"[{persona['role']}] Reconcile quarterly cash flow liabilities with 10-K regulatory filings.",
                "context_tokens": 768,
                "max_output_tokens": 256,
                "priority": 1,
                "deadline_slo_ms": 2000.0,
                "reasoning": "Document retrieval analysis with moderate deadline urgency.",
            }
        elif workload_type == WorkloadType.SUMMARIZATION:
            return {
                "prompt": f"[{persona['role']}] Extract key risk factors and operational bottlenecks from clinical trial telemetry.",
                "context_tokens": 1024,
                "max_output_tokens": 180,
                "priority": 2,
                "deadline_slo_ms": 3500.0,
                "reasoning": "Long context batch processing with relaxed deadline.",
            }
        else:
            return {
                "prompt": f"[{persona['role']}] What is the recommended strategy for reducing P99 tail latency in Kubernetes?",
                "context_tokens": 160,
                "max_output_tokens": 80,
                "priority": 1,
                "deadline_slo_ms": 800.0,
                "reasoning": "Interactive real-time user enquiry requiring prompt response.",
            }
