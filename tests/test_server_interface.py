"""
Unit tests for server_interface (Part 2: Servers / Virtual Data Centre).
Verifies heterogeneous server model, Fan et al. power formula, two-phase latency, and cluster dynamics.
"""

import unittest
from server_interface.models import ServerType, ServerStatus, ExecutionTask
from server_interface.cluster import VirtualDataCentre, DEFAULT_SERVERS
from server_interface.power_model import calculate_instantaneous_power, calculate_task_energy
from server_interface.execution_engine import calculate_execution_duration


class TestServerInterface(unittest.TestCase):

    def setUp(self):
        self.vdc = VirtualDataCentre()

    def test_cluster_initialization(self):
        self.assertEqual(len(self.vdc.servers), 3)
        self.assertIn("srv_gpu_01", self.vdc.servers)
        self.assertIn("srv_acc_02", self.vdc.servers)
        self.assertIn("srv_cpu_03", self.vdc.servers)

        # Baseline idle power sum: 75 + 25 + 45 = 145 W
        self.assertAlmostEqual(self.vdc.get_cluster_power_w(), 145.0, places=1)

    def test_fan_power_formula(self):
        h100 = DEFAULT_SERVERS[0]
        # At u = 0, power should equal idle power
        p_idle = calculate_instantaneous_power(h100, active_streams=0)
        self.assertAlmostEqual(p_idle, 75.0, places=1)

        # At u = 1.0 (32 streams), power should equal peak power (350W)
        p_peak = calculate_instantaneous_power(h100, active_streams=32)
        self.assertAlmostEqual(p_peak, 350.0, places=1)

        # At intermediate utilization (e.g. 16 streams), power should be strictly between idle and peak
        p_mid = calculate_instantaneous_power(h100, active_streams=16)
        self.assertGreater(p_mid, 75.0)
        self.assertLess(p_mid, 350.0)

    def test_execution_duration(self):
        h100 = DEFAULT_SERVERS[0]
        xeon = DEFAULT_SERVERS[2]

        # Same tokens on H100 vs Xeon
        t_gpu = calculate_execution_duration(h100, context_tokens=1000, output_tokens=200, current_active_streams=1)
        t_cpu = calculate_execution_duration(xeon, context_tokens=1000, output_tokens=200, current_active_streams=1)

        # GPU must execute faster than CPU
        self.assertLess(t_gpu, t_cpu)
        self.assertGreater(t_gpu, 0.0)

    def test_dispatch_and_execution_step(self):
        task = ExecutionTask(
            request_id="req_test_001",
            user_id="usr_01",
            workload_type="TEXT_CHAT",
            context_tokens=128,
            max_output_tokens=32,
            deadline_slo_ms=2000,
            priority_level="P1_INTERACTIVE",
            arrival_time=0.0,
        )

        ok = self.vdc.dispatch_to_server("srv_gpu_01", task)
        self.assertTrue(ok)
        self.assertEqual(len(self.vdc.servers["srv_gpu_01"].active_streams), 1)

        # Step forward until completed
        completed = []
        for _ in range(50):
            completed.extend(self.vdc.step(dt=0.1))

        self.assertEqual(len(completed), 1)
        evt = completed[0]
        self.assertEqual(evt.request_id, "req_test_001")
        self.assertTrue(evt.slo_met)
        self.assertGreater(evt.energy_consumed_joules, 0.0)

    def test_reset_cluster(self):
        task = ExecutionTask(
            request_id="req_test_002",
            user_id="usr_02",
            workload_type="TEXT_CHAT",
            context_tokens=128,
            max_output_tokens=32,
            deadline_slo_ms=2000,
            priority_level="P1_INTERACTIVE",
            arrival_time=0.0,
        )
        self.vdc.dispatch_to_server("srv_gpu_01", task)
        self.vdc.reset_cluster()

        srv = self.vdc.servers["srv_gpu_01"]
        self.assertEqual(len(srv.active_streams), 0)
        self.assertEqual(len(srv.ingress_queue), 0)
        self.assertEqual(srv.status, ServerStatus.IDLE)
        self.assertAlmostEqual(self.vdc.get_cluster_power_w(), 145.0, places=1)


if __name__ == "__main__":
    unittest.main()
