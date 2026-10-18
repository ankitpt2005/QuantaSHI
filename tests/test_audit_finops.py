"""
Unit tests for QuantaSHI Phase 3: Auditable FinOps SRE Engine & Counterfactuals.
Verifies decision record export, pruned alternatives traceability, and Pareto weight adjustments.
"""

import unittest
from simulation_engine import SimulationSession
from user_interface.generator import SimulationScenario
from system_interface.models import RoutingPolicy


class TestFinOpsAudit(unittest.TestCase):

    def setUp(self):
        self.session = SimulationSession(
            scenario=SimulationScenario.SCENARIO_2_FLASH_BURST,
            seed=42,
            duration_seconds=10.0,
            speed=5.0
        )

    def test_audit_records_traceability(self):
        # Start and advance simulation to process requests
        self.session.start()
        self.session.advance(3.0)
        records = self.session.get_audit_records()
        self.assertGreater(len(records), 0, "Audit trail should have recorded decisions")

        sample = records[0]
        # Verify mandatory FinOps audit trail fields
        self.assertIn("request_id", sample)
        self.assertIn("user_id", sample)
        self.assertIn("arrival_timestamp", sample)
        self.assertIn("action", sample)
        self.assertIn("selected_server_id", sample)
        self.assertIn("solver_provenance", sample)
        self.assertIn("solver_runtime_ms", sample)
        self.assertIn("predicted_energy_joules", sample)
        self.assertIn("predicted_turnaround_ms", sample)
        self.assertIn("deadline_headroom_ms", sample)
        self.assertIn("candidate_scores", sample)
        self.assertIn("rejected_alternatives", sample)

        # Verify counterfactual reasoning exists
        if sample["action"] in ("DISPATCH_IMMEDIATE", "ENQUEUE") and sample["selected_server_id"] != "NONE":
            self.assertIsInstance(sample["rejected_alternatives"], list)
            # Should explain why other nodes weren't chosen
            for alt in sample["rejected_alternatives"]:
                if "server_id" in alt:
                    self.assertIn("reason", alt)
                    self.assertIn("marginal_energy_j", alt)
                    self.assertIn("predicted_turnaround_ms", alt)

    def test_pareto_weights_adjustment(self):
        optimizer = self.session.primary.scheduler.optimizer
        # Test switching policy
        optimizer.set_policy(RoutingPolicy.ENERGY_OPTIMIZED)
        self.assertAlmostEqual(optimizer.weights.weight_energy, 0.85)
        self.assertAlmostEqual(optimizer.weights.weight_latency, 0.15)

        # Test custom weights
        optimizer.weights.weight_energy = 0.70
        optimizer.weights.weight_latency = 0.30
        self.assertAlmostEqual(optimizer.weights.weight_energy, 0.70)
        self.assertAlmostEqual(optimizer.weights.weight_latency, 0.30)


if __name__ == "__main__":
    unittest.main()
