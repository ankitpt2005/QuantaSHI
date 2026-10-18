"""
Execution engine mechanics for heterogeneous inference servers.
Implements prefill (compute-bound) and decode (memory-bandwidth-bound) two-phase latency modeling.
"""

from __future__ import annotations
import math
from .models import ServerHardwareConfig, ExecutionTask, CompletionEvent
from .power_model import calculate_instantaneous_power, calculate_task_energy


def calculate_execution_duration(
    config: ServerHardwareConfig,
    context_tokens: int,
    output_tokens: int,
    current_active_streams: int,
) -> float:
    """
    Computes total execution time T_exec = T_prefill + T_decode (in seconds).
    
    Prefill Phase (FLOP/compute bound):
        T_prefill = T_ctx / (R_prefill * M^0.15)
    
    Decode Phase (Memory bandwidth bound):
        T_decode = (T_out / R_decode) * (1.0 + 0.04 * (M - 1))
    """
    m = max(1, current_active_streams)

    # Prefill phase
    prefill_eff_speed = config.prefill_speed_tokens_sec * math.pow(m, 0.15)
    t_prefill = context_tokens / max(1.0, prefill_eff_speed)

    # Decode phase with memory bandwidth degradation factor alpha = 0.04
    decode_eff_speed = config.decode_speed_tokens_sec / (1.0 + 0.04 * (m - 1))
    t_decode = output_tokens / max(0.1, decode_eff_speed)

    return t_prefill + t_decode


def create_completion_event(
    task: ExecutionTask,
    server_id: str,
    current_power_w: float,
    completed_timestamp: float,
) -> CompletionEvent:
    """
    Creates a detailed telemetry completion event for a finished request.
    """
    start_time = task.start_time if task.start_time is not None else task.arrival_time
    queue_wait_sec = max(0.0, start_time - task.arrival_time)
    exec_latency_sec = max(0.0, completed_timestamp - start_time)
    total_turnaround_sec = queue_wait_sec + exec_latency_sec

    queue_wait_ms = queue_wait_sec * 1000.0
    exec_latency_ms = exec_latency_sec * 1000.0
    total_turnaround_ms = total_turnaround_sec * 1000.0

    slo_met = total_turnaround_ms <= task.deadline_slo_ms
    energy_j = calculate_task_energy(current_power_w, exec_latency_sec)

    return CompletionEvent(
        request_id=task.request_id,
        user_id=task.user_id,
        server_id=server_id,
        workload_type=task.workload_type,
        context_tokens=task.context_tokens,
        output_tokens=task.max_output_tokens,
        queue_wait_ms=queue_wait_ms,
        exec_latency_ms=exec_latency_ms,
        total_turnaround_ms=total_turnaround_ms,
        deadline_slo_ms=task.deadline_slo_ms,
        slo_met=slo_met,
        energy_consumed_joules=energy_j,
        completed_at=completed_timestamp,
    )
