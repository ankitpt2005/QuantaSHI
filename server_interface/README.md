# QuantaSHI — Server Interface & Virtual Data Centre

This directory contains all components, execution mechanics, and visualizer files for **Part 2: Servers (Virtual Data Centre)**.

## Architecture

```
server_interface/
├── SERVERS_SPECIFICATION.md  # Architectural specification, formulas & server profiles
├── __init__.py                # Package entry point
├── models.py                  # Pydantic/dataclass models (ServerType, ServerHardwareConfig, ExecutionTask, etc.)
├── power_model.py             # Empirical Fan et al. (ISCA 2007) power equation & energy integration
├── execution_engine.py        # Two-phase prefill/decode latency calculations & SLO verification
├── cluster.py                 # VirtualDataCentre cluster manager and heterogeneous server instances
├── cli.py                     # CLI test tool for dispatching requests to servers
├── README.md                  # This documentation
└── web/                       # Dedicated Server Interface web visualizer
    ├── index.html             # Standalone Server Interface page with Reset Cluster button
    ├── servers_app.js         # Real-time compute stream meters, live power bars, queue depths
    └── styles.css             # Datathon-style chassis styles
```

## Heterogeneous Cluster Specifications

| Server ID | Hardware Model | Type | Max Streams | Prefill Speed | Decode Speed | Idle / Peak Power | Exponent $r$ |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `srv_gpu_01` | NVIDIA H100 PCIe 80GB HBM3 | High-Perf Accelerator | 32 streams | 12,000 tok/s | 85.0 tok/s | 75 W / 350 W | 1.35 |
| `srv_acc_02` | NVIDIA L4 24GB / IBM Telum | Balanced Accelerator | 16 streams | 3,200 tok/s | 38.0 tok/s | 25 W / 72 W | 1.40 |
| `srv_cpu_03` | Intel Xeon Platinum 8480+ | Commodity CPU | 4 streams | 650 tok/s | 12.0 tok/s | 45 W / 220 W | 1.10 |

## Running the Server Interface

1. **Standalone Web Visualizer:**
   Run the local launcher and open `/server_interface/web/` in your browser.
2. **CLI Runner:**
   ```bash
   python -m server_interface.cli --tasks 20 --target all
   ```
