"""
Unit tests for user_interface (Part 1: Users / Workload Generator).
Verifies schemas, distribution sampling, network topology, and simulation scenarios.
"""

import unittest
import uuid
from user_interface.models import InferenceRequest, PriorityLevel, WorkloadType, UserTier, UserStatus
from user_interface.topology import NetworkTopology
from user_interface.generator import WorkloadGenerator, SimulationScenario


class TestUserInterface(unittest.TestCase):

    def setUp(self):
        self.generator = WorkloadGenerator(seed=123)

    def test_topology_initialization(self):
        topo = self.generator.topology
        self.assertEqual(len(topo.users), 100)
        
        # Check tier distribution
        p0_users = [u for u in topo.users.values() if u.tier == UserTier.ENTERPRISE_P0]
        p1_users = [u for u in topo.users.values() if u.tier == UserTier.PRO_P1]
        p2_users = [u for u in topo.users.values() if u.tier == UserTier.STANDARD_P2]
        
        self.assertEqual(len(p0_users), 15)
        self.assertEqual(len(p1_users), 60)
        self.assertEqual(len(p2_users), 25)

        # Check links
        payload = topo.get_topology_payload()
        self.assertEqual(payload["num_nodes"], 100)
        self.assertGreater(payload["num_edges"], 50)

    def test_single_request_schema(self):
        req = self.generator.create_single_request("usr_001", timestamp=1.5)
        self.assertIsInstance(req, InferenceRequest)
        self.assertEqual(req.user_id, "usr_001")
        self.assertEqual(req.arrival_timestamp, 1.5)
        self.assertTrue(uuid.UUID(req.request_id))
        self.assertGreaterEqual(req.context_tokens, 1)
        self.assertGreaterEqual(req.max_output_tokens, 1)
        self.assertIn(req.priority_level, [PriorityLevel.P0_CRITICAL, PriorityLevel.P1_INTERACTIVE, PriorityLevel.P2_BATCH])
        self.assertGreater(req.deadline_slo_ms, 0)
        self.assertIsInstance(req.prompt_preview, str)
        self.assertGreater(len(req.prompt_preview), 5)

        # Test dictionary serialization
        d = req.to_dict()
        req_deserialized = InferenceRequest.from_dict(d)
        self.assertEqual(req.request_id, req_deserialized.request_id)
        self.assertEqual(req.context_tokens, req_deserialized.context_tokens)

    def test_scenario_1_steady_state(self):
        trace = self.generator.generate_trace(duration_seconds=10.0, scenario=SimulationScenario.SCENARIO_1_STEADY_STATE)
        self.assertGreater(len(trace), 50)
        for i in range(len(trace) - 1):
            self.assertLessEqual(trace[i].arrival_timestamp, trace[i + 1].arrival_timestamp)

    def test_scenario_2_burst_spike(self):
        trace = self.generator.generate_trace(duration_seconds=30.0, scenario=SimulationScenario.SCENARIO_2_FLASH_BURST)
        burst_reqs = [r for r in trace if 20.0 <= r.arrival_timestamp <= 21.0]
        self.assertGreaterEqual(len(burst_reqs), 40, "Burst spike at t=20s should contain at least 40 requests")

    def test_scenario_3_bimodal_distribution(self):
        trace = self.generator.generate_trace(duration_seconds=20.0, scenario=SimulationScenario.SCENARIO_3_BIMODAL)
        short_chats = [r for r in trace if r.workload_type == WorkloadType.TEXT_CHAT]
        heavy_rag = [r for r in trace if r.workload_type in (WorkloadType.RAG_QA, WorkloadType.SUMMARIZATION)]
        self.assertGreater(len(short_chats), len(heavy_rag))
        if heavy_rag:
            self.assertGreater(heavy_rag[0].context_tokens, 1000)

    def test_manual_burst_trigger(self):
        burst = self.generator.trigger_burst(num_burst_users=25, current_time=5.0)
        self.assertEqual(len(burst), 25)
        for r in burst:
            self.assertGreaterEqual(r.arrival_timestamp, 5.0)


if __name__ == "__main__":
    unittest.main()
