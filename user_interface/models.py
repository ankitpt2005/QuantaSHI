"""
Data models and dataclasses for Part 1: Users (Workload Generator).
Defines strict schemas for virtual users and inference requests.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import IntEnum, Enum
from typing import Optional, List, Dict, Any
import uuid


class PriorityLevel(IntEnum):
    P0_CRITICAL = 0
    P1_INTERACTIVE = 1
    P2_BATCH = 2


class WorkloadType(str, Enum):
    TEXT_CHAT = "TEXT_CHAT"
    CODE_GEN = "CODE_GEN"
    RAG_QA = "RAG_QA"
    SUMMARIZATION = "SUMMARIZATION"


class UserStatus(str, Enum):
    IDLE = "IDLE"
    REQUESTING = "REQUESTING"
    AWAITING_RESPONSE = "AWAITING_RESPONSE"


class UserTier(str, Enum):
    ENTERPRISE_P0 = "Enterprise_P0"
    PRO_P1 = "Pro_P1"
    STANDARD_P2 = "Standard_P2"


@dataclass(frozen=True)
class InferenceRequest:
    """Represents a discrete AI inference request arriving from a virtual user."""
    request_id: str
    user_id: str
    arrival_timestamp: float
    workload_type: WorkloadType
    context_tokens: int
    max_output_tokens: int
    priority_level: PriorityLevel
    deadline_slo_ms: float
    prompt_preview: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "arrival_timestamp": round(self.arrival_timestamp, 3),
            "workload_type": self.workload_type.value if isinstance(self.workload_type, Enum) else self.workload_type,
            "context_tokens": self.context_tokens,
            "max_output_tokens": self.max_output_tokens,
            "priority_level": int(self.priority_level),
            "deadline_slo_ms": round(self.deadline_slo_ms, 2),
            "prompt_preview": self.prompt_preview,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> InferenceRequest:
        return cls(
            request_id=data["request_id"],
            user_id=data["user_id"],
            arrival_timestamp=float(data["arrival_timestamp"]),
            workload_type=WorkloadType(data["workload_type"]),
            context_tokens=int(data["context_tokens"]),
            max_output_tokens=int(data["max_output_tokens"]),
            priority_level=PriorityLevel(int(data["priority_level"])),
            deadline_slo_ms=float(data["deadline_slo_ms"]),
            prompt_preview=str(data.get("prompt_preview", "")),
        )


@dataclass
class VirtualUser:
    """Represents a simulated client node in the 100-user constellation topology."""
    user_id: str
    label: str
    tier: UserTier
    cluster_group: int
    status: UserStatus = UserStatus.IDLE
    connected_peers: List[str] = field(default_factory=list)
    active_request: Optional[InferenceRequest] = None
    total_requests_sent: int = 0
    total_tokens_consumed: int = 0
    last_active_time: float = 0.0
    think_time_mean: float = 10.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "label": self.label,
            "tier": self.tier.value if isinstance(self.tier, Enum) else self.tier,
            "cluster_group": self.cluster_group,
            "status": self.status.value if isinstance(self.status, Enum) else self.status,
            "connected_peers": list(self.connected_peers),
            "active_request": self.active_request.to_dict() if self.active_request else None,
            "metrics": {
                "total_requests_sent": self.total_requests_sent,
                "total_tokens_consumed": self.total_tokens_consumed,
                "last_active_time": round(self.last_active_time, 3),
            },
        }
