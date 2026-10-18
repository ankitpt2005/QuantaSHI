"""
Adaptive Slack-Aware Ingress Buffer.
Buffers incoming inference requests and dynamically triggers batch optimization epochs
based on arrival rate, timer thresholds, and critical deadline slack.
"""

from __future__ import annotations
from typing import List, Optional, Tuple
import time

from user_interface.models import InferenceRequest
from server_interface.cluster import VirtualDataCentre
from .feasibility import prefilter_request_feasibility


class AdaptiveIngressBuffer:
    """Dynamically buffers requests and triggers batch scheduling epochs."""

    def __init__(
        self,
        steady_batch_max: int = 5,
        burst_batch_max: int = 12,
        steady_timeout_sec: float = 0.040,   # 40 ms
        burst_timeout_sec: float = 0.015,    # 15 ms
        critical_slack_ms: float = 25.0,     # 25 ms
        burst_threshold_rps: float = 25.0,   # 25 req/s
    ):
        self.steady_batch_max = steady_batch_max
        self.burst_batch_max = burst_batch_max
        self.steady_timeout_sec = steady_timeout_sec
        self.burst_timeout_sec = burst_timeout_sec
        self.critical_slack_ms = critical_slack_ms
        self.burst_threshold_rps = burst_threshold_rps

        self.buffer: List[InferenceRequest] = []
        self.last_flush_time = time.time()
        self.arrival_history: List[float] = []

    @property
    def current_arrival_rate_rps(self) -> float:
        now = time.time()
        self.arrival_history = [t for t in self.arrival_history if now - t <= 1.0]
        return float(len(self.arrival_history))

    @property
    def is_burst_regime(self) -> bool:
        return self.current_arrival_rate_rps >= self.burst_threshold_rps

    @property
    def dynamic_batch_max(self) -> int:
        return self.burst_batch_max if self.is_burst_regime else self.steady_batch_max

    @property
    def dynamic_timeout_sec(self) -> float:
        return self.burst_timeout_sec if self.is_burst_regime else self.steady_timeout_sec

    def push(self, req: InferenceRequest):
        now = time.time()
        self.buffer.append(req)
        self.arrival_history.append(now)

    def should_trigger_epoch(
        self,
        cluster: VirtualDataCentre,
        current_time_sec: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """
        Evaluates trigger condition:
            (Count >= B_max) OR (Timer >= tau_max) OR (Min Slack <= 25 ms)
        """
        if not self.buffer:
            return False, "EMPTY"

        now = current_time_sec if current_time_sec is not None else time.time()

        # Trigger Condition 1: Batch Capacity Reached
        if len(self.buffer) >= self.dynamic_batch_max:
            return True, f"BATCH_CAP_REACHED ({len(self.buffer)} >= {self.dynamic_batch_max})"

        # Trigger Condition 2: Buffering Timeout Reached
        elapsed_buffer_time = now - self.last_flush_time
        if elapsed_buffer_time >= self.dynamic_timeout_sec:
            return True, f"BUFFER_TIMEOUT_REACHED ({elapsed_buffer_time*1000:.1f}ms >= {self.dynamic_timeout_sec*1000:.1f}ms)"

        # Trigger Condition 3: Critical Deadline Slack
        for req in self.buffer:
            profile = prefilter_request_feasibility(
                req=req,
                cluster=cluster,
                current_time_sec=now,
                expected_buffering_ms=0.0,
            )
            # Find minimum slack among feasible servers
            if profile.feasible_servers:
                min_slack = min(s.slack_ms for s in profile.feasible_servers.values())
                if min_slack <= self.critical_slack_ms:
                    return True, f"CRITICAL_SLACK_REACHED (req {req.request_id} has {min_slack:.1f}ms slack <= {self.critical_slack_ms}ms)"

        return False, "BUFFERING"

    def pop_batch(self, current_time_sec: Optional[float] = None) -> List[InferenceRequest]:
        now = current_time_sec if current_time_sec is not None else time.time()
        batch = list(self.buffer)
        self.buffer.clear()
        self.last_flush_time = now
        return batch

    def clear(self):
        self.buffer.clear()
        self.last_flush_time = time.time()
        self.arrival_history.clear()
