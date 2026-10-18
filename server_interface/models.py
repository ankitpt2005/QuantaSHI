"""
Data models for Part 2: Servers (Virtual Data Centre).
Defines heterogeneous server architectures, compute streams, and completion telemetry.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional
import time


class ServerType(str, Enum):
    HIGH_PERF_ACCELERATOR = "HIGH_PERF_ACCELERATOR"  # e.g., NVIDIA H100
    BALANCED_ACCELERATOR = "BALANCED_ACCELERATOR"    # e.g., NVIDIA L4 / IBM Telum
    COMMODITY_CPU = "COMMODITY_CPU"                  # e.g., Intel Xeon Platinum 8480+


class ServerStatus(str, Enum):
    IDLE = "IDLE"
    PROCESSING = "PROCESSING"
    CONGESTED = "CONGESTED"
    DRAINING = "DRAINING"
    OFFLINE = "OFFLINE"


@dataclass
class ServerHardwareConfig:
    server_id: str
    name: str
    model: str
    server_type: ServerType
    max_streams: int
    prefill_speed_tokens_sec: float
    decode_speed_tokens_sec: float
    vram_gb: int
    idle_power_w: float
    peak_power_w: float
    power_exponent_r: float
    ui_color: str = "#38bdf8"


@dataclass
class ExecutionTask:
    request_id: str
    user_id: str
    workload_type: str
    context_tokens: int
    max_output_tokens: int
    deadline_slo_ms: int
    priority_level: str
    arrival_time: float
    start_time: Optional[float] = None
    estimated_duration_sec: float = 0.0
    progress_sec: float = 0.0


@dataclass
class CompletionEvent:
    request_id: str
    user_id: str
    server_id: str
    workload_type: str
    context_tokens: int
    output_tokens: int
    queue_wait_ms: float
    exec_latency_ms: float
    total_turnaround_ms: float
    deadline_slo_ms: int
    slo_met: bool
    energy_consumed_joules: float
    completed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "server_id": self.server_id,
            "workload_type": self.workload_type,
            "tokens": self.context_tokens + self.output_tokens,
            "queue_wait_ms": round(self.queue_wait_ms, 2),
            "exec_latency_ms": round(self.exec_latency_ms, 2),
            "total_turnaround_ms": round(self.total_turnaround_ms, 2),
            "deadline_slo_ms": self.deadline_slo_ms,
            "slo_met": self.slo_met,
            "energy_joules": round(self.energy_consumed_joules, 2),
            "completed_at": self.completed_at,
        }


@dataclass
class ServerTelemetrySnapshot:
    server_id: str
    status: ServerStatus
    active_streams_count: int
    max_streams_capacity: int
    stream_utilization_pct: float
    queue_depth: int
    current_power_w: float
    cumulative_energy_joules: float
    completed_tasks_count: int
    slo_violations_count: int
    total_tokens_processed: int
