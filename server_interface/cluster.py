"""
Virtual Data Centre cluster manager and heterogeneous server instances.
Manages the 3 physical server models (H100, L4, Xeon), stream queues, and power integration.
"""

from __future__ import annotations
from typing import Dict, List, Optional
import time

from .models import (
    ServerType,
    ServerStatus,
    ServerHardwareConfig,
    ExecutionTask,
    CompletionEvent,
    ServerTelemetrySnapshot,
)
from .power_model import calculate_instantaneous_power
from .execution_engine import calculate_execution_duration, create_completion_event

# Validated Server Hardware Specifications from SERVERS_SPECIFICATION.md
DEFAULT_SERVERS: List[ServerHardwareConfig] = [
    ServerHardwareConfig(
        server_id="srv_gpu_01",
        name="Server 1: High-Performance GPU",
        model="NVIDIA H100 PCIe 80GB HBM3",
        server_type=ServerType.HIGH_PERF_ACCELERATOR,
        max_streams=32,
        prefill_speed_tokens_sec=12000.0,
        decode_speed_tokens_sec=85.0,
        vram_gb=80,
        idle_power_w=75.0,
        peak_power_w=350.0,
        power_exponent_r=1.35,
        ui_color="#38bdf8",
    ),
    ServerHardwareConfig(
        server_id="srv_acc_02",
        name="Server 2: Energy-Efficient Tensor",
        model="NVIDIA L4 24GB / IBM Telum On-Chip",
        server_type=ServerType.BALANCED_ACCELERATOR,
        max_streams=16,
        prefill_speed_tokens_sec=3200.0,
        decode_speed_tokens_sec=38.0,
        vram_gb=24,
        idle_power_w=25.0,
        peak_power_w=72.0,
        power_exponent_r=1.40,
        ui_color="#10b981",
    ),
    ServerHardwareConfig(
        server_id="srv_cpu_03",
        name="Server 3: General-Purpose CPU",
        model="Intel Xeon Platinum 8480+ / LinuxONE Core",
        server_type=ServerType.COMMODITY_CPU,
        max_streams=4,
        prefill_speed_tokens_sec=650.0,
        decode_speed_tokens_sec=12.0,
        vram_gb=64,
        idle_power_w=45.0,
        peak_power_w=220.0,
        power_exponent_r=1.10,
        ui_color="#f59e0b",
    ),
]


