# QuantaSHI — Part 3: Decision Engine and Quantum Optimization Specification

**Document Version:** 2.2.0 (Mathematical Consistency & Rigorous Formulation Pass)  
**Status:** Under Engineering & Scientific Review  
**Component:** Part 3 — QuantaSHI System (Decision Engine & Optimization Layer)  
**Parent Framework:** QuantaSHI Heterogeneous AI Infrastructure Framework  

---

## 1. Problem Statement & Operational Scope

### 1.1 Objective & Context
In a virtualized, heterogeneous AI inference data centre, arriving requests exhibit high variability in prompt token length, target output generation, deadline Service Level Objectives (SLOs), and computational intensity. Compute nodes feature disparate hardware architectures—high-throughput GPU accelerators, balanced energy-efficient tensor processors, and commodity general-purpose CPUs—characterized by non-linear power-to-utilization profiles.

The **QuantaSHI System** is the central decision and optimization engine positioned between **Part 1: Users (Workload Generator)** and **Part 2: Servers (Virtual Data Centre)**. Its core function is to solve the **online, energy-aware, deadline-constrained heterogeneous scheduling problem**: dynamically assigning incoming and queued inference requests to candidate servers such that cluster electrical energy consumption is minimized while physical server concurrency bounds and individual request deadline Service Level Objectives (SLOs) are strictly maintained.

```
+------------------------------------+
|  Part 1: Users (Workload Gen)      |
|  - 100 Virtual Client Nodes        |
|  - Continuous & Bursty Ingress     |
+-----------------+------------------+
                  |
                  | [1] Ingress Request Stream (Matching Part 1 Schema)
                  v
+------------------------------------+       [2] Server State & Telemetry
|  Part 3: QuantaSHI System Engine   | <===================================+
|  - Adaptive Slack-Aware Mini-Batch |                                     |
|  - Deterministic Feasibility Gate  |                                     |
|  - Mathematical Formulation (QUBO) |                                     |
|  - Multi-Solver Suite (SA/MILP)    |                                     |
|  - Post-Solve Validation & Fallback|                                     |
|  - Deterministic Attribution Logger|                                     |
+-----------------+------------------+                                     |
                  |                                                        |
                  | [3] Dispatch Directives (Assignment Commands)           |
                  v                                                        |
+------------------------------------+                                     |
|  Part 2: Servers (Virtual DC)      | ------------------------------------+
|  - srv_gpu_01 (High-Perf GPU)      |
|  - srv_acc_02 (Balanced Tensor)    |
|  - srv_cpu_03 (Commodity CPU)      |
+------------------------------------+
```

### 1.2 Information Received by the System

1. **From Part 1 (Users — Ingress Request Stream):**
   Matches the authoritative schema in `user_interface/models.py`:
   - `request_id`: Standard UUID v4 string (`str(uuid.uuid4())`).
   - `user_id`: Formatted client ID string `usr_001` through `usr_100` (zero-padded 3-digit string).
   - `arrival_timestamp`: Simulation arrival epoch in seconds ($t_{\text{arr}} \in \mathbb{R}^+$).
   - `workload_type`: Enum string matching Part 1 `WorkloadType` exactly:
     `TEXT_CHAT`, `CODE_GEN`, `RAG_QA`, `SUMMARIZATION`.
   - `context_tokens`: Integer prompt token count ($T_{\text{ctx}} \in [1, 8192]$).
   - `max_output_tokens`: Integer generation token ceiling ($T_{\text{out}} \in [1, 2048]$).
   - `priority_level`: Integer enum matching Part 1 `PriorityLevel`:
     `P0_CRITICAL = 0`, `P1_INTERACTIVE = 1`, `P2_BATCH = 2`.
   - `deadline_slo_ms`: Client turnaround deadline in milliseconds ($\text{SLO} \in [100.0, 10000.0]\text{ ms}$, float).
   - `prompt_preview`: Text preview snippet of prompt payload (`str`).

2. **From Part 2 (Servers — Virtual Data Centre State):**
   *(Note: Parameters from Part 2 are simulation assumptions currently undergoing technical validation. They are modeled as parameterized inputs rather than validated physical constants.)*
   - `active_streams`: Current concurrent stream count $M_s(t) \in [0, M_{\max, s}]$.
   - `max_streams`: Hardware stream limit $M_{\max, s} \in \{32, 16, 4\}$.
   - `queue_depth`: Count of requests currently waiting in server memory queue $Q_s(t) \in \mathbb{N}_0$.
   - `status`: Server operational status enum (`IDLE`, `PROCESSING`, `CONGESTED`, `DRAINING`, `OFFLINE`).
   - `prefill_speed`: Nominal prefill processing rate $R_{\text{prefill}, s}$ (tokens/second).
   - `decode_speed`: Nominal decode generation rate $R_{\text{decode}, s}$ (tokens/second/stream).
   - `power_params`: Idle power $P_{\text{idle}, s}$, peak power $P_{\text{peak}, s}$, and empirical exponent $r_s$ from the Fan et al. (2007) model.

