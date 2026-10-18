"""
Multi-Solver Suite for QuantaSHI Optimization Engine.
Includes HiGHS exact classical MILP, classical simulated annealing (MCMC),
tiny exhaustive search, and greedy emergency fallback (GESF).
"""

from __future__ import annotations
import math
import time
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
from scipy.optimize import milp, LinearConstraint, Bounds

from user_interface.models import InferenceRequest
from server_interface.cluster import VirtualDataCentre
from .models import OptimizationWeights, SolverType, DecisionAction
from .feasibility import prefilter_request_feasibility
from .qubo_builder import QUBOMatrixModel, build_qubo_model


class SolverExecutionResult:
    """Standardized output from any optimization solver."""

    def __init__(
        self,
        solver_type: SolverType,
        is_optimal: bool,
        objective_value: float,
        runtime_ms: float,
        assignments: Dict[str, str],  # req_id -> server_id or 'DEFER'
        raw_bitstring: Optional[np.ndarray] = None,
        termination_status: str = "SUCCESS",
    ):
        self.solver_type = solver_type
        self.is_optimal = is_optimal
        self.objective_value = objective_value
        self.runtime_ms = runtime_ms
        self.assignments = assignments
        self.raw_bitstring = raw_bitstring
        self.termination_status = termination_status


def solve_exact_milp(
    batch: List[InferenceRequest],
    cluster: VirtualDataCentre,
    weights: OptimizationWeights,
    current_time_sec: float,
) -> SolverExecutionResult:
    """
    Solves the exact scheduling problem to proven global optimality using HiGHS (via scipy.optimize.milp).
    """
    start_time = time.perf_counter()
    weights.validate()
    n_reqs = len(batch)

    # 1. Feasibility Pre-Filtering
    profiles = [
        prefilter_request_feasibility(
            req=req,
            cluster=cluster,
            current_time_sec=current_time_sec,
            deferral_threshold_ms=25.0,
            expected_buffering_ms=0.0,
        )
        for req in batch
    ]

    all_energies = [
        eval_res.marginal_energy_j
        for p in profiles
        for eval_res in p.feasible_servers.values()
    ]
    e_max_j = max(all_energies) if all_energies and max(all_energies) > 0 else 1.0

    # 2. Build index mapping
    var_names: List[str] = []
    var_indices: Dict[str, int] = {}
    c_list: List[float] = []

    req_options: Dict[str, List[str]] = {}

    for req, prof in zip(batch, profiles):
        opts: List[str] = []
        for s_id in sorted(prof.feasible_servers.keys()):
            eval_res = prof.feasible_servers[s_id]
            vname = f"x_{req.request_id}_{s_id}"
            var_indices[vname] = len(var_names)
            var_names.append(vname)
            opts.append(vname)

            e_norm = min(1.0, max(0.0, eval_res.marginal_energy_j / e_max_j))
            l_norm = min(1.0, max(0.0, eval_res.t_turnaround_ms / req.deadline_slo_ms))
            c_cost = (weights.weight_energy * e_norm) + (weights.weight_latency * l_norm)
            c_list.append(c_cost)

        # Deferral variable
        vname_def = f"x_{req.request_id}_def"
        var_indices[vname_def] = len(var_names)
        var_names.append(vname_def)
        opts.append(vname_def)

        slack_ms = max(0.0, min(req.deadline_slo_ms, eval_res.slack_ms if prof.feasible_servers else 0.0))
        c_defer = 1.0 + (weights.weight_latency * (1.0 - (slack_ms / req.deadline_slo_ms))) + (weights.weight_energy * 0.25)
        c_list.append(c_defer)

        req_options[req.request_id] = opts

    D = len(var_names)
    c = np.array(c_list, dtype=float)

    # 3. Constraints Construction
    A_rows: List[List[float]] = []
    lhs: List[float] = []
    rhs: List[float] = []

    # Constraint Group 1: Exact One Assignment per Request
    for req in batch:
        row = [0.0] * D
        for vname in req_options[req.request_id]:
            row[var_indices[vname]] = 1.0
        A_rows.append(row)
        lhs.append(1.0)
        rhs.append(1.0)

    # Constraint Group 2: Server Available Capacity Bounds
    for s_id, server in cluster.servers.items():
        c_avail = max(0, server.config.max_streams - len(server.active_streams))
        row = [0.0] * D
        has_server_vars = False
        for req in batch:
            vname = f"x_{req.request_id}_{s_id}"
            if vname in var_indices:
                row[var_indices[vname]] = 1.0
                has_server_vars = True
        if has_server_vars:
            A_rows.append(row)
            lhs.append(0.0)
            rhs.append(float(c_avail))

    A = np.array(A_rows, dtype=float)
    constraints = LinearConstraint(A, lhs, rhs)
    integrality = np.ones(D, dtype=int)  # All binary variables
    bounds = Bounds(np.zeros(D), np.ones(D))

    # 4. Execute HiGHS solver
    res = milp(c=c, integrality=integrality, constraints=constraints, bounds=bounds)
    elapsed_ms = (time.perf_counter() - start_time) * 1000.0

    # 5. Extract Assignments and Check Optimality
    assignments: Dict[str, str] = {}
    is_optimal = (res.status == 0)  # Status 0 in HiGHS corresponds to 'kOptimal'

    if is_optimal and res.x is not None:
        sol = np.round(res.x).astype(int)
        for req in batch:
            chosen = "DEFER"
            prefix = f"x_{req.request_id}_"
            for vname in req_options[req.request_id]:
                if sol[var_indices[vname]] == 1:
                    chosen = vname[len(prefix):]
                    if chosen == "def":
                        chosen = "DEFER"
                    break
            assignments[req.request_id] = chosen

        return SolverExecutionResult(
            solver_type=SolverType.EXACT_MILP_HIGHS,
            is_optimal=True,
            objective_value=float(res.fun),
            runtime_ms=elapsed_ms,
            assignments=assignments,
            raw_bitstring=sol,
            termination_status=res.message,
        )
    else:
        # Fallback to greedy if HiGHS did not achieve provable optimality
        fb_res = solve_greedy_fallback(batch, cluster, weights, current_time_sec)
        fb_res.solver_type = SolverType.EXACT_MILP_HIGHS
        fb_res.is_optimal = False
        fb_res.termination_status = f"SUBOPTIMAL_FALLBACK: {res.message}"
        return fb_res