class ServerInstance:
    """Represents a physical server node in the virtual data centre."""

    def __init__(self, config: ServerHardwareConfig):
        self.config = config
        self.status = ServerStatus.IDLE
        self.active_streams: List[ExecutionTask] = []
        self.ingress_queue: List[ExecutionTask] = []
        self.completed_count = 0
        self.slo_violations = 0
        self.total_tokens_processed = 0
        self.cumulative_energy_joules = 0.0

    @property
    def current_power_w(self) -> float:
        return calculate_instantaneous_power(
            self.config, len(self.active_streams), self.status
        )

    def dispatch(self, task: ExecutionTask, arrival_time: float) -> bool:
        """Enqueues or immediately executes an incoming inference task."""
        if self.status in (ServerStatus.OFFLINE, ServerStatus.DRAINING):
            return False

        task.arrival_time = arrival_time
        task.estimated_duration_sec = calculate_execution_duration(
            self.config,
            task.context_tokens,
            task.max_output_tokens,
            len(self.active_streams) + 1,
        )

        if len(self.active_streams) < self.config.max_streams:
            task.start_time = arrival_time
            self.active_streams.append(task)
            self.status = (
                ServerStatus.CONGESTED
                if len(self.active_streams) >= self.config.max_streams
                else ServerStatus.PROCESSING
            )
        else:
            self.ingress_queue.append(task)
            self.status = ServerStatus.CONGESTED

        return True

    def step(self, dt: float, current_time: float) -> List[CompletionEvent]:
        """Advances execution by dt seconds and returns completed events."""
        if self.status == ServerStatus.OFFLINE:
            return []

        # Integrate power draw over dt
        self.cumulative_energy_joules += self.current_power_w * dt

        completed_events: List[CompletionEvent] = []
        remaining_streams: List[ExecutionTask] = []

        for stream in self.active_streams:
            stream.progress_sec += dt
            if stream.progress_sec >= stream.estimated_duration_sec:
                # Finished
                self.completed_count += 1
                self.total_tokens_processed += (
                    stream.context_tokens + stream.max_output_tokens
                )
                evt = create_completion_event(
                    stream, self.config.server_id, self.current_power_w, current_time
                )
                if not evt.slo_met:
                    self.slo_violations += 1
                completed_events.append(evt)
            else:
                remaining_streams.append(stream)

        self.active_streams = remaining_streams

        # Pull from ingress queue into available compute stream slots
        while (
            self.ingress_queue
            and len(self.active_streams) < self.config.max_streams
            and self.status != ServerStatus.DRAINING
        ):
            next_task = self.ingress_queue.pop(0)
            next_task.start_time = current_time
            next_task.estimated_duration_sec = calculate_execution_duration(
                self.config,
                next_task.context_tokens,
                next_task.max_output_tokens,
                len(self.active_streams) + 1,
            )
            self.active_streams.append(next_task)

        # Update server operational status
        if len(self.active_streams) == 0 and len(self.ingress_queue) == 0:
            if self.status not in (ServerStatus.DRAINING, ServerStatus.OFFLINE):
                self.status = ServerStatus.IDLE
        elif len(self.active_streams) >= self.config.max_streams:
            self.status = ServerStatus.CONGESTED
        else:
            if self.status not in (ServerStatus.DRAINING, ServerStatus.OFFLINE):
                self.status = ServerStatus.PROCESSING

        return completed_events

    def get_snapshot(self) -> ServerTelemetrySnapshot:
        total_slots = self.config.max_streams
        active = len(self.active_streams)
        utilization = (active / float(total_slots) * 100.0) if total_slots > 0 else 0.0

        return ServerTelemetrySnapshot(
            server_id=self.config.server_id,
            status=self.status,
            active_streams_count=active,
            max_streams_capacity=total_slots,
            stream_utilization_pct=round(utilization, 1),
            queue_depth=len(self.ingress_queue),
            current_power_w=round(self.current_power_w, 2),
            cumulative_energy_joules=round(self.cumulative_energy_joules, 2),
            completed_tasks_count=self.completed_count,
            slo_violations_count=self.slo_violations,
            total_tokens_processed=self.total_tokens_processed,
        )

    def reset(self):
        self.status = ServerStatus.IDLE
        self.active_streams.clear()
        self.ingress_queue.clear()
        self.completed_count = 0
        self.slo_violations = 0
        self.total_tokens_processed = 0
        self.cumulative_energy_joules = 0.0


class VirtualDataCentre:
    """Cluster coordinator managing the 3 heterogeneous virtual servers."""

    def __init__(self, configs: Optional[List[ServerHardwareConfig]] = None):
        configs = configs or DEFAULT_SERVERS
        self.servers: Dict[str, ServerInstance] = {
            cfg.server_id: ServerInstance(cfg) for cfg in configs
        }
        self.clock = 0.0

    def dispatch_to_server(self, server_id: str, task: ExecutionTask) -> bool:
        srv = self.servers.get(server_id)
        if not srv:
            return False
        return srv.dispatch(task, self.clock)

    def step(self, dt: float) -> List[CompletionEvent]:
        self.clock += dt
        all_completions: List[CompletionEvent] = []
        for srv in self.servers.values():
            all_completions.extend(srv.step(dt, self.clock))
        return all_completions

    def get_cluster_power_w(self) -> float:
        return sum(s.current_power_w for s in self.servers.values())

    def get_cluster_snapshots(self) -> Dict[str, ServerTelemetrySnapshot]:
        return {sid: s.get_snapshot() for sid, s in self.servers.items()}

    def reset_cluster(self):
        self.clock = 0.0
        for srv in self.servers.values():
            srv.reset()
