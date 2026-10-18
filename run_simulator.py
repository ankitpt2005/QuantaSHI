"""
QuantaSHI - Heterogeneous AI Infrastructure Simulator Launcher & Agent Gateway.
Serves the 3 distinct interfaces (user_interface, server_interface, system_interface),
the unified control portal, and the live REST API for the 3 autonomous AI agents.
"""

import http.server
import socketserver
import os
import sys
import json
import time
import threading
import urllib.parse
import csv
import io

from user_interface.agent import UserWorkloadAgent
from server_interface.agent import ServerOpsAgent
from server_interface.cluster import VirtualDataCentre
from system_interface.agent import SystemReasoningAgent
from system_interface.models import RoutingPolicy, OptimizationWeights
from system_interface.scheduler import QuantaSHIScheduler
from simulation_engine import SimulationSession

PORT = int(os.environ.get("QUANTASHI_PORT", "8000"))
DIRECTORY = os.path.dirname(os.path.abspath(__file__))

# Shared state for live simulator & agents
# The live session is the source of truth for the dashboard and both matched
# experiments.  Legacy agent endpoints read its current primary cluster.
simulation = SimulationSession()
simulation_lock = threading.RLock()
user_agent = UserWorkloadAgent()
server_agent = ServerOpsAgent()
system_agent = SystemReasoningAgent()


def simulation_snapshot():
    with simulation_lock:
        return simulation.snapshot()


def simulation_clock_loop():
    """Advance virtual time independently of browser polling or rendering."""
    previous = time.monotonic()
    while True:
        time.sleep(0.05)
        now = time.monotonic()
        elapsed = now - previous
        previous = now
        with simulation_lock:
            simulation.advance(elapsed * simulation.speed)


class CustomHTTPHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def log_message(self, format, *args):
        # Silent logger for clean terminal output
        pass

    def _send_json_response(self, data, status_code=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _send_csv_response(self, csv_data: str, filename: str = "quantashi_finops_audit.csv"):
        body = csv_data.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query = urllib.parse.parse_qs(parsed_url.query)

        if path == "/api/agent/status":
            self._send_json_response({
                "status": "ONLINE",
                "agents": {
                    "user_agent": {"name": user_agent.agent_name, "model": user_agent.model, "history_count": len(user_agent.history)},
                    "server_agent": {"name": server_agent.agent_name, "model": server_agent.model, "history_count": len(server_agent.diagnostic_history)},
                    "system_agent": {"name": system_agent.agent_name, "model": system_agent.model, "history_count": len(system_agent.explanation_history)},
                }
            })
            return
        if path in ("/api/simulation", "/api/simulation/state"):
            self._send_json_response(simulation_snapshot())
            return
        if path == "/api/finops/audit-export":
            with simulation_lock:
                records = simulation.get_audit_records()
                snapshot = simulation.snapshot()

            fmt = query.get("format", ["json"])[0].lower()
            if fmt == "csv" or "text/csv" in self.headers.get("Accept", ""):
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow([
                    "Request ID", "User ID", "Arrival (s)", "Workload Type", "Context Tokens",
                    "Max Output Tokens", "Deadline SLO (ms)", "Status", "Selected Server", "Action",
                    "Solver Provenance", "Solver Runtime (ms)", "Predicted Energy (J)",
                    "Predicted Turnaround (ms)", "Deadline Headroom (ms)", "SLO Met",
                    "Rejected Alternatives (Counterfactuals)"
                ])
                for r in records:
                    counterfactuals_str = "; ".join(
                        f"Server {alt.get('server_id', '?')}: {alt.get('reason', '')} (Turnaround {alt.get('predicted_turnaround_ms', 0)}ms, {alt.get('marginal_energy_j', 0)}J)"
                        for alt in r.get("rejected_alternatives", [])
                    ) if r.get("rejected_alternatives") else "None"
                    writer.writerow([
                        r["request_id"], r["user_id"], r["arrival_timestamp"], r["workload_type"],
                        r["context_tokens"], r["max_output_tokens"], r["deadline_slo_ms"],
                        r["status"], r["selected_server_id"], r["action"], r["solver_provenance"],
                        r["solver_runtime_ms"], r["predicted_energy_joules"],
                        r["predicted_turnaround_ms"], r["deadline_headroom_ms"],
                        "YES" if r.get("slo_met") is True else ("NO" if r.get("slo_met") is False else "PENDING"),
                        counterfactuals_str
                    ])
                self._send_csv_response(output.getvalue())
                return

            self._send_json_response({
                "audit_meta": {
                    "scenario": snapshot.get("scenario"),
                    "seed": snapshot.get("seed"),
                    "clock_seconds": snapshot.get("clock_seconds"),
                    "total_records": len(records),
                    "note": "Auditable FinOps decision log with pruned alternatives and counterfactual rationale."
                },
                "records": records
            })
            return
        if path == "/api/simulation/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                while True:
                    data = json.dumps(simulation_snapshot())
                    self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(0.1)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return
            return
        super().do_GET()

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            params = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            params = {}

        # Endpoint 1: User Interface AI Agent (Workload Generation)
        if self.path == "/api/agent/user":
            req = user_agent.generate_dynamic_request()
            self._send_json_response({
                "success": True,
                "agent": user_agent.agent_name,
                "request": {
                    "request_id": req.request_id,
                    "user_id": req.user_id,
                    "workload_type": req.workload_type.value,
                    "context_tokens": req.context_tokens,
                    "max_output_tokens": req.max_output_tokens,
                    "priority_level": req.priority_level.value,
                    "deadline_slo_ms": req.deadline_slo_ms,
                    "prompt_preview": req.prompt_preview,
                },
                "history": user_agent.history[-5:],
            })
            return

        # Endpoint 2: Server Interface AI Agent (Data Centre Ops Diagnostics)
        elif self.path == "/api/agent/server":
            with simulation_lock:
                diag = server_agent.diagnose_cluster(simulation.primary.cluster)
            self._send_json_response({
                "success": True,
                "agent": server_agent.agent_name,
                "diagnosis": diag,
            })
            return

        # Endpoint 3: System Interface AI Agent (Decision Reasoning & Explainability)
        elif self.path == "/api/agent/system":
            # Generate or use request to obtain real dispatch decision
            req = user_agent.generate_dynamic_request()
            with simulation_lock:
                dec = simulation.primary.scheduler.route_request(req)
                explanation = system_agent.explain_decision(dec, req, simulation.primary.cluster)
            self._send_json_response({
                "success": True,
                "agent": system_agent.agent_name,
                "decision": dec.to_dict(),
                "explanation": explanation,
            })
            return

        elif self.path == "/api/simulation/control":
            action = str(params.get("action", "")).upper()
            try:
                with simulation_lock:
                    if action == "START" or action == "RESUME":
                        simulation.start()
                    elif action == "PAUSE":
                        simulation.pause()
                    elif action == "RESET":
                        simulation.reset(
                            seed=params.get("seed", simulation.seed),
                            scenario=params.get("scenario", simulation.scenario.value),
                            duration_seconds=params.get("duration_seconds", simulation.duration_seconds),
                            speed=params.get("speed", simulation.speed),
                        )
                    elif action == "SPEED":
                        simulation.speed = max(0.1, min(50.0, float(params["speed"])))
                    elif action == "SET_POLICY":
                        policy_name = str(params.get("policy", "BALANCED_PARETO"))
                        try:
                            policy = RoutingPolicy(policy_name)
                            simulation.primary.scheduler.optimizer.set_policy(policy)
                        except ValueError:
                            self._send_json_response({"error": f"Unknown policy: {policy_name}"}, status_code=400)
                            return
                    elif action == "SET_WEIGHTS":
                        w_e = float(params.get("weight_energy", 0.5))
                        w_l = float(params.get("weight_latency", 0.5))
                        simulation.primary.scheduler.optimizer.weights.weight_energy = w_e
                        simulation.primary.scheduler.optimizer.weights.weight_latency = w_l
                    else:
                        self._send_json_response({"error": "INVALID_ACTION"}, status_code=400)
                        return
                    snapshot = simulation.snapshot()
                self._send_json_response(snapshot)
            except (KeyError, TypeError, ValueError) as exc:
                self._send_json_response({"error": "INVALID_CONFIGURATION", "detail": str(exc)}, status_code=400)
            return

        else:
            self._send_json_response({"error": "NOT_FOUND"}, status_code=404)


def main():
    os.chdir(DIRECTORY)
    port = PORT
    
    server = None
    for attempt_port in range(port, port + 10):
        try:
            socketserver.ThreadingTCPServer.allow_reuse_address = True
            server = socketserver.ThreadingTCPServer(("", attempt_port), CustomHTTPHandler)
            port = attempt_port
            break
        except OSError:
            continue

    if server is None:
        print("[!] Could not bind to any port from 8000 to 8010.")
        sys.exit(1)

    url = f"http://localhost:{port}"
    print("\n" + "=" * 70)
    print(" QuantaSHI — Unified Autonomous Infrastructure & FinOps Platform")
    print("=" * 70)
    print(f" [+] Access Everything at ONE Single URL:")
    print(f"     --> {url}/")
    print("=" * 70)
    print("  • User Interface (100-node network web)")
    print("  • Server Interface (2D hardware rack enclosure)")
    print("  • System Interface (Explainability & dispatch stream)")
    print("  • Autonomous AI Agents (User, Server, System agents)")
    print("  • 1-Click FinOps Audit CSV Export")
    print("  --> ALL accessible inside this single link with unified tabs.")
    print("=" * 70)
    print(" [+] Press Ctrl+C to stop the server.\n")

    try:
        threading.Thread(target=simulation_clock_loop, daemon=True, name="quantashi-simulation-clock").start()
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[+] Server stopped cleanly.")
        server.server_close()


if __name__ == "__main__":
    main()
