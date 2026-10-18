"""
Command-Line Interface for Part 1: Users (Workload Generator).
Allows generating, benchmarking, and exporting inference request traces to JSON.
"""

import argparse
import json
import os
import sys
from .generator import WorkloadGenerator, SimulationScenario


def main():
    parser = argparse.ArgumentParser(
        description="QuantaSHI - Part 1: Users (AI Inference Workload Generator)"
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default="SCENARIO_1_STEADY_STATE",
        choices=[s.value for s in SimulationScenario],
        help="Workload scenario to execute",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=60.0,
        help="Simulation duration in seconds (default: 60.0s)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Path to output JSON trace file",
    )
    parser.add_argument(
        "--export-topology",
        type=str,
        default=None,
        help="Path to export the 100-user network graph topology JSON",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        default=True,
        help="Print summary statistics",
    )

    args = parser.parse_args()

    scenario = SimulationScenario(args.scenario)
    generator = WorkloadGenerator(seed=42)

    print(f"\n=======================================================")
    print(f" QuantaSHI Workload Generator - Part 1: Users")
    print(f" Scenario: {scenario.value}")
    print(f" Duration: {args.duration}s | Virtual Users: 100")
    print(f"=======================================================\n")

    if args.export_topology:
        os.makedirs(os.path.dirname(os.path.abspath(args.export_topology)), exist_ok=True)
        topo_data = generator.topology.get_topology_payload()
        with open(args.export_topology, "w", encoding="utf-8") as f:
            json.dump(topo_data, f, indent=2)
        print(f"[+] Exported topology ({topo_data['num_nodes']} nodes, {topo_data['num_edges']} edges) to: {args.export_topology}")

    requests = generator.generate_trace(duration_seconds=args.duration, scenario=scenario)

    if args.summary:
        num_reqs = len(requests)
        qps = num_reqs / args.duration if args.duration > 0 else 0
        total_in_tokens = sum(r.context_tokens for r in requests)
        total_out_tokens = sum(r.max_output_tokens for r in requests)
        avg_deadline = sum(r.deadline_slo_ms for r in requests) / max(1, num_reqs)

        p0_count = sum(1 for r in requests if r.priority_level == 0)
        p1_count = sum(1 for r in requests if r.priority_level == 1)
        p2_count = sum(1 for r in requests if r.priority_level == 2)

        print(f"Total Requests Generated : {num_reqs}")
        print(f"Average Ingress Rate     : {qps:.1f} req/s")
        print(f"Total Prompt Tokens (In) : {total_in_tokens:,} tokens")
        print(f"Total Output Tokens (Out): {total_out_tokens:,} tokens")
        print(f"Average Deadline SLO     : {avg_deadline:.1f} ms")
        print(f"Priority Split           : P0: {p0_count} ({p0_count/max(1,num_reqs)*100:.1f}%), "
              f"P1: {p1_count} ({p1_count/max(1,num_reqs)*100:.1f}%), "
              f"P2: {p2_count} ({p2_count/max(1,num_reqs)*100:.1f}%)")
        print(f"First Request Timestamp  : {requests[0].arrival_timestamp:.3f}s")
        print(f"Last Request Timestamp   : {requests[-1].arrival_timestamp:.3f}s")
        print(f"-------------------------------------------------------")

    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        trace_dicts = [r.to_dict() for r in requests]
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(trace_dicts, f, indent=2)
        print(f"[+] Saved {len(requests)} requests to: {args.output}\n")


if __name__ == "__main__":
    main()
