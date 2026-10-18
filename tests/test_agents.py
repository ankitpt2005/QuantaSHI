"""
Unit tests for QuantaSHI Autonomous AI Agents across all 3 interfaces:
1. Part 1 (user_interface): UserWorkloadAgent
2. Part 2 (server_interface): ServerOpsAgent
3. Part 3 (system_interface): SystemReasoningAgent
"""

import unittest
from user_interface.agent import UserWorkloadAgent, USER_PERSONAS
from user_interface.models import WorkloadType, PriorityLevel
from server_interface.cluster import VirtualDataCentre
from server_interface.agent import ServerOpsAgent
from system_interface.agent import SystemReasoningAgent
from system_interface.models import RoutingPolicy
from system_interface.scheduler import QuantaSHIScheduler


class TestAIAgents(unittest.TestCase):

    def setUp(self):
        self.cluster = VirtualDataCentre()
        self.user_agent = UserWorkloadAgent()
        self.server_agent = ServerOpsAgent()
        self.system_agent = SystemReasoningAgent()
        self.scheduler = QuantaSHIScheduler(cluster=self.cluster)

    def test_user_workload_agent_generation(self):
        """Tests that UserWorkloadAgent synthesizes valid, authentic InferenceRequests."""
        req = self.user_agent.generate_dynamic_request()
        self.assertIsNotNone(req.request_id)
        self.assertTrue(req.user_id.startswith("usr_"))
        self.assertIn(req.workload_type, list(WorkloadType))
        self.assertGreater(req.context_tokens, 0)
        self.assertGreater(req.max_output_tokens, 0)
        self.assertGreater(req.deadline_slo_ms, 0)
        self.assertGreater(len(req.prompt_preview), 5)
        self.assertGreater(len(self.user_agent.history), 0)

    def test_user_workload_agent_fallback(self):
        """Tests local synthesis fallback logic for each workload type."""
        persona = USER_PERSONAS[0]
        for w_type in WorkloadType:
            synth = self.user_agent._fallback_synthesis(persona, w_type)
            self.assertIn("prompt", synth)
            self.assertIn("context_tokens", synth)
            self.assertIn("max_output_tokens", synth)
            self.assertIn("deadline_slo_ms", synth)

    def test_server_ops_agent_diagnostics(self):
        """Tests that ServerOpsAgent evaluates cluster telemetry and returns structured diagnostics."""
        diag = self.server_agent.diagnose_cluster(self.cluster)
        self.assertIn("cluster_health_score", diag)
        self.assertIn("server_health", diag)
        self.assertIn("srv_gpu_01", diag["server_health"])
        self.assertIn("srv_acc_02", diag["server_health"])
        self.assertIn("srv_cpu_03", diag["server_health"])
        self.assertIn("recommended_actions", diag)
        self.assertIsInstance(diag["recommended_actions"], list)
        self.assertGreater(len(self.server_agent.diagnostic_history), 0)

    def test_system_reasoning_agent_explainability(self):
        """Tests that SystemReasoningAgent provides natural language explainability for scheduling decisions."""
        req = self.user_agent.generate_dynamic_request()
        decision = self.scheduler.route_request(req)

        explanation = self.system_agent.explain_decision(decision, req, self.cluster)
        self.assertIn("rationale", explanation)
        self.assertIn("energy_tradeoff", explanation)
        self.assertIn("sla_confidence", explanation)
        self.assertIn(explanation["sla_confidence"], ["HIGH", "MODERATE", "RISKY"])
        self.assertGreater(len(self.system_agent.explanation_history), 0)

    def test_system_agent_dynamic_weight_tuning(self):
        """Tests dynamic Pareto weight adjustment based on traffic pressure."""
        burst_weights = self.system_agent.dynamically_tune_weights(arrival_rate_rps=35.0, cluster_utilization_pct=85.0)
        self.assertAlmostEqual(burst_weights.weight_latency, 0.80)
        self.assertAlmostEqual(burst_weights.weight_energy, 0.20)

        idle_weights = self.system_agent.dynamically_tune_weights(arrival_rate_rps=4.0, cluster_utilization_pct=15.0)
        self.assertAlmostEqual(idle_weights.weight_latency, 0.15)
        self.assertAlmostEqual(idle_weights.weight_energy, 0.85)


if __name__ == "__main__":
    unittest.main()
