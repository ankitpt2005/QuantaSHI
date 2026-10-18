"""
Multi-objective optimization solver for QuantaSHI Decision Engine.
Evaluates Pareto trade-off between marginal server energy and execution turnaround latency,
interfacing with HiGHS exact classical MILP, classical simulated annealing, and GESF fallback.
"""

from __future__ import annotations
import uuid
import time
from typing import Dict, List, Optional, Tuple, Any

from server_interface.cluster import VirtualDataCentre
from user_interface.models import InferenceRequest, PriorityLevel, WorkloadType

from .models import RoutingPolicy, OptimizationWeights, DispatchDecision, DecisionAction, SolverType
from .feasibility import prefilter_request_feasibility, FeasibleServerEvaluation
from .qubo_builder import build_qubo_model
from .solvers import (
    solve_exact_milp,
    solve_simulated_annealing,
    solve_greedy_fallback,
    solve_tiny_exhaustive,
    solve_qaoa_simulation,
)


class QuantaSHIOptimizer:
    """Evaluates heterogeneous servers and scores dispatch candidates."""

    def __init__(
        self,
        policy: RoutingPolicy = RoutingPolicy.BALANCED_PARETO,
        solver_type: SolverType = SolverType.EXACT_MILP_HIGHS,
    ):
        self.policy = policy
        self.solver_type = solver_type
        self.weights = self._weights_for_policy(policy)

    def set_policy(self, policy: RoutingPolicy):
        self.policy = policy
        self.weights = self._weights_for_policy(policy)

    def _weights_for_policy(self, policy: RoutingPolicy) -> OptimizationWeights:
        if policy == RoutingPolicy.ENERGY_OPTIMIZED:
            return OptimizationWeights(weight_energy=0.85, weight_latency=0.15)
        elif policy == RoutingPolicy.LATENCY_FIRST:
            return OptimizationWeights(weight_energy=0.10, weight_latency=0.90)
        elif policy == RoutingPolicy.BALANCED_PARETO:
            return OptimizationWeights(weight_energy=0.50, weight_latency=0.50)
        else:
            return OptimizationWeights(weight_energy=0.50, weight_latency=0.50)

    def evaluate_request(
        self,
        req: InferenceRequest,
        cluster: VirtualDataCentre,
        current_time_sec: float = 0.0,
    ) -> DispatchDecision:
        """Evaluates a single request and returns a complete DispatchDecision."""
        decisions = self.evaluate_batch([req], cluster, current_time_sec=current_time_sec)
        return decisions[0]

    def evaluate_batch(
        self,
        batch: List[InferenceRequest],
        cluster: VirtualDataCentre,
        current_time_sec: float = 0.0,
    ) -> List[DispatchDecision]:
        """
        Evaluates a batch of requests against the cluster state.
        Adheres to Stages 2-5 of Part 3 Specification:
        Stage 2: Deterministic Feasibility Pre-Filter
        Stage 3-4: Solver execution (HiGHS MILP, SA, or GESF fallback)
        Stage 5: Constraint validation and decision assembly
        """
        if not batch:
            return []

        now = current_time_sec if current_time_sec > 0.0 else (batch[0].arrival_timestamp if batch else 0.0)
        decisions: List[DispatchDecision] = []

        # Handle ROUND_ROBIN policy explicitly
        if self.policy == RoutingPolicy.ROUND_ROBIN:
            available_servers = [
                sid for sid, s in cluster.servers.items()
                if s.status.value not in ("OFFLINE", "DRAINING")
            ]
            if not available_servers:
                available_servers = list(cluster.servers.keys())

            for i, req in enumerate(batch):
                chosen_server = available_servers[i % len(available_servers)]
                server = cluster.servers.get(chosen_server)
                action = (
                    DecisionAction.DISPATCH_IMMEDIATE
                    if server and len(server.active_streams) < server.config.max_streams
                    else DecisionAction.ENQUEUE
                )
                decisions.append(
                    DispatchDecision(
                        decision_id=f"dec_{uuid.uuid4().hex[:8]}",
                        request_id=req.request_id,
                        user_id=req.user_id,
                        selected_server_id=chosen_server,
                        action=action,
                        policy=self.policy,
                        predicted_exec_ms=150.0,
                        predicted_wait_ms=0.0,
                        predicted_total_turnaround_ms=150.0,
                        deadline_slo_ms=req.deadline_slo_ms,
                        deadline_headroom_ms=max(0.0, req.deadline_slo_ms - 150.0),
                        predicted_energy_joules=15.0,
                        solver_provenance=SolverType.GREEDY_FALLBACK_GESF,
                        solver_runtime_ms=0.05,
                        fallback_triggered=False,
                    )
                )
            return decisions

        # Stage 2: Feasibility Pre-Filtering
        profiles = {
            req.request_id: prefilter_request_feasibility(
                req=req,
                cluster=cluster,
                current_time_sec=now,
            )
            for req in batch
        }

        admissible_reqs: List[InferenceRequest] = []
        for req in batch:
            prof = profiles[req.request_id]
            if prof.must_reject:
                # Immediate REJECT (HTTP 429/504)
                decisions.append(
                    DispatchDecision(
                        decision_id=f"dec_{uuid.uuid4().hex[:8]}",
                        request_id=req.request_id,
                        user_id=req.user_id,
                        selected_server_id=None,
                        action=DecisionAction.REJECT,
                        policy=self.policy,
                        predicted_exec_ms=0.0,
                        predicted_wait_ms=0.0,
                        predicted_total_turnaround_ms=0.0,
                        deadline_slo_ms=req.deadline_slo_ms,
                        deadline_headroom_ms=-1.0,
                        predicted_energy_joules=0.0,
                        solver_provenance=self.solver_type,
                        solver_runtime_ms=0.0,
                        fallback_triggered=False,
                        candidate_scores={},
                        rejected_alternatives=[
                            {"reason": prof.rejection_reason or "Deadline cannot be met on any operational node"}
                        ],
                    )
                )
            else:
                admissible_reqs.append(req)

        if not admissible_reqs:
            return decisions

        # Stage 3 & 4: Solve for Admissible Requests
        fallback_needed = False
        solver_res = None

        try:
            if self.solver_type == SolverType.EXACT_MILP_HIGHS:
                solver_res = solve_exact_milp(admissible_reqs, cluster, self.weights, now)
                if not solver_res.is_optimal:
                    fallback_needed = True
            elif self.solver_type == SolverType.CLASSICAL_SIMULATED_ANNEALING:
                qubo_model = build_qubo_model(admissible_reqs, cluster, self.weights, now)
                solver_res = solve_simulated_annealing(qubo_model, admissible_reqs)
            elif self.solver_type == SolverType.TINY_EXHAUSTIVE_SEARCH:
                qubo_model = build_qubo_model(admissible_reqs, cluster, self.weights, now)
                solver_res = solve_tiny_exhaustive(qubo_model, admissible_reqs)
            elif self.solver_type == SolverType.QAOA_CIRCUIT_SIMULATION:
                qubo_model = build_qubo_model(admissible_reqs, cluster, self.weights, now)
                solver_res = solve_qaoa_simulation(qubo_model, admissible_reqs)
            else:
                solver_res = solve_greedy_fallback(admissible_reqs, cluster, self.weights, now)
        except Exception:
            fallback_needed = True

        if fallback_needed or solver_res is None:
            solver_res = solve_greedy_fallback(admissible_reqs, cluster, self.weights, now)
            solver_res.fallback_triggered = True

        # Assemble Decisions
        for req in admissible_reqs:
            chosen = solver_res.assignments.get(req.request_id, "DEFER")
            prof = profiles[req.request_id]

            if chosen == "DEFER":
                action = DecisionAction.DEFER
                selected_server_id = None
                p_exec = 0.0
                p_wait = 0.0
                p_total = 0.0
                headroom = req.deadline_slo_ms
                energy_j = 0.0
            else:
                selected_server_id = chosen
                server = cluster.servers.get(chosen)
                if server and len(server.active_streams) < server.config.max_streams:
                    action = DecisionAction.DISPATCH_IMMEDIATE
                else:
                    action = DecisionAction.ENQUEUE

                if chosen in prof.feasible_servers:
                    eval_res = prof.feasible_servers[chosen]
                    p_exec = eval_res.t_exec_ms
                    p_wait = eval_res.t_wait_ms
                    p_total = eval_res.t_turnaround_ms
                    headroom = eval_res.slack_ms
                    energy_j = eval_res.marginal_energy_j
                else:
                    p_exec = 100.0
                    p_wait = 0.0
                    p_total = 100.0
                    headroom = max(0.0, req.deadline_slo_ms - 100.0)
                    energy_j = 10.0

            scores = {}
            for sid, eval_s in prof.feasible_servers.items():
                e_norm = min(1.0, eval_s.marginal_energy_j / 100.0)
                l_norm = min(1.0, eval_s.t_turnaround_ms / req.deadline_slo_ms)
                scores[sid] = (self.weights.weight_energy * e_norm) + (self.weights.weight_latency * l_norm)

            rejected_alternatives = []
            for sid, eval_s in prof.feasible_servers.items():
                if sid == selected_server_id:
                    continue
                rejected_alternatives.append({
                    "server_id": sid,
                    "reason": "Feasible candidate not selected by the policy solution",
                    "predicted_turnaround_ms": round(eval_s.t_turnaround_ms, 2),
                    "marginal_energy_j": round(eval_s.marginal_energy_j, 2),
                    "weighted_score": round(scores[sid], 4),
                })
            if action == DecisionAction.DEFER:
                rejected_alternatives.append({
                    "reason": "Solver deferred this flexible request; it remains in the lifecycle and will be re-evaluated."
                })

            decisions.append(
                DispatchDecision(
                    decision_id=f"dec_{uuid.uuid4().hex[:8]}",
                    request_id=req.request_id,
                    user_id=req.user_id,
                    selected_server_id=selected_server_id,
                    action=action,
                    policy=self.policy,
                    predicted_exec_ms=p_exec,
                    predicted_wait_ms=p_wait,
                    predicted_total_turnaround_ms=p_total,
                    deadline_slo_ms=req.deadline_slo_ms,
                    deadline_headroom_ms=headroom,
                    predicted_energy_joules=energy_j,
                    solver_provenance=solver_res.solver_type,
                    solver_runtime_ms=solver_res.runtime_ms,
                    fallback_triggered=getattr(solver_res, "fallback_triggered", False),
                    candidate_scores=scores,
                    rejected_alternatives=rejected_alternatives,
                )
            )

        return decisions

    def evaluate(
        self,
        request_id: str,
        context_tokens: int,
        output_tokens: int,
        deadline_slo_ms: int | float,
        cluster: VirtualDataCentre,
        user_id: str = "usr_001",
    ) -> DispatchDecision:
        """Backwards compatibility wrapper for evaluating raw token parameters."""
        req = InferenceRequest(
            request_id=request_id,
            user_id=user_id,
            arrival_timestamp=time.time(),
            workload_type=WorkloadType.TEXT_CHAT,
            context_tokens=context_tokens,
            max_output_tokens=output_tokens,
            priority_level=PriorityLevel.P1_INTERACTIVE,
            deadline_slo_ms=float(deadline_slo_ms),
            prompt_preview="Request evaluate payload",
        )
        return self.evaluate_request(req, cluster)