### 1.3 Permitted System Decisions & Reconciled Decision Space
For every request $r_i$ evaluated during a scheduling epoch $t$, the system outputs one of four mutually exclusive outcomes:
- **`DISPATCH(r_i, s)`**: Assign request $r_i$ to operational server $s \in \mathcal{S}$ for immediate execution if $M_s(t) < M_{\max, s}$.
- **`ENQUEUE(r_i, s)`**: Place request $r_i$ into the memory queue of operational server $s$ if active compute slots are saturated, provided total turnaround (queue wait + execution) satisfies $\text{SLO}_i$.
- **`DEFER(r_i)`**: Retain request $r_i$ in the central scheduling buffer for the subsequent optimization window. This decision is strictly permitted **only** if the remaining deadline slack exceeds the deferral delay threshold:
  $$\text{Slack}_i(t) = \text{SLO}_i - \left[(t - t_{\text{arr}, i}) \times 1000.0 + \tau_{\text{buffer\_next}}\right] - \min_{s \in \mathcal{S}_{\text{avail}}} \left( \hat{T}_{\text{wait, ms}}(s) + \hat{T}_{\text{exec, ms}}(s, r_i) \right) > \tau_{\text{defer\_threshold}}$$
  where $\tau_{\text{buffer\_next}} \in [15.0, 40.0]\text{ ms}$ is the expected queuing duration until the next batch epoch.
- **`REJECT(r_i)`**: Explicitly reject request $r_i$ (emitting an immediate HTTP 429/504 load-shedding response) if mathematical verification proves that no available server can satisfy the deadline without causing cascading SLO violations. This prevents wasting cluster energy on doomed requests.

**Mathematical Reconciliation of Decisions:**
- **`REJECT` is handled via pre-filtering:** Requests with zero feasible server assignments are triaged and removed before constructing optimization variables.
- **`DEFER` is represented explicitly:** In the mathematical formulation, candidate requests are assigned either to an operational physical server $s \in \mathcal{S}$ or to a virtual deferral slot $s_{\text{def}}$. Every admitted request in optimization satisfies:
  $$\sum_{s \in \mathcal{S}} x_{i,s} + x_{i, \text{def}} = 1 \quad \forall r_i \in \mathcal{B}$$

### 1.4 Inviolable Hard Constraints
1. **Zero Assignment to Inactive Nodes:** $x_{i,s} = 0 \quad \forall s \text{ where } \text{status}_s \in \{\text{OFFLINE}, \text{DRAINING}\}$.
2. **Server Hardware Capacity Ceiling:** The number of assignments cannot exceed the available slot capacity:
   $$\sum_{i=1}^{N} x_{i,s} \le C_s^{\text{avail}}(t) \quad \forall s \in \mathcal{S}$$
3. **Strict Feasibility Guarantee:** No request may be dispatched to a server $s$ where the predicted total turnaround time $\hat{T}_{\text{turnaround, ms}}(s, r_i)$ exceeds its deadline $\text{SLO}_i$.
4. **Conservation of Assignment:** Each admitted candidate request is mapped to exactly one destination: $\sum_{s \in \mathcal{S} \cup \{s_{\text{def}}\}} x_{i,s} = 1$.

---

## 2. Standardized Physical Units & Explicit Conversions

All calculations adhere strictly to standardized physical units with explicit conversion factors:

| Quantity | Variable Symbol | Standard Unit | Explicit Conversion Rule |
| :--- | :--- | :--- | :--- |
| **Token Counts** | $T_{\text{ctx}}, T_{\text{out}}$ | Integer tokens | Dimensionless count |
| **Processing Rates** | $R_{\text{prefill}}, R_{\text{decode}}$ | Tokens / second | $\text{tokens} \cdot \text{s}^{-1}$ |
| **Execution Latency** | $T_{\text{prefill}}, T_{\text{decode}}, T_{\text{exec}}$ | Seconds $[\text{s}]$ | Derived directly from rate division: $\frac{\text{tokens}}{\text{tokens/s}} = [\text{s}]$ |
| **Turnaround & Deadlines** | $T_{\text{exec, ms}}, T_{\text{wait, ms}}, \text{SLO}$ | Milliseconds $[\text{ms}]$ | $T_{\text{ms}} = T_{\text{s}} \times 1000.0 \quad [\text{ms}]$ |
| **Instantaneous Power** | $P_s(u), \Delta P(s, r_i)$ | Watts $[\text{W}]$ | $1\text{ W} = 1\text{ Joule} \cdot \text{s}^{-1}$ |
| **Marginal Energy** | $E_{\text{marginal}}(s, r_i)$ | Joules $[\text{J}]$ | $E_{\text{marginal}} = \Delta P [\text{W}] \times T_{\text{exec}} [\text{s}] = \Delta P [\text{W}] \times \left(\frac{T_{\text{exec, ms}}}{1000.0}\right) [\text{J}]$ |
| **Objective Weights** | $w_E, w_L$ | Dimensionless scalar | $w_E + w_L = 1.0, \quad w_E, w_L \in [0.0, 1.0]$ |

---

## 3. Scheduling Realism: Concurrency, Queuing, and Power Modeling

### 3.1 Ground-Truth Server Simulator vs. Decision-Time Optimizer Approximation

To resolve all inconsistencies between models, we explicitly separate the ground-truth physical simulation from the decision-time optimization heuristic:

