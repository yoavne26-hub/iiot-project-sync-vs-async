"""Tkinter visual simulator for the IIOT project."""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from backend.config import ASYNC_QUEUE_TIMEOUT, DEFAULT_SEED, MAX_ITERATIONS
from backend.network import generate_random_graph
from backend.simulations import (
    SimulationResult,
    run_asynchronous_visual_simulation,
    run_synchronous_visual_simulation,
)


BACKGROUND = "#e8eef7"
SURFACE_BG = "#f7faff"
PANEL_BG = "#ffffff"
PANEL_SOFT = "#f1f5f9"
GRAPH_BG = "#09111f"
EDGE_COLOR = "#5b708d"
EDGE_ACTIVE = "#facc15"
EDGE_CHANGED = "#22c55e"
NODE_FILL = "#e0f2fe"
NODE_OUTLINE = "#38bdf8"
NODE_TEXT = "#082032"
NODE_SEND = "#fde68a"
NODE_RECV = "#86efac"
NODE_CONVERGED = "#bbf7d0"
LOG_BG = "#08111e"
LOG_TEXT = "#dbe7f5"
ACCENT = "#2563eb"
ACCENT_DARK = "#1d4ed8"
TEXT_MAIN = "#0f172a"
TEXT_MUTED = "#475569"
ASYNC_SIMULTANEOUS_WINDOW_MS = 2.0
PLAYBACK_SPEED_OPTIONS = ("0.5x", "1x", "2x", "5x", "10x")
DEFAULT_CANVAS_WIDTH = 860
DEFAULT_CANVAS_HEIGHT = 500
MIN_CANVAS_WIDTH = 320
MIN_CANVAS_HEIGHT = 240


def edge_key(left: int, right: int) -> tuple[int, int]:
    """Return a stable undirected edge key."""

    return (min(left, right), max(left, right))


def calculate_circular_layout(
    node_ids: list[int],
    width: int,
    height: int,
    padding_x: int = 86,
    padding_top: int = 72,
    padding_bottom: int = 110,
) -> dict[int, tuple[float, float]]:
    """Arrange nodes on a circle inside the available canvas area."""

    if not node_ids:
        return {}

    if len(node_ids) == 1:
        return {node_ids[0]: (width / 2, height / 2)}

    radius_x = max(60.0, (width / 2) - padding_x)
    radius_y = max(60.0, (height - padding_top - padding_bottom) / 2)
    center_x = width / 2
    center_y = padding_top + radius_y
    layout: dict[int, tuple[float, float]] = {}

    for index, node_id in enumerate(sorted(node_ids)):
        angle = (2 * math.pi * index / len(node_ids)) - (math.pi / 2)
        x = center_x + radius_x * math.cos(angle)
        y = center_y + radius_y * math.sin(angle)
        layout[node_id] = (x, y)

    return layout


def calculate_force_layout(
    graph: dict[int, list[int]],
    width: int,
    height: int,
    padding_x: int,
    padding_top: int,
    padding_bottom: int,
) -> dict[int, tuple[float, float]]:
    """Arrange nodes with a deterministic force layout for dense graphs."""

    node_ids = sorted(graph)
    if len(node_ids) <= 2:
        return calculate_circular_layout(node_ids, width, height, padding_x, padding_top, padding_bottom)

    positions = calculate_circular_layout(node_ids, width, height, padding_x, padding_top, padding_bottom)
    left = padding_x
    right = max(left + 1, width - padding_x)
    top = padding_top
    bottom = max(top + 1, height - padding_bottom)
    area = max((right - left) * (bottom - top), 1)
    ideal = math.sqrt(area / len(node_ids))
    temperature = min(right - left, bottom - top) / 7

    edges = {
        edge_key(agent_id, neighbor_id)
        for agent_id, neighbors in graph.items()
        for neighbor_id in neighbors
    }

    for _ in range(90):
        displacement = {node_id: [0.0, 0.0] for node_id in node_ids}

        for index, left_node in enumerate(node_ids):
            x1, y1 = positions[left_node]
            for right_node in node_ids[index + 1 :]:
                x2, y2 = positions[right_node]
                dx = x1 - x2
                dy = y1 - y2
                distance = max(math.hypot(dx, dy), 0.01)
                force = (ideal * ideal) / distance
                offset_x = (dx / distance) * force
                offset_y = (dy / distance) * force
                displacement[left_node][0] += offset_x
                displacement[left_node][1] += offset_y
                displacement[right_node][0] -= offset_x
                displacement[right_node][1] -= offset_y

        for left_node, right_node in edges:
            x1, y1 = positions[left_node]
            x2, y2 = positions[right_node]
            dx = x1 - x2
            dy = y1 - y2
            distance = max(math.hypot(dx, dy), 0.01)
            force = (distance * distance) / ideal
            offset_x = (dx / distance) * force
            offset_y = (dy / distance) * force
            displacement[left_node][0] -= offset_x
            displacement[left_node][1] -= offset_y
            displacement[right_node][0] += offset_x
            displacement[right_node][1] += offset_y

        for node_id in node_ids:
            x, y = positions[node_id]
            dx, dy = displacement[node_id]
            distance = max(math.hypot(dx, dy), 0.01)
            x += (dx / distance) * min(abs(dx), temperature)
            y += (dy / distance) * min(abs(dy), temperature)
            positions[node_id] = (
                min(right, max(left, x)),
                min(bottom, max(top, y)),
            )
        temperature *= 0.94

    return positions


def format_payload(payload: dict[int, int] | None) -> str:
    """Return a compact payload string for the log."""

    if not payload:
        return "empty"
    return ", ".join(
        f"{target}:{distance}" for target, distance in sorted(payload.items())
    )


