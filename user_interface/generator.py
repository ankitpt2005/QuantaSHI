"""
Core Workload Generator Engine for Part 1: Users.
Generates realistic inference requests across 4 validated scenarios.
"""

from __future__ import annotations
import asyncio
import enum
import random
import time
import uuid
from typing import AsyncGenerator, Dict, List, Optional

from .models import (
    InferenceRequest,
    VirtualUser,
    UserStatus,
    PriorityLevel,
    WorkloadType,
    UserTier,
)
from .topology import NetworkTopology
from .distributions import AzureTraceCalibratedSampler
from .prompt_corpus import get_random_prompt


class SimulationScenario(str, enum.Enum):
    SCENARIO_1_STEADY_STATE = "SCENARIO_1_STEADY_STATE"
    SCENARIO_2_FLASH_BURST = "SCENARIO_2_FLASH_BURST"
    SCENARIO_3_BIMODAL = "SCENARIO_3_BIMODAL"
    SCENARIO_4_CONTENTION = "SCENARIO_4_CONTENTION"


class WorkloadGenerator:
    """
    Autonomous, decoupled workload generator simulating realistic
    AI data center inference traffic originating from 100 virtual users.
    """

    def __init__(self, topology: Optional[NetworkTopology] = None, seed: int = 42):
        self.topology = topology or NetworkTopology(num_users=100, seed=seed)
        self.sampler = AzureTraceCalibratedSampler()
        self.simulated_time = 0.0
        random.seed(seed)

    def _determine_workload_type(self, scenario: SimulationScenario) -> WorkloadType:
        """Determines workload type based on scenario traffic requirements."""
        if scenario == SimulationScenario.SCENARIO_3_BIMODAL:
            # 80% short chat, 20% heavy RAG or summarization
            if random.random() < 0.80:
                return WorkloadType.TEXT_CHAT
            return random.choice([WorkloadType.RAG_QA, WorkloadType.SUMMARIZATION])

        # Standard mixture
        roll = random.random()
        if roll < 0.50:
            return WorkloadType.TEXT_CHAT
        elif roll < 0.75:
            return WorkloadType.CODE_GEN
        elif roll < 0.90:
            return WorkloadType.RAG_QA
        else:
            return WorkloadType.SUMMARIZATION

    def _determine_priority(self, user: VirtualUser) -> PriorityLevel:
        """Determines request priority class based on user SLA tier."""
        if user.tier == UserTier.ENTERPRISE_P0:
            return PriorityLevel.P0_CRITICAL
        elif user.tier == UserTier.PRO_P1:
            return PriorityLevel.P1_INTERACTIVE
        else:
            return PriorityLevel.P2_BATCH

    def create_single_request(
        self,
        user_id: str,
        timestamp: float,
        scenario: SimulationScenario = SimulationScenario.SCENARIO_1_STEADY_STATE,
        workload_type_override: Optional[WorkloadType] = None,
    ) -> InferenceRequest:
        """Generates a discrete, validated InferenceRequest for a given user."""
        user = self.topology.get_user(user_id)
        w_type = workload_type_override or self._determine_workload_type(scenario)
        priority = self._determine_priority(user)

        ctx_tokens, out_tokens = self.sampler.sample_tokens(w_type)

        # In Bimodal scenario, accentuate context lengths
        if scenario == SimulationScenario.SCENARIO_3_BIMODAL:
            if w_type == WorkloadType.TEXT_CHAT:
                ctx_tokens = random.randint(48, 256)
                out_tokens = random.randint(24, 128)
            else:
                ctx_tokens = random.randint(4096, 16384)
                out_tokens = random.randint(256, 1024)

        deadline_ms = self.sampler.calculate_deadline_slo_ms(
            context_tokens=ctx_tokens,
            max_output_tokens=out_tokens,
            priority=priority,
        )

        prompt = get_random_prompt(w_type)
        req_id = str(uuid.UUID(int=random.getrandbits(128), version=4))

        request = InferenceRequest(
            request_id=req_id,
            user_id=user_id,
            arrival_timestamp=timestamp,
            workload_type=w_type,
            context_tokens=ctx_tokens,
            max_output_tokens=out_tokens,
            priority_level=priority,
            deadline_slo_ms=deadline_ms,
            prompt_preview=prompt,
        )

        # Update virtual user's telemetry state
        user.status = UserStatus.REQUESTING
        user.active_request = request
        user.total_requests_sent += 1
        user.total_tokens_consumed += (ctx_tokens + out_tokens)
        user.last_active_time = timestamp

        return request

    def generate_trace(
        self,
        duration_seconds: float = 60.0,
        scenario: SimulationScenario = SimulationScenario.SCENARIO_1_STEADY_STATE,
    ) -> List[InferenceRequest]:
        """
        Generates an end-to-end discrete event trace over the given simulation window.
        Returns a chronologically ordered list of InferenceRequests.
        """
        requests: List[InferenceRequest] = []
        user_ids = list(self.topology.users.keys())

        # Reset states
        for user in self.topology.users.values():
            user.status = UserStatus.IDLE
            user.active_request = None
            user.total_requests_sent = 0
            user.total_tokens_consumed = 0

        # Maintain per-user next arrival schedule
        current_time = 0.0

        if scenario == SimulationScenario.SCENARIO_1_STEADY_STATE:
            # Baseline Poisson arrival process: lambda ~ 18 req/sec across 100 users
            arrival_rate = 18.0
            t = 0.0
            while t < duration_seconds:
                dt = self.sampler.sample_poisson_interval(arrival_rate)
                t += dt
                if t >= duration_seconds:
                    break
                # Select user with priority weighting (Enterprise users more active)
                weights = [
                    3.0 if self.topology.users[uid].tier == UserTier.ENTERPRISE_P0
                    else 1.5 if self.topology.users[uid].tier == UserTier.PRO_P1
                    else 0.8
                    for uid in user_ids
                ]
                selected_user = random.choices(user_ids, weights=weights, k=1)[0]
                req = self.create_single_request(selected_user, t, scenario)
                requests.append(req)

        elif scenario == SimulationScenario.SCENARIO_2_FLASH_BURST:
            # Phase 1: 0 - 20s: Baseline 15 req/s
            t = 0.0
            while t < 20.0:
                t += self.sampler.sample_poisson_interval(15.0)
                if t >= 20.0:
                    break
                u = random.choice(user_ids)
                requests.append(self.create_single_request(u, t, scenario))

            # Phase 2: 20s - 35s: FLASH SURGE (5x spike, 100 req/s, 50 users firing in 500ms)
            burst_users = random.sample(user_ids, 50)
            for bu in burst_users:
                burst_t = 20.0 + random.uniform(0.05, 0.45)
                requests.append(self.create_single_request(bu, burst_t, scenario))

            # Continuous surge traffic until 35s
            t = 20.5
            while t < 35.0:
                t += self.sampler.sample_poisson_interval(95.0)
                if t >= 35.0:
                    break
                u = random.choice(user_ids)
                requests.append(self.create_single_request(u, t, scenario))

            # Phase 3: 35s - 60s: Recovery baseline 15 req/s
            t = 35.0
            while t < duration_seconds:
                t += self.sampler.sample_poisson_interval(15.0)
                if t >= duration_seconds:
                    break
                u = random.choice(user_ids)
                requests.append(self.create_single_request(u, t, scenario))

        elif scenario == SimulationScenario.SCENARIO_3_BIMODAL:
            # Continuous arrivals with 80% short chat / 20% heavy elephant contexts
            t = 0.0
            while t < duration_seconds:
                t += self.sampler.sample_poisson_interval(22.0)
                if t >= duration_seconds:
                    break
                u = random.choice(user_ids)
                requests.append(self.create_single_request(u, t, scenario))

        elif scenario == SimulationScenario.SCENARIO_4_CONTENTION:
            # Over-capacity sustained arrival rate ~ 50 req/sec
            t = 0.0
            while t < duration_seconds:
                t += self.sampler.sample_poisson_interval(50.0)
                if t >= duration_seconds:
                    break
                u = random.choice(user_ids)
                requests.append(self.create_single_request(u, t, scenario))

        # Sort chronologically by arrival_timestamp
        requests.sort(key=lambda r: r.arrival_timestamp)
        return requests

    def trigger_burst(
        self,
        num_burst_users: int = 35,
        current_time: float = 0.0,
    ) -> List[InferenceRequest]:
        """Instantly fires a correlated burst across multiple users (used for interactive UI trigger)."""
        user_ids = list(self.topology.users.keys())
        selected = random.sample(user_ids, min(num_burst_users, len(user_ids)))
        burst_reqs = []
        for uid in selected:
            t_jitter = current_time + random.uniform(0.01, 0.25)
            burst_reqs.append(
                self.create_single_request(
                    user_id=uid,
                    timestamp=t_jitter,
                    scenario=SimulationScenario.SCENARIO_2_FLASH_BURST,
                )
            )
        return burst_reqs

    def get_user_state(self, user_id: str) -> Dict:
        """Returns the current state dictionary of a user node for UI inspection."""
        return self.topology.get_user(user_id).to_dict()

    async def stream_requests(
        self,
        scenario: SimulationScenario = SimulationScenario.SCENARIO_1_STEADY_STATE,
        time_scale: float = 1.0,
    ) -> AsyncGenerator[InferenceRequest, None]:
        """
        Asynchronously streams requests in real time according to the selected scenario.
        time_scale: 1.0 = real-time, 2.0 = 2x speedup.
        """
        trace = self.generate_trace(duration_seconds=60.0, scenario=scenario)
        prev_time = 0.0

        for req in trace:
            delta = req.arrival_timestamp - prev_time
            if delta > 0:
                await asyncio.sleep(delta / max(0.1, time_scale))
            prev_time = req.arrival_timestamp
            yield req