1. **Ground-Truth Physical Server Simulator (Part 2):**
   - Evaluates **total simulated cluster energy** continuously over the physical power timeline:
     $$E_{\text{cluster}}(T) = \sum_{s \in \mathcal{S}} \int_0^T P_s(t) \, dt \quad [\text{Joules}]$$
     where $P_s(t) = P_{\text{idle}, s} + (P_{\text{peak}, s} - P_{\text{idle}, s}) \cdot (2u(t) - u(t)^{r_s})$.
   - Tracks exact discrete completion events, continuous queue drainage, memory bandwidth contention, and latency.

2. **Online Optimizer Proxy Model (Part 3):**
   - The optimizer operates in discrete decision epochs $\Delta t$ and cannot foresee future stochastic arrivals.
   - It evaluates the **decision-time marginal dynamic energy heuristic proxy**:
     $$E_{\text{marginal}}(s, r_i) = \Delta P(s, r_i) \cdot \left(\frac{\hat{T}_{\text{exec, ms}}(s, r_i)}{1000.0}\right) \quad [\text{Joules}]$$
     where $\Delta P(s, r_i) = P_s\left(\frac{M_s + 1}{M_{\max, s}}\right) - P_s\left(\frac{M_s}{M_{\max, s}}\right) \quad [\text{Watts}]$.
   - **Important Distinction:** This marginal energy proxy is clearly labeled as an **online dispatch heuristic**. Baseline idle power ($P_{\text{idle}}$) is an invariant chassis cost integrated by the simulator but excluded from marginal request dispatch to prevent double-counting across concurrent streams.

### 3.2 Two-Phase Latency & Joint Concurrency Recalculation

Execution latency comprises two distinct phases computed in seconds and converted to milliseconds:
$$\hat{T}_{\text{exec, ms}}(s, r_i) = \left( \hat{T}_{\text{prefill, s}}(s, r_i) + \hat{T}_{\text{decode, s}}(s, r_i) \right) \times 1000.0 \quad [\text{ms}]$$

When a batch of $N$ requests assigns $k_s = \sum_{i=1}^N x_{i,s}$ tasks to server $s$, predictions must **not** assume independent execution:

