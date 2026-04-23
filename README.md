# IIOT Project Visuals

Desktop Tkinter visual simulator for an IIOT network-routing exercise. The project models a group of agents connected by an undirected graph and visualizes how routing-table information spreads through the network in synchronous and asynchronous modes.

## What It Does

- Generates a random agent network from configurable parameters.
- Runs synchronous simulations where messages are collected and delivered round by round.
- Runs asynchronous simulations where agents process queued messages independently.
- Records message sends, message processing, table changes, convergence, and timing metrics.
- Displays an interactive Tkinter playback of the network, final tables, logs, and summaries.

## Project Structure

- `main.py` - application entrypoint.
- `backend/config.py` - default constants such as seed, maximum iterations, and async queue timeout.
- `backend/network.py` - random undirected graph generation.
- `backend/models.py` - core data models: agents, messages, and routing/update tables.
- `backend/simulations.py` - synchronous and asynchronous simulators plus trace recording.
- `frontend/visualizer.py` - Tkinter GUI, graph playback, tables, logs, and summary panels.
- `docs/` - assignment/reference documents.
- `requirements.txt` - Python dependency list.

## Core Models

The backend is built around three simple ideas:

- `Agent` - one node in the network. Each agent has a unique numeric ID, a list of neighbors, and its own update table.
- `Message` - a payload sent from one agent to one neighbor. The payload contains only `{target: distance}` pairs.
- `UpdateTable` - the local knowledge of one agent. Each row stores:
  - `target` - destination agent ID
  - `distance` - known distance to that destination
  - `via` - the neighbor through which that destination is currently reached

Every agent starts with exactly one row in its table:

- `(self, 0, self)`

That means each agent initially knows only how to reach itself with distance `0`.

## Update Algorithm

The update rule is implemented in `UpdateTable.process_incoming_payload(...)`.

When agent `Ai` receives a message from neighbor `Aj`, it processes every row in `Aj`'s payload:

1. Read one `(target, received_distance)` pair from the incoming payload.
2. Compute `candidate_distance = received_distance + 1`.
3. If `target` does not exist in `Ai`'s table, add a new row:
   - `(target, candidate_distance, Aj)`
4. If `target` already exists but the current known distance is larger than `candidate_distance`, replace the row:
   - `(target, candidate_distance, Aj)`
5. Otherwise leave the row unchanged.

Important detail:

- Agents do **not** send the `via` column in messages.
- They only send `{target: distance}`.
- The receiving agent reconstructs the `via` column locally as `sender`.

This is a distance-vector style update rule: each agent improves its table only when a shorter path is discovered.

## Environments

The project implements the same update algorithm in two different execution environments.

### Synchronous Environment

The synchronous simulator works in explicit rounds.

How it behaves:

1. At the start of a round, each agent prepares outgoing messages from its current table.
2. Those messages are stored in `current_round_messages`.
3. The simulator processes all messages in that round.
4. If tables changed, the next wave of messages is built into `next_round_messages`.
5. Those new messages become visible only in the **next** round.

This means:

- no message generated during round `i` can affect round `i` immediately
- all agents conceptually act against the same round snapshot
- convergence happens when a full round completes with no table changes

This is the clean round-based interpretation of the exercise.

### Asynchronous Environment

The asynchronous simulator treats each agent as its own worker thread.

How it behaves:

1. Each agent owns a blocking inbox queue.
2. A worker thread waits until a message arrives for that agent.
3. When a message arrives, the agent updates its table immediately.
4. If the table changed, the agent immediately sends its updated payload to all neighbors.
5. There is no global round barrier.

This means:

- agents react independently
- useful updates can ripple through the graph immediately
- an agent stays idle until it receives a message
- convergence happens when no messages are left queued or being processed

The async environment is therefore event-driven rather than round-driven.

## How The Whole System Works

From startup to visualization, the flow is:

1. `main.py` launches the Tkinter application.
2. The user chooses:
   - number of agents
   - edge probability
   - random seed
   - environment (`sync`, `async`, or both`)
3. `backend/network.py` generates a random undirected graph.
4. `build_agents(...)` converts that graph into `Agent` objects.
5. The selected simulator runs:
   - `SynchronousSimulator`
   - `AsynchronousSimulator`
6. While the simulator runs, the backend records a structured trace of:
   - messages sent
   - messages processed
   - round boundaries
   - table changes
   - convergence
7. The frontend replays that trace on the graph canvas and shows:
   - live message flow
   - final tables for every agent
   - summary metrics such as iterations, message counts, distances, density, and runtime

## Convergence

The project uses the assignment's convergence idea: the system has converged when tables stop changing.

In practice:

- synchronous: convergence is detected when an entire round finishes without any table updates
- asynchronous: convergence is detected when no message remains in flight and no worker is still processing a message

## Measurement And Summary

Each simulation result includes:

- number of iterations or processed message steps
- total messages sent
- total messages processed
- total table changes
- runtime in seconds and milliseconds
- graph statistics such as node count, edge count, density, and degree metrics
- routing statistics such as longest distance, average distance, known routes, and reachability percentage

These values are used by the GUI summary tab so the user can compare synchronous and asynchronous behavior on the same generated network.

## Requirements

The project currently uses only the Python standard library. Python 3.10 or newer is recommended because the code uses modern type hint syntax.

Tkinter is required for the GUI. It is included with most standard Python installations on Windows.

## Setup

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

The requirements file is intentionally empty except for a note because there are no third-party dependencies.

## Run The Visualizer

```powershell
python main.py
```