class SimulationPlaybackFrame(ttk.Frame):
    """One visual playback tab for a single simulation result."""

    def __init__(
        self,
        parent: ttk.Notebook,
        result: SimulationResult,
        speed_var: tk.StringVar,
    ) -> None:
        super().__init__(parent)
        self.result = result
        self.speed_var = speed_var
        self.canvas_width = DEFAULT_CANVAS_WIDTH
        self.canvas_height = DEFAULT_CANVAS_HEIGHT
        self.node_radius = 22
        self.positions: dict[int, tuple[float, float]] = {}
        self.playback_events = self._build_playback_events(result.events)

        self.current_event_index = 0
        self.playback_job: str | None = None
        self.animation_jobs: list[str] = []
        self.animation_token = 0
        self.is_paused = False
        self.current_message_dots: set[int] = set()
        self.active_burst_remaining = 0
        self.message_counts: dict[tuple[int, int], int] = {}
        self.node_shapes: dict[int, dict[str, int]] = {}
        self.edge_shapes: dict[tuple[int, int], dict[str, int]] = {}
        self.pending_resize = False
        self.last_canvas_size = (self.canvas_width, self.canvas_height)
        self.summary_items: list[tuple[str, object]] = []
        self.summary_window_id: int | None = None
        self.summary_column_count = 0

        self.status_var = tk.StringVar(value="Ready")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.play_toggle_var = tk.StringVar(value="Pause")
        self.current_event_var = tk.StringVar(value="Waiting for playback")
        self.current_payload_var = tk.StringVar(value="-")
        self.current_effect_var = tk.StringVar(value="-")
        self.current_round_var = tk.StringVar(value="-")
        self.graph_meta_var = tk.StringVar(value=self._graph_metadata_text())

        self._build_layout()
        self.configure(style="App.TFrame")
        self._draw_graph()
        self._populate_final_tables()
        self._populate_summary()
        self._set_intro_text()
        self.after(self._scaled_delay(250), self.start_playback)

    def _build_playback_events(self, raw_events: list[dict[str, object]]) -> list[dict[str, object]]:
        """Merge send/process pairs into one delivery animation event."""

        pending_sends: dict[tuple[int, int], list[dict[str, object]]] = {}
        playback_events: list[dict[str, object]] = []

        for event in raw_events:
            kind = event["kind"]
            if kind == "message_sent":
                key = edge_key(int(event["sender"]), int(event["receiver"]))
                pending_sends.setdefault(key, []).append(event)
                continue

            if kind == "message_processed":
                key = edge_key(int(event["sender"]), int(event["receiver"]))
                pending_queue = pending_sends.get(key, [])
                sent_event = pending_queue.pop(0) if pending_queue else {}
                playback_events.append(
                    {
                        "step": event["step"],
                        "kind": "message_delivery",
                        "title": f"Delivery {event['sender']} -> {event['receiver']}",
                        "description": event["description"],
                        "sender": event["sender"],
                        "receiver": event["receiver"],
                        "payload": sent_event.get("payload"),
                        "changed": event["changed"],
                        "round_number": event.get("round_number"),
                        "sent_timestamp_ms": sent_event.get("timestamp_ms"),
                        "processed_timestamp_ms": event.get("timestamp_ms"),
                    }
                )
                continue

            playback_events.append(event)

        for pending_queue in pending_sends.values():
            for orphan in pending_queue:
                insert_at = len(playback_events)
                for i, ev in enumerate(playback_events):
                    if ev["step"] >= orphan["step"]:
                        insert_at = i
                        break
                playback_events.insert(insert_at, orphan)

        return playback_events

    def _build_layout(self) -> None:
        """Create the widgets for the tab."""

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        control_bar = ttk.Frame(self, style="App.TFrame", padding=(16, 14, 16, 10))
        control_bar.grid(row=0, column=0, sticky="ew")
        control_bar.columnconfigure(6, weight=1)

        ttk.Label(
            control_bar,
            text=self.result.title,
            style="PaneTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(control_bar, text="Start Over", style="Toolbar.TButton", command=self.replay).grid(
            row=0, column=1, padx=(16, 8)
        )
        self.play_toggle_button = ttk.Button(
            control_bar,
            textvariable=self.play_toggle_var,
            style="Toolbar.TButton",
            command=self.toggle_playback,
        )
        self.play_toggle_button.grid(
            row=0, column=2, padx=8
        )
        ttk.Button(control_bar, text="Skip to End", style="Toolbar.TButton", command=self.skip_to_end).grid(
            row=0, column=3, padx=8
        )
        ttk.Label(control_bar, text="Speed", style="Muted.TLabel").grid(
            row=0, column=4, sticky="w", padx=(12, 6)
        )
        ttk.Combobox(
            control_bar,
            textvariable=self.speed_var,
            values=PLAYBACK_SPEED_OPTIONS,
            state="readonly",
            width=6,
            style="Modern.TCombobox",
        ).grid(row=0, column=5, sticky="w")
        ttk.Progressbar(
            control_bar,
            variable=self.progress_var,
            maximum=max(len(self.playback_events), 1),
            mode="determinate",
            style="Playback.Horizontal.TProgressbar",
        ).grid(row=0, column=6, sticky="ew", padx=(16, 12))
        ttk.Label(control_bar, textvariable=self.status_var, style="Muted.TLabel").grid(
            row=0, column=7, sticky="e"
        )

        content_area = ttk.Frame(self, style="App.TFrame", padding=(16, 0, 16, 16))
        content_area.grid(row=1, column=0, sticky="nsew")
        content_area.columnconfigure(0, weight=1)
        content_area.rowconfigure(0, weight=1)

        self.view_notebook = ttk.Notebook(content_area)
        self.view_notebook.grid(row=0, column=0, sticky="nsew")

        live_view = ttk.Frame(self.view_notebook, style="App.TFrame", padding=0)
        live_view.columnconfigure(0, weight=4)
        live_view.columnconfigure(1, weight=2)
        live_view.rowconfigure(0, weight=1)

        results_view = ttk.Frame(self.view_notebook, style="App.TFrame", padding=0)
        results_view.columnconfigure(0, weight=1)
        results_view.rowconfigure(0, weight=1)

        self.view_notebook.add(live_view, text="Live Playback")
        self.view_notebook.add(results_view, text="Results")

        self.results_view_notebook = ttk.Notebook(results_view)
        self.results_view_notebook.grid(row=0, column=0, sticky="nsew")

        tables_view = ttk.Frame(self.results_view_notebook, style="App.TFrame", padding=0)
        tables_view.columnconfigure(0, weight=1)
        tables_view.rowconfigure(0, weight=1)

        summary_view = ttk.Frame(self.results_view_notebook, style="App.TFrame", padding=0)
        summary_view.columnconfigure(0, weight=1)
        summary_view.rowconfigure(0, weight=1)

        self.results_view_notebook.add(summary_view, text="Summary")
        self.results_view_notebook.add(tables_view, text="Tables")

        graph_panel = ttk.Frame(live_view, style="Card.TFrame", padding=10)
        graph_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        graph_panel.rowconfigure(2, weight=1)
        graph_panel.columnconfigure(0, weight=1)

        ttk.Label(graph_panel, text="Graph Visual", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        ttk.Label(graph_panel, textvariable=self.graph_meta_var, style="CardMuted.TLabel").grid(
            row=1, column=0, sticky="w", pady=(0, 8)
        )
        self.canvas = tk.Canvas(
            graph_panel,
            width=self.canvas_width,
            height=self.canvas_height,
            bg=GRAPH_BG,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.grid(row=2, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        side_panel = ttk.Frame(live_view, style="App.TFrame")
        side_panel.grid(row=0, column=1, sticky="nsew")
        side_panel.columnconfigure(0, weight=1)
        side_panel.rowconfigure(0, weight=0)
        side_panel.rowconfigure(1, weight=1)

        details_panel = ttk.Frame(side_panel, style="Card.TFrame", padding=10)
        details_panel.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        details_panel.columnconfigure(1, weight=1)
        ttk.Label(details_panel, text="Current Event", style="Section.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )
        details = (
            ("Message", self.current_event_var),
            ("Payload", self.current_payload_var),
            ("Effect", self.current_effect_var),
            ("Round", self.current_round_var),
        )
        for row, (label, variable) in enumerate(details, start=1):
            ttk.Label(details_panel, text=label, style="MetricLabel.TLabel").grid(
                row=row, column=0, sticky="nw", padx=(0, 8), pady=2
            )
            ttk.Label(details_panel, textvariable=variable, style="CardValue.TLabel", wraplength=320).grid(
                row=row, column=1, sticky="ew", pady=2
            )

        log_panel = ttk.Frame(side_panel, style="Card.TFrame", padding=10)
        log_panel.grid(row=1, column=0, sticky="nsew")
        log_panel.rowconfigure(1, weight=1)
        log_panel.columnconfigure(0, weight=1)

        ttk.Label(log_panel, text="Message Log", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        self.log_widget = ScrolledText(
            log_panel,
            width=44,
            height=28,
            bg=LOG_BG,
            fg=LOG_TEXT,
            insertbackground=LOG_TEXT,
            relief="flat",
            wrap="word",
            font=("Consolas", 10),
            padx=14,
            pady=12,
        )
        self.log_widget.grid(row=1, column=0, sticky="nsew")
        self.log_widget.tag_configure("title", foreground="#ffffff", font=("Consolas", 10, "bold"))
        self.log_widget.tag_configure("info", foreground="#93c5fd")
        self.log_widget.tag_configure("send", foreground="#fde68a")
        self.log_widget.tag_configure("recv_changed", foreground="#86efac")
        self.log_widget.tag_configure("recv_no_change", foreground="#cbd5e1")
        self.log_widget.configure(state="disabled")

        tables_panel = ttk.Frame(tables_view, style="Card.TFrame", padding=12)
        tables_panel.grid(row=0, column=0, sticky="nsew")
        tables_panel.columnconfigure(0, weight=1)
        tables_panel.rowconfigure(1, weight=1)

        ttk.Label(tables_panel, text="Final Tables", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        self.tables_notebook = ttk.Notebook(tables_panel)
        self.tables_notebook.grid(row=1, column=0, sticky="nsew")

        summary_panel = ttk.Frame(summary_view, style="Card.TFrame", padding=12)
        summary_panel.grid(row=0, column=0, sticky="nsew")
        summary_panel.columnconfigure(0, weight=1)
        summary_panel.rowconfigure(1, weight=1)
        ttk.Label(summary_panel, text="Simulation Summary", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        self.summary_canvas = tk.Canvas(
            summary_panel,
            bg=PANEL_BG,
            highlightthickness=0,
            bd=0,
        )
        self.summary_canvas.grid(row=1, column=0, sticky="nsew")
        self.summary_scrollbar = ttk.Scrollbar(
            summary_panel,
            orient="vertical",
            command=self.summary_canvas.yview,
        )
        self.summary_scrollbar.grid(row=1, column=1, sticky="ns", padx=(8, 0))
        self.summary_canvas.configure(yscrollcommand=self.summary_scrollbar.set)
        self.summary_frame = ttk.Frame(self.summary_canvas, style="Card.TFrame")
        self.summary_window_id = self.summary_canvas.create_window(
            (0, 0),
            window=self.summary_frame,
            anchor="nw",
        )
        self.summary_frame.bind("<Configure>", self._on_summary_frame_configure)
        self.summary_canvas.bind("<Configure>", self._on_summary_canvas_configure)

    def _draw_graph(self) -> None:
        """Draw the literal nodes and edges on the canvas."""

        width, height = self._current_canvas_size()
        self.canvas_width = width
        self.canvas_height = height
        self.node_radius = self._calculate_node_radius(width, height)
        padding_x, padding_top, padding_bottom = self._calculate_graph_padding(width, height)
        edge_count = int(self.result.graph_summary["edge_count"])
        self.positions = calculate_circular_layout(
            list(self.result.graph.keys()),
            width,
            height,
            padding_x=padding_x,
            padding_top=padding_top,
            padding_bottom=padding_bottom,
        )
        self.canvas.delete("all")
        self.node_shapes.clear()
        self.edge_shapes.clear()

        for agent_id, neighbors in sorted(self.result.graph.items()):
            for neighbor_id in neighbors:
                key = edge_key(agent_id, neighbor_id)
                if key in self.edge_shapes:
                    continue

                x1, y1 = self.positions[key[0]]
                x2, y2 = self.positions[key[1]]
                points: tuple[float, ...]
                if edge_count > len(self.result.graph):
                    curve_offset = self._edge_curve_offset(key, x1, y1, x2, y2)
                    mid_x = (x1 + x2) / 2
                    mid_y = (y1 + y2) / 2
                    points = (x1, y1, mid_x + curve_offset[0], mid_y + curve_offset[1], x2, y2)
                else:
                    points = (x1, y1, x2, y2)
                line_id = self.canvas.create_line(
                    *points,
                    fill=EDGE_COLOR,
                    width=3,
                    smooth=edge_count > len(self.result.graph),
                )
                self.edge_shapes[key] = {
                    "line": line_id,
                }

        for node_id, (x, y) in sorted(self.positions.items()):
            label_size = max(9, min(14, self.node_radius // 2 + 3))
            caption_size = max(8, min(11, self.node_radius // 3 + 3))
            caption_offset = self.node_radius + max(12, caption_size + 4)
            halo_id = self.canvas.create_oval(
                x - self.node_radius - 10,
                y - self.node_radius - 10,
                x + self.node_radius + 10,
                y + self.node_radius + 10,
                outline="",
                fill="",
            )
            circle_id = self.canvas.create_oval(
                x - self.node_radius,
                y - self.node_radius,
                x + self.node_radius,
                y + self.node_radius,
                fill=NODE_FILL,
                outline=NODE_OUTLINE,
                width=3,
            )
            label_id = self.canvas.create_text(
                x,
                y,
                text=str(node_id),
                fill=NODE_TEXT,
                font=("Segoe UI", label_size, "bold"),
            )
            caption_id = self.canvas.create_text(
                x,
                y + caption_offset,
                text=f"Agent {node_id}",
                fill="#e2e8f0",
                font=("Segoe UI Semibold", caption_size),
            )
            self.node_shapes[node_id] = {
                "halo": halo_id,
                "circle": circle_id,
                "label": label_id,
                "caption": caption_id,
            }

        self._draw_graph_legend(width)

    def _edge_curve_offset(
        self,
        key: tuple[int, int],
        x1: float,
        y1: float,
        x2: float,
        y2: float,
    ) -> tuple[float, float]:
        """Return a small deterministic perpendicular offset for busy graphs."""

        dx = x2 - x1
        dy = y2 - y1
        distance = max(math.hypot(dx, dy), 1.0)
        normal_x = -dy / distance
        normal_y = dx / distance
        direction = -1 if (key[0] + key[1]) % 2 else 1
        magnitude = 12 + ((key[0] * 7 + key[1] * 11) % 13)
        return normal_x * magnitude * direction, normal_y * magnitude * direction

    def _draw_graph_legend(self, width: int) -> None:
        """Draw a compact color legend inside the graph canvas."""

        items = (
            (EDGE_ACTIVE, "message"),
            (EDGE_CHANGED, "updated"),
            (NODE_SEND, "sender"),
            (NODE_RECV, "receiver"),
        )
        x = max(14, width - 390)
        y = 16
        self.canvas.create_rectangle(
            x - 10,
            y - 8,
            x + 368,
            y + 30,
            fill="#111827",
            outline="#1f2937",
        )
        cursor = x
        for color, label in items:
            self.canvas.create_oval(cursor, y, cursor + 12, y + 12, fill=color, outline="")
            self.canvas.create_text(
                cursor + 18,
                y + 6,
                text=label,
                fill="#e2e8f0",
                anchor="w",
                font=("Segoe UI", 9),
            )
            cursor += 88

    def _graph_metadata_text(self) -> str:
        """Return compact graph metadata for the live view."""

        summary = self.result.graph_summary
        return (
            f"Nodes {summary['node_count']}  |  Edges {summary['edge_count']}  |  "
            f"Density {self.result.summary['graph_density']}  |  "
            f"Isolated {self.result.summary['isolated_nodes']}  |  "
            f"Events {len(self.playback_events)}"
        )

    def _populate_final_tables(self) -> None:
        """Create a table tab for every agent."""

        for tab_id in self.tables_notebook.tabs():
            self.tables_notebook.forget(tab_id)

        for agent_id in sorted(self.result.final_tables, key=lambda value: int(value)):
            agent_state = self.result.final_tables[agent_id]
            frame = ttk.Frame(self.tables_notebook, style="Card.TFrame", padding=8)
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(0, weight=1)
            tree = ttk.Treeview(
                frame,
                columns=("target", "distance", "via"),
                show="headings",
                height=4,
            )
            tree.heading("target", text="Target")
            tree.heading("distance", text="Distance")
            tree.heading("via", text="Via")
            tree.column("target", width=90, anchor="center")
            tree.column("distance", width=90, anchor="center")
            tree.column("via", width=90, anchor="center")

            for row in agent_state["rows"]:
                tree.insert("", "end", values=(row["target"], row["distance"], row["via"]))

            tree.grid(row=0, column=0, sticky="ew")
            self.tables_notebook.add(frame, text=f"Agent {agent_id}")

    def _populate_summary(self) -> None:
        """Render the summary metrics beneath the tables."""

        self.summary_items = [
            ("Nodes", self.result.graph_summary["node_count"]),
            ("Edges", self.result.graph_summary["edge_count"]),
            ("Density", self.result.summary["graph_density"]),
            ("Avg Degree", self.result.summary["average_degree"]),
            ("Max Degree", self.result.summary["max_degree"]),
            ("Isolated Nodes", self.result.summary["isolated_nodes"]),
            ("Iterations", self.result.summary["iterations"]),
            ("Messages", self.result.summary["messages_sent"]),
            ("Processed", self.result.summary["messages_processed"]),
            ("Table Changes", self.result.summary["table_changes"]),
            ("Useful %", f"{self.result.summary['useful_message_percentage']}%"),
            ("Reachability %", f"{self.result.summary['reachability_percentage']}%"),
            ("Longest Distance", self.result.summary["longest_distance"]),
            ("Avg Distance", self.result.summary["average_distance"]),
            ("Known Routes", self.result.summary["known_routes"]),
            ("Unreachable Routes", self.result.summary["unreachable_routes"]),
            ("Runtime ms", self.result.summary["runtime_milliseconds"]),
            ("Runtime s", self.result.summary["runtime_seconds"]),
        ]

        self._render_summary_cards()

    def _render_summary_cards(self) -> None:
        """Lay out summary cards based on the current available width."""

        for child in self.summary_frame.winfo_children():
            child.destroy()

        available_width = self.summary_canvas.winfo_width()
        if available_width <= 1:
            available_width = 920

        card_min_width = 170
        gap = 12
        columns = max(1, min(4, available_width // (card_min_width + gap)))
        self.summary_column_count = columns

        for column in range(columns):
            self.summary_frame.columnconfigure(column, weight=1, uniform="summary")

        for index, (label, value) in enumerate(self.summary_items):
            row = index // columns
            column = index % columns
            card = ttk.Frame(self.summary_frame, style="Metric.TFrame", padding=10)
            card.grid(row=row, column=column, padx=6, pady=6, sticky="ew")
            ttk.Label(card, text=label, style="MetricLabel.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Label(card, text=str(value), style="MetricValue.TLabel").grid(row=1, column=0, sticky="w")

    def _set_intro_text(self) -> None:
        """Write the intro lines to the log."""

        self._clear_log()
        self._append_log(self.result.title, "title")
        self._append_log(self.result.purpose, "info")
        self._append_log("Playback will animate each delivery in one motion: yellow while traveling, green on arrival.", "info")

    def _playback_speed(self) -> float:
        """Return the currently selected playback speed multiplier."""

        try:
            speed = float(str(self.speed_var.get()).rstrip("x"))
            if speed > 0:
                return speed
        except (TypeError, ValueError):
            pass
        return 1.0

    def _scaled_delay(self, delay_ms: int) -> int:
        """Scale a base delay by the current playback speed."""

        return max(1, int(delay_ms / self._playback_speed()))

    def start_playback(self) -> None:
        """Start the event playback from the beginning."""

        self._cancel_all_jobs()
        self.current_event_index = 0
        self.active_burst_remaining = 0
        self.message_counts.clear()
        self.is_paused = False
        self._draw_graph()
        self._set_intro_text()
        self._reset_current_details()
        self.play_toggle_var.set("Pause")
        self._set_progress_status("Running")
        self._schedule_next(self._scaled_delay(350))

    def replay(self) -> None:
        """Replay the simulation."""

        self.start_playback()

    def toggle_playback(self) -> None:
        """Toggle between paused and running playback states."""

        if self.is_paused:
            self.resume()
        else:
            self.pause()

    def pause(self) -> None:
        """Pause playback if it is active."""

        if self.playback_job is not None or self.animation_jobs:
            self._cancel_all_jobs()
            self.is_paused = True
            self.play_toggle_var.set("Resume")
            self._set_progress_status("Paused")

    def resume(self) -> None:
        """Resume playback if it was paused."""

        if self.playback_job is None and not self.animation_jobs and self.current_event_index < len(self.playback_events):
            self.is_paused = False
            self.play_toggle_var.set("Pause")
            self._set_progress_status("Running")
            self._schedule_next(self._scaled_delay(100))

    def skip_to_end(self) -> None:
        """Jump playback to the completed visual state."""

        self._cancel_all_jobs()
        self.current_event_index = len(self.playback_events)
        self.is_paused = False
        self.play_toggle_var.set("Pause")
        self._draw_graph()
        self._reapply_visual_progress()
        self._complete_playback()

    def _complete_playback(self) -> None:
        """Mark the run as completed without scheduling more work."""

        self._set_progress_status("Completed")
        self.play_toggle_var.set("Pause")
        self._append_log("Simulation complete.", "info")
        self._clear_transient_state()
        self.current_event_var.set("Simulation complete")
        self.current_payload_var.set("-")
        self.current_effect_var.set("Final tables ready")
        self.current_round_var.set("-")

    def _set_progress_status(self, state: str) -> None:
        """Update the progress bar and status text using playback position."""

        total = max(len(self.playback_events), 1)
        position = min(self.current_event_index, len(self.playback_events))
        self.progress_var.set(position)
        self.status_var.set(f"{state}  {position} / {total}")

    def _reset_current_details(self) -> None:
        """Clear the current event panel."""

        self.current_event_var.set("Waiting for playback")
        self.current_payload_var.set("-")
        self.current_effect_var.set("-")
        self.current_round_var.set("-")

    def _set_current_details(self, event: dict[str, object]) -> None:
        """Render event details in the side panel."""

        kind = str(event["kind"]).replace("_", " ").title()
        sender = event.get("sender")
        receiver = event.get("receiver")
        if sender is not None and receiver is not None:
            self.current_event_var.set(f"{kind}: {sender} -> {receiver}")
        else:
            self.current_event_var.set(kind)

        payload = event.get("payload")
        self.current_payload_var.set(format_payload(payload) if payload is not None else "-")

        if event.get("changed") is True:
            effect = "table updated"
        elif event.get("changed") is False:
            effect = "no table change"
        else:
            effect = str(event.get("description", "-"))
        self.current_effect_var.set(effect)

        round_number = event.get("round_number")
        if round_number is not None:
            self.current_round_var.set(str(round_number))
        elif event.get("processed_timestamp_ms") is not None:
            self.current_round_var.set(f"{float(event['processed_timestamp_ms']):.1f} ms")
        else:
            self.current_round_var.set("-")

    def _schedule_next(self, delay_ms: int) -> None:
        """Schedule playback of the next event."""

        self.playback_job = self.after(delay_ms, self._play_next_event)

    def _schedule_animation(self, delay_ms: int, callback) -> None:
        """Track animation callbacks so pause/replay can cancel them."""

        job_id = self.after(delay_ms, callback)
        self.animation_jobs.append(job_id)

    def _consume_animation_job(self, job_id: str) -> None:
        """Remove a completed animation job from the tracked list."""

        if job_id in self.animation_jobs:
            self.animation_jobs.remove(job_id)

    def _cancel_all_jobs(self) -> None:
        """Cancel playback and animation callbacks."""

        self.animation_token += 1
        if self.playback_job is not None:
            self.after_cancel(self.playback_job)
            self.playback_job = None

        for job_id in list(self.animation_jobs):
            self.after_cancel(job_id)
        self.animation_jobs.clear()

        for dot_id in list(self.current_message_dots):
            self.canvas.delete(dot_id)
        self.current_message_dots.clear()
        self.active_burst_remaining = 0

    def _on_canvas_resize(self, _event: tk.Event) -> None:
        """Redraw the graph to fit the current canvas size."""

        width, height = self._current_canvas_size()
        if width < MIN_CANVAS_WIDTH or height < MIN_CANVAS_HEIGHT:
            return
        if (width, height) == self.last_canvas_size:
            return
        self.last_canvas_size = (width, height)
        if self.animation_jobs or self.current_message_dots:
            self.pending_resize = True
            return
        self._draw_graph()
        self._reapply_visual_progress()
        self.pending_resize = False

    def _play_next_event(self) -> None:
        """Handle the next event in the trace."""

        self.playback_job = None
        if self.current_event_index >= len(self.playback_events):
            self._complete_playback()
            return

        event = self.playback_events[self.current_event_index]
        if self.result.environment == "async" and event["kind"] == "message_delivery":
            burst_events = self._collect_async_burst()
            self._set_current_details(burst_events[-1])
            self._set_progress_status("Running")
            self._handle_async_delivery_burst(burst_events)
            return

        self.current_event_index += 1
        self._set_current_details(event)
        self._set_progress_status("Running")

        if event["kind"] == "message_delivery":
            self._handle_message_delivery(event)
            return

        if event["kind"] == "message_sent":
            self._handle_orphan_message_sent(event)
            return

        if event["kind"] == "round_start":
            self._append_log(
                f"[Round {event['round_number']}] collected outgoing messages.",
                "info",
            )
        elif event["kind"] == "round_end":
            self._append_log(
                f"[Round {event['round_number']}] finished with {event['description']}",
                "info",
            )
        elif event["kind"] == "converged":
            self._append_log("Network converged. All tables stabilized.", "info")
            self._clear_transient_state()
        else:
            self._append_log(event["description"], "info")

        self._schedule_next(self._scaled_delay(380))

    def _collect_async_burst(self) -> list[dict[str, object]]:
        """Collect deliveries that began effectively at the same time."""

        def _effective_timestamp(event: dict[str, object]) -> float:
            ts = event.get("sent_timestamp_ms")
            if ts is not None:
                return float(ts)
            return float(event.get("processed_timestamp_ms") or 0.0)

        burst: list[dict[str, object]] = []
        first_event = self.playback_events[self.current_event_index]
        first_timestamp = _effective_timestamp(first_event)

        while self.current_event_index < len(self.playback_events):
            event = self.playback_events[self.current_event_index]
            if event["kind"] != "message_delivery":
                break

            timestamp = _effective_timestamp(event)
            if burst and abs(timestamp - first_timestamp) > ASYNC_SIMULTANEOUS_WINDOW_MS:
                break

            burst.append(event)
            self.current_event_index += 1

        return burst

    def _handle_async_delivery_burst(self, events: list[dict[str, object]]) -> None:
        """Animate multiple async deliveries that happened at nearly the same time."""

        self._clear_transient_state()
        self.active_burst_remaining = len(events)

        for event in events:
            sender = int(event["sender"])
            receiver = int(event["receiver"])
            key = edge_key(sender, receiver)
            self._update_edge_count(key)
            self._set_node_color(sender, NODE_SEND, halo=EDGE_ACTIVE)
            self._set_edge_color(key, EDGE_ACTIVE, width=5)
            payload = event.get("payload")
            payload_str = format_payload(payload) if payload is not None else "unpaired"
            self._append_log(
                f"Send  {sender} -> {receiver} | payload [{payload_str}]",
                "send",
            )
            changed = bool(event["changed"])
            self._animate_message_dot(
                sender=sender,
                receiver=receiver,
                on_arrival=lambda s=sender, r=receiver, c=changed: self._complete_async_burst_delivery(s, r, c),
            )

    def _complete_async_burst_delivery(self, sender: int, receiver: int, changed: bool) -> None:
        """Mark one message in the active async burst as delivered."""

        self._complete_delivery(sender, receiver, changed, schedule_next=False)
        self.active_burst_remaining -= 1
        if self.active_burst_remaining == 0:
            self._apply_pending_resize_if_needed()
            self._set_progress_status("Running")
            self._schedule_next(self._scaled_delay(220))

    def _handle_message_delivery(self, event: dict[str, object]) -> None:
        """Animate a full sender-to-receiver delivery in one motion."""

        sender = int(event["sender"])
        receiver = int(event["receiver"])
        key = edge_key(sender, receiver)
        self._update_edge_count(key)
        self._clear_transient_state()
        self._set_node_color(sender, NODE_SEND, halo=EDGE_ACTIVE)
        self._set_edge_color(key, EDGE_ACTIVE, width=5)
        payload = event.get("payload")
        payload_str = format_payload(payload) if payload is not None else "unpaired"
        self._append_log(
            f"Send  {sender} -> {receiver} | payload [{payload_str}]",
            "send",
        )
        changed = bool(event["changed"])
        self._animate_message_dot(
            sender=sender,
            receiver=receiver,
            on_arrival=lambda: self._complete_delivery(sender, receiver, changed, schedule_next=True),
        )

    def _handle_orphan_message_sent(self, event: dict[str, object]) -> None:
        """Fallback for unexpected unpaired send events."""

        sender = int(event["sender"])
        receiver = int(event["receiver"])
        key = edge_key(sender, receiver)
        self._update_edge_count(key)
        self._clear_transient_state()
        self._set_node_color(sender, NODE_SEND, halo=EDGE_ACTIVE)
        self._set_edge_color(key, EDGE_ACTIVE, width=5)
        payload = event.get("payload")
        payload_str = format_payload(payload) if payload is not None else "unpaired"
        self._append_log(f"Send  {sender} -> {receiver} | payload [{payload_str}]", "send")
        self._schedule_next(self._scaled_delay(220))

    def _complete_delivery(self, sender: int, receiver: int, changed: bool, schedule_next: bool) -> None:
        """Mark the receiver as having received the message on arrival."""

        key = edge_key(sender, receiver)
        self._set_node_color(receiver, NODE_RECV, halo=EDGE_CHANGED if changed else NODE_RECV)
        self._set_edge_color(key, EDGE_CHANGED if changed else EDGE_ACTIVE, width=5 if changed else 4)
        state_text = "table updated" if changed else "no table change"
        self.current_effect_var.set(state_text)
        self._append_log(
            f"Recv  {sender} -> {receiver} | {state_text}",
            "recv_changed" if changed else "recv_no_change",
        )
        self._apply_pending_resize_if_needed()
        if schedule_next:
            self._schedule_next(self._scaled_delay(220))

    def _animate_message_dot(self, sender: int, receiver: int, on_arrival) -> None:
        """Move a glowing dot from sender to receiver across the line."""

        x1, y1 = self.positions[sender]
        x2, y2 = self.positions[receiver]
        dot_radius = 8
        dot = self.canvas.create_oval(
            x1 - dot_radius,
            y1 - dot_radius,
            x1 + dot_radius,
            y1 + dot_radius,
            fill=EDGE_ACTIVE,
            outline="",
        )
        self.current_message_dots.add(dot)

        total_steps = 16
        step_delay = self._scaled_delay(28)
        token = self.animation_token
        holder: dict[str, str] = {}

        def animate(step_index: int) -> None:
            if token != self.animation_token:
                return
            progress = step_index / total_steps
            x = x1 + ((x2 - x1) * progress)
            y = y1 + ((y2 - y1) * progress)
            self.canvas.coords(
                dot,
                x - dot_radius,
                y - dot_radius,
                x + dot_radius,
                y + dot_radius,
            )
            if step_index < total_steps:

                def continue_animation() -> None:
                    self._consume_animation_job(holder["id"])
                    animate(step_index + 1)

                holder["id"] = self.after(step_delay, continue_animation)
                self.animation_jobs.append(holder["id"])
                return

            self.canvas.delete(dot)
            self.current_message_dots.discard(dot)
            if token == self.animation_token:
                on_arrival()

        animate(0)

    def _clear_transient_state(self) -> None:
        """Reset nodes and edges to their default display state."""

        for node_id in self.node_shapes:
            self._set_node_color(node_id, NODE_FILL, halo="")

        for key in self.edge_shapes:
            self._set_edge_color(key, EDGE_COLOR, width=3)

    def _paint_all_nodes(self, color: str) -> None:
        """Paint every node with the same fill color."""

        for node_id in self.node_shapes:
            self._set_node_color(node_id, color, halo="")

    def _set_node_color(self, node_id: int, fill: str, halo: str) -> None:
        """Update the fill and halo of one node."""

        shapes = self.node_shapes[node_id]
        self.canvas.itemconfigure(shapes["circle"], fill=fill)
        self.canvas.itemconfigure(shapes["halo"], fill=halo, outline="")

    def _set_edge_color(self, key: tuple[int, int], color: str, width: int) -> None:
        """Update the color and width of one edge."""

        shapes = self.edge_shapes[key]
        self.canvas.itemconfigure(shapes["line"], fill=color, width=width)

    def _update_edge_count(self, key: tuple[int, int]) -> None:
        """Increment the traversal count for an edge."""
        self.message_counts[key] = self.message_counts.get(key, 0) + 1

    def _append_log(self, line: str, tag: str | None = None) -> None:
        """Append one line to the message log."""

        self.log_widget.configure(state="normal")
        start = self.log_widget.index("end-1c")
        self.log_widget.insert("end", line + "\n")
        if tag is not None:
            self.log_widget.tag_add(tag, start, "end-1c")
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def _clear_log(self) -> None:
        """Clear the message log."""

        self.log_widget.configure(state="normal")
        self.log_widget.delete("1.0", "end")
        self.log_widget.configure(state="disabled")

    def _reapply_visual_progress(self) -> None:
        """Rebuild the static visual state up to the current event index."""

        self.message_counts.clear()
        for event in self.playback_events[: self.current_event_index]:
            if event["kind"] in {"message_delivery", "message_sent"}:
                key = edge_key(int(event["sender"]), int(event["receiver"]))
                self._update_edge_count(key)

        if self.current_event_index == 0:
            return

        last_event = self.playback_events[self.current_event_index - 1]
        if last_event["kind"] == "message_delivery":
            burst_start = self.current_event_index - 1
            last_timestamp = float(
                last_event.get("sent_timestamp_ms")
                or last_event.get("processed_timestamp_ms")
                or -1.0
            )
            while burst_start > 0:
                previous_event = self.playback_events[burst_start - 1]
                if previous_event["kind"] != "message_delivery":
                    break
                previous_timestamp = float(
                    previous_event.get("sent_timestamp_ms")
                    or previous_event.get("processed_timestamp_ms")
                    or -999.0
                )
                if abs(previous_timestamp - last_timestamp) > ASYNC_SIMULTANEOUS_WINDOW_MS:
                    break
                burst_start -= 1

            for burst_event in self.playback_events[burst_start:self.current_event_index]:
                sender = int(burst_event["sender"])
                receiver = int(burst_event["receiver"])
                changed = bool(burst_event["changed"])
                self._set_node_color(sender, NODE_SEND, halo=EDGE_ACTIVE)
                self._set_node_color(receiver, NODE_RECV, halo=EDGE_CHANGED if changed else NODE_RECV)
                self._set_edge_color(
                    edge_key(sender, receiver),
                    EDGE_CHANGED if changed else EDGE_ACTIVE,
                    width=5 if changed else 4,
                )
        elif last_event["kind"] == "message_sent":
            sender = int(last_event["sender"])
            receiver = int(last_event["receiver"])
            self._set_node_color(sender, NODE_SEND, halo=EDGE_ACTIVE)
            self._set_edge_color(edge_key(sender, receiver), EDGE_ACTIVE, width=5)
        elif last_event["kind"] == "converged":
            self._clear_transient_state()

    def _current_canvas_size(self) -> tuple[int, int]:
        """Return the current drawable canvas size with sane minimum fallbacks."""

        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if width <= 1:
            width = self.canvas_width
        if height <= 1:
            height = self.canvas_height
        return max(MIN_CANVAS_WIDTH, width), max(MIN_CANVAS_HEIGHT, height)

    def _calculate_node_radius(self, width: int, height: int) -> int:
        """Scale node radius so dense graphs still fit on smaller canvases."""

        node_count = max(1, len(self.result.graph))
        circumference_budget = (2 * math.pi * max(min(width, height) / 2.6, 1.0)) / node_count
        size_budget = min(width, height) / max(node_count + 3, 6)
        return max(10, min(24, int(min(circumference_budget / 2.4, size_budget))))

    def _calculate_graph_padding(self, width: int, height: int) -> tuple[int, int, int]:
        """Keep nodes and captions inside the current canvas bounds."""

        horizontal = max(self.node_radius + 24, min(86, int(width * 0.1)))
        top = max(self.node_radius + 24, min(72, int(height * 0.12)))
        bottom = max(self.node_radius + 46, min(110, int(height * 0.18)))
        return horizontal, top, bottom

    def _apply_pending_resize_if_needed(self) -> None:
        """Redraw after a deferred resize once no message animation is active."""

        if not self.pending_resize or self.animation_jobs or self.current_message_dots:
            return
        self._draw_graph()
        self._reapply_visual_progress()
        self.pending_resize = False

    def _on_summary_frame_configure(self, _event: tk.Event) -> None:
        """Keep the summary canvas scroll region synced to its content."""

        self.summary_canvas.configure(scrollregion=self.summary_canvas.bbox("all"))

    def _on_summary_canvas_configure(self, event: tk.Event) -> None:
        """Resize and relayout summary cards when the viewport width changes."""

        if self.summary_window_id is not None:
            self.summary_canvas.itemconfigure(self.summary_window_id, width=event.width)

        card_min_width = 170
        gap = 12
        columns = max(1, min(4, event.width // (card_min_width + gap)))
        if columns != self.summary_column_count and self.summary_items:
            self._render_summary_cards()


class IIOTVisualizerApp(tk.Tk):
    """Starter window and container for the simulation views."""

    def __init__(self) -> None:
        super().__init__()
        self.title("IIOT Project Visual Simulator")
        self._configure_window_size()
        self.configure(bg=BACKGROUND)

        self.environment_var = tk.StringVar(value="both")
        self.nodes_var = tk.IntVar(value=5)
        self.edge_probability_var = tk.StringVar(value="0.4")
        self.seed_var = tk.StringVar(value=str(DEFAULT_SEED))
        self.playback_speed_var = tk.StringVar(value="1x")

        self._configure_styles()
        self._build_layout()

    def _configure_window_size(self) -> None:
        """Choose a startup size that fits on the current display."""

        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        window_width = min(1500, max(960, int(screen_width * 0.92)))
        window_height = min(980, max(720, int(screen_height * 0.88)))
        self.geometry(f"{window_width}x{window_height}")

        min_width = min(window_width, max(760, min(1100, screen_width - 120)))
        min_height = min(window_height, max(620, min(760, screen_height - 140)))
        self.minsize(min_width, min_height)

    def _configure_styles(self) -> None:
        """Set a simple visual style for the application."""

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("App.TFrame", background=BACKGROUND)
        style.configure("Hero.TFrame", background=PANEL_BG, relief="flat", borderwidth=0)
        style.configure("Card.TFrame", background=PANEL_BG, relief="flat", borderwidth=0)
        style.configure("Metric.TFrame", background=PANEL_SOFT)
        style.configure("Title.TLabel", background=PANEL_BG, foreground=TEXT_MAIN, font=("Segoe UI Semibold", 24))
        style.configure("PaneTitle.TLabel", background=BACKGROUND, foreground=TEXT_MAIN, font=("Segoe UI Semibold", 18))
        style.configure("Section.TLabel", background=PANEL_BG, foreground=TEXT_MAIN, font=("Segoe UI Semibold", 13))
        style.configure("Field.TLabel", background=PANEL_BG, foreground=TEXT_MUTED, font=("Segoe UI", 10, "bold"))
        style.configure("Muted.TLabel", background=BACKGROUND, foreground=TEXT_MUTED, font=("Segoe UI", 10))
        style.configure("HeroSub.TLabel", background=PANEL_BG, foreground=TEXT_MUTED, font=("Segoe UI", 11))
        style.configure("CardMuted.TLabel", background=PANEL_BG, foreground=TEXT_MUTED, font=("Segoe UI", 9))
        style.configure("CardValue.TLabel", background=PANEL_BG, foreground=TEXT_MAIN, font=("Segoe UI", 10))
        style.configure("MetricLabel.TLabel", background=PANEL_SOFT, foreground=TEXT_MUTED, font=("Segoe UI", 9, "bold"))
        style.configure("MetricValue.TLabel", background=PANEL_SOFT, foreground=TEXT_MAIN, font=("Segoe UI Semibold", 13))
        style.configure("TLabel", background=BACKGROUND, foreground=TEXT_MAIN, font=("Segoe UI", 10))
        style.configure(
            "Primary.TButton",
            font=("Segoe UI Semibold", 10),
            padding=(16, 10),
            background=ACCENT,
            foreground="#ffffff",
            borderwidth=0,
        )
        style.map(
            "Primary.TButton",
            background=[("active", ACCENT_DARK), ("pressed", ACCENT_DARK)],
            foreground=[("disabled", "#cbd5e1"), ("!disabled", "#ffffff")],
        )
        style.configure(
            "Toolbar.TButton",
            font=("Segoe UI Semibold", 10),
            padding=(14, 8),
            background=PANEL_BG,
            foreground=TEXT_MAIN,
            borderwidth=1,
            relief="flat",
        )
        style.map(
            "Toolbar.TButton",
            background=[("active", "#dbeafe"), ("pressed", "#bfdbfe")],
            bordercolor=[("active", ACCENT)],
        )
        style.configure(
            "Compact.TButton",
            font=("Segoe UI Semibold", 9),
            padding=(8, 6),
            background=PANEL_BG,
            foreground=TEXT_MAIN,
            borderwidth=1,
            relief="flat",
        )
        style.map(
            "Compact.TButton",
            background=[("active", "#dbeafe"), ("pressed", "#bfdbfe")],
            bordercolor=[("active", ACCENT)],
        )
        style.configure(
            "Playback.Horizontal.TProgressbar",
            troughcolor="#dbe7f5",
            background=ACCENT,
            bordercolor="#dbe7f5",
            lightcolor=ACCENT,
            darkcolor=ACCENT,
        )
        style.configure("TNotebook", background=BACKGROUND, borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure(
            "TNotebook.Tab",
            font=("Segoe UI Semibold", 10),
            padding=(16, 8),
            background="#dbe7f5",
            foreground=TEXT_MUTED,
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", PANEL_BG), ("active", "#dfe9f7")],
            foreground=[("selected", TEXT_MAIN), ("active", TEXT_MAIN)],
        )
        style.configure(
            "Treeview",
            background=PANEL_BG,
            fieldbackground=PANEL_BG,
            foreground=TEXT_MAIN,
            rowheight=28,
            borderwidth=0,
            relief="flat",
            font=("Segoe UI", 10),
        )
        style.configure(
            "Treeview.Heading",
            background="#e2e8f0",
            foreground=TEXT_MAIN,
            relief="flat",
            borderwidth=0,
            font=("Segoe UI Semibold", 10),
        )
        style.map("Treeview.Heading", background=[("active", "#dbeafe")])
        style.configure(
            "Modern.TCombobox",
            fieldbackground=PANEL_SOFT,
            background=PANEL_SOFT,
            foreground=TEXT_MAIN,
            borderwidth=0,
            arrowsize=14,
            padding=6,
        )
        style.configure(
            "Modern.TSpinbox",
            fieldbackground=PANEL_SOFT,
            background=PANEL_SOFT,
            foreground=TEXT_MAIN,
            arrowsize=14,
            padding=6,
        )
        style.configure(
            "Modern.TEntry",
            fieldbackground=PANEL_SOFT,
            foreground=TEXT_MAIN,
            padding=6,
        )

    def _build_layout(self) -> None:
        """Create the starter controls and results area."""

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top_panel = ttk.Frame(self, style="App.TFrame", padding=(18, 18, 18, 12))
        top_panel.grid(row=0, column=0, sticky="ew")
        top_panel.columnconfigure(0, weight=1)

        hero = ttk.Frame(top_panel, style="Hero.TFrame", padding=(20, 18, 20, 18))
        hero.grid(row=0, column=0, sticky="ew")
        for index in range(6):
            hero.columnconfigure(index, weight=0)
        hero.columnconfigure(6, weight=1)

        ttk.Label(hero, text="IIOT Visual Simulator", style="Title.TLabel").grid(
            row=0, column=0, columnspan=7, sticky="w"
        )
        ttk.Label(
            hero,
            text="Configure a run, then watch messages move across the network in real time.",
            style="HeroSub.TLabel",
        ).grid(row=1, column=0, columnspan=7, sticky="w", pady=(4, 16))

        ttk.Label(hero, text="Environment", style="Field.TLabel").grid(row=2, column=0, sticky="w")
        environment_combo = ttk.Combobox(
            hero,
            textvariable=self.environment_var,
            values=("sync", "async", "both"),
            state="readonly",
            width=14,
            style="Modern.TCombobox",
        )
        environment_combo.grid(row=3, column=0, sticky="w", padx=(0, 14))

        ttk.Label(hero, text="Nodes", style="Field.TLabel").grid(row=2, column=1, sticky="w")
        ttk.Spinbox(
            hero,
            from_=2,
            to=40,
            textvariable=self.nodes_var,
            width=8,
            style="Modern.TSpinbox",
        ).grid(row=3, column=1, sticky="w", padx=(0, 14))

        ttk.Label(hero, text="Edge Probability", style="Field.TLabel").grid(row=2, column=2, sticky="w")
        ttk.Entry(hero, textvariable=self.edge_probability_var, width=10, style="Modern.TEntry").grid(
            row=3, column=2, sticky="w", padx=(0, 14)
        )

        ttk.Label(hero, text="Seed", style="Field.TLabel").grid(row=2, column=3, sticky="w")
        ttk.Entry(hero, textvariable=self.seed_var, width=10, style="Modern.TEntry").grid(
            row=3, column=3, sticky="w", padx=(0, 14)
        )

        ttk.Button(
            hero,
            text="Run Simulation",
            style="Primary.TButton",
            command=self.run_selected_simulation,
        ).grid(
            row=3, column=4, sticky="w", padx=(10, 8)
        )

        self.feedback_var = tk.StringVar(value="Waiting to run.")
        ttk.Label(hero, textvariable=self.feedback_var, style="HeroSub.TLabel").grid(
            row=3, column=6, sticky="e"
        )

        results_frame = ttk.Frame(self, style="App.TFrame", padding=(18, 0, 18, 18))
        results_frame.grid(row=1, column=0, sticky="nsew")
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(0, weight=1)

        self.results_notebook = ttk.Notebook(results_frame)
        self.results_notebook.grid(row=0, column=0, sticky="nsew")

        placeholder = ttk.Frame(self.results_notebook, style="Card.TFrame", padding=24)
        ttk.Label(
            placeholder,
            text="Run a simulation to populate the graph, message log, tables, and summary.",
            style="HeroSub.TLabel",
        ).grid(row=0, column=0, sticky="w")
        self.results_notebook.add(placeholder, text="Starter")

    def run_selected_simulation(self) -> None:
        """Generate the graph, run the simulation, and build result tabs."""

        try:
            node_count = int(self.nodes_var.get())
        except (TypeError, ValueError):
            self.feedback_var.set("Nodes must be a whole number from 2 to 40.")
            return

        try:
            edge_probability = float(self.edge_probability_var.get())
        except (TypeError, ValueError):
            self.feedback_var.set("Edge probability must be a decimal from 0 to 1.")
            return

        try:
            seed = int(self.seed_var.get())
        except (TypeError, ValueError):
            self.feedback_var.set("Seed must be a whole number.")
            return

        if not 2 <= node_count <= 40:
            self.feedback_var.set("Nodes must be between 2 and 40.")
            return

        if not 0 <= edge_probability <= 1:
            self.feedback_var.set("Edge probability must be between 0 and 1.")
            return

        graph = generate_random_graph(
            num_agents=node_count,
            edge_probability=edge_probability,
            seed=seed,
        )
        edge_count = sum(len(neighbors) for neighbors in graph.values()) // 2
        if edge_count == 0:
            self.feedback_var.set("This seed produced no edges. Increase probability or change seed.")
            return

        for tab_id in self.results_notebook.tabs():
            self.results_notebook.forget(tab_id)

        generated = 0
        environment = self.environment_var.get()
        results: list[SimulationResult] = []
        if environment in {"sync", "both"}:
            sync_result = run_synchronous_visual_simulation(graph=graph, max_rounds=MAX_ITERATIONS)
            sync_tab = SimulationPlaybackFrame(
                self.results_notebook,
                sync_result,
                speed_var=self.playback_speed_var,
            )
            self.results_notebook.add(sync_tab, text="Synchronous")
            results.append(sync_result)
            generated += 1

        if environment in {"async", "both"}:
            async_result = run_asynchronous_visual_simulation(
                graph=graph,
                queue_timeout=ASYNC_QUEUE_TIMEOUT,
            )
            async_tab = SimulationPlaybackFrame(
                self.results_notebook,
                async_result,
                speed_var=self.playback_speed_var,
            )
            self.results_notebook.add(async_tab, text="Asynchronous")
            results.append(async_result)
            generated += 1

        if len(results) == 2:
            comparison_tab = self._build_comparison_tab(results)
            self.results_notebook.insert(0, comparison_tab, text="Comparison")

        self.feedback_var.set(
            f"Generated {generated} visual simulation tab{'s' if generated != 1 else ''} for {node_count} nodes, {edge_count} edges."
        )
        if self.results_notebook.tabs():
            self.results_notebook.select(self.results_notebook.tabs()[0])

    def _build_comparison_tab(self, results: list[SimulationResult]) -> ttk.Frame:
        """Create a side-by-side comparison for sync and async runs."""

        frame = ttk.Frame(self.results_notebook, style="Card.TFrame", padding=18)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        ttk.Label(frame, text="Synchronous vs Asynchronous", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 10)
        )
        table = ttk.Treeview(
            frame,
            columns=("metric", "sync", "async", "delta"),
            show="headings",
            height=10,
        )
        for column, title, width in (
            ("metric", "Metric", 180),
            ("sync", "Synchronous", 130),
            ("async", "Asynchronous", 130),
            ("delta", "Async - Sync", 130),
        ):
            table.heading(column, text=title)
            table.column(column, width=width, anchor="center")

        by_environment = {result.environment: result for result in results}
        sync = by_environment["sync"].summary
        async_summary = by_environment["async"].summary
        metrics = (
            ("Iterations", "iterations"),
            ("Messages Sent", "messages_sent"),
            ("Messages Processed", "messages_processed"),
            ("Table Changes", "table_changes"),
            ("Useful %", "useful_message_percentage"),
            ("Reachability %", "reachability_percentage"),
            ("Avg Distance", "average_distance"),
            ("Runtime ms", "runtime_milliseconds"),
        )
        for label, key in metrics:
            sync_value = sync[key]
            async_value = async_summary[key]
            delta = self._format_delta(sync_value, async_value)
            table.insert("", "end", values=(label, sync_value, async_value, delta))

        table.grid(row=1, column=0, sticky="nsew")
        return frame

    def _format_delta(self, left: object, right: object) -> str:
        """Return a compact numeric delta for comparison tables."""

        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            delta = right - left
            if isinstance(delta, float):
                return f"{delta:+.2f}"
            return f"{delta:+d}"
        return "-"


def launch_app() -> None:
    """Run the desktop visual simulator."""

    app = IIOTVisualizerApp()
    app.mainloop()