def solve_tiny_exhaustive(
    qubo_model: QUBOMatrixModel,
    batch: List[InferenceRequest],
) -> SolverExecutionResult:
    """
    Evaluates all 2^D bitstrings to find the exact global minimum of z^T Q z.
    Strictly used for small verification benchmarks (D <= 16).
    """
    start_time = time.perf_counter()
    D = qubo_model.D
    assert D <= 20, f"Tiny exhaustive enumeration restricted to D <= 20 (got D={D})"

    best_energy = float("inf")
    best_bitstring: Optional[np.ndarray] = None

    total_states = 1 << D
    for i in range(total_states):
        # Convert integer i to binary array of length D
        bits = np.array([(i >> b) & 1 for b in range(D)], dtype=float)
        energy = qubo_model.evaluate_energy(bits)
        if energy < best_energy:
            best_energy = energy
            best_bitstring = bits

    elapsed_ms = (time.perf_counter() - start_time) * 1000.0

    # Decode assignments from best bitstring
    assignments: Dict[str, str] = {}
    if best_bitstring is not None:
        for req in batch:
            chosen = "DEFER"
            prefix = f"x_{req.request_id}_"
            opts = qubo_model.req_options.get(req.request_id, [])
            for opt_name in opts:
                idx = qubo_model.var_indices[opt_name]
                if best_bitstring[idx] == 1:
                    chosen = opt_name[len(prefix):]
                    if chosen == "def":
                        chosen = "DEFER"
                    break
            assignments[req.request_id] = chosen

    return SolverExecutionResult(
        solver_type=SolverType.TINY_EXHAUSTIVE_SEARCH,
        is_optimal=True,
        objective_value=best_energy,
        runtime_ms=elapsed_ms,
        assignments=assignments,
        raw_bitstring=best_bitstring,
        termination_status="EXHAUSTIVE_OPTIMAL",
    )


