"""
Deterministic Feasibility Gate and Physical Latency/Power Predictor.
Implements pre-filtering, joint concurrency recalculation, and deadline verification.
"""

from __future__ import annotations
import math
from typing import Dict, List, Optional, Tuple

from server_interface.cluster import VirtualDataCentre, ServerInstance
from server_interface.models import ServerStatus, ServerHardwareConfig
from server_interface.power_model import calculate_instantaneous_power
from user_interface.models import InferenceRequest

from .models import FeasibleServerEvaluation, RequestFeasibilityProfile


def calculate_two_phase_latency(
    config: ServerHardwareConfig,
    context_tokens: int,
    output_tokens: int,
    concurrency_m: int,
) -> Tuple[float, float, float]:
    """
    Computes two-phase prefill and decode latency in seconds and milliseconds.

    Prefill Phase (Compute bound):
        T_prefill = T_ctx / (R_prefill * (M + 1)^0.15)  [seconds]

    Decode Phase (Memory bandwidth bound with contention factor alpha = 0.04):
        T_decode = (T_out / R_decode) * (1.0 + 0.04 * M)  [seconds]

    Returns:
        (t_prefill_ms, t_decode_ms, t_exec_ms)
    """
    m = max(1, concurrency_m)

    # Prefill phase in seconds
    prefill_eff_speed = config.prefill_speed_tokens_sec * math.pow(m + 1, 0.15)
    t_prefill_s = context_tokens / max(1.0, prefill_eff_speed)

    # Decode phase in seconds
    decode_eff_speed = config.decode_speed_tokens_sec / (1.0 + 0.04 * m)
    t_decode_s = output_tokens / max(0.1, decode_eff_speed)

    t_exec_s = t_prefill_s + t_decode_s

    # Explicit conversion to milliseconds
    t_prefill_ms = t_prefill_s * 1000.0
    t_decode_ms = t_decode_s * 1000.0
    t_exec_ms = t_exec_s * 1000.0

    return t_prefill_ms, t_decode_ms, t_exec_ms


def calculate_marginal_power_and_energy(
    config: ServerHardwareConfig,
    current_active_streams: int,
    t_exec_ms: float,
    status: ServerStatus,
) -> Tuple[float, float]:
    """
    Computes decision-time marginal dynamic power and energy in Joules.
    Excludes baseline chassis idle power to prevent double-counting across streams.

    Returns:
        (marginal_power_w, marginal_energy_j)
    """
    if status in (ServerStatus.OFFLINE, ServerStatus.DRAINING):
        return 0.0, 0.0

    # Current power vs Power with 1 additional stream
    p_curr = calculate_instantaneous_power(config, current_active_streams, status)
    p_new = calculate_instantaneous_power(config, current_active_streams + 1, status)
    marginal_power_w = max(0.0, p_new - p_curr)

    # Energy in Joules = Power (Watts) * Time (seconds)
    t_exec_s = t_exec_ms / 1000.0
    marginal_energy_j = marginal_power_w * t_exec_s

    return marginal_power_w, marginal_energy_j


