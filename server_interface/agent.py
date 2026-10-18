"""
QuantaSHI - Part 2: Server Interface AI Agent (Autonomous Data Centre Ops Agent).
Replaces manual threshold checks with an intelligent Site Reliability & Hardware Ops AI Agent
that continuously analyzes cluster telemetry, diagnoses thermal/power bottlenecks, and issues
autonomous operational recommendations (e.g., node draining, stream throttling, rebalancing).
"""

from __future__ import annotations
import json
import time
from typing import Dict, List, Optional, Any

from ai_agent_client import call_llm
from .cluster import VirtualDataCentre


class ServerOpsAgent:
    """
    Dedicated AI Agent for Part 2: Servers (Virtual Data Centre Ops & Health).
    Evaluates physical cluster telemetry and diagnoses efficiency bottlenecks.
    """

    def __init__(self, model: str = "openai/gpt-4o-mini"):
        self.model = model
        self.agent_name = "ServerOpsAgent"
        self.diagnostic_history: List[Dict[str, Any]] = []

    def diagnose_cluster(self, cluster: VirtualDataCentre) -> Dict[str, Any]:
        """
        Extracts real-time telemetry from all servers and queries the AI Agent
        to diagnose cluster health and provide actionable operational directives.
        """
        telemetry = {}
        for s_id, server in cluster.servers.items():
            active = len(server.active_streams)
            queue = len(server.ingress_queue)
            p_curr = server.current_power_w
            e_total = server.cumulative_energy_joules
            tokens = server.total_tokens_processed
            violations = server.slo_violations
            status = server.status.value
            max_s = server.config.max_streams

            telemetry[s_id] = {
                "name": server.config.name,
                "model": server.config.model,
                "status": status,
                "active_streams": active,
                "max_streams": max_s,
                "utilization_pct": round((active / max(1, max_s)) * 100.0, 1),
                "queue_depth": queue,
                "current_power_w": round(p_curr, 1),
                "cumulative_energy_j": round(e_total, 1),
                "tokens_processed": tokens,
                "slo_violations": violations,
            }

        system_prompt = (
            "You are an autonomous AI Site Reliability Engineer and Data Centre Operations Agent for QuantaSHI.\n"
            "Analyze the provided virtual data centre telemetry for 3 heterogeneous compute nodes:\n"
            "1. srv_gpu_01 (High-Performance GPU, 300W peak, 32 max streams)\n"
            "2. srv_acc_02 (Balanced Tensor Accelerator, 70W peak, 16 max streams)\n"
            "3. srv_cpu_03 (Commodity CPU, 120W peak, 4 max streams)\n\n"
            "Return a strictly valid JSON object with the following keys:\n"
            "- cluster_health_score: integer 0-100\n"
            "- server_health: object mapping server_id to status ('OPTIMAL', 'ELEVATED_LOAD', 'CONGESTED', 'NEEDS_DRAIN')\n"
            "- primary_bottleneck: string naming the main operational concern\n"
            "- recommended_actions: list of 1-3 concise operational directives\n"
            "- executive_summary: 2-sentence diagnostic assessment\n"
            "Respond ONLY with valid JSON. No markdown ticks or commentary."
        )

        user_content = f"Current Cluster Telemetry: {json.dumps(telemetry, indent=2)}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        llm_res = call_llm(
            messages=messages,
            model=self.model,
            temperature=0.4,
            max_tokens=400,
        )

        diagnostic = None
        if llm_res.get("success") and llm_res.get("content"):
            try:
                raw_text = llm_res["content"].strip()
                if raw_text.startswith("```json"):
                    raw_text = raw_text[7:]
                if raw_text.startswith("```"):
                    raw_text = raw_text[3:]
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3]
                diagnostic = json.loads(raw_text.strip())
            except Exception:
                diagnostic = None

        if not diagnostic:
            diagnostic = self._fallback_diagnosis(telemetry)

        diagnostic["timestamp"] = time.time()
        diagnostic["telemetry_snapshot"] = telemetry

        self.diagnostic_history.append(diagnostic)
        if len(self.diagnostic_history) > 30:
            self.diagnostic_history.pop(0)

        return diagnostic

    def _fallback_diagnosis(self, telemetry: Dict[str, Any]) -> Dict[str, Any]:
        """Deterministic diagnostic logic when LLM gateway is offline."""
        server_health = {}
        actions = []
        bottleneck = "None - Steady-state operation"
        health_score = 95

        for s_id, data in telemetry.items():
            util = data.get("utilization_pct", 0)
            queue = data.get("queue_depth", 0)
            if queue > 3 or util >= 90:
                server_health[s_id] = "CONGESTED"
                bottleneck = f"Queue saturation on {s_id}"
                actions.append(f"Throttle ingress or offload traffic from {s_id}")
                health_score -= 20
            elif util >= 60:
                server_health[s_id] = "ELEVATED_LOAD"
            else:
                server_health[s_id] = "OPTIMAL"

        if not actions:
            actions = ["Maintain current multi-stream dispatch parameters", "Monitor DRAM bandwidth contention"]

        return {
            "cluster_health_score": max(20, health_score),
            "server_health": server_health,
            "primary_bottleneck": bottleneck,
            "recommended_actions": actions,
            "executive_summary": "Heterogeneous cluster operating within standard thermal and concurrency envelopes. Power consumption is balanced across accelerated nodes.",
        }
