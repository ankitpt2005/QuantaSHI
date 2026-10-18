# QuantaSHI — System Interface & Decision Engine

This directory contains all components, optimization solvers, and visualizer files for **Part 3: System (Decision & Optimization Engine)**.

## Architecture

```
system_interface/
├── SYSTEM_SPECIFICATION.md   # Architectural & mathematical optimization specification
├── __init__.py                # Package entry point
├── models.py                  # Models (RoutingPolicy, OptimizationWeights, DispatchDecision, SystemMetrics)
├── optimizer.py               # QuantaSHIOptimizer Pareto multi-objective scoring solver
├── scheduler.py               # QuantaSHIScheduler connecting user requests to server cluster
├── README.md                  # This documentation
└── web/                       # Dedicated System Interface web visualizer
    ├── index.html             # Standalone System Interface page with Reset Engine button
    ├── system_app.js          # Interactive policy switcher, live decision logs, dispatch engine
    └── styles.css             # Datathon-style styling
```

## Supported Dispatch Policies

1. **`BALANCED_PARETO`** ($w_E = 0.50, w_L = 0.50$): Balances energy conservation against latency headroom.
2. **`ENERGY_OPTIMIZED`** ($w_E = 0.85, w_L = 0.15$): Maximizes cluster power efficiency by favoring lower-power accelerators.
3. **`LATENCY_FIRST`** ($w_E = 0.10, w_L = 0.90$): Directs requests to high-speed GPUs for minimal latency.
4. **`ROUND_ROBIN`**: Baseline round-robin benchmark.

## Running the System Interface

1. **Standalone Web Visualizer:**
   Run the local launcher and open `/system_interface/web/` in your browser.
2. **Python Scheduler Integration:**
   ```python
   from user_interface.generator import WorkloadGenerator
   from server_interface.cluster import VirtualDataCentre
   from system_interface.scheduler import QuantaSHIScheduler

   vdc = VirtualDataCentre()
   scheduler = QuantaSHIScheduler(cluster=vdc)
   ```