def evaluate_server_for_request(
    server: ServerInstance,
    req: InferenceRequest,
    current_time_sec: float,
    assigned_in_batch_count: int = 0,
    expected_buffering_ms: float = 0.0,
) -> FeasibleServerEvaluation:
    """
    Evaluates whether server s can feasibly process request req within deadline.
    Accounts for joint batch concurrency and existing queue depth.
    """
    config = server.config
    server_id = config.server_id

    # Check 1: Server operational status
    if server.status in (ServerStatus.OFFLINE, ServerStatus.DRAINING):
        return FeasibleServerEvaluation(
            server_id=server_id,
            t_prefill_ms=0.0,
            t_decode_ms=0.0,
            t_exec_ms=0.0,
            t_wait_ms=0.0,
            t_turnaround_ms=0.0,
            deadline_slo_ms=req.deadline_slo_ms,
            slack_ms=-req.deadline_slo_ms,
            marginal_power_w=0.0,
            marginal_energy_j=0.0,
            is_feasible=False,
            rejection_reason=f"Server {server_id} is {server.status.value}",
        )

    # Check 2: Active streams and available immediate slots
    curr_active = len(server.active_streams)
    curr_queue = len(server.ingress_queue)
    avail_immediate = max(0, config.max_streams - curr_active)

    joint_active = curr_active + assigned_in_batch_count

    # Latency calculation
    t_prefill_ms, t_decode_ms, t_exec_ms = calculate_two_phase_latency(
        config,
        req.context_tokens,
        req.max_output_tokens,
        concurrency_m=joint_active,
    )

    # Queue delay calculation
    if assigned_in_batch_count < avail_immediate and curr_queue == 0:
        t_wait_ms = 0.0
    else:
        # Excess tasks enter queue behind existing queue
        excess_rank = max(1, curr_queue + (assigned_in_batch_count - avail_immediate) + 1)
        # Average turnaround of current server streams
        avg_exec_s = (t_exec_ms / 1000.0)
        t_wait_ms = ((curr_queue + excess_rank) / float(config.max_streams)) * avg_exec_s * 1000.0

    t_turnaround_ms = t_wait_ms + t_exec_ms

    # Elapsed time since arrival + expected future buffering
    elapsed_sec = current_time_sec - req.arrival_timestamp
    if elapsed_sec < 0.0 or elapsed_sec > 3600.0:  # Guard against epoch mismatch (simulation vs wallclock)
        elapsed_sec = 0.0
    elapsed_ms = elapsed_sec * 1000.0
    total_latency_from_arrival = elapsed_ms + expected_buffering_ms + t_turnaround_ms
    slack_ms = req.deadline_slo_ms - total_latency_from_arrival

    # Marginal power & energy
    p_marginal_w, e_marginal_j = calculate_marginal_power_and_energy(
        config,
        current_active_streams=joint_active,
        t_exec_ms=t_exec_ms,
        status=server.status,
    )

    is_feasible = (slack_ms >= 0.0)
    rejection_reason = None if is_feasible else (
        f"Turnaround latency ({t_turnaround_ms:.1f}ms) + elapsed ({elapsed_ms:.1f}ms) "
        f"exceeds deadline ({req.deadline_slo_ms:.1f}ms) by {-slack_ms:.1f}ms"
    )

    return FeasibleServerEvaluation(
        server_id=server_id,
        t_prefill_ms=t_prefill_ms,
        t_decode_ms=t_decode_ms,
        t_exec_ms=t_exec_ms,
        t_wait_ms=t_wait_ms,
        t_turnaround_ms=t_turnaround_ms,
        deadline_slo_ms=req.deadline_slo_ms,
        slack_ms=slack_ms,
        marginal_power_w=p_marginal_w,
        marginal_energy_j=e_marginal_j,
        is_feasible=is_feasible,
        rejection_reason=rejection_reason,
    )


def prefilter_request_feasibility(
    req: InferenceRequest,
    cluster: VirtualDataCentre,
    current_time_sec: float,
    deferral_threshold_ms: float = 30.0,
    expected_buffering_ms: float = 0.0,
) -> RequestFeasibilityProfile:
    """
    Evaluates request against all servers in the cluster.
    Identifies feasible server set F_i.
    If F_i is empty, triages into DEFER or REJECT based on remaining slack.
    """
    profile = RequestFeasibilityProfile(
        request_id=req.request_id,
        user_id=req.user_id,
    )

    max_slack_found = -float("inf")

    for s_id, server in cluster.servers.items():
        eval_result = evaluate_server_for_request(
            server=server,
            req=req,
            current_time_sec=current_time_sec,
            assigned_in_batch_count=0,
            expected_buffering_ms=expected_buffering_ms,
        )
        if eval_result.is_feasible:
            profile.feasible_servers[s_id] = eval_result
        if eval_result.slack_ms > max_slack_found:
            max_slack_found = eval_result.slack_ms

    if not profile.feasible_servers:
        # No server can currently meet the deadline
        if max_slack_found > deferral_threshold_ms:
            profile.can_defer = True
        else:
            profile.must_reject = True
            profile.rejection_reason = (
                f"No operational server can satisfy deadline {req.deadline_slo_ms}ms "
                f"(maximum slack is {max_slack_found:.1f}ms < threshold {deferral_threshold_ms}ms)"
            )

    return profile
