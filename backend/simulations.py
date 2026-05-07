"""Simulation engine and trace generation for the Tkinter visualizer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import queue
import threading
import time

from backend.config import ASYNC_QUEUE_TIMEOUT, MAX_ITERATIONS
from backend.models import Agent, Message


def print_separator(char: str = "=", length: int = 40) -> None:
    """Print a simple separator line for optional console output."""

    print(char * length)


def build_agents(graph: dict[int, list[int]]) -> dict[int, Agent]:
    """Create Agent objects from an adjacency list."""

    return {
        agent_id: Agent(agent_id=agent_id, neighbors=neighbors)
        for agent_id, neighbors in sorted(graph.items())
    }


def summarize_graph(graph: dict[int, list[int]]) -> dict[str, object]:
    """Return basic graph statistics for the report."""

    edge_count = sum(len(neighbors) for neighbors in graph.values()) // 2
    isolated_nodes = [node_id for node_id, neighbors in graph.items() if not neighbors]
    degree_values = [len(neighbors) for neighbors in graph.values()]
    node_count = len(graph)
    possible_edges = (node_count * (node_count - 1)) / 2 if node_count > 1 else 0

    return {
        "node_count": node_count,
        "edge_count": edge_count,
        "isolated_nodes": isolated_nodes,
        "max_degree": max(degree_values, default=0),
        "min_degree": min(degree_values, default=0),
        "average_degree": (
            round(sum(degree_values) / len(degree_values), 2) if degree_values else 0.0
        ),
        "density": round(edge_count / possible_edges, 3) if possible_edges else 0.0,
        "adjacency": {
            str(agent_id): list(neighbors) for agent_id, neighbors in sorted(graph.items())
        },
    }


def export_tables(agents: dict[int, Agent]) -> dict[str, dict[str, object]]:
    """Return the final table of each agent."""

    return {
        str(agent_id): agent.export_state()
        for agent_id, agent in sorted(agents.items())
    }


def summarize_distances(
    final_tables: dict[str, dict[str, object]],
    graph_summary: dict[str, object],
) -> dict[str, int | float]:
    """Return aggregate distance metrics from the final agent tables."""

    distances: list[int] = []
    for agent_state in final_tables.values():
        owner_id = int(agent_state["agent_id"])
        for row in agent_state["rows"]:
            if int(row["target"]) == owner_id:
                continue
            distances.append(int(row["distance"]))

    node_count = int(graph_summary["node_count"])
    ordered_pairs = node_count * max(node_count - 1, 0)
    known_routes = len(distances)
    unreachable_routes = max(ordered_pairs - known_routes, 0)

    return {
        "longest_distance": max(distances, default=0),
        "average_distance": round(sum(distances) / len(distances), 2) if distances else 0.0,
        "known_routes": known_routes,
        "unreachable_routes": unreachable_routes,
        "reachability_percentage": round((known_routes / ordered_pairs) * 100, 1)
        if ordered_pairs
        else 100.0,
    }


def _message_payload_summary(payload: dict[int, int]) -> str:
    """Return a compact description of a message payload."""

    entries = [f"{target}:{distance}" for target, distance in sorted(payload.items())]
    return ", ".join(entries) if entries else "empty"


@dataclass
class SimulationEvent:
    """One event in the simulation trace."""

    step: int
    kind: str
    title: str
    description: str
    sender: int | None = None
    receiver: int | None = None
    payload: dict[int, int] | None = None
    changed: bool | None = None
    round_number: int | None = None
    agent_state: dict[str, object] | None = None
    timestamp_ms: float | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly event object."""

        data: dict[str, object] = {
            "step": self.step,
            "kind": self.kind,
            "title": self.title,
            "description": self.description,
        }

        if self.sender is not None:
            data["sender"] = self.sender
        if self.receiver is not None:
            data["receiver"] = self.receiver
        if self.payload is not None:
            data["payload"] = self.payload
        if self.changed is not None:
            data["changed"] = self.changed
        if self.round_number is not None:
            data["round_number"] = self.round_number
        if self.agent_state is not None:
            data["agent_state"] = self.agent_state
        if self.timestamp_ms is not None:
            data["timestamp_ms"] = self.timestamp_ms

        return data


