# QuantaSHI — User Interface & Workload Generator

This directory contains all components, data, and visualizer files for **Part 1: Users (Client Workload Generator)**.

## Architecture

```
user_interface/
├── USERS_SPECIFICATION.md   # Architectural & mathematical workload specification
├── __init__.py               # Package entry point
├── models.py                 # Pydantic schemas (InferenceRequest, UserProfile, PriorityLevel, etc.)
├── distributions.py          # Azure trace calibrated Gamma/Lognormal token & Poisson arrival samplers
├── prompt_corpus.py          # Real-world prompt template corpus across domains
├── topology.py               # 100-user 2D network mesh topology generator
├── generator.py              # Discrete-event workload generator & simulation scenarios
├── cli.py                    # CLI trace generation tool
├── README.md                 # This documentation
└── web/                      # Dedicated User Interface web visualizer
    ├── index.html            # Standalone User Interface page
    ├── users_app.js          # Low-code 2D constellation mesh, blast mode & client inspector
    ├── styles.css            # Practical datathon styles (dark mode, crisp typography)
    └── data/                 # Generated scenario traces
        ├── sample_trace.json
        ├── topology.json
        ├── trace_scenario_2.json
        ├── trace_scenario_3.json
        └── trace_scenario_4.json
```

## Running the User Interface

1. **Standalone Web Visualizer:**
   Run the local launcher and open `/user_interface/web/` in your browser.
2. **CLI Generator:**
   ```bash
   python -m user_interface.cli --scenario bursty --duration 60 --output trace.json
   ```
