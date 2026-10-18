"""Authoritative event-driven simulation for the QuantaSHI live demo.

The browser never invents load, energy, or decisions.  It reads snapshots from
this module, which advances the workload generator, scheduler and virtual data
centre on one simulation clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any, Dict, List, Optional

from server_interface.cluster import VirtualDataCentre
from server_interface.models import CompletionEvent
from system_interface.models import DecisionAction, RoutingPolicy, SolverType
from system_interface.scheduler import QuantaSHIScheduler
from user_interface.generator import SimulationScenario, WorkloadGenerator
from user_interface.models import InferenceRequest


FINAL_STATUSES = {"COMPLETED", "REJECTED"}


@dataclass
class RequestLifecycle:
    request: InferenceRequest
    status: str = "GENERATED"
    selected_server_id: Optional[str] = None
    decision: Optional[Dict[str, Any]] = None
    completion: Optional[Dict[str, Any]] = None
    defer_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        payload = self.request.to_dict()
        payload.update({
            "status": self.status,
            "selected_server_id": self.selected_server_id,
            "decision": self.decision,
            "completion": self.completion,
            "defer_count": self.defer_count,
        })
        return payload


class SimulationTrack:
    """One scheduler/cluster run over a shared synthetic trace."""

    def __init__(self, label: str, policy: RoutingPolicy, solver: SolverType):
        self.label = label
        self.cluster = VirtualDataCentre()
        self.scheduler = QuantaSHIScheduler(self.cluster, policy=policy, solver_type=solver)
        self.records: Dict[str, RequestLifecycle] = {}
        self.deferred: List[tuple[float, str]] = []
        self.completions: List[CompletionEvent] = []
        self.events: List[Dict[str, Any]] = []

    def _event(self, timestamp: float, kind: str, message: str, **details: Any) -> None:
        self.events.append({"timestamp": round(timestamp, 3), "kind": kind, "message": message, **details})
        del self.events[:-150]

    def submit(self, req: InferenceRequest, timestamp: float, is_retry: bool = False) -> None:
        record = self.records.setdefault(req.request_id, RequestLifecycle(request=req))
        decision = self.scheduler.route_request(req)
        record.decision = decision.to_dict()
        record.selected_server_id = decision.selected_server_id

        if decision.action == DecisionAction.DISPATCH_IMMEDIATE:
            record.status = "PROCESSING"
        elif decision.action == DecisionAction.ENQUEUE:
            record.status = "QUEUED"
        elif decision.action == DecisionAction.DEFER:
            record.status = "DEFERRED"
            record.defer_count += 1
            # A deferred request remains visible and is re-evaluated shortly.
            self.deferred.append((timestamp + 0.25, req.request_id))
        else:
            record.status = "REJECTED"

        verb = "re-evaluated" if is_retry else "arrived"
        self._event(
            timestamp,
            decision.action.value,
            f"{req.request_id[:8]} {verb}: {decision.action.value.replace('_', ' ').lower()}",
            request_id=req.request_id,
            server_id=decision.selected_server_id,
            policy=self.scheduler.policy.value,
        )

    def advance_to(self, target_time: float) -> None:
        if target_time < self.cluster.clock:
            raise ValueError("Simulation time cannot move backwards")
        completions = self.cluster.step(target_time - self.cluster.clock)
        for completion in completions:
            self.completions.append(completion)
            record = self.records.get(completion.request_id)
            if record:
                record.status = "COMPLETED"
                record.completion = completion.to_dict()
            self._event(
                target_time,
                "COMPLETED",
                f"{completion.request_id[:8]} completed on {completion.server_id}",
                request_id=completion.request_id,
                server_id=completion.server_id,
                slo_met=completion.slo_met,
            )

        due, waiting = [], []
        for due_at, request_id in self.deferred:
            (due if due_at <= target_time else waiting).append((due_at, request_id))
        self.deferred = waiting
        for _, request_id in due:
            record = self.records.get(request_id)
            if record and record.status == "DEFERRED":
                self.submit(record.request, target_time, is_retry=True)

    def is_idle(self) -> bool:
        return not self.deferred and all(
            not server.active_streams and not server.ingress_queue
            for server in self.cluster.servers.values()
        )

    def _metrics(self) -> Dict[str, Any]:
        records = list(self.records.values())
        completed = [record for record in records if record.status == "COMPLETED"]
        rejected = [record for record in records if record.status == "REJECTED"]
        queued = [record for record in records if record.status == "QUEUED"]
        deferred = [record for record in records if record.status == "DEFERRED"]
        latencies = sorted(
            record.completion["total_turnaround_ms"] for record in completed if record.completion
        )
        deadline_misses = sum(
            1 for record in completed if record.completion and not record.completion["slo_met"]
        )
        p95 = latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))] if latencies else 0.0
        energy_j = sum(server.cumulative_energy_joules for server in self.cluster.servers.values())
        on_time_completed = [record for record in completed if record.completion and record.completion.get("slo_met")]
        return {
            "generated": len(records), "completed": len(completed), "rejected": len(rejected),
            "deferred_current": len(deferred), "queued_current": len(queued),
            "processing_current": sum(1 for record in records if record.status == "PROCESSING"),
            "throughput_rps": round(len(completed) / max(self.cluster.clock, 0.001), 3),
            "avg_turnaround_ms": round(mean(latencies), 2) if latencies else 0.0,
            "p95_turnaround_ms": round(p95, 2),
            "deadline_miss_rate_pct": round(100 * deadline_misses / len(completed), 2) if completed else 0.0,
            "estimated_total_energy_j": round(energy_j, 2),
            "estimated_energy_per_completed_j": round(energy_j / len(completed), 2) if completed else 0.0,
            "estimated_energy_per_ontime_j": round(energy_j / len(on_time_completed), 2) if on_time_completed else 0.0,
            "decision_counts": {
                "dispatch": self.scheduler.total_dispatched,
                "defer": self.scheduler.total_deferred,
                "reject": self.scheduler.total_rejected,
                "fallback": self.scheduler.total_fallbacks,
            },
        }

    def snapshot(self) -> Dict[str, Any]:
        servers = []
        for server_id, server in self.cluster.servers.items():
            telemetry = server.get_snapshot()
            servers.append({
                "server_id": server_id, "name": server.config.name, "model": server.config.model,
                "type": server.config.server_type.value, "max_streams": server.config.max_streams,
                "idle_power_w": server.config.idle_power_w, "peak_power_w": server.config.peak_power_w,
                "status": telemetry.status.value, "active_streams": telemetry.active_streams_count,
                "queue_depth": telemetry.queue_depth, "utilization_pct": telemetry.stream_utilization_pct,
                "current_power_w": telemetry.current_power_w,
                "cumulative_energy_j": telemetry.cumulative_energy_joules,
                "completed": telemetry.completed_tasks_count,
                "slo_violations": telemetry.slo_violations_count,
            })
        newest_records = sorted(self.records.values(), key=lambda item: item.request.arrival_timestamp, reverse=True)
        return {
            "label": self.label, "policy": self.scheduler.policy.value,
            "metrics": self._metrics(), "servers": servers,
            "recent_events": list(reversed(self.events[-25:])),
            "recent_requests": [record.to_dict() for record in newest_records[:20]],
            "recent_decisions": [decision.to_dict() for decision in self.scheduler.decisions_history[:20]],
        }


class SimulationSession:
    """Coordinates matched QuantaSHI and round-robin experiments."""

    def __init__(self, seed: int = 42, scenario: SimulationScenario = SimulationScenario.SCENARIO_2_FLASH_BURST,
                 duration_seconds: float = 60.0, speed: float = 4.0):
        self.seed = seed
        self.scenario = scenario
        self.duration_seconds = duration_seconds
        self.speed = speed
        self.status = "READY"
        self.trace: List[InferenceRequest] = []
        self.trace_index = 0
        self.primary: SimulationTrack
        self.baseline: SimulationTrack
        self.reset(seed=seed, scenario=scenario, duration_seconds=duration_seconds, speed=speed)

    def reset(self, seed: Optional[int] = None, scenario: Optional[SimulationScenario | str] = None,
              duration_seconds: Optional[float] = None, speed: Optional[float] = None) -> None:
        if seed is not None:
            self.seed = int(seed)
        if scenario is not None:
            self.scenario = SimulationScenario(scenario)
        if duration_seconds is not None:
            self.duration_seconds = float(duration_seconds)
        if speed is not None:
            self.speed = float(speed)
        generator = WorkloadGenerator(seed=self.seed)
        self.trace = generator.generate_trace(self.duration_seconds, self.scenario)
        # Keep the 100-person synthetic population available to the unified UI.
        # Runtime activity is derived from the authoritative lifecycle ledger,
        # rather than the generator's precomputed trace-generation state.
        self.user_catalog = {
            user_id: {"user_id": user_id, "label": user.label, "tier": user.tier.value}
            for user_id, user in generator.topology.users.items()
        }
        self.trace_index = 0
        self.primary = SimulationTrack("QuantaSHI", RoutingPolicy.BALANCED_PARETO, SolverType.EXACT_MILP_HIGHS)
        self.baseline = SimulationTrack("Round robin baseline", RoutingPolicy.ROUND_ROBIN, SolverType.GREEDY_FALLBACK_GESF)
        self.status = "READY"

    @property
    def clock(self) -> float:
        return self.primary.cluster.clock

    def start(self) -> None:
        if self.status in ("READY", "PAUSED"):
            self.status = "RUNNING"

    def pause(self) -> None:
        if self.status == "RUNNING":
            self.status = "PAUSED"

    def advance(self, delta_seconds: float) -> None:
        if self.status != "RUNNING" or delta_seconds <= 0:
            return
        target = self.clock + delta_seconds
        while self.trace_index < len(self.trace) and self.trace[self.trace_index].arrival_timestamp <= target:
            request = self.trace[self.trace_index]
            self.primary.advance_to(request.arrival_timestamp)
            self.baseline.advance_to(request.arrival_timestamp)
            self.primary.submit(request, request.arrival_timestamp)
            self.baseline.submit(request, request.arrival_timestamp)
            self.trace_index += 1
        self.primary.advance_to(target)
        self.baseline.advance_to(target)
        if self.trace_index == len(self.trace) and self.primary.is_idle() and self.baseline.is_idle():
            self.status = "COMPLETED"

    def snapshot(self) -> Dict[str, Any]:
        primary = self.primary.snapshot()
        baseline = self.baseline.snapshot()
        p_energy = primary["metrics"]["estimated_total_energy_j"]
        b_energy = baseline["metrics"]["estimated_total_energy_j"]
        comparison = {
            "same_seed": self.seed, "same_trace_requests": len(self.trace),
            "energy_delta_j": round(b_energy - p_energy, 2),
            "energy_delta_pct": round((b_energy - p_energy) * 100 / b_energy, 2) if b_energy else 0.0,
            "note": "Estimated simulation energy, not a physical measurement.",
        }
        requests_by_user: Dict[str, List[RequestLifecycle]] = {
            user_id: [] for user_id in self.user_catalog
        }
        for record in self.primary.records.values():
            requests_by_user.setdefault(record.request.user_id, []).append(record)
        user_rows = []
        for user_id, user in self.user_catalog.items():
            records = requests_by_user.get(user_id, [])
            active = sum(1 for record in records if record.status not in FINAL_STATUSES)
            user_rows.append({
                **user,
                "requests_generated": len(records),
                "active_requests": active,
                "status": "AWAITING_RESPONSE" if active else "IDLE",
            })
        user_rows.sort(key=lambda user: (-user["active_requests"], -user["requests_generated"], user["user_id"]))
        synthetic_users = {
            "population": len(self.user_catalog),
            "active_users": sum(1 for user in user_rows if user["active_requests"]),
            "users_with_requests": sum(1 for user in user_rows if user["requests_generated"]),
            "top_active": user_rows[:20],
        }
        return {
            "status": self.status, "clock_seconds": round(self.clock, 3), "speed": self.speed,
            "scenario": self.scenario.value, "seed": self.seed, "trace_total": len(self.trace),
            "trace_delivered": self.trace_index, "primary": primary, "baseline": baseline,
            "comparison": comparison, "synthetic_users": synthetic_users,
            "assumptions": "Synthetic users and modeled hardware/power parameters. Energy is estimated from the configured model.",
        }

    def get_audit_records(self) -> List[Dict[str, Any]]:
        """Returns comprehensive decision audit trail for FinOps and SRE governance."""
        records = []
        for record in self.primary.records.values():
            dec = record.decision or {}
            comp = record.completion or {}
            records.append({
                "request_id": record.request.request_id,
                "user_id": record.request.user_id,
                "arrival_timestamp": round(record.request.arrival_timestamp, 3),
                "workload_type": record.request.workload_type.value,
                "context_tokens": record.request.context_tokens,
                "max_output_tokens": record.request.max_output_tokens,
                "deadline_slo_ms": record.request.deadline_slo_ms,
                "status": record.status,
                "selected_server_id": record.selected_server_id or "NONE",
                "action": dec.get("action", "UNKNOWN"),
                "solver_provenance": dec.get("solver_provenance", "UNKNOWN"),
                "solver_runtime_ms": dec.get("solver_runtime_ms", 0.0),
                "predicted_energy_joules": dec.get("predicted_energy_joules", 0.0),
                "predicted_turnaround_ms": dec.get("predicted_total_turnaround_ms", 0.0),
                "deadline_headroom_ms": dec.get("deadline_headroom_ms", 0.0),
                "candidate_scores": dec.get("candidate_scores", {}),
                "rejected_alternatives": dec.get("rejected_alternatives", []),
                "completed_turnaround_ms": comp.get("total_turnaround_ms"),
                "slo_met": comp.get("slo_met"),
            })
        records.sort(key=lambda r: r["arrival_timestamp"])
        return records