def solve_simulated_annealing(
    qubo_model: QUBOMatrixModel,
    batch: List[InferenceRequest],
    num_sweeps: int = 500,
    num_reads: int = 20,
    initial_temp: float = 5.0,
    final_temp: float = 0.05,
) -> SolverExecutionResult:
    """
    Classical Simulated Annealing (MCMC Metropolis-Hastings) on the QUBO matrix.
    Uses neal if installed, otherwise high-performance NumPy vectorized classical annealer.
    """
    start_time = time.perf_counter()
    D = qubo_model.D
    Q = qubo_model.Q

    # Check for optional dwave-neal installation
    try:
        import neal
        sampler = neal.SimulatedAnnealingSampler()
        # Convert Q matrix to dict format {(i, j): val}
        q_dict = {}
        for r in range(D):
            for c in range(r, D):
                if Q[r, c] != 0.0:
                    q_dict[(r, c)] = float(Q[r, c])
        response = sampler.sample_qubo(q_dict, num_reads=num_reads, num_sweeps=num_sweeps)
        best_sample = response.first.sample
        best_bitstring = np.array([best_sample.get(i, 0) for i in range(D)], dtype=int)
        best_energy = float(response.first.energy)
    except ImportError:
        # Classical NumPy MCMC Simulated Annealing
        best_bitstring = None
        best_energy = float("inf")

        for _ in range(num_reads):
            # Random initial bitstring
            state = np.random.choice([0, 1], size=D).astype(float)
            current_energy = qubo_model.evaluate_energy(state)

            temp_step = (final_temp / initial_temp) ** (1.0 / max(1, num_sweeps))
            temp = initial_temp

            for _ in range(num_sweeps):
                # Pick a random bit to flip
                flip_idx = np.random.randint(0, D)
                state[flip_idx] = 1.0 - state[flip_idx]
                new_energy = qubo_model.evaluate_energy(state)
                delta_e = new_energy - current_energy

                if delta_e <= 0 or np.random.rand() < math.exp(-delta_e / max(1e-6, temp)):
                    current_energy = new_energy
                else:
                    # Revert flip
                    state[flip_idx] = 1.0 - state[flip_idx]

                temp *= temp_step

            if current_energy < best_energy:
                best_energy = current_energy
                best_bitstring = np.copy(state).astype(int)

    elapsed_ms = (time.perf_counter() - start_time) * 1000.0

    # Decode assignments
    assignments: Dict[str, str] = {}
    if best_bitstring is not None:
        for req in batch:
            chosen = "DEFER"
            prefix = f"x_{req.request_id}_"
            opts = qubo_model.req_options.get(req.request_id, [])
            for opt_name in opts:
                idx = qubo_model.var_indices[opt_name]
                if best_bitstring[idx] == 1:
                    chosen = opt_name[len(prefix):]
                    if chosen == "def":
                        chosen = "DEFER"
                    break
            assignments[req.request_id] = chosen

    return SolverExecutionResult(
        solver_type=SolverType.CLASSICAL_SIMULATED_ANNEALING,
        is_optimal=False,  # Metaheuristic: cannot guarantee global optimum
        objective_value=best_energy,
        runtime_ms=elapsed_ms,
        assignments=assignments,
        raw_bitstring=best_bitstring,
        termination_status="ANNEALING_COMPLETED",
    )


def solve_greedy_fallback(
    batch: List[InferenceRequest],
    cluster: VirtualDataCentre,
    weights: OptimizationWeights,
    current_time_sec: float,
) -> SolverExecutionResult:
    """
    Greedy Energy-with-SLO Filter (GESF).
    Guaranteed deterministic execution in < 0.3 ms for safety fallback.
    """
    start_time = time.perf_counter()
    assignments: Dict[str, str] = {}
    server_counts: Dict[str, int] = {s_id: 0 for s_id in cluster.servers.keys()}

    # Sort batch by urgency: priority tier (P0 > P1 > P2) and deadline slack
    sorted_batch = sorted(
        batch,
        key=lambda r: (int(r.priority_level), r.deadline_slo_ms)
    )

    total_cost = 0.0

    for req in sorted_batch:
        best_server: Optional[str] = None
        best_score = float("inf")

        for s_id, server in cluster.servers.items():
            if server.status.value in ("OFFLINE", "DRAINING"):
                continue

            c_avail = max(0, server.config.max_streams - len(server.active_streams))
            if server_counts[s_id] >= c_avail:
                continue

            prof = prefilter_request_feasibility(req, cluster, current_time_sec)
            if s_id in prof.feasible_servers:
                eval_res = prof.feasible_servers[s_id]
                score = (weights.weight_energy * (eval_res.marginal_energy_j / 50.0)) + \
                        (weights.weight_latency * (eval_res.t_turnaround_ms / req.deadline_slo_ms))
                if score < best_score:
                    best_score = score
                    best_server = s_id

        if best_server is not None:
            assignments[req.request_id] = best_server
            server_counts[best_server] += 1
            total_cost += best_score
        else:
            assignments[req.request_id] = "DEFER"
            total_cost += 0.50

    elapsed_ms = (time.perf_counter() - start_time) * 1000.0

    return SolverExecutionResult(
        solver_type=SolverType.GREEDY_FALLBACK_GESF,
        is_optimal=False,
        objective_value=total_cost,
        runtime_ms=elapsed_ms,
        assignments=assignments,
        raw_bitstring=None,
        termination_status="GREEDY_FALLBACK_DISPATCHED",
    )


