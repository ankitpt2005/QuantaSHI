"""
QUBO Matrix Builder and Mathematical Embedding Engine.
Constructs verified upper-triangular Q matrix including one-hot assignment with deferral
and slack-variable capacity encoding.
"""

from __future__ import annotations
import math
from typing import Dict, List, Tuple, Any
import numpy as np

from user_interface.models import InferenceRequest
from server_interface.cluster import VirtualDataCentre
from .models import OptimizationWeights
from .feasibility import prefilter_request_feasibility, FeasibleServerEvaluation


class QUBOMatrixModel:
    """Represents an assembled QUBO problem with variable mapping and metadata."""

    def __init__(
        self,
        Q: np.ndarray,
        var_names: List[str],
        var_indices: Dict[str, int],
        req_options: Dict[str, List[str]],
        server_slacks: Dict[str, List[Tuple[str, int]]],
        e_max_j: float,
        lambda_assign: float = 3.0,
        lambda_cap: float = 5.0,
    ):
        self.Q = Q  # Upper-triangular matrix of shape (D, D)
        self.D = Q.shape[0]
        self.var_names = var_names
        self.var_indices = var_indices
        self.req_options = req_options
        self.server_slacks = server_slacks
        self.e_max_j = e_max_j
        self.lambda_assign = lambda_assign
        self.lambda_cap = lambda_cap

    def evaluate_energy(self, bitstring: np.ndarray | List[int]) -> float:
        """Evaluates E(z) = z^T Q z under upper-triangular convention."""
        z = np.asarray(bitstring, dtype=float)
        return float(np.dot(z, np.dot(self.Q, z)))


