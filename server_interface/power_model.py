"""
Power and Energy Consumption Model for Heterogeneous Data Centre Servers.
Implements the validated empirical power formula by Fan, Weber, and Barroso (ISCA 2007).
"""

from __future__ import annotations
import math
from .models import ServerHardwareConfig, ServerStatus


def calculate_instantaneous_power(
    config: ServerHardwareConfig,
    active_streams: int,
    status: ServerStatus = ServerStatus.PROCESSING,
) -> float:
    """
    Computes instantaneous power draw P(u) based on stream utilization u.

    Formula:
        P(u) = P_idle + (P_peak - P_idle) * (2*u - u^r)
    """
    if status == ServerStatus.OFFLINE:
        return 0.0

    if config.max_streams <= 0:
        return config.idle_power_w

    # Utilization ratio bounded [0.0, 1.0]
    u = min(1.0, max(0.0, active_streams / float(config.max_streams)))

    # Fan et al. non-linear empirical dynamic scaling
    dynamic_scaling = (2.0 * u) - math.pow(u, config.power_exponent_r)
    dynamic_scaling = max(0.0, dynamic_scaling)

    return config.idle_power_w + (config.peak_power_w - config.idle_power_w) * dynamic_scaling


def calculate_task_energy(
    avg_power_w: float,
    execution_duration_sec: float,
) -> float:
    """
    Calculates energy consumed by a task in Joules (Watt-seconds).
    E (Joules) = Power (Watts) * Time (Seconds)
    """
    return avg_power_w * execution_duration_sec