1. **Available Immediate Slots:** $A_s(t) = \max\left(0, M_{\max, s} - M_s(t)\right)$.
2. **Immediate Execution Sub-batch ($k_s \le A_s(t)$):**
   - All $k_s$ requests start immediately: $\hat{T}_{\text{wait, ms}}(s) = 0.0\text{ ms}$.
   - Concurrency increases to $M_s' = M_s(t) + k_s$.
   - Decode latency for each assigned request scales with the joint concurrency $M_s'$:
     $$\hat{T}_{\text{decode, ms}}(s, r_i \mid k_s) = \frac{T_{\text{out}, i}}{R_{\text{decode}, s}} \cdot \left( 1.0 + 0.04 \cdot M_s' \right) \times 1000.0 \quad [\text{ms}]$$
   - Prefill latency scales as:
     $$\hat{T}_{\text{prefill, ms}}(s, r_i \mid k_s) = \frac{T_{\text{ctx}, i}}{R_{\text{prefill}, s} \cdot (M_s' + 1)^{0.15}} \times 1000.0 \quad [\text{ms}]$$
3. **Queued Sub-batch ($k_s > A_s(t)$):**
   - Exactly $A_s(t)$ requests occupy remaining slots (operating at $M_{\max, s}$).
   - The excess $k_s - A_s(t)$ requests are queued behind the existing $Q_s(t)$ tasks.
   - For a request at queue rank $q \in \{1, \dots, k_s - A_s(t)\}$, queue wait time incorporates existing queued work:
     $$\hat{T}_{\text{wait, ms}}(s, q) = \left( \frac{Q_s(t) + q}{M_{\max, s}} \right) \cdot \bar{T}_{\text{exec, s}} \times 1000.0 \quad [\text{ms}]$$
   - Total predicted turnaround time:
     $$\hat{T}_{\text{turnaround, ms}}(s, r_i) = \hat{T}_{\text{wait, ms}}(s, q) + \hat{T}_{\text{exec, ms}}(s, r_i \mid M_{\max, s}) \quad [\text{ms}]$$

---

## 4. Adaptive Slack-Aware Batch Formation

### 4.1 Ingress Rate vs. Batch Timing Reconciliation
Part 1 defines two distinct operational regimes:
- **Normal Steady-State Ingress:** $15\text{--}20\text{ req/s}$ (mean inter-arrival $\Delta t \approx 50\text{--}66\text{ ms}$).
- **Flash Burst Spike Ingress:** $100\text{ req/s}$ (mean inter-arrival $\Delta t \approx 10\text{ ms}$, with up to 40 requests arriving in a sudden pulse).

A fixed timer or rigid batch size fails under burst conditions: a 40 ms timer causes excessive buffering during bursts, whereas urgent requests ($\text{SLO} = 250\text{ ms}$) risk deadline failure while waiting for a batch to fill.

### 4.2 Dynamic Batch Triggering Rule
The system implements an **Adaptive Slack-Aware Ingress Buffer**:

$$\text{Trigger Batch Epoch } \iff \left( |\mathcal{B}| \ge B_{\max} \right) \lor \left( \Delta t_{\text{buffer}} \ge \tau_{\max} \right) \lor \left( \min_{r_i \in \mathcal{B}} \text{Slack}_i(t) \le \tau_{\text{slack\_crit}} \right)$$

Where:
- **Maximum Batch Cap ($B_{\max}$):**
  $$B_{\max} = \begin{cases} 5, & \text{if } \lambda_{\text{ingress}} < 25\text{ req/s} \quad (\text{Normal Steady-State}) \\ 12, & \text{if } \lambda_{\text{ingress}} \ge 25\text{ req/s} \quad (\text{Burst Regime}) \end{cases}$$
- **Maximum Buffering Timeout ($\tau_{\max}$):**
  $$\tau_{\max} = \begin{cases} 40\text{ ms}, & \text{Normal mode} \\ 15\text{ ms}, & \text{Burst mode} \end{cases}$$
- **Critical Slack Threshold ($\tau_{\text{slack\_crit}} = 25\text{ ms}$):**
  If *any* request in the buffer has remaining deadline slack $\le 25\text{ ms}$, the buffer triggers an **immediate emergency dispatch epoch**.

---

## 5. Mathematical Formulations: Exact MILP & Corrected QUBO

### 5.1 Exact Classical Formulation (HiGHS / SciPy MILP)
The exact scheduling problem over batch $\mathcal{B}$ is formulated as a Mixed-Integer Linear Program (MILP):

$$\min_{\mathbf{x}} J(\mathbf{x}) = \sum_{i=1}^{N} \sum_{s=1}^{K} x_{i,s} \left[ w_E \left(\frac{E_{\text{marginal}}(s, r_i)}{E_{\max}}\right) + w_L \left(\frac{\hat{T}_{\text{turnaround, ms}}(s, r_i)}{\text{SLO}_i}\right) \right] + \sum_{i=1}^{N} x_{i, \text{def}} \cdot C_{\text{defer}, i}$$

Subject to:
1. **Exact-One Assignment / Deferral:**
   $$\sum_{s=1}^{K} x_{i,s} + x_{i, \text{def}} = 1 \quad \forall i \in \{1, \dots, N\}$$
2. **Server Available Capacity Constraints:**
   $$\sum_{i=1}^{N} x_{i,s} \le C_s^{\text{avail}}(t) \quad \forall s \in \{1, \dots, K\}$$
3. **Deterministic Deadline Pruning (Bound Constraints):**
   $$x_{i,s} = 0 \quad \forall (i, s) \text{ where } \hat{T}_{\text{turnaround, ms}}(s, r_i) > \text{SLO}_i$$
4. **Binary Domains:**
   $$x_{i,s} \in \{0, 1\}, \quad x_{i, \text{def}} \in \{0, 1\} \quad \forall i, s$$

**Verification & Solvability:**
- Solved to proven global optimality via standard Branch-and-Cut in `scipy.optimize.milp` using the open-source **HiGHS** solver engine.
- **Reporting Requirement:** The engine must inspect `res.status == 0` (`res.success == True`, HiGHS status `kOptimal`). Only solutions verified with status `kOptimal` may be reported as exact global optima.

---

### 5.2 Corrected QUBO Formulation with Slack-Variable Capacity Encoding

The problem is mapped to an unconstrained Quadratic Unconstrained Binary Optimization (QUBO) model:
$$\min_{\mathbf{z} \in \{0, 1\}^D} \mathbf{z}^T \mathbf{Q} \mathbf{z}$$

#### 5.2.1 Matrix Convention
We adopt the **standard upper-triangular matrix convention**:
$$E(\mathbf{z}) = \sum_{p=1}^D Q_{p,p} z_p + \sum_{p < q}^D Q_{p,q} z_p z_q$$
where $\mathbf{z} \in \{0, 1\}^D$ and $Q_{p,q}$ are real coefficients of $\mathbf{Q} \in \mathbb{R}^{D \times D}$.

#### 5.2.2 Variable Pruning & Index Mapping
Let $\mathcal{F}_i \subseteq \mathcal{S}$ denote the subset of servers that physically satisfy $\hat{T}_{\text{turnaround, ms}}(s, r_i) \le \text{SLO}_i$ and are not OFFLINE or DRAINING.
- **Variable Elimination:** Any variable $x_{i,s}$ for $s \notin \mathcal{F}_i$ is **strictly eliminated** from $\mathbf{z}$.
- If fixed-size mapping is required (e.g. for QAOA quantum circuit compilation), the variable is retained with an infinite diagonal barrier:
  $$Q_{(i,s), (i,s)} = +M_{\text{barrier}} \quad (M_{\text{barrier}} \ge 50.0)$$

#### 5.2.3 Normalization Parameters & Deferral Cost
- **Reference Energy ($E_{\max}$):**
  $$E_{\max} = \max_{(i, s) \in \mathcal{F}} E_{\text{marginal}}(s, r_i) \quad [\text{Joules}]$$
  (If all $E_{\text{marginal}} = 0$, $E_{\max} = 1.0\text{ J}$ by convention.)
- **Deferral Cost ($C_{\text{defer}, i}$):**
  $$C_{\text{defer}, i} = w_L \left(1.0 - \frac{\text{Slack}_i(t)}{\text{SLO}_i}\right) + w_E \cdot 0.25 \in [0.0, 1.0]$$
  This bounds deferral cost to $[0, 1]$, ensuring high-slack requests can be deferred when servers are loaded, while low-slack requests are prioritized.

#### 5.2.4 Exact One-Hot Assignment Penalty (Including Deferral)
Each request $r_i$ must be assigned to exactly one feasible server or deferred:
$$H_{\text{assign}, i} = \lambda_{\text{assign}} \left( \sum_{s \in \mathcal{F}_i} x_{i,s} + x_{i,\text{def}} - 1 \right)^2$$

Expanding using binary idempotency ($z_p^2 = z_p$):
$$\left( \sum_{u \in \mathcal{F}_i^+} x_{i,u} - 1 \right)^2 = 1 - \sum_{u \in \mathcal{F}_i^+} x_{i,u} + 2 \sum_{u < v \in \mathcal{F}_i^+} x_{i,u} x_{i,v} \quad (\mathcal{F}_i^+ = \mathcal{F}_i \cup \{s_{\text{def}}\})$$

Dropping constant $+1 \cdot \lambda_{\text{assign}}$:
- **Linear Diagonal Terms:**
  $$Q_{(i,s), (i,s)} = w_E \left(\frac{E_{\text{marginal}}(s, r_i)}{E_{\max}}\right) + w_L \left(\frac{\hat{T}_{\text{turnaround, ms}}(s, r_i)}{\text{SLO}_i}\right) - \lambda_{\text{assign}} \quad \forall s \in \mathcal{F}_i$$
  $$Q_{(i,\text{def}), (i,\text{def})} = C_{\text{defer}, i} - \lambda_{\text{assign}}$$
- **Off-Diagonal Interaction Terms ($u < v \in \mathcal{F}_i^+$):**
  $$Q_{(i,u), (i,v)} = +2 \lambda_{\text{assign}}$$

#### 5.2.5 Corrected Capacity Penalty with Slack Variables
For each server $s$ where available capacity $0 < C_s^{\text{avail}} < N$, we introduce binary slack variables $y_{s, m}$ to represent the integer slack $S_s \in \{0, \dots, C_s^{\text{avail}}\}$:
$$S_s = \sum_{m=0}^{M_s-1} 2^m y_{s,m} + R_s y_{s, M_s}$$
where $M_s = \lfloor \log_2 C_s^{\text{avail}} \rfloor$ and $R_s = C_s^{\text{avail}} - (2^{M_s} - 1)$.

$$H_{\text{cap}, s} = \lambda_{\text{cap}} \left( \sum_{i=1}^N x_{i,s} + \sum_{m=0}^{M_s-1} 2^m y_{s,m} + R_s y_{s, M_s} - C_s^{\text{avail}} \right)^2$$

- **Handling $C_s^{\text{avail}} = 0$:** If a server has zero capacity, $s$ is excluded from all $\mathcal{F}_i$; no slack variables are added.
- **Handling $C_s^{\text{avail}} \ge N$:** The constraint cannot be violated by a batch of size $N$; no slack variables or penalties are added.
- **Mathematical Calibration of Multipliers:**
  Since normalized costs satisfy $\max(w_E \hat{E} + w_L \hat{L}) \le 1.0$:
  $$\lambda_{\text{assign}} = 3.0, \quad \lambda_{\text{cap}} = 5.0$$
  This mathematically guarantees that constraint satisfaction strictly dominates objective minimization.

---

### 5.3 QUBO Dimension & QAOA Simulator Scalability

Total binary variables: $D = \sum_{i=1}^N (|\mathcal{F}_i| + 1) + \sum_{s: C_s^{\text{avail}} < N} (M_s + 1)$.
- For $N = 10$, $K = 3$: $D \approx 40\text{--}46$ variables.
- **Classical Simulation Footprint:** Simulating $D=46$ qubits via statevector requires $2^{46} \times 16\text{ bytes} \approx 1.13\text{ Petabytes}$ of RAM.
- **Resolved Resolution:**
  - **Classical Solvers (Simulated Annealing & HiGHS):** Handle the full batch size ($N \in [5, 12]$, $D \le 50$) in $< 10\text{ ms}$ on CPU.
  - **QAOA Circuit Simulation (Qiskit Aer):** Restricted to an isolated **reduced micro-batch benchmark**:
    $$N_{\text{QAOA}} = 2\text{ requests}, \quad K = 2\text{ servers} \implies D_{\text{QAOA}} = 2 \times 3 = 6\text{ to } 8\text{ qubits}$$
    This requires $< 100\text{ KB}$ RAM and executes in milliseconds on classical workstations.

---

## 6. Solver Suite & Transparent Terminology

```
+---------------------------------------------------------------------------------------------------+
|                                      SOLVER COMPARISON MATRIX                                     |
+--------------------------+-----------------------+-----------------------+------------------------+
| Solver Name              | Paradigm / Engine     | Formulation           | Deployment Medium      |
+--------------------------+-----------------------+-----------------------+------------------------+
| 1. Uniform Round-Robin   | Naive Baseline        | Sequential index      | Classical CPU          |
| 2. Greedy Energy-SLA     | Heuristic Baseline    | Priority filter       | Classical CPU          |
| 3. Simulated Annealing   | Classical Metaheur.   | QUBO Matrix           | Classical CPU (neal)   |
| 4. Exact Branch-and-Cut  | Classical Exact       | Constrained MILP      | Classical CPU (HiGHS)  |
| 5. Simulated QAOA        | Gate-based Quantum    | Ising Hamiltonian     | Qiskit Aer Simulator   |
+--------------------------+-----------------------+-----------------------+------------------------+
```

### 6.1 Accurate Terminology & Disambiguation
1. **`dwave-neal` is Classical Simulated Annealing (SA):**
   `dwave-neal` implements classical Markov Chain Monte Carlo (MCMC) simulated annealing using the Metropolis-Hastings criterion on classical CPUs. It does **not** perform simulated quantum annealing (SQA), does not simulate quantum tunneling, and is **not** a quantum algorithm. We classify it accurately as a **Classical Heuristic Annealer**.
2. **QAOA on Qiskit Simulator:**
   Simulating the Quantum Approximate Optimization Algorithm on a classical statevector simulator (e.g. `qiskit-aer`) models parameterized quantum circuits ($U(C, \gamma) U(B, \beta)$).
   **Scientific Integrity Requirement:** Classical simulation of quantum circuits on classical CPUs **does not prove quantum advantage**. It serves solely to validate quantum circuit compilation, parameter optimization convergence ($p=1, 2$), and theoretical feasibility on idealized qubits.

### 6.2 Evaluated Solver Suite

| Dimension | 1. Uniform Round-Robin (RR) | 2. Greedy Energy-with-SLO (GESF) | 3. Classical Simulated Annealing (`neal`) | 4. Exact Integer Solver (HiGHS / SciPy) | 5. QAOA Circuit Simulation (Qiskit) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Algorithm Type** | Deterministic baseline | Greedy heuristic ($O(N \log K)$) | Classical stochastic MCMC | Branch-and-cut / Simplex | Parameterized quantum ansatz ($p=1$) |
| **Mathematical Formulation** | Modulo index | Deterministic greedy | QUBO ($\mathbf{z}^T \mathbf{Q} \mathbf{z}$) | Constrained Linear MILP | Ising Hamiltonian ($H_C$) |
| **Optimality Guarantee** | None | Local greedy only | Approximate (heuristic) | **Exact Global Optimum** | Approximate ($\le \alpha$-approximation) |
| **Solver Runtime** | *[Target: $< 0.1$ ms]* | *[Target: $< 0.5$ ms]* | *[Target: $2\text{--}8$ ms]* | *[Target: $3\text{--}20$ ms]* | *[Target: $50\text{--}500$ ms for $D \le 8$]* |
| **Execution Medium** | Classical CPU | Classical CPU | Classical CPU (C-optimized) | Classical CPU (C++ compiled) | Classical CPU (Qiskit Aer) |
| **Batch Capacity** | $N \le 100$ | $N \le 100$ | $N \le 20$ ($D \le 100$) | $N \le 15$ ($D \le 60$) | $N \le 2$ ($D \le 8\text{ qubits}$) |

*(Note: All solver runtimes bracketed with [Target] are design assumptions pending empirical measurement under controlled hardware conditions.)*

---

## 7. Decision Engine Workflow & Fallback Safeguards

```
[Ingress Request Buffer]
           |
           v
[Stage 1: Adaptive Buffer Trigger] (Checks Count >= B_max, Timer >= tau_max, or Slack <= 25ms)
           |
           v
[Stage 2: Deterministic Feasibility Filter]
   - Filters OFFLINE / DRAINING servers
   - Prunes pairs where T_turnaround > SLO
   - Flags mathematically unachievable requests -> Immediate REJECT (HTTP 429/504)
           |
           v
[Stage 3: Optimization Problem Assembler]
   - Constructs Q matrix (QUBO with slack variables) or MILP constraint model
           |
           +---------------------------------------------+
           |                                             |
           v                                             v
[Stage 4A: Primary Solver (SA / QIA)]         [Stage 4B: QAOA Simulator (Benchmark)]
   - Enforces 15.0 ms Timeout Watchdog
           |
           +--- Timeout (> 15 ms) or Infeasible Solution ---+
           |                                                |
           v                                                v
[Stage 5: Constraint Validation Gate]             [Stage 4C: Safe Classical Fallback (GESF)]
   - Verifies sum(x) == 1                                   |
   - Verifies capacity ceilings                             |
   - Repaired if minor violation                            |
           |                                                |
           +<-----------------------------------------------+
           |
           v
[Stage 6: Dispatch Execution Directives] -> Sent to Part 2 Servers
           |
           v
[Stage 7: Decision Attribution & Audit Logger]
           |
           v
[Stage 8: Closed-Loop Telemetry Calibration]
```

### 7.1 Fallback Safeguard Trigger Rules
The system invokes the **Greedy Energy-with-SLO Filter (GESF)** fallback immediately if any of the following conditions occur:
1. **Solver Timeout:** Primary optimizer execution duration exceeds $T_{\text{budget}} = 15.0\text{ ms}$ `[Target Assumption]`.
2. **Infeasible Bitstring:** The optimizer returns an output violating single-assignment ($\sum_u x_{iu} \neq 1$) or exceeding hardware stream capacity.
3. **Execution Exception:** Solver raises an out-of-memory error, convergence failure, or numerical exception.

The fallback algorithm is deterministic, non-iterative, and guaranteed to complete in $< 0.5\text{ ms}$ `[Target Assumption]`.

---

## 8. Tiny Exhaustive-Enumeration Verification Test

To verify mathematical consistency between the exact constrained problem, the HiGHS MILP solver, and the QUBO matrix formulation, we specify a **Tiny Exhaustive Test Case**:

### 8.1 Test Case Parameters
- **Requests ($N = 2$):**
  - $r_1$: $T_{\text{ctx}} = 128$, $T_{\text{out}} = 64$, $\text{SLO} = 1500\text{ ms}$.
  - $r_2$: $T_{\text{ctx}} = 512$, $T_{\text{out}} = 128$, $\text{SLO} = 800\text{ ms}$.
- **Servers ($K = 2$):**
  - $s_1$: `srv_gpu_01` (Fast, high power: $P = 280\text{ W}$, $T_{\text{exec}} \approx 20\text{ ms}$, capacity $C_1 = 2$).
  - $s_2$: `srv_acc_02` (Balanced, low power: $P = 50\text{ W}$, $T_{\text{exec}} \approx 100\text{ ms}$, capacity $C_2 = 1$).
- **Candidate Options per Request:** $\mathcal{S}^+ = \{s_1, s_2, s_{\text{def}}\}$ (3 options).
- **Total Valid Assignment States:** $(K + 1)^N = 3^2 = 9$ discrete states:
  $\{(s_1, s_1), (s_1, s_2), (s_1, \text{def}), (s_2, s_1), (s_2, s_2), (s_2, \text{def}), (\text{def}, s_1), (\text{def}, s_2), (\text{def}, \text{def})\}$.

### 8.2 Expected Verification Behaviors
1. **Capacity Infeasibility:**
   The state $(s_2, s_2)$ assigns 2 requests to $s_2$ where capacity $C_2 = 1$. The slack QUBO penalty must evaluate to $\ge \lambda_{\text{cap}} = 5.0$, making its energy strictly higher than any valid assignment.
2. **Global Minimum Agreement:**
   The state minimizing the exact mathematical objective (expected: $(s_2, s_1)$ or $(s_1, s_2)$ depending on weights) must be:
   - Found as status `kOptimal` by HiGHS MILP.
   - Identified as the exact minimum energy bitstring $\mathbf{z}^*$ across all $2^D$ bitstrings evaluated by the QUBO matrix $\mathbf{z}^T \mathbf{Q} \mathbf{z}$.
3. **One-Hot Violation Penalties:**
   All bitstrings with $\sum_u x_{iu} \neq 1$ must incur positive multiples of $\lambda_{\text{assign}} = 3.0$, rendering them strictly uncompetitive.

---

## 9. Validated Citations & Evidence

1. **Fan, Weber, and Barroso (ISCA 2007):**
   *Power Provisioning for a Warehouse-sized Computer.* Proceedings of the 34th Annual International Symposium on Computer Architecture, pp. 13–23.
   *Relevance:* Established the non-linear server power formula $P(u) = P_{\text{idle}} + (P_{\text{peak}} - P_{\text{idle}})(2u - u^r)$ used in Part 2 and Part 3.
2. **Kwon et al. (SOSP 2023):**
   *Efficient Memory Management for Large Language Model Serving with PagedAttention.* Proceedings of the 29th ACM Symposium on Operating Systems Principles, pp. 611–626.
   *Relevance:* Foundational architecture for multi-stream LLM batching; focused on memory paging and throughput without optimizing non-linear electrical grid energy or heterogeneous power trade-offs.
3. **Farhi, Goldstone, and Gutmann (arXiv 2014):**
   *A Quantum Approximate Optimization Algorithm.* arXiv:1411.4028.
   *Relevance:* Defines the gate-based QAOA circuit formulation implemented in Qiskit for comparison.
4. **Lucas (Frontiers in Physics 2014):**
   *Ising Formulations of Many NP Problems.* Frontiers in Physics, Vol. 2, p. 5.
   *Relevance:* Mathematical derivations for mapping assignment, matching, and knapsack constraints to unconstrained binary quadratic forms (QUBO).
5. **Guerreschi and Matsuura (Scientific Reports 2019):**
   *QAOA for Max-Cut Requires Hundreds of Qubits for Quantum Speedup.* Scientific Reports, Vol. 9, Art. 6903.
   *Relevance:* Demonstrated that for small-scale combinatorial problems ($< 100$ variables), classical heuristics and exact solvers routinely outperform QAOA in execution time and solution quality due to circuit depth and classical parameter optimization overhead.

---

## 10. Key Equations Summary

1. **Exact Linear Integer Optimization Objective:**
   $$\min_{\mathbf{x}} J(\mathbf{x}) = \sum_{i=1}^N \sum_{s=1}^K x_{i,s} \left[ w_E \left(\frac{E_{\text{marginal}}(s, r_i)}{E_{\max}}\right) + w_L \left(\frac{\hat{T}_{\text{turnaround, ms}}(s, r_i)}{\text{SLO}_i}\right) \right] + \sum_{i=1}^N x_{i, \text{def}} C_{\text{defer}, i}$$

2. **Chassis-Safe Marginal Dynamic Energy ($J$):**
   $$\Delta P(s, r_i) = P_s\left(\frac{M_s + 1}{M_{\max, s}}\right) - P_s\left(\frac{M_s}{M_{\max, s}}\right) \quad [\text{W}]$$
   $$E_{\text{marginal}}(s, r_i) = \Delta P(s, r_i) \cdot \left(\frac{\hat{T}_{\text{exec, ms}}(s, r_i)}{1000.0}\right) \quad [\text{J}]$$

3. **Two-Phase Execution Latency Conversion:**
   $$\hat{T}_{\text{exec, ms}}(s, r_i \mid k_s) = \left[ \frac{T_{\text{ctx}, i}}{R_{\text{prefill}, s} \cdot (M_s + k_s + 1)^{0.15}} + \frac{T_{\text{out}, i}}{R_{\text{decode}, s}} \cdot (1.0 + 0.04 \cdot (M_s + k_s)) \right] \times 1000.0 \quad [\text{ms}]$$

4. **QUBO One-Hot Assignment Penalty (Including Deferral):**
   $$H_{\text{assign}, i} = -\lambda_{\text{assign}} \sum_{u \in \mathcal{F}_i^+} x_{i,u} + 2\lambda_{\text{assign}} \sum_{u < v \in \mathcal{F}_i^+} x_{i,u} x_{i,v} \quad (\mathcal{F}_i^+ = \mathcal{F}_i \cup \{s_{\text{def}}\})$$

5. **QUBO Slack Capacity Penalty:**
   $$H_{\text{cap}, s} = \lambda_{\text{cap}} \left( \sum_{i=1}^N x_{i,s} + \sum_{m=0}^{M_s-1} 2^m y_{s,m} + R_s y_{s, M_s} - C_s^{\text{avail}} \right)^2$$

---

## 11. Concise List of Unresolved Engineering Assumptions

The following items are explicitly recorded as **unverified engineering assumptions** pending physical testbench verification:
1. **Part 2 Hardware Execution Rates:** The nominal prefill speeds ($12000, 3200, 650\text{ tok/s}$) and decode speeds ($85, 38, 12\text{ tok/s}$) are simulation baselines derived from hardware specs; they are not yet calibrated against physical H100 PCIe, L4, or Xeon 8480+ testbenches.
2. **Inter-Stream Decode Contention Factor ($\alpha = 0.04$):** The linear 4% degradation per stream is an analytical proxy for DRAM bus saturation under continuous batching; empirical calibration with varying KV-cache sizes is required.
3. **Solver Runtimes:** All bracketed solver runtimes (e.g. $[2\text{--}8\text{ ms}]$ for SA, $[3\text{--}20\text{ ms}]$ for HiGHS) are design targets and have not yet been measured on targeted hardware architectures.
4. **Fan et al. Power Exponents:** Exponents ($r = 1.35$ GPU, $1.40$ Tensor, $1.10$ CPU) are working assumptions from published literature pending physical power meter validation.

---

## 12. Minimum Validation Checklist & Experiment Plan (IBM Z / LinuxONE Compatible)

### 12.1 Platform Portability & Architecture Constraints
The implementation strictly adheres to platform portability constraints compatible with standard enterprise Linux distributions on `s390x` (IBM Z / LinuxONE) and `x86_64`:
- **Python Version:** Python 3.10 / 3.11 / 3.12.
- **Dependencies:**
  - `numpy`, `scipy` (core matrix manipulations; native s390x wheel availability).
  - `dwave-neal` (pure-C / OpenMP simulated annealing; zero proprietary GPU/x86 dependencies).
  - `qiskit`, `qiskit-aer` (for baseline QAOA circuit execution).
  - `pydantic` v2 (data schema enforcement).

### 12.2 Minimum Phased Milestones

```
Phase 1: Mathematical Module & Feasibility Gate
├── Implement request pre-filtering (pruning deadline-infeasible pairs & offline servers).
├── Implement Adaptive Slack-Aware Ingress Buffer (arrival rate & slack monitoring).
└── Unit test: Verify zero-deadline-violation pruning and exact QUBO penalty expansion.

Phase 2: Multi-Solver Suite Implementation
├── Solver 1: Uniform Round-Robin (FIFO-RR).
├── Solver 2: Greedy Energy-with-SLO Filter (GESF - Fallback).
├── Solver 3: Classical Simulated Annealing (dwave-neal).
├── Solver 4: Exact Branch-and-Cut MILP (HiGHS via scipy.optimize.milp).
└── Solver 5: QAOA on Qiskit Aer Statevector simulator (reduced-batch benchmark, D <= 8).

Phase 3: Automated Experimental Evaluation & Reporting
├── Execute Section 8 Tiny Exhaustive-Enumeration Test (N=2, K=2) validating QUBO == HiGHS.
├── Benchmark all 5 solvers across Part 1 Scenarios 1–4.
├── Empirically measure solver runtimes (mean, p95, p99 ms) under CPU pinning.
├── Sweep objective weights w_E in [0.0, 1.0] to plot empirical Pareto frontiers.
└── Conduct paired Wilcoxon signed-rank tests (alpha = 0.01) across 10 random seeds.
```

---

*End of Technical Specification — QuantaSHI Part 3: Decision Engine and Quantum Optimization*
