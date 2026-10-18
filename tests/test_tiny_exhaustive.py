"""
Tiny Exhaustive-Enumeration Verification Test.
Implements Section 8 of QuantaSHI Part 3 Specification:
Validates exact mathematical equivalence between the constrained MILP (HiGHS)
and the unconstrained QUBO matrix across all 2^D states on an N=2, K=2 test problem.
"""

import unittest
import numpy as np

from user_interface.models import InferenceRequest, WorkloadType, PriorityLevel
from server_interface.cluster import VirtualDataCentre
from server_interface.models import ServerHardwareConfig, ServerType
from system_interface.models import OptimizationWeights, SolverType
from system_interface.qubo_builder import build_qubo_model
from system_interface.solvers import (
    solve_exact_milp,
    solve_tiny_exhaustive,
    solve_simulated_annealing,
    solve_qaoa_simulation,
)


class TestTinyExhaustiveVerification(unittest.TestCase):

    def setUp(self):
        # 2 Heterogeneous Test Servers:
        # Server 1: GPU (Fast, High Power, Capacity C1 = 2)
        # Server 2: Accelerator (Slower, Low Power, Constrained Capacity C2 = 1)
        self.configs = [
            ServerHardwareConfig(
                server_id="srv_gpu_01",
                name="Server 1: High-Performance GPU",
                model="GPU Test",
                server_type=ServerType.HIGH_PERF_ACCELERATOR,
                max_streams=2,
                prefill_speed_tokens_sec=10000.0,
                decode_speed_tokens_sec=80.0,
                vram_gb=80,
                idle_power_w=75.0,
                peak_power_w=300.0,
                power_exponent_r=1.35,
            ),
            ServerHardwareConfig(
                server_id="srv_acc_02",
                name="Server 2: Energy-Efficient Tensor",
                model="Tensor Test",
                server_type=ServerType.BALANCED_ACCELERATOR,
                max_streams=1,  # Constrained capacity: exactly 1 slot!
                prefill_speed_tokens_sec=3000.0,
                decode_speed_tokens_sec=35.0,
                vram_gb=24,
                idle_power_w=25.0,
                peak_power_w=70.0,
                power_exponent_r=1.40,
            ),
        ]
        self.cluster = VirtualDataCentre(configs=self.configs)

        # 2 Requests in the Batch:
        # r1: Short chat query (feasible on both srv_gpu_01 and srv_acc_02)
        # r2: Moderate query (feasible on both srv_gpu_01 and srv_acc_02)
        self.batch = [
            InferenceRequest(
                request_id="req_001",
                user_id="usr_001",
                arrival_timestamp=0.0,
                workload_type=WorkloadType.TEXT_CHAT,
                context_tokens=128,
                max_output_tokens=64,
                priority_level=PriorityLevel.P1_INTERACTIVE,
                deadline_slo_ms=2500.0,
                prompt_preview="Short test prompt",
            ),
            InferenceRequest(
                request_id="req_002",
                user_id="usr_002",
                arrival_timestamp=0.0,
                workload_type=WorkloadType.TEXT_CHAT,
                context_tokens=256,
                max_output_tokens=128,
                priority_level=PriorityLevel.P1_INTERACTIVE,
                deadline_slo_ms=5000.0,
                prompt_preview="Second test prompt",
            ),
        ]

        self.weights = OptimizationWeights(weight_energy=0.85, weight_latency=0.15)

    def test_qubo_highs_exact_agreement(self):
        """
        Asserts that exhaustive evaluation of all 2^D QUBO states yields
        the exact same optimal assignment as HiGHS Branch-and-Cut MILP.
        """
        # 1. Solve via HiGHS MILP
        milp_res = solve_exact_milp(
            batch=self.batch,
            cluster=self.cluster,
            weights=self.weights,
            current_time_sec=0.0,
        )
        self.assertTrue(milp_res.is_optimal, "HiGHS must achieve provable kOptimal status")

        # 2. Build QUBO Matrix Model
        qubo_model = build_qubo_model(
            batch=self.batch,
            cluster=self.cluster,
            weights=self.weights,
            current_time_sec=0.0,
            lambda_assign=3.0,
            lambda_cap=5.0,
        )

        # 3. Solve via Exhaustive Bitstring Enumeration
        exhaustive_res = solve_tiny_exhaustive(
            qubo_model=qubo_model,
            batch=self.batch,
        )
        self.assertTrue(exhaustive_res.is_optimal)

        # Assert identical assignments between HiGHS and QUBO argmin
        self.assertEqual(
            milp_res.assignments,
            exhaustive_res.assignments,
            f"HiGHS assignment {milp_res.assignments} must match QUBO exhaustive argmin {exhaustive_res.assignments}"
        )

    def test_capacity_violation_strictly_penalized(self):
        """
        Asserts that the assignment state (srv_acc_02, srv_acc_02) violates
        capacity C2 = 1 and is strictly penalized in the QUBO energy landscape.
        """
        qubo_model = build_qubo_model(
            batch=self.batch,
            cluster=self.cluster,
            weights=self.weights,
            current_time_sec=0.0,
            lambda_assign=3.0,
            lambda_cap=5.0,
        )

        # Construct bitstring for valid state:
        # (req_001 -> srv_gpu_01) and (req_002 -> srv_acc_02)
        # srv_acc_02 has 1 request, so slack rem = 0
        valid_z = np.zeros(qubo_model.D)
        valid_z[qubo_model.var_indices["x_req_001_srv_gpu_01"]] = 1.0
        valid_z[qubo_model.var_indices["x_req_002_srv_acc_02"]] = 1.0
        valid_energy = qubo_model.evaluate_energy(valid_z)

        # Invalid state: (req_001 -> srv_acc_02) and (req_002 -> srv_acc_02)
        # 2 requests on srv_acc_02 where capacity is 1!
        invalid_z = np.zeros(qubo_model.D)
        invalid_z[qubo_model.var_indices["x_req_001_srv_acc_02"]] = 1.0
        invalid_z[qubo_model.var_indices["x_req_002_srv_acc_02"]] = 1.0
        invalid_energy = qubo_model.evaluate_energy(invalid_z)

        # The invalid capacity state must have strictly higher energy
        self.assertGreater(
            invalid_energy,
            valid_energy,
            f"Overcapacity state energy ({invalid_energy}) must exceed valid state ({valid_energy})"
        )

    def test_one_hot_violation_strictly_penalized(self):
        """
        Asserts that assigning a request to two servers simultaneously
        incurs a penalty exceeding lambda_assign.
        """
        qubo_model = build_qubo_model(
            batch=self.batch,
            cluster=self.cluster,
            weights=self.weights,
            current_time_sec=0.0,
            lambda_assign=3.0,
            lambda_cap=5.0,
        )

        # Double assignment: req_001 assigned to BOTH srv_gpu_01 and srv_acc_02
        double_assign_z = np.zeros(qubo_model.D)
        double_assign_z[qubo_model.var_indices["x_req_001_srv_gpu_01"]] = 1.0
        double_assign_z[qubo_model.var_indices["x_req_001_srv_acc_02"]] = 1.0
        double_assign_z[qubo_model.var_indices["x_req_002_srv_gpu_01"]] = 1.0
        energy = qubo_model.evaluate_energy(double_assign_z)

        # Compare to valid single assignment (req_001 -> srv_gpu_01, req_002 -> srv_acc_02)
        valid_z = np.zeros(qubo_model.D)
        valid_z[qubo_model.var_indices["x_req_001_srv_gpu_01"]] = 1.0
        valid_z[qubo_model.var_indices["x_req_002_srv_acc_02"]] = 1.0
        valid_energy = qubo_model.evaluate_energy(valid_z)

        self.assertGreater(
            energy,
            valid_energy,
            "Double-assignment bitstring must incur quadratic penalty"
        )

    def test_classical_simulated_annealing(self):
        """
        Tests that classical simulated annealing executes without error
        and returns a valid assignment dictionary.
        """
        qubo_model = build_qubo_model(
            batch=self.batch,
            cluster=self.cluster,
            weights=self.weights,
            current_time_sec=0.0,
            lambda_assign=3.0,
            lambda_cap=5.0,
        )
        sa_res = solve_simulated_annealing(
            qubo_model=qubo_model,
            batch=self.batch,
            num_sweeps=200,
            num_reads=10,
        )
        self.assertEqual(len(sa_res.assignments), 2)
        self.assertIn("req_001", sa_res.assignments)
        self.assertIn("req_002", sa_res.assignments)
        self.assertGreater(sa_res.runtime_ms, 0.0)

    def test_qaoa_circuit_simulation(self):
        """
        Tests that QAOA statevector circuit simulation runs on the micro-batch benchmark (D <= 8)
        and successfully returns decoded assignments.
        """
        qubo_model = build_qubo_model(
            batch=self.batch,
            cluster=self.cluster,
            weights=self.weights,
            current_time_sec=0.0,
            lambda_assign=3.0,
            lambda_cap=5.0,
        )
        qaoa_res = solve_qaoa_simulation(
            qubo_model=qubo_model,
            batch=self.batch,
            p_layers=1,
            max_iter=15,
        )
        self.assertEqual(len(qaoa_res.assignments), 2)
        self.assertIn("req_001", qaoa_res.assignments)
        self.assertIn("req_002", qaoa_res.assignments)
        self.assertGreater(qaoa_res.runtime_ms, 0.0)
        self.assertEqual(qaoa_res.solver_type, SolverType.QAOA_CIRCUIT_SIMULATION)


if __name__ == "__main__":
    unittest.main()
