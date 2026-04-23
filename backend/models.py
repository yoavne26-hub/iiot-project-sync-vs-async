"""Core data models for the Tkinter IIOT visualizer."""

from dataclasses import dataclass


@dataclass
class TableRow:
    """One row in an agent routing table."""

    target: int
    distance: int
    via: int


class UpdateTable:
    """Stores the known distances for a single agent."""

    def __init__(self, owner_id: int) -> None:
        if owner_id < 0:
            raise ValueError("Agent ID must be non-negative.")

        self.owner_id = owner_id
        self.rows: dict[int, TableRow] = {
            owner_id: TableRow(target=owner_id, distance=0, via=owner_id)
        }

    def export_payload(self) -> dict[int, int]:
        """Export the table as {target: distance}."""

        return {target: row.distance for target, row in self.rows.items()}

    def export_rows(self) -> list[dict[str, int]]:
        """Export rows in a JSON-friendly structure."""

        return [
            {
                "target": row.target,
                "distance": row.distance,
                "via": row.via,
            }
            for _, row in sorted(self.rows.items())
        ]

    def has_target(self, target: int) -> bool:
        """Return True if the target already exists in the table."""

        return target in self.rows

    def get_distance(self, target: int) -> int | None:
        """Return the known distance to a target, or None if it is unknown."""

        row = self.rows.get(target)
        return row.distance if row is not None else None

    def process_incoming_payload(self, sender: int, payload: dict[int, int]) -> bool:
        """Process one received payload and update the table if needed."""

        changed = False

        for target, received_distance in payload.items():
            candidate_distance = received_distance + 1
            current_row = self.rows.get(target)

            if current_row is None or candidate_distance < current_row.distance:
                self.rows[target] = TableRow(
                    target=target,
                    distance=candidate_distance,
                    via=sender,
                )
                changed = True

        return changed

    def pretty_string(self) -> str:
        """Return a readable multi-line string for the table."""

        lines = [
            f"Update Table for Agent {self.owner_id}",
            f"{'Target':<10}{'Distance':<10}{'Via':<10}",
            "-" * 30,
        ]

        for target in sorted(self.rows):
            row = self.rows[target]
            lines.append(f"{row.target:<10}{row.distance:<10}{row.via:<10}")

        return "\n".join(lines)

    def print_table(self) -> None:
        """Print the table in a clear format."""

        print(self.pretty_string())


@dataclass
class Message:
    """A message sent from one agent to another."""

    sender: int
    receiver: int
    payload: dict[int, int]


class Agent:
    """Represents one agent in the network."""

    def __init__(self, agent_id: int, neighbors: list[int]) -> None:
        if not isinstance(agent_id, int) or agent_id < 0:
            raise ValueError("Agent ID must be a non-negative integer.")
        if not isinstance(neighbors, list):
            raise ValueError("Neighbors must be provided as a list of integers.")
        if any(not isinstance(neighbor, int) or neighbor < 0 for neighbor in neighbors):
            raise ValueError("Neighbors must be non-negative integers.")
        if agent_id in neighbors:
            raise ValueError("An agent cannot be its own neighbor.")

        self.agent_id = agent_id
        self.neighbors = sorted(set(neighbors))
        self.table = UpdateTable(owner_id=agent_id)

    def get_payload(self) -> dict[int, int]:
        """Return the table summary used for outgoing messages."""

        return self.table.export_payload()

    def receive_message(self, sender: int, payload: dict[int, int]) -> bool:
        """Process one incoming payload and return True if the table changed."""

        if sender not in self.neighbors:
            raise ValueError(f"Agent {sender} is not a neighbor of agent {self.agent_id}.")

        return self.table.process_incoming_payload(sender=sender, payload=payload)

    def export_state(self) -> dict[str, object]:
        """Return a JSON-friendly snapshot of the agent."""

        return {
            "agent_id": self.agent_id,
            "neighbors": list(self.neighbors),
            "rows": self.table.export_rows(),
            "known_targets": len(self.table.rows),
        }

    def print_state(self) -> None:
        """Print the current state of the agent."""

        print(f"Agent {self.agent_id}")
        print(f"Neighbors: {self.neighbors}")
        self.table.print_table()
