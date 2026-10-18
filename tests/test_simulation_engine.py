"""Integration tests for the authoritative end-to-end simulation session."""

import unittest

from simulation_engine import SimulationSession
from user_interface.generator import SimulationScenario


class TestSimulationEngine(unittest.TestCase):
    def _new_session(self):
        return SimulationSession(
            seed=19,
            scenario=SimulationScenario.SCENARIO_1_STEADY_STATE,
            duration_seconds=1.5,
            speed=1.0,
        )

    def test_seed_produces_the_same_workload_trace(self):
        first = self._new_session()
        second = self._new_session()
        first_trace = [(r.request_id, r.user_id, r.arrival_timestamp, r.workload_type, r.context_tokens, r.max_output_tokens) for r in first.trace]
        second_trace = [(r.request_id, r.user_id, r.arrival_timestamp, r.workload_type, r.context_tokens, r.max_output_tokens) for r in second.trace]
        self.assertEqual(first_trace, second_trace)

    def test_every_generated_request_has_a_visible_lifecycle(self):
        session = self._new_session()
        session.start()
        for _ in range(30):
            session.advance(0.1)

        for track in (session.primary, session.baseline):
            self.assertEqual(len(track.records), session.trace_index)
            self.assertTrue(all(record.status for record in track.records.values()))
            for server in track.cluster.servers.values():
                self.assertLessEqual(len(server.active_streams), server.config.max_streams)

    def test_pause_holds_the_shared_simulation_clock(self):
        session = self._new_session()
        session.start()
        session.advance(0.5)
        clock_before_pause = session.clock
        session.pause()
        session.advance(3.0)
        self.assertEqual(session.clock, clock_before_pause)

    def test_metrics_include_ontime_energy(self):
        session = self._new_session()
        session.start()
        for _ in range(20):
            session.advance(0.1)
        snap = session.snapshot()
        primary_metrics = snap["primary"]["metrics"]
        self.assertIn("estimated_energy_per_ontime_j", primary_metrics)
        self.assertIn("estimated_energy_per_completed_j", primary_metrics)
        self.assertIn("deadline_miss_rate_pct", primary_metrics)


if __name__ == "__main__":
    unittest.main()
