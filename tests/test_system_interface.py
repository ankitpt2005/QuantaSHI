"""
Unit tests for system_interface (Part 3: System / Decision & Optimization Engine).
Verifies Pareto optimization scoring, policy switching, and end-to-end integration between users, system, and servers.
"""

import unittest
from user_interface.generator import WorkloadGenerator
from server_interface.cluster import VirtualDataCentre
from system_interface.models import RoutingPolicy
from system_interface.optimizer import QuantaSHIOptimizer
from system_interface.scheduler import QuantaSHIScheduler


class TestSystemInterface(unittest.TestCase):

    def setUp(self):
        self.cluster = VirtualDataCentre()
        self.generator = WorkloadGenerator(seed=42)
        self.scheduler = QuantaSHIScheduler(cluster=self.cluster, policy=RoutingPolicy.BALANCED_PARETO)

    def test_optimizer_policy_weights(self):
        opt = QuantaSHIOptimizer(policy=RoutingPolicy.ENERGY_OPTIMIZED)
        self.assertAlmostEqual(opt.weights.weight_energy, 0.85)
        self.assertAlmostEqual(opt.weights.weight_latency, 0.15)

        opt.set_policy(RoutingPolicy.LATENCY_FIRST)
        self.assertAlmostEqual(opt.weights.weight_energy, 0.10)
        self.assertAlmostEqual(opt.weights.weight_latency, 0.90)

    def test_end_to_end_route_request(self):
        # Generate single request from user_interface
        req = self.generator.create_single_request("usr_001", timestamp=1.0)
        
        # Route via system_interface
        decision = self.scheduler.route_request(req)

        self.assertIsNotNone(decision.decision_id)
        self.assertEqual(decision.request_id, req.request_id)
        self.assertIn(decision.selected_server_id, ["srv_gpu_01", "srv_acc_02", "srv_cpu_03"])

        # Check that target server in server_interface received the task
        target_srv = self.cluster.servers[decision.selected_server_id]
        self.assertEqual(len(target_srv.active_streams), 1)

    def test_system_reset(self):
        req = self.generator.create_single_request("usr_002", timestamp=2.0)
        self.scheduler.route_request(req)
        self.assertEqual(self.scheduler.total_dispatched, 1)

        self.scheduler.reset()
        self.assertEqual(self.scheduler.total_dispatched, 0)
        self.assertEqual(len(self.scheduler.decisions_history), 0)


if __name__ == "__main__":
    unittest.main()
