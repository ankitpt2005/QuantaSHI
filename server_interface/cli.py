"""
CLI testing tool for Part 2: Servers (Virtual Data Centre).
Dispatches sample synthetic requests to the 3 heterogeneous servers and prints execution telemetry.
"""

import argparse
import time
from .cluster import VirtualDataCentre
from .models import ExecutionTask


def main():
    parser = argparse.ArgumentParser(description="QuantaSHI Server Cluster Simulator CLI")
    parser.add_argument("--tasks", type=int, default=10, help="Number of sample tasks to simulate")
    parser.add_argument("--target", type=str, default="srv_gpu_01", choices=["srv_gpu_01", "srv_acc_02", "srv_cpu_03", "all"])
    args = parser.parse_args()

    vdc = VirtualDataCentre()
    print("=" * 64)
    print(" QuantaSHI - Virtual Data Centre Server Cluster CLI")
    print("=" * 64)
    print(f"[+] Initial cluster power: {vdc.get_cluster_power_w():.1f} W (idle baseline)")

    targets = ["srv_gpu_01", "srv_acc_02", "srv_cpu_03"] if args.target == "all" else [args.target]

    for i in range(args.tasks):
        srv_id = targets[i % len(targets)]
        task = ExecutionTask(
            request_id=f"req_{i+1:04d}",
            user_id=f"usr_{(i%100)+1:02d}",
            workload_type="TEXT_CHAT" if i % 2 == 0 else "RAG_QA",
            context_tokens=256 + (i * 50),
            max_output_tokens=128,
            deadline_slo_ms=1200,
            priority_level="P1_INTERACTIVE",
            arrival_time=0.0,
        )
        vdc.dispatch_to_server(srv_id, task)

    # Step simulation forward
    all_done = []
    for _ in range(50):
        done = vdc.step(dt=0.1)
        all_done.extend(done)

    print(f"\n[+] Executed {len(all_done)} inference tasks across cluster:")
    for evt in all_done[:5]:
        print(f"    - {evt.request_id} on {evt.server_id}: latency={evt.exec_latency_ms:.1f}ms, SLA={'MET' if evt.slo_met else 'VIOLATED'}, energy={evt.energy_consumed_joules:.1f}J")

    print("\n[+] Final Server Snapshots:")
    for sid, snap in vdc.get_cluster_snapshots().items():
        print(f"    - [{sid}] status={snap.status.value}, active={snap.active_streams_count}/{snap.max_streams_capacity}, power={snap.current_power_w:.1f}W, completed={snap.completed_tasks_count}")
    print("=" * 64)


if __name__ == "__main__":
    main()
