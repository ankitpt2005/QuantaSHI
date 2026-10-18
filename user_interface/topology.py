"""
Topology generator for the 100 Virtual Users network constellation.
Establishes user profiles, cluster groupings, and interconnected mesh topology.
"""

import math
import random
from typing import Dict, List, Any
from .models import VirtualUser, UserTier, PriorityLevel, UserStatus


class NetworkTopology:
    """
    Manages the 100 virtual user nodes, their tier assignments,
    cluster affiliations, and visual mesh connections.
    """

    CLUSTER_NAMES = [
        "FinTech Core",
        "Autonomous Agents",
        "Enterprise Analytics",
        "Developer Workspaces",
        "Healthcare RAG",
    ]

    def __init__(self, num_users: int = 100, seed: int = 42):
        self.num_users = num_users
        self.users: Dict[str, VirtualUser] = {}
        self.links: List[Dict[str, Any]] = []
        self._initialize_topology(seed)

    def _initialize_topology(self, seed: int):
        random.seed(seed)
        num_clusters = len(self.CLUSTER_NAMES)

        # 1. Instantiate 100 users with assigned tiers
        for i in range(1, self.num_users + 1):
            user_id = f"usr_{i:03d}"
            cluster_id = (i - 1) % num_clusters

            # Realistic Tier distribution: 15% P0, 60% P1, 25% P2
            if i <= 15:
                tier = UserTier.ENTERPRISE_P0
                think_mean = 5.0
            elif i <= 75:
                tier = UserTier.PRO_P1
                think_mean = 9.0
            else:
                tier = UserTier.STANDARD_P2
                think_mean = 16.0

            label = f"User {i:03d} ({self.CLUSTER_NAMES[cluster_id]})"
            self.users[user_id] = VirtualUser(
                user_id=user_id,
                label=label,
                tier=tier,
                cluster_group=cluster_id,
                status=UserStatus.IDLE,
                think_time_mean=think_mean,
            )

        # 2. Establish organic constellation mesh edges (intra-cluster + bridge links)
        # Cluster centers in 2D space for clean initial positioning
        cluster_centers = [
            (350 + 260 * math.cos(2 * math.pi * k / num_clusters),
             350 + 260 * math.sin(2 * math.pi * k / num_clusters))
            for k in range(num_clusters)
        ]

        node_positions = {}
        for user_id, user in self.users.items():
            cx, cy = cluster_centers[user.cluster_group]
            radius = random.uniform(25, 140)
            angle = random.uniform(0, 2 * math.pi)
            node_positions[user_id] = {
                "x": round(cx + radius * math.cos(angle), 1),
                "y": round(cy + radius * math.sin(angle), 1),
            }

        # Connect nodes with nearest neighbors in cluster + occasional bridges
        all_ids = list(self.users.keys())
        for u_id in all_ids:
            curr_user = self.users[u_id]
            curr_pos = node_positions[u_id]

            # Candidate neighbors in same cluster
            same_cluster_ids = [
                uid for uid in all_ids
                if self.users[uid].cluster_group == curr_user.cluster_group and uid != u_id
            ]

            # Sort by Euclidean distance
            def dist(target_id):
                tp = node_positions[target_id]
                return (tp["x"] - curr_pos["x"]) ** 2 + (tp["y"] - curr_pos["y"]) ** 2

            same_cluster_ids.sort(key=dist)
            # Pick 2-4 nearest peers
            selected_peers = same_cluster_ids[: random.randint(2, 4)]

            # 15% chance to establish a bridge link to another cluster
            if random.random() < 0.25:
                diff_cluster_ids = [
                    uid for uid in all_ids
                    if self.users[uid].cluster_group != curr_user.cluster_group
                ]
                if diff_cluster_ids:
                    diff_cluster_ids.sort(key=dist)
                    selected_peers.append(diff_cluster_ids[0])

            for p_id in selected_peers:
                if p_id not in curr_user.connected_peers:
                    curr_user.connected_peers.append(p_id)
                # Link format
                link_key = tuple(sorted([u_id, p_id]))
                if not any(l["source"] == link_key[0] and l["target"] == link_key[1] for l in self.links):
                    self.links.append({
                        "source": link_key[0],
                        "target": link_key[1],
                        "weight": round(random.uniform(0.4, 1.0), 2),
                    })

        self.node_positions = node_positions

    def get_user(self, user_id: str) -> VirtualUser:
        return self.users[user_id]

    def get_topology_payload(self) -> Dict[str, Any]:
        """Returns JSON-serializable graph topology containing all nodes, coordinates, and links."""
        nodes = []
        for user_id, user in self.users.items():
            u_dict = user.to_dict()
            pos = self.node_positions.get(user_id, {"x": 400, "y": 400})
            u_dict["x"] = pos["x"]
            u_dict["y"] = pos["y"]
            nodes.append(u_dict)

        return {
            "num_nodes": len(nodes),
            "num_edges": len(self.links),
            "clusters": self.CLUSTER_NAMES,
            "nodes": nodes,
            "links": self.links,
        }