@dataclass
class SimulationResult:
    """Structured simulation result used by the visualizer."""

    environment: str
    title: str
    graph: dict[int, list[int]]
    purpose: str
    metrics: dict[str, int | float | str]
    graph_summary: dict[str, object]
    events: list[dict[str, object]]
    final_tables: dict[str, dict[str, object]]
    summary: dict[str, int | float | str]
    generated_in_seconds: float
    notes: list[str] = field(default_factory=list)


class SimulationRecorder:
    """Thread-safe recorder for visualization events."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._step = 0
        self._events: list[dict[str, object]] = []
        self._started_at = time.perf_counter()

    def add(self, event: SimulationEvent) -> None:
        """Add an event while assigning the next step index."""

        with self._lock:
            self._step += 1
            event.step = self._step
            if event.timestamp_ms is None:
                event.timestamp_ms = round((time.perf_counter() - self._started_at) * 1000, 3)
            self._events.append(event.to_dict())

    def record_round_start(self, round_number: int, message_count: int) -> None:
        """Record the start of a synchronous round."""

        self.add(
            SimulationEvent(
                step=0,
                kind="round_start",
                title=f"Round {round_number} started",
                description=(
                    f"The synchronous simulator collected {message_count} outgoing "
                    f"messages before delivering any of them."
                ),
                round_number=round_number,
            )
        )

    def record_round_end(self, round_number: int, changes_in_round: int) -> None:
        """Record the end of a synchronous round."""

        changed_label = "change" if changes_in_round == 1 else "changes"
        self.add(
            SimulationEvent(
                step=0,
                kind="round_end",
                title=f"Round {round_number} finished",
                description=(
                    f"The round completed with {changes_in_round} table {changed_label}."
                ),
                round_number=round_number,
            )
        )

    def record_message_sent(self, message: Message, round_number: int | None = None) -> None:
        """Record one message being sent."""

        round_text = f" in round {round_number}" if round_number is not None else ""
        # The visualizer uses this event to animate the payload moving on an edge.
        self.add(
            SimulationEvent(
                step=0,
                kind="message_sent",
                title=f"Message {message.sender} -> {message.receiver}",
                description=(
                    f"Agent {message.sender} sent its current distance summary{round_text}: "
                    f"{_message_payload_summary(message.payload)}."
                ),
                sender=message.sender,
                receiver=message.receiver,
                payload=message.payload.copy(),
                round_number=round_number,
            )
        )

    def record_message_processed(
        self,
        message: Message,
        changed: bool,
        receiver: Agent,
        round_number: int | None = None,
    ) -> None:
        """Record one message being processed by its receiver."""

        effect = "updated" if changed else "did not change"
        round_text = f" during round {round_number}" if round_number is not None else ""
        # Store the receiver snapshot after processing so the UI can show the table change.
        self.add(
            SimulationEvent(
                step=0,
                kind="message_processed",
                title=f"Agent {message.receiver} processed a message",
                description=(
                    f"Agent {message.receiver} processed Agent {message.sender}'s payload{round_text} "
                    f"and {effect} its table."
                ),
                sender=message.sender,
                receiver=message.receiver,
                changed=changed,
                round_number=round_number,
                agent_state=receiver.export_state(),
            )
        )

    def record_convergence(self, environment: str) -> None:
        """Record convergence of the simulation."""

        self.add(
            SimulationEvent(
                step=0,
                kind="converged",
                title=f"{environment} convergence reached",
                description=(
                    "No more useful updates are propagating through the network, "
                    "so the distance tables have stabilized."
                ),
            )
        )

    def export(self) -> list[dict[str, object]]:
        """Return a stable copy of the recorded events."""

        with self._lock:
            return list(self._events)


@dataclass
class DeliveryResult:
    """One processed delivery from the current synchronous round."""

    message: Message
    changed: bool


class SynchronousSimulator:
    """Runs the synchronous version of the agent update process."""

    def __init__(
        self,
        agents: dict[int, Agent],
        max_rounds: int,
        verbose: bool = True,
    ) -> None:
        if max_rounds <= 0:
            raise ValueError("max_rounds must be greater than 0.")

        self.agents = dict(sorted(agents.items()))
        self.max_rounds = max_rounds
        self.verbose = verbose

        self.rounds_completed = 0
        self.total_messages_sent = 0
        self.total_deliveries_processed = 0
        self.total_table_changes = 0
        self.current_round_messages: list[Message] = []
        self.next_round_messages: list[Message] = []
        self._round_buffers_seeded = False

    def build_outgoing_messages(self) -> list[Message]:
        """Build one outgoing payload per neighbor from the current agent state."""

        messages: list[Message] = []

        for agent_id in sorted(self.agents):
            agent = self.agents[agent_id]
            payload = agent.get_payload()

            for neighbor_id in agent.neighbors:
                # Copy the payload so later table edits do not mutate this queued message.
                messages.append(
                    Message(
                        sender=agent.agent_id,
                        receiver=neighbor_id,
                        payload=payload.copy(),
                    )
                )

        return messages

    def seed_current_round_messages(self) -> list[Message]:
        """Prepare the initial messages that are available in round 1."""

        if self._round_buffers_seeded:
            return self.current_round_messages

        # Synchronous mode freezes all messages before round 1 starts.
        self.current_round_messages = self.build_outgoing_messages()
        self.total_messages_sent += len(self.current_round_messages)
        self._round_buffers_seeded = True
        return self.current_round_messages

    def process_current_round_messages(self) -> list[DeliveryResult]:
        """Process only the messages that were available at round start."""

        results: list[DeliveryResult] = []

        for message in self.current_round_messages:
            receiver = self.agents[message.receiver]
            # Deliveries update receiver tables, but they do not create messages mid-round.
            changed = receiver.receive_message(
                sender=message.sender,
                payload=message.payload,
            )
            self.total_deliveries_processed += 1
            if changed:
                self.total_table_changes += 1

            results.append(DeliveryResult(message=message, changed=changed))

        return results

    def build_next_round_messages(self) -> list[Message]:
        """Prepare the messages that will become available next round."""

        # New knowledge is broadcast only after the current round finishes.
        self.next_round_messages = self.build_outgoing_messages()
        self.total_messages_sent += len(self.next_round_messages)
        return self.next_round_messages

    def advance_to_next_round(self) -> None:
        """Advance the round boundary explicitly."""

        # Swap buffers so next-round messages become the current round's input.
        self.current_round_messages = self.next_round_messages
        self.next_round_messages = []

    def has_converged(self, results: list[DeliveryResult]) -> bool:
        """Return True if a full round completed with no table changes."""

        return not any(result.changed for result in results)

    def run_one_round(self) -> bool:
        """Perform exactly one synchronous round."""

        if not self._round_buffers_seeded:
            self.seed_current_round_messages()

        message_count = len(self.current_round_messages)
        results = self.process_current_round_messages()
        self.rounds_completed += 1
        changed = not self.has_converged(results)

        if self.verbose:
            print(f"Round {self.rounds_completed}")
            print(f"Messages available this round: {message_count}")
            print(f"Table changes: {sum(1 for result in results if result.changed)}")
            print_separator("-", 30)

        if changed:
            self.build_next_round_messages()
            self.advance_to_next_round()
        else:
            self.current_round_messages = []
            self.next_round_messages = []

        return changed

    def run(self) -> None:
        """Run synchronous rounds until convergence or the round limit."""

        if self.verbose:
            print("Starting synchronous simulation")
            print_separator()

        self.seed_current_round_messages()

        while self.rounds_completed < self.max_rounds:
            changed = self.run_one_round()
            if not changed:
                if self.verbose:
                    print("No table changes in the round. The system has converged.")
                    print_separator()
                return

        if self.verbose:
            print("Maximum round limit reached before convergence.")
            print_separator()


class AsyncAgentWorker(threading.Thread):
    """Worker thread that processes messages for one agent."""

    def __init__(self, agent: Agent, simulator: "AsynchronousSimulator") -> None:
        super().__init__(name=f"AgentWorker-{agent.agent_id}", daemon=True)
        self.agent = agent
        self.simulator = simulator
        self.inbox: queue.Queue[Message | None] = queue.Queue()

    def run(self) -> None:
        """Block on the inbox and react to messages as they arrive."""

        while True:
            message = self.inbox.get()
            if message is None:
                # None is the shutdown signal sent by the simulator controller.
                return

            changed = False
            try:
                # Async workers process messages immediately when they leave the inbox.
                changed = self.agent.receive_message(
                    sender=message.sender,
                    payload=message.payload,
                )
                if self.simulator.on_message_processed is not None:
                    self.simulator.on_message_processed(message, changed, self.agent)

                if changed:
                    # A useful update immediately triggers a new broadcast from this agent.
                    self.simulator.broadcast_from(self.agent.agent_id)
            except Exception as error:
                self.simulator.register_worker_error(error)
                return
            finally:
                self.simulator.finish_processed_message(changed=changed)


class AsynchronousSimulator:
    """Runs the asynchronous version of the agent update process."""

    def __init__(
        self,
        agents: dict[int, Agent],
        queue_timeout: float,
        verbose: bool = True,
        on_message_sent: Callable[[Message], None] | None = None,
        on_message_processed: Callable[[Message, bool, Agent], None] | None = None,
    ) -> None:
        if queue_timeout <= 0:
            raise ValueError("queue_timeout must be greater than 0.")

        self.agents = dict(sorted(agents.items()))
        self.queue_timeout = queue_timeout
        self.verbose = verbose
        self.on_message_sent = on_message_sent
        self.on_message_processed = on_message_processed

        self.stop_event = threading.Event()
        self.state_condition = threading.Condition()
        self.worker_error: Exception | None = None

        self.total_messages_sent = 0
        self.total_messages_processed = 0
        self.total_table_changes = 0
        self.in_flight_messages = 0
        self.runtime_seconds = 0.0

        self.workers = {
            agent_id: AsyncAgentWorker(agent=agent, simulator=self)
            for agent_id, agent in self.agents.items()
        }

    def send_message(self, message: Message) -> None:
        """Place a message into one agent inbox and update async state."""

        with self.state_condition:
            # In-flight count is the async convergence signal.
            self.total_messages_sent += 1
            self.in_flight_messages += 1

        if self.on_message_sent is not None:
            self.on_message_sent(message)

        self.workers[message.receiver].inbox.put(message)

    def broadcast_from(self, agent_id: int) -> None:
        """Send the current payload of one agent to all of its neighbors."""

        agent = self.agents[agent_id]
        payload = agent.get_payload()

        for neighbor_id in agent.neighbors:
            # Each neighbor receives its own payload copy.
            self.send_message(
                Message(
                    sender=agent.agent_id,
                    receiver=neighbor_id,
                    payload=payload.copy(),
                )
            )

    def kickoff_initial_messages(self) -> None:
        """Send the initial wave that starts the asynchronous reactions."""

        for agent_id in sorted(self.agents):
            self.broadcast_from(agent_id)

    def finish_processed_message(self, changed: bool) -> None:
        """Mark one message as fully handled and notify convergence waiters."""

        with self.state_condition:
            # When this reaches zero, no queued or active async work remains.
            self.total_messages_processed += 1
            self.in_flight_messages -= 1
            if changed:
                self.total_table_changes += 1
            self.state_condition.notify_all()

    def register_worker_error(self, error: Exception) -> None:
        """Store the first worker error and wake the controller."""

        with self.state_condition:
            if self.worker_error is None:
                self.worker_error = error
            self.stop_event.set()
            self.state_condition.notify_all()

    def has_converged(self) -> bool:
        """Return True when no queued or active message remains."""

        with self.state_condition:
            return self.in_flight_messages == 0

    def wait_for_convergence(self) -> None:
        """Block until the asynchronous system becomes quiescent."""

        with self.state_condition:
            while self.in_flight_messages > 0 and self.worker_error is None:
                self.state_condition.wait()

            if self.worker_error is not None:
                raise RuntimeError("Asynchronous worker failed.") from self.worker_error

    def start_workers(self) -> None:
        """Start all agent worker threads."""

        for worker in self.workers.values():
            worker.start()

    def stop_workers(self) -> None:
        """Signal workers to stop and wait for them to exit cleanly."""

        self.stop_event.set()
        for worker in self.workers.values():
            worker.inbox.put(None)
        for worker in self.workers.values():
            worker.join()

    def run(self) -> None:
        """Run the asynchronous simulation until centralized termination."""

        if self.verbose:
            print("Starting asynchronous simulation")
            print_separator()

        start_time = time.perf_counter()
        self.start_workers()
        self.kickoff_initial_messages()

        try:
            self.wait_for_convergence()
        finally:
            self.stop_workers()
            self.runtime_seconds = time.perf_counter() - start_time

        if self.verbose:
            print("Asynchronous simulation finished.")
            print_separator()


def run_synchronous_visual_simulation(
    graph: dict[int, list[int]],
    max_rounds: int = MAX_ITERATIONS,
) -> SimulationResult:
    """Run the synchronous simulator and capture a full trace."""

    agents = build_agents(graph)
    simulator = SynchronousSimulator(agents=agents, max_rounds=max_rounds, verbose=False)
    recorder = SimulationRecorder()
    started_at = time.perf_counter()

    simulator.seed_current_round_messages()

    while simulator.rounds_completed < simulator.max_rounds:
        round_number = simulator.rounds_completed + 1
        current_round_messages = list(simulator.current_round_messages)

        # The recorder mirrors the synchronous delivery order for the frontend trace.
        recorder.record_round_start(
            round_number=round_number,
            message_count=len(current_round_messages),
        )
        for message in current_round_messages:
            recorder.record_message_sent(message=message, round_number=round_number)

        delivery_results = simulator.process_current_round_messages()
        changes_in_round = 0
        for result in delivery_results:
            receiver = simulator.agents[result.message.receiver]
            if result.changed:
                changes_in_round += 1
            recorder.record_message_processed(
                message=result.message,
                changed=result.changed,
                receiver=receiver,
                round_number=round_number,
            )

        simulator.rounds_completed += 1
        recorder.record_round_end(round_number=round_number, changes_in_round=changes_in_round)

        if simulator.has_converged(delivery_results):
            # A full round with no changes means all shortest paths are stable.
            recorder.record_convergence(environment="Synchronous")
            simulator.current_round_messages = []
            simulator.next_round_messages = []
            break

        simulator.build_next_round_messages()
        simulator.advance_to_next_round()

    elapsed = time.perf_counter() - started_at

    final_tables = export_tables(simulator.agents)
    graph_summary = summarize_graph(graph)
    distance_summary = summarize_distances(final_tables, graph_summary)
    useful_message_percentage = (
        round((simulator.total_table_changes / simulator.total_deliveries_processed) * 100, 1)
        if simulator.total_deliveries_processed
        else 0.0
    )

    return SimulationResult(
        environment="sync",
        title="Synchronous Simulation",
        graph={agent_id: list(neighbors) for agent_id, neighbors in sorted(graph.items())},
        purpose=(
            "This mode demonstrates round-based propagation. Every agent sends its "
            "current knowledge at the start of each round, and only after the full "
            "round is collected do deliveries update routing tables."
        ),
        metrics={
            "rounds_completed": simulator.rounds_completed,
            "messages_sent": simulator.total_messages_sent,
            "messages_processed": simulator.total_deliveries_processed,
            "table_changes": simulator.total_table_changes,
            "max_rounds": simulator.max_rounds,
        },
        graph_summary=graph_summary,
        events=recorder.export(),
        final_tables=final_tables,
        summary={
            "iterations": simulator.rounds_completed,
            "messages_sent": simulator.total_messages_sent,
            "messages_processed": simulator.total_deliveries_processed,
            "table_changes": simulator.total_table_changes,
            "runtime_seconds": round(elapsed, 6),
            "runtime_milliseconds": round(elapsed * 1000, 2),
            "useful_message_percentage": useful_message_percentage,
            "graph_density": graph_summary["density"],
            "average_degree": graph_summary["average_degree"],
            "max_degree": graph_summary["max_degree"],
            "isolated_nodes": len(graph_summary["isolated_nodes"]),
            **distance_summary,
        },
        generated_in_seconds=elapsed,
        notes=[
            "Synchronous execution preserves a clean round boundary.",
            "The same payload can be observed by multiple neighbors in one round before updates take effect.",
        ],
    )


def run_asynchronous_visual_simulation(
    graph: dict[int, list[int]],
    queue_timeout: float = ASYNC_QUEUE_TIMEOUT,
) -> SimulationResult:
    """Run the asynchronous simulator and capture a full trace."""

    agents = build_agents(graph)
    recorder = SimulationRecorder()
    started_at = time.perf_counter()

    simulator = AsynchronousSimulator(
        agents=agents,
        queue_timeout=queue_timeout,
        verbose=False,
        on_message_sent=recorder.record_message_sent,
        on_message_processed=recorder.record_message_processed,
    )
    simulator.run()
    recorder.record_convergence(environment="Asynchronous")
    elapsed = time.perf_counter() - started_at

    final_tables = export_tables(simulator.agents)
    graph_summary = summarize_graph(graph)
    distance_summary = summarize_distances(final_tables, graph_summary)
    useful_message_percentage = (
        round((simulator.total_table_changes / simulator.total_messages_processed) * 100, 1)
        if simulator.total_messages_processed
        else 0.0
    )

    return SimulationResult(
        environment="async",
        title="Asynchronous Simulation",
        graph={agent_id: list(neighbors) for agent_id, neighbors in sorted(graph.items())},
        purpose=(
            "This mode demonstrates message-driven propagation. Agents react as soon "
            "as a payload arrives, and successful updates can immediately trigger new "
            "messages without waiting for a global round boundary."
        ),
        metrics={
            "messages_sent": simulator.total_messages_sent,
            "messages_processed": simulator.total_messages_processed,
            "table_changes": simulator.total_table_changes,
            "queue_timeout": queue_timeout,
            "runtime_seconds": round(simulator.runtime_seconds, 6),
        },
        graph_summary=graph_summary,
        events=recorder.export(),
        final_tables=final_tables,
        summary={
            "iterations": simulator.total_messages_processed,
            "messages_sent": simulator.total_messages_sent,
            "messages_processed": simulator.total_messages_processed,
            "table_changes": simulator.total_table_changes,
            "runtime_seconds": round(simulator.runtime_seconds, 6),
            "runtime_milliseconds": round(simulator.runtime_seconds * 1000, 2),
            "useful_message_percentage": useful_message_percentage,
            "graph_density": graph_summary["density"],
            "average_degree": graph_summary["average_degree"],
            "max_degree": graph_summary["max_degree"],
            "isolated_nodes": len(graph_summary["isolated_nodes"]),
            **distance_summary,
        },
        generated_in_seconds=elapsed,
        notes=[
            "Asynchronous execution exposes causal message chains directly on the graph.",
            "Updates can ripple through the network immediately after a table change.",
        ],
    )
