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

    def _make_task(self, request_id, context=128, output=32):
        return ExecutionTask(
            request_id=request_id,
            user_id="usr_test",
            workload_type="TEXT_CHAT",
            context_tokens=context,
            max_output_tokens=output,
            deadline_slo_ms=2000,
            priority_level="P1_INTERACTIVE",
            arrival_time=0.0,
        )

    def test_node_drain_lifecycle(self):
        srv = self.vdc.servers["srv_gpu_01"]

        self.assertTrue(self.vdc.dispatch_to_server("srv_gpu_01", self._make_task("req_drain_01")))
        self.assertTrue(srv.drain())
        self.assertEqual(srv.status, ServerStatus.DRAINING)

        # New assignments are rejected while draining.
        self.assertFalse(self.vdc.dispatch_to_server("srv_gpu_01", self._make_task("req_drain_02")))

        # The in-flight task still completes.
        completed = []
        for _ in range(50):
            completed.extend(self.vdc.step(dt=0.1))
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].request_id, "req_drain_01")

        # Recover the drained node back to IDLE.
        self.assertTrue(srv.recover())
        self.assertEqual(srv.status, ServerStatus.IDLE)

    def test_node_fault_injection_and_recovery(self):
        srv = self.vdc.servers["srv_acc_02"]

        self.assertTrue(self.vdc.dispatch_to_server("srv_acc_02", self._make_task("req_fault_01")))
        self.assertTrue(srv.set_offline())
        self.assertEqual(srv.status, ServerStatus.OFFLINE)
        self.assertEqual(len(srv.active_streams), 0)
        self.assertEqual(len(srv.ingress_queue), 0)

        # Offline node rejects new work.
        self.assertFalse(self.vdc.dispatch_to_server("srv_acc_02", self._make_task("req_fault_02")))

        self.assertTrue(srv.recover())
        self.assertEqual(srv.status, ServerStatus.IDLE)

    def test_estimated_queue_wait_telemetry(self):
        srv = self.vdc.servers["srv_cpu_03"]  # 4 stream slots

        # Fill all 4 stream slots, then queue a 5th task.
        for i in range(4):
            self.vdc.dispatch_to_server("srv_cpu_03", self._make_task(f"req_q_{i}"))
        self.vdc.dispatch_to_server("srv_cpu_03", self._make_task("req_q_queued"))

        snap = srv.get_snapshot()
        self.assertEqual(snap.queue_depth, 1)
        self.assertGreater(snap.estimated_queue_wait_ms, 0.0)

        # Idle server (empty queue) reports zero estimated wait.
        self.vdc.reset_cluster()
        self.assertEqual(srv.get_snapshot().estimated_queue_wait_ms, 0.0)


if __name__ == "__main__":
    unittest.main()