def build_qubo_model(
    batch: List[InferenceRequest],
    cluster: VirtualDataCentre,
    weights: OptimizationWeights,
    current_time_sec: float,
    lambda_assign: float = 3.0,
    lambda_cap: float = 5.0,
) -> QUBOMatrixModel:
    """
    Constructs the exact upper-triangular QUBO matrix Q from batch and server state.
    """
    weights.validate()
    n_reqs = len(batch)

    # 1. Evaluate profiles and determine feasible servers F_i
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

    # Find E_max across all feasible options in the batch
    all_energies = [
        eval_res.marginal_energy_j
        for p in profiles
        for eval_res in p.feasible_servers.values()
    ]
    e_max_j = max(all_energies) if all_energies and max(all_energies) > 0 else 1.0

    # 2. Build variable index mapping
    var_names: List[str] = []
    var_indices: Dict[str, int] = {}
    req_options: Dict[str, List[str]] = {}

    for req, prof in zip(batch, profiles):
        opts: List[str] = []
        # Feasible servers for request i
        for s_id in sorted(prof.feasible_servers.keys()):
            vname = f"x_{req.request_id}_{s_id}"
            var_indices[vname] = len(var_names)
            var_names.append(vname)
            opts.append(vname)

        # Deferral variable for request i
        vname_def = f"x_{req.request_id}_def"
        var_indices[vname_def] = len(var_names)
        var_names.append(vname_def)
        opts.append(vname_def)

        req_options[req.request_id] = opts

    # Capacity slack variables for constrained servers
    server_slacks: Dict[str, List[Tuple[str, int]]] = {}
    for s_id, server in sorted(cluster.servers.items()):
        c_avail = max(0, server.config.max_streams - len(server.active_streams))
        # Add slacks only if 0 < c_avail < N (if c_avail >= N, capacity cannot be breached)
        if 0 < c_avail < n_reqs:
            m_s = int(math.floor(math.log2(c_avail)))
            slacks: List[Tuple[str, int]] = []
            for bit in range(m_s):
                weight = 1 << bit
                y_name = f"y_{s_id}_{bit}"
                var_indices[y_name] = len(var_names)
                var_names.append(y_name)
                slacks.append((y_name, weight))

            rem = c_avail - ((1 << m_s) - 1)
            if rem > 0:
                y_name_rem = f"y_{s_id}_rem"
                var_indices[y_name_rem] = len(var_names)
                var_names.append(y_name_rem)
                slacks.append((y_name_rem, rem))

            server_slacks[s_id] = slacks

    D = len(var_names)
    Q = np.zeros((D, D), dtype=float)

    # 3. Populate Objective and One-Hot Assignment Penalties
    for req, prof in zip(batch, profiles):
        # A. Feasible Server Variables
        for s_id, eval_res in prof.feasible_servers.items():
            idx = var_indices[f"x_{req.request_id}_{s_id}"]
            e_norm = min(1.0, max(0.0, eval_res.marginal_energy_j / e_max_j))
            l_norm = min(1.0, max(0.0, eval_res.t_turnaround_ms / req.deadline_slo_ms))

            c_obj = (weights.weight_energy * e_norm) + (weights.weight_latency * l_norm)
            # Diagonal: Linear objective cost - lambda_assign
            Q[idx, idx] += (c_obj - lambda_assign)

        # B. Deferral Variable
        def_idx = var_indices[f"x_{req.request_id}_def"]
        slack_ms = max(0.0, min(req.deadline_slo_ms, eval_res.slack_ms if prof.feasible_servers else 0.0))
        c_defer = 1.0 + (weights.weight_latency * (1.0 - (slack_ms / req.deadline_slo_ms))) + (weights.weight_energy * 0.25)
        Q[def_idx, def_idx] += (c_defer - lambda_assign)

        # C. Mutual Exclusion Pairwise Interactions: +2 * lambda_assign
        opts = req_options[req.request_id]
        for i_opt in range(len(opts)):
            u_idx = var_indices[opts[i_opt]]
            for j_opt in range(i_opt + 1, len(opts)):
                v_idx = var_indices[opts[j_opt]]
                p = min(u_idx, v_idx)
                q = max(u_idx, v_idx)
                Q[p, q] += 2.0 * lambda_assign

    # 4. Populate Server Capacity Penalties with Slack Variables
    # H_cap = lambda_cap * ( sum_i x_is + sum_m w_m y_sm - C_avail )^2
    for s_id, slacks in server_slacks.items():
        c_avail = max(0, cluster.servers[s_id].config.max_streams - len(cluster.servers[s_id].active_streams))
        # Identify all assignment variables for server s_id in this batch
        x_vars = [var_indices[f"x_{req.request_id}_{s_id}"] for req in batch if f"x_{req.request_id}_{s_id}" in var_indices]
        if not x_vars:
            continue

        # Term expansion: ( sum_k w_k z_k - C_avail )^2
        # where z_k includes x_is (weight=1) and y_sm (weight=w_m)
        all_terms: List[Tuple[int, float]] = [(idx, 1.0) for idx in x_vars]
        for y_name, w in slacks:
            all_terms.append((var_indices[y_name], float(w)))

        # Linear diagonal terms: lambda_cap * (w_k^2 - 2 * w_k * C_avail)
        for idx, w in all_terms:
            Q[idx, idx] += lambda_cap * (w * w - 2.0 * w * c_avail)

        # Off-diagonal cross terms: +2 * lambda_cap * w_k * w_l
        for i_t in range(len(all_terms)):
            idx_1, w_1 = all_terms[i_t]
            for j_t in range(i_t + 1, len(all_terms)):
                idx_2, w_2 = all_terms[j_t]
                p = min(idx_1, idx_2)
                q = max(idx_1, idx_2)
                Q[p, q] += 2.0 * lambda_cap * w_1 * w_2

    return QUBOMatrixModel(
        Q=Q,
        var_names=var_names,
        var_indices=var_indices,
        req_options=req_options,
        server_slacks=server_slacks,
        e_max_j=e_max_j,
        lambda_assign=lambda_assign,
        lambda_cap=lambda_cap,
    )
