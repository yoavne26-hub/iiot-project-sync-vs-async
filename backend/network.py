"""Graph creation utilities for the IIOT project."""

import random


def generate_random_graph(
    num_agents: int,
    edge_probability: float,
    seed: int | None = None,
) -> dict[int, list[int]]:
    """Generate a random undirected graph as an adjacency list."""

    if num_agents <= 0:
        raise ValueError("Number of agents must be greater than 0.")

    if not 0 <= edge_probability <= 1:
        raise ValueError("Edge probability must be between 0 and 1.")

    rng = random.Random(seed)
    graph: dict[int, list[int]] = {agent_id: [] for agent_id in range(num_agents)}

    for left in range(num_agents):
        for right in range(left + 1, num_agents):
            if rng.random() < edge_probability:
                graph[left].append(right)
                graph[right].append(left)

    for agent_id in graph:
        graph[agent_id].sort()

    return graph


def print_graph(graph: dict[int, list[int]]) -> None:
    """Print the adjacency list in a clear format."""

    print("Generated Graph")
    print("-" * 30)
    for agent_id in sorted(graph):
        print(f"Agent {agent_id}: {graph[agent_id]}")
