"""
Data models for Part 3: System (Decision Engine & Optimization Layer).
Defines routing policies, dispatch decisions, optimization weights, feasibility results, and explainability schemas.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Dict, List, Optional, Any
import time


class RoutingPolicy(str, Enum):
    ENERGY_OPTIMIZED = "ENERGY_OPTIMIZED"
    LATENCY_FIRST = "LATENCY_FIRST"
    BALANCED_PARETO = "BALANCED_PARETO"
    ROUND_ROBIN = "ROUND_ROBIN"


class DecisionAction(str, Enum):
    DISPATCH_IMMEDIATE = "DISPATCH_IMMEDIATE"
    ENQUEUE = "ENQUEUE"
    DEFER = "DEFER"
    REJECT = "REJECT"


class SolverType(str, Enum):
    EXACT_MILP_HIGHS = "EXACT_MILP_HIGHS"
    CLASSICAL_SIMULATED_ANNEALING = "CLASSICAL_SIMULATED_ANNEALING"
    GREEDY_FALLBACK_GESF = "GREEDY_FALLBACK_GESF"
    TINY_EXHAUSTIVE_SEARCH = "TINY_EXHAUSTIVE_SEARCH"
    QAOA_CIRCUIT_SIMULATION = "QAOA_CIRCUIT_SIMULATION"


@dataclass
class OptimizationWeights:
    weight_energy: float = 0.50
    weight_latency: float = 0.50

    def validate(self):
        total = self.weight_energy + self.weight_latency
        if total <= 0:
            self.weight_energy = 0.5
            self.weight_latency = 0.5
        else:
            self.weight_energy /= total
            self.weight_latency /= total


@dataclass
class FeasibleServerEvaluation:
    server_id: str
    t_prefill_ms: float
    t_decode_ms: float
    t_exec_ms: float
    t_wait_ms: float
    t_turnaround_ms: float
    deadline_slo_ms: float
    slack_ms: float
    marginal_power_w: float
    marginal_energy_j: float
    is_feasible: bool
    rejection_reason: Optional[str] = None


@dataclass
class RequestFeasibilityProfile:
    request_id: str
    user_id: str
    feasible_servers: Dict[str, FeasibleServerEvaluation] = field(default_factory=dict)
    can_defer: bool = False
    must_reject: bool = False
    rejection_reason: Optional[str] = None


@dataclass
class DispatchDecision:
    decision_id: str
    request_id: str
    user_id: str
    selected_server_id: Optional[str]
    action: DecisionAction
    policy: RoutingPolicy
    predicted_exec_ms: float
    predicted_wait_ms: float
    predicted_total_turnaround_ms: float
    deadline_slo_ms: float
    deadline_headroom_ms: float
    predicted_energy_joules: float
    solver_provenance: SolverType
    solver_runtime_ms: float
    fallback_triggered: bool = False
    candidate_scores: Dict[str, float] = field(default_factory=dict)
    rejected_alternatives: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "request_id": self.request_id,
            "user_id": self.user_id,
            "selected_server_id": self.selected_server_id,
            "action": self.action.value,
            "policy": self.policy.value,
            "predicted_exec_ms": round(self.predicted_exec_ms, 2),
            "predicted_wait_ms": round(self.predicted_wait_ms, 2),
            "predicted_total_turnaround_ms": round(self.predicted_total_turnaround_ms, 2),
            "deadline_slo_ms": round(self.deadline_slo_ms, 2),
            "deadline_headroom_ms": round(self.deadline_headroom_ms, 2),
            "predicted_energy_joules": round(self.predicted_energy_joules, 2),
            "solver_provenance": self.solver_provenance.value,
            "solver_runtime_ms": round(self.solver_runtime_ms, 3),
            "fallback_triggered": self.fallback_triggered,
            "candidate_scores": {k: round(v, 4) for k, v in self.candidate_scores.items()},
            "rejected_alternatives": self.rejected_alternatives,
            "timestamp": self.timestamp,
        }


@dataclass
class SystemMetrics:
    total_dispatched: int = 0
    total_deferred: int = 0
    total_rejected: int = 0
    total_fallbacks: int = 0
    total_energy_saved_pct: float = 0.0
    sla_compliance_rate_pct: float = 100.0
    active_policy: RoutingPolicy = RoutingPolicy.BALANCED_PARETO