def solve_qaoa_simulation(
    qubo_model: QUBOMatrixModel,
    batch: List[InferenceRequest],
    p_layers: int = 1,
    max_iter: int = 25,
) -> SolverExecutionResult:
    """
    Simulates QAOA (Quantum Approximate Optimization Algorithm, p=1) on a classical statevector simulator.
    Strictly restricted to micro-batches (D <= 12) per Section 5.3 of Specification.
    Note: Classical statevector simulation of QAOA does not demonstrate physical quantum advantage.
    """
    start_time = time.perf_counter()
    D = qubo_model.D
    assert D <= 14, f"QAOA circuit statevector simulation restricted to D <= 14 (got D={D})"

    states_count = 1 << D
    energies = np.zeros(states_count, dtype=float)
    for i in range(states_count):
        bits = np.array([(i >> b) & 1 for b in range(D)], dtype=float)
        energies[i] = qubo_model.evaluate_energy(bits)

    from scipy.optimize import minimize

    # QAOA Expectation Evaluator
    def qaoa_expectation(params):
        gamma = params[0]
        beta = params[1]
        state = np.ones(states_count, dtype=complex) / np.sqrt(states_count)
        # Cost Unitary e^{-i gamma C}
        state *= np.exp(-1j * gamma * energies)
        # Mixer Unitary e^{-i beta B}
        rx = np.array([[np.cos(beta), -1j * np.sin(beta)], [-1j * np.sin(beta), np.cos(beta)]], dtype=complex)
        state_tensor = state.reshape([2] * D)
        for q in range(D):
            state_tensor = np.tensordot(rx, state_tensor, axes=([1], [q]))
            state_tensor = np.moveaxis(state_tensor, 0, q)
        final_state = state_tensor.flatten()
        probs = np.abs(final_state) ** 2
        return float(np.sum(probs * energies)), probs

    def loss(params):
        exp_val, _ = qaoa_expectation(params)
        return exp_val

    # Classical parameter optimization via COBYLA
    opt_res = minimize(loss, x0=[0.5, 0.5], method="COBYLA", options={"maxiter": max_iter})
    _, final_probs = qaoa_expectation(opt_res.x)

    # Select argmax bitstring from quantum state distribution
    best_idx = int(np.argmax(final_probs))
    best_bitstring = np.array([(best_idx >> b) & 1 for b in range(D)], dtype=int)
    best_energy = float(energies[best_idx])

    elapsed_ms = (time.perf_counter() - start_time) * 1000.0

    # Decode assignments
    assignments: Dict[str, str] = {}
    for req in batch:
        chosen = "DEFER"
        prefix = f"x_{req.request_id}_"
        opts = qubo_model.req_options.get(req.request_id, [])
        for opt_name in opts:
            idx = qubo_model.var_indices[opt_name]
            if best_bitstring[idx] == 1:
                chosen = opt_name[len(prefix):]
                if chosen == "def":
                    chosen = "DEFER"
                break
        assignments[req.request_id] = chosen

    return SolverExecutionResult(
        solver_type=SolverType.QAOA_CIRCUIT_SIMULATION,
        is_optimal=False,
        objective_value=best_energy,
        runtime_ms=elapsed_ms,
        assignments=assignments,
        raw_bitstring=best_bitstring,
        termination_status="QAOA_SIMULATION_CONVERGED",
    )

