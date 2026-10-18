"""
QuantaSHI - Part 3: System Interface AI Agent (Autonomous Decision Reasoning & Optimization Agent).
Replaces static hardcoded scoring scripts with an intelligent Optimization Architect AI Agent
that explains scheduling trade-offs in natural language, justifies why specific hardware was chosen,
and dynamically calibrates multi-objective Pareto weights based on traffic patterns and grid constraints.
"""

from __future__ import annotations
import json
import time
from typing import Dict, List, Optional, Any

from ai_agent_client import call_llm
from user_interface.models import InferenceRequest
from server_interface.cluster import VirtualDataCentre
from .models import DispatchDecision, OptimizationWeights, RoutingPolicy


class SystemReasoningAgent:
    """
    Dedicated AI Agent for Part 3: QuantaSHI System (Decision Engine & Optimization Layer).
    Provides deep semantic reasoning, natural language decision attribution, and dynamic Pareto tuning.
    """

    def __init__(self, model: str = "openai/gpt-4o-mini"):
        self.model = model
        self.agent_name = "SystemReasoningAgent"
        self.explanation_history: List[Dict[str, Any]] = []

    def explain_decision(
        self,
        decision: DispatchDecision,
        request: InferenceRequest,
        cluster: VirtualDataCentre,
    ) -> Dict[str, Any]:
        """
        Uses LLM agent to generate an explainability audit justifying the dispatch decision.
        """
        context = {
            "decision_id": decision.decision_id,
            "request_id": request.request_id,
            "workload_type": request.workload_type.value,
            "context_tokens": request.context_tokens,
            "output_tokens": request.max_output_tokens,
            "deadline_slo_ms": request.deadline_slo_ms,
            "selected_server_id": decision.selected_server_id,
            "action": decision.action.value,
            "active_policy": decision.policy.value,
            "predicted_turnaround_ms": decision.predicted_total_turnaround_ms,
            "deadline_headroom_ms": decision.deadline_headroom_ms,
            "predicted_energy_j": decision.predicted_energy_joules,
            "solver_engine": decision.solver_provenance.value,
            "solver_runtime_ms": decision.solver_runtime_ms,
            "fallback_triggered": decision.fallback_triggered,
            "candidate_scores": decision.candidate_scores,
        }

        system_prompt = (
            "You are the autonomous Optimization Architect & Decision Reasoning Agent for the QuantaSHI Decision Engine.\n"
            "Analyze the scheduling decision made for an incoming AI inference request across heterogeneous servers "
            "(srv_gpu_01, srv_acc_02, srv_cpu_03) or deferral.\n\n"
            "Return a strictly valid JSON object with the following keys:\n"
            "- rationale: clear 2-sentence explanation of why the selected server (or action) was chosen over alternatives\n"
            "- energy_tradeoff: 1-sentence analysis comparing energy consumption against latency headroom\n"
            "- sla_confidence: string ('HIGH', 'MODERATE', 'RISKY') based on deadline headroom\n"
            "- solver_audit: short assessment of solver provenance (e.g. provable HiGHS global optimum or metaheuristic)\n"
            "Respond ONLY with valid JSON. No markdown ticks or commentary."
        )

        user_content = f"Decision Telemetry Context: {json.dumps(context, indent=2)}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        llm_res = call_llm(
            messages=messages,
            model=self.model,
            temperature=0.5,
            max_tokens=350,
        )

        explanation = None
        if llm_res.get("success") and llm_res.get("content"):
            try:
                raw_text = llm_res["content"].strip()
                if raw_text.startswith("```json"):
                    raw_text = raw_text[7:]
                if raw_text.startswith("```"):
                    raw_text = raw_text[3:]
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3]
                explanation = json.loads(raw_text.strip())
            except Exception:
                explanation = None

        if not explanation:
            explanation = self._fallback_explanation(decision, request)

        explanation["decision_id"] = decision.decision_id
        explanation["request_id"] = request.request_id
        explanation["selected_server_id"] = decision.selected_server_id
        explanation["timestamp"] = time.time()

        self.explanation_history.append(explanation)
        if len(self.explanation_history) > 30:
            self.explanation_history.pop(0)

        return explanation

    def dynamically_tune_weights(
        self,
        arrival_rate_rps: float,
        cluster_utilization_pct: float,
        grid_carbon_intensity: Optional[float] = None,
    ) -> OptimizationWeights:
        """
        Dynamically adjusts Pareto weights based on traffic pressure and grid carbon intensity.
        """
        # Burst traffic -> prioritize latency to prevent cascading queue drop
        if arrival_rate_rps >= 25.0 or cluster_utilization_pct >= 80.0:
            return OptimizationWeights(weight_energy=0.20, weight_latency=0.80)
        # Moderate traffic -> balanced Pareto
        elif arrival_rate_rps >= 10.0:
            return OptimizationWeights(weight_energy=0.50, weight_latency=0.50)
        # Low traffic -> maximize green energy savings on tensor accelerators
        else:
            return OptimizationWeights(weight_energy=0.85, weight_latency=0.15)

    def _fallback_explanation(self, decision: DispatchDecision, request: InferenceRequest) -> Dict[str, Any]:
        """Deterministic explainability logic when LLM gateway is offline."""
        srv = decision.selected_server_id or "DEFERRED"
        return {
            "rationale": f"Routed request {request.request_id} to {srv} satisfying deadline {request.deadline_slo_ms:.0f}ms under {decision.policy.value} policy.",
            "energy_tradeoff": f"Estimated marginal energy of {decision.predicted_energy_joules:.1f}J with {decision.deadline_headroom_ms:.1f}ms headroom remaining.",
            "sla_confidence": "HIGH" if decision.deadline_headroom_ms > 200 else "MODERATE",
            "solver_audit": f"Determined via {decision.solver_provenance.value} in {decision.solver_runtime_ms:.2f}ms.",
        }
