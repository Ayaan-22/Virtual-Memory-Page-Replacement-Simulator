# ============================================================
#  Virtual Memory & Page Replacement Simulator
#  Authors: 23K-2084 Ayaan Irfan | 23K-2082 Muneeb Ahmed | 23K-2064 Faizan Ashfaq
# ============================================================

import random
import collections
import threading
import statistics
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, StringVar, IntVar
from abc import ABC, abstractmethod

import matplotlib
matplotlib.use('TkAgg')
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt

# ──────────────────────────────────────────────────────────────
#  SIMULATION ENGINE
# ──────────────────────────────────────────────────────────────

class PageReplacementAlgorithm(ABC):
    """Abstract base class — all algorithms inherit from here."""

    def __init__(self, capacity: int):
        self.capacity = capacity
        self.frames: set = set()
        self.hits = 0
        self.misses = 0
        self.eviction_count: collections.Counter = collections.Counter()
        self.fault_latencies: list = []
        self.residency_times: list = []
        self._entry_time: dict = {}

    # ── lifecycle ──────────────────────────────────────────────

    def reset(self):
        self.hits = 0
        self.misses = 0
        self.frames.clear()
        self.fault_latencies.clear()
        self.residency_times.clear()
        self.eviction_count.clear()
        self._entry_time.clear()

    # ── shared bookkeeping ─────────────────────────────────────

    def _check(self, page, disk_latency: float, prefetch: bool) -> bool:
        """Return True on hit. On miss record latency (unless prefetch)."""
        if page in self.frames:
            if not prefetch:
                self.hits += 1
            return True
        if not prefetch:
            self.misses += 1
            self.fault_latencies.append(disk_latency)
        return False

    def _evict_record(self, victim, time: int):
        self.eviction_count[victim] += 1
        self.residency_times.append(time - self._entry_time.pop(victim, time))
        self.frames.discard(victim)

    def _insert(self, page, time: int):
        self.frames.add(page)
        self._entry_time[page] = time

    # ── abstract interface ─────────────────────────────────────

    @abstractmethod
    def access(self, page, time: int, disk_latency: float = 0,
                prefetch: bool = False, future_ref=None):
        ...

    # ── statistics ─────────────────────────────────────────────

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            'hits':                self.hits,
            'misses':              self.misses,
            'hit_rate':            (self.hits / total) if total else 0.0,
            'avg_fault_latency_ms': (sum(self.fault_latencies) / len(self.fault_latencies))
                                    if self.fault_latencies else 0.0,
            'avg_residency':       (sum(self.residency_times) / len(self.residency_times))
                                    if self.residency_times else 0.0,
            'eviction_counts':     dict(self.eviction_count),
        }


# ── concrete algorithms ────────────────────────────────────────

class FIFO(PageReplacementAlgorithm):
    """First-In, First-Out — evict the oldest loaded page."""

    def __init__(self, capacity):
        super().__init__(capacity)
        self._queue: collections.deque = collections.deque()

    def reset(self):
        super().reset()
        self._queue.clear()

    def access(self, page, time, disk_latency=0, prefetch=False, future_ref=None):
        if self._check(page, disk_latency, prefetch):
            return
        if len(self.frames) < self.capacity:
            self._insert(page, time)
            self._queue.append(page)
        else:
            victim = self._queue.popleft()
            self._evict_record(victim, time)
            self._insert(page, time)
            self._queue.append(page)


class LRU(PageReplacementAlgorithm):
    """Least Recently Used — evict the page accessed longest ago."""

    def __init__(self, capacity):
        super().__init__(capacity)
        self._order: collections.OrderedDict = collections.OrderedDict()

    def reset(self):
        super().reset()
        self._order.clear()

    def access(self, page, time, disk_latency=0, prefetch=False, future_ref=None):
        if self._check(page, disk_latency, prefetch):
            self._order.move_to_end(page)
            return
        if len(self._order) >= self.capacity:
            victim, _ = self._order.popitem(last=False)
            self._evict_record(victim, time)
        self._order[page] = True
        self._insert(page, time)

    def stats(self):
        self.frames = set(self._order.keys())
        return super().stats()


class Optimal(PageReplacementAlgorithm):
    """Belady's Optimal — evict the page used farthest in the future."""

    def access(self, page, time, disk_latency=0, prefetch=False, future_ref=None):
        if self._check(page, disk_latency, prefetch):
            return
        if len(self.frames) < self.capacity:
            self._insert(page, time)
            return
        # Build next-use map for current frames
        future_ref = future_ref or []
        next_use: dict = {}
        for idx, p in enumerate(future_ref):
            if p in self.frames and p not in next_use:
                next_use[p] = idx
        # Victim = page used farthest (or never)
        victim = max(self.frames,
                     key=lambda p: next_use.get(p, float('inf')))
        self._evict_record(victim, time)
        self._insert(page, time)


class Clock(PageReplacementAlgorithm):
    """Clock / Second-Chance — circular buffer with reference bits."""

    def __init__(self, capacity):
        super().__init__(capacity)
        self._slots:     list = [None] * capacity
        self._use_bits:  list = [0]    * capacity
        self._ptr:       int  = 0
        self._page_idx:  dict = {}

    def reset(self):
        super().reset()
        self._slots    = [None] * self.capacity
        self._use_bits = [0]    * self.capacity
        self._ptr      = 0
        self._page_idx.clear()

    def access(self, page, time, disk_latency=0, prefetch=False, future_ref=None):
        if page in self.frames:
            if not prefetch:
                self.hits += 1
            self._use_bits[self._page_idx[page]] = 1
            return
        if not prefetch:
            self.misses += 1
            self.fault_latencies.append(disk_latency)

        if None in self._slots:
            idx = self._slots.index(None)
        else:
            while self._use_bits[self._ptr] == 1:
                self._use_bits[self._ptr] = 0
                self._ptr = (self._ptr + 1) % self.capacity
            victim = self._slots[self._ptr]
            self._evict_record(victim, time)
            self._page_idx.pop(victim, None)
            idx = self._ptr
            self._ptr = (self._ptr + 1) % self.capacity

        self._slots[idx]    = page
        self._use_bits[idx] = 1
        self.frames.add(page)
        self._entry_time[page] = time
        self._page_idx[page]   = idx


class SecondChance(Clock):
    """Alias for Clock (identical behaviour)."""


class RandomReplacement(PageReplacementAlgorithm):
    """Random Replacement — evict a uniformly random page."""

    def __init__(self, capacity):
        super().__init__(capacity)
        self._rng = random.Random(42)   # reproducible seed

    def access(self, page, time, disk_latency=0, prefetch=False, future_ref=None):
        if self._check(page, disk_latency, prefetch):
            return
        if len(self.frames) < self.capacity:
            self._insert(page, time)
        else:
            victim = self._rng.choice(tuple(self.frames))
            self._evict_record(victim, time)
            self._insert(page, time)


class LFU(PageReplacementAlgorithm):
    """Least Frequently Used — evict the page with the fewest accesses."""

    def __init__(self, capacity):
        super().__init__(capacity)
        self._count: collections.Counter = collections.Counter()

    def reset(self):
        super().reset()
        self._count.clear()

    def access(self, page, time, disk_latency=0, prefetch=False, future_ref=None):
        self._count[page] += 1
        if self._check(page, disk_latency, prefetch):
            return
        if len(self.frames) < self.capacity:
            self._insert(page, time)
            return
        min_c = min(self._count[p] for p in self.frames)
        candidates = [p for p in self.frames if self._count[p] == min_c]
        victim = min(candidates, key=lambda p: self._entry_time.get(p, time))
        self._evict_record(victim, time)
        self._count.pop(victim, None)
        self._insert(page, time)


class MFU(PageReplacementAlgorithm):
    """Most Frequently Used — evict the page with the most accesses."""

    def __init__(self, capacity):
        super().__init__(capacity)
        self._count: collections.Counter = collections.Counter()

    def reset(self):
        super().reset()
        self._count.clear()

    def access(self, page, time, disk_latency=0, prefetch=False, future_ref=None):
        self._count[page] += 1
        if self._check(page, disk_latency, prefetch):
            return
        if len(self.frames) < self.capacity:
            self._insert(page, time)
            return
        max_c = max(self._count[p] for p in self.frames)
        candidates = [p for p in self.frames if self._count[p] == max_c]
        victim = min(candidates, key=lambda p: self._entry_time.get(p, time))
        self._evict_record(victim, time)
        self._count.pop(victim, None)
        self._insert(page, time)


# ── TLB ────────────────────────────────────────────────────────

class TLB:
    """Translation Look-aside Buffer backed by any replacement algorithm."""

    def __init__(self, capacity: int, replacement_cls):
        self.capacity = capacity
        self._repl    = replacement_cls(capacity)
        self.hits     = 0
        self.misses   = 0

    def reset(self):
        self.hits   = 0
        self.misses = 0
        self._repl.reset()

    def access(self, page) -> bool:
        if page in self._repl.frames:
            self.hits += 1
            return True
        self.misses += 1
        self._repl.access(page, time=0, disk_latency=0, prefetch=True)
        return False

    def stats(self) -> dict:
        total = self.hits + self.misses
        base  = self._repl.stats()
        base.update({
            'tlb_hits':     self.hits,
            'tlb_misses':   self.misses,
            'tlb_hit_rate': (self.hits / total) if total else 0.0,
        })
        return base


# ── Simulator ──────────────────────────────────────────────────

_ALGO_MAP: dict = {
    'FIFO':        FIFO,
    'LRU':         LRU,
    'Optimal':     Optimal,
    'Clock':       Clock,
    'SecondChance':SecondChance,
    'Random':      RandomReplacement,
    'LFU':         LFU,
    'MFU':         MFU,
}


class VirtualMemorySimulator:
    """Runs multiple page-replacement algorithms on a reference string."""

    def __init__(self, frame_count: int,
                 tlb_enabled: bool = False,
                 tlb_size: int = 0,
                 tlb_algo: str = 'LRU'):
        self.frame_count    = frame_count
        self.algorithms:    dict = {}
        self.disk_latency:  float = 0.0
        self.prefetch:      bool = False
        self.prefetch_count:int  = 0
        self.tlb: TLB | None = (
            TLB(tlb_size, _ALGO_MAP[tlb_algo])
            if tlb_enabled and tlb_size > 0 and tlb_algo in _ALGO_MAP
            else None
        )

    def add_algorithm(self, name: str, algo_cls):
        self.algorithms[name] = algo_cls(self.frame_count)

    def set_disk_latency(self, ms: float):
        self.disk_latency = ms

    def enable_prefetch(self, prefetch: bool = False, prefetch_count: int = 0):
        self.prefetch       = prefetch
        self.prefetch_count = prefetch_count

    def _reset_all(self):
        for algo in self.algorithms.values():
            algo.reset()
        if self.tlb:
            self.tlb.reset()

    def run(self, reference_string: list):
        self._reset_all()
        for t, page in enumerate(reference_string):
            if self.tlb and self.tlb.access(page):
                continue
            for name, algo in self.algorithms.items():
                future = reference_string[t + 1:] if isinstance(algo, Optimal) else None
                algo.access(page, t, disk_latency=self.disk_latency, future_ref=future)
            if self.prefetch:
                for i in range(1, self.prefetch_count + 1):
                    if t + i < len(reference_string):
                        nxt = reference_string[t + i]
                        for algo in self.algorithms.values():
                            algo.access(nxt, t + i, disk_latency=0, prefetch=True)

    # ── step-by-step trace (for the Trace tab) ─────────────────

    def run_trace(self, reference_string: list, algo_name: str) -> list[dict]:
        """
        Return a list of dicts, one per reference:
          { 'page': int, 'frames': list, 'fault': bool }
        """
        algo_cls = _ALGO_MAP.get(algo_name)
        if algo_cls is None:
            return []
        algo = algo_cls(self.frame_count)
        trace = []
        for t, page in enumerate(reference_string):
            before_misses = algo.misses
            future = reference_string[t + 1:] if algo_name == 'Optimal' else None
            algo.access(page, t, disk_latency=0, future_ref=future)
            # derive current frame snapshot
            if isinstance(algo, (Clock, SecondChance)):
                snap = [p for p in algo._slots if p is not None]
            elif isinstance(algo, LRU):
                snap = list(algo._order.keys())
            else:
                snap = sorted(algo.frames)
            trace.append({
                'page':   page,
                'frames': snap[:],
                'fault':  algo.misses > before_misses,
            })
        return trace

    def report(self) -> dict:
        result = {name: algo.stats() for name, algo in self.algorithms.items()}
        if self.tlb:
            result['TLB'] = self.tlb.stats()
        return result

    def compute_avg_hit_rates(self, workloads: list) -> dict:
        algs = list(self.algorithms.keys())
        if self.tlb:
            algs.append('TLB')
        totals = {a: 0.0 for a in algs}
        for ref in workloads:
            self.run(ref)
            st = self.report()
            for a in algs:
                key = 'tlb_hit_rate' if a == 'TLB' else 'hit_rate'
                totals[a] += st[a][key]
        n = len(workloads)
        return {a: totals[a] / n for a in algs}


# ──────────────────────────────────────────────────────────────
#  USER INTERFACE
# ──────────────────────────────────────────────────────────────

_FONT_LABEL  = ("Segoe UI", 10)
_FONT_HEADER = ("Segoe UI", 10, "bold")
_FONT_MONO   = ("Courier New", 9)

_ALL_ALGOS = [
    ("FIFO",        FIFO),
    ("LRU",         LRU),
    ("Optimal",     Optimal),
    ("Clock",       Clock),
    ("SecondChance",SecondChance),
    ("Random",      RandomReplacement),
    ("LFU",         LFU),
    ("MFU",         MFU),
]


class PageReplacementUI:
    def __init__(self, master: tk.Tk):
        self.master = master
        master.title("Virtual Memory & Page Replacement Simulator")
        master.geometry("1050x720")
        master.resizable(True, True)
        master.protocol("WM_DELETE_WINDOW", master.destroy)

        self.sim:        VirtualMemorySimulator | None = None
        self._ref_str:   list = []
        self._run_btn:   ttk.Button | None = None

        self._build_notebook()

    # ── notebook skeleton ──────────────────────────────────────

    def _build_notebook(self):
        nb = ttk.Notebook(self.master)
        nb.pack(fill=tk.BOTH, expand=True)
        self._nb = nb

        self._tab_config  = ttk.Frame(nb); nb.add(self._tab_config,  text="  Configuration  ")
        self._tab_graphs  = ttk.Frame(nb); nb.add(self._tab_graphs,  text="  Graphs  ")
        self._tab_trace   = ttk.Frame(nb); nb.add(self._tab_trace,   text="  Step-by-Step Trace  ")
        self._tab_results = ttk.Frame(nb); nb.add(self._tab_results, text="  Results  ")

        self._build_config_tab()
        self._build_graphs_tab()
        self._build_trace_tab()
        self._build_results_tab()

    # ── Configuration tab ──────────────────────────────────────

    def _build_config_tab(self):
        outer = ttk.Frame(self._tab_config, padding=20)
        outer.pack(fill=tk.BOTH, expand=True)

        # ---- left column: parameters ----
        left = ttk.LabelFrame(outer, text=" Simulation Parameters ", padding=15)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        r = 0
        ttk.Label(left, text="Number of Frames:", font=_FONT_LABEL).grid(row=r, column=0, sticky="w", pady=4)
        self._frames_var = StringVar(value="4")
        ttk.Entry(left, textvariable=self._frames_var, width=10).grid(row=r, column=1, sticky="w", pady=4); r += 1

        ttk.Label(left, text="Disk Latency (ms):", font=_FONT_LABEL).grid(row=r, column=0, sticky="w", pady=4)
        self._disk_lat_var = StringVar(value="10")
        ttk.Entry(left, textvariable=self._disk_lat_var, width=10).grid(row=r, column=1, sticky="w", pady=4); r += 1

        # TLB
        self._tlb_var = IntVar(value=0)
        ttk.Checkbutton(left, text="Enable TLB", variable=self._tlb_var,
                        command=self._toggle_tlb).grid(row=r, column=0, sticky="w", pady=4); r += 1

        ttk.Label(left, text="TLB Size:", font=_FONT_LABEL).grid(row=r, column=0, sticky="w", pady=4)
        self._tlb_size_var = StringVar(value="2")
        self._tlb_size_entry = ttk.Entry(left, textvariable=self._tlb_size_var, width=10, state="disabled")
        self._tlb_size_entry.grid(row=r, column=1, sticky="w", pady=4); r += 1

        ttk.Label(left, text="TLB Policy:", font=_FONT_LABEL).grid(row=r, column=0, sticky="w", pady=4)
        self._tlb_policy_var = StringVar(value="LRU")
        self._tlb_policy_cb  = ttk.Combobox(left, textvariable=self._tlb_policy_var,
                                             values=list(_ALGO_MAP.keys()),
                                             state="disabled", width=14)
        self._tlb_policy_cb.grid(row=r, column=1, sticky="w", pady=4); r += 1

        # Prefetch
        self._prefetch_var = IntVar(value=0)
        ttk.Checkbutton(left, text="Enable Prefetch", variable=self._prefetch_var,
                        command=self._toggle_prefetch).grid(row=r, column=0, sticky="w", pady=4); r += 1

        ttk.Label(left, text="Prefetch Count:", font=_FONT_LABEL).grid(row=r, column=0, sticky="w", pady=4)
        self._prefetch_count_var = StringVar(value="1")
        self._prefetch_count_entry = ttk.Entry(left, textvariable=self._prefetch_count_var, width=10, state="disabled")
        self._prefetch_count_entry.grid(row=r, column=1, sticky="w", pady=4); r += 1

        # Reference string
        ttk.Separator(left, orient="horizontal").grid(row=r, column=0, columnspan=2, sticky="ew", pady=8); r += 1
        ttk.Label(left, text="Reference String:", font=_FONT_LABEL).grid(row=r, column=0, sticky="nw", pady=4)
        self._ref_str_var = StringVar(value="7 0 1 2 0 3 0 4 2 3 0 3 2 1 2 0 1 7 0 1")
        ttk.Entry(left, textvariable=self._ref_str_var, width=42).grid(row=r, column=1, sticky="w", pady=4); r += 1
        ttk.Label(left, text="Space-separated integers  or  'random <len> <max_page>'",
                  font=("Segoe UI", 8), foreground="gray").grid(row=r, column=0, columnspan=2, sticky="w"); r += 1

        # ---- right column: graph type + trace algo ----
        right = ttk.LabelFrame(outer, text=" Visualisation Options ", padding=15)
        right.grid(row=0, column=1, sticky="nsew")

        ttk.Label(right, text="Avg Hit-Rate Chart Type:", font=_FONT_LABEL).grid(row=0, column=0, sticky="w", pady=4)
        self._graph_type_var = StringVar(value="Bar")
        ttk.Combobox(right, textvariable=self._graph_type_var,
                     values=["Bar", "Line", "Pie"],
                     state="readonly", width=12).grid(row=0, column=1, sticky="w", pady=4)

        ttk.Label(right, text="Trace Algorithm:", font=_FONT_LABEL).grid(row=1, column=0, sticky="w", pady=4)
        self._trace_algo_var = StringVar(value="FIFO")
        ttk.Combobox(right, textvariable=self._trace_algo_var,
                     values=list(_ALGO_MAP.keys()),
                     state="readonly", width=12).grid(row=1, column=1, sticky="w", pady=4)

        outer.columnconfigure(0, weight=3)
        outer.columnconfigure(1, weight=1)

        # ---- Run button ----
        btn_frame = ttk.Frame(outer)
        btn_frame.grid(row=1, column=0, columnspan=2, pady=18)
        self._run_btn = ttk.Button(btn_frame, text="▶  Run Simulation",
                                   command=self._run_thread, width=22)
        self._run_btn.pack()

    # ── Graphs tab ─────────────────────────────────────────────

    def _build_graphs_tab(self):
        frame = ttk.Frame(self._tab_graphs, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.rowconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        self._avg_chart_frame = ttk.LabelFrame(frame, text="Average Hit Rates (across workloads)", padding=5)
        self._avg_chart_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        ttk.Label(self._avg_chart_frame, text="Run a simulation to see chart.", foreground="gray").pack(expand=True)

        self._workload_chart_frame = ttk.LabelFrame(frame, text="Hit Rate per Workload (per algorithm)", padding=5)
        self._workload_chart_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        ttk.Label(self._workload_chart_frame, text="Run a simulation to see chart.", foreground="gray").pack(expand=True)

        self._fault_chart_frame = ttk.LabelFrame(frame, text="Page Faults per Algorithm (user string)", padding=5)
        self._fault_chart_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        ttk.Label(self._fault_chart_frame, text="Run a simulation to see chart.", foreground="gray").pack(expand=True)

        self._residency_chart_frame = ttk.LabelFrame(frame, text="Avg. Residency Time per Algorithm", padding=5)
        self._residency_chart_frame.grid(row=1, column=1, sticky="nsew", padx=5, pady=5)
        ttk.Label(self._residency_chart_frame, text="Run a simulation to see chart.", foreground="gray").pack(expand=True)

    # ── Trace tab ──────────────────────────────────────────────

    def _build_trace_tab(self):
        frame = ttk.Frame(self._tab_trace, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        lbl = ttk.Label(frame, text="Step-by-step frame state for the selected algorithm  "
                                    "(★ = page fault)", font=_FONT_HEADER)
        lbl.pack(anchor="w", pady=(0, 6))

        cols_frame = ttk.Frame(frame)
        cols_frame.pack(fill=tk.BOTH, expand=True)

        self._trace_tree = ttk.Treeview(cols_frame,
                                        columns=("step", "page", "frames", "fault"),
                                        show="headings", height=28)
        self._trace_tree.heading("step",   text="Step")
        self._trace_tree.heading("page",   text="Page")
        self._trace_tree.heading("frames", text="Frames in Memory")
        self._trace_tree.heading("fault",  text="Fault?")
        self._trace_tree.column("step",   width=55,  anchor="center")
        self._trace_tree.column("page",   width=60,  anchor="center")
        self._trace_tree.column("frames", width=340, anchor="w")
        self._trace_tree.column("fault",  width=70,  anchor="center")
        self._trace_tree.tag_configure("fault", background="#ffe0e0")
        self._trace_tree.tag_configure("hit",   background="#e8f5e9")

        sb = ttk.Scrollbar(cols_frame, orient="vertical", command=self._trace_tree.yview)
        self._trace_tree.configure(yscrollcommand=sb.set)
        self._trace_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        # summary label
        self._trace_summary_var = StringVar(value="")
        ttk.Label(frame, textvariable=self._trace_summary_var,
                  font=("Segoe UI", 9, "italic"), foreground="#555").pack(anchor="w", pady=(6, 0))

    # ── Results tab ────────────────────────────────────────────

    def _build_results_tab(self):
        frame = ttk.Frame(self._tab_results, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self._stats_text = scrolledtext.ScrolledText(frame, wrap=tk.WORD,
                                                     font=_FONT_MONO,
                                                     state=tk.DISABLED)
        self._stats_text.pack(fill=tk.BOTH, expand=True)
        self._stats_text.tag_configure("header", font=("Courier New", 9, "bold"))
        self._stats_text.tag_configure("algo",   foreground="#005A9C")

    # ── toggle helpers ─────────────────────────────────────────

    def _toggle_tlb(self):
        on = bool(self._tlb_var.get())
        self._tlb_size_entry.config(state="normal"    if on else "disabled")
        self._tlb_policy_cb .config(state="readonly"  if on else "disabled")

    def _toggle_prefetch(self):
        on = bool(self._prefetch_var.get())
        self._prefetch_count_entry.config(state="normal" if on else "disabled")

    # ── input parsing ──────────────────────────────────────────

    def _parse_ref_str(self, text: str) -> list:
        tokens = text.strip().split()
        if not tokens:
            raise ValueError("Reference string cannot be empty.")
        if tokens[0].lower() == 'random':
            if len(tokens) != 3:
                raise ValueError("Syntax: random <length> <max_page>")
            length, max_page = int(tokens[1]), int(tokens[2])
            if length <= 0 or max_page <= 0:
                raise ValueError("length and max_page must be positive.")
            return [random.randint(0, max_page - 1) for _ in range(length)]
        try:
            return [int(x) for x in tokens]
        except ValueError:
            raise ValueError("All tokens must be integers (or use 'random N M').")

    def _validate_int(self, var: StringVar, label: str, positive: bool = True) -> int:
        try:
            v = int(var.get().strip())
            if positive and v <= 0:
                raise ValueError
            if not positive and v < 0:
                raise ValueError
            return v
        except ValueError:
            raise ValueError(f"{label} must be a {'positive' if positive else 'non-negative'} integer.")

    # ── simulation thread ──────────────────────────────────────

    def _run_thread(self):
        if self._run_btn:
            self._run_btn.config(state=tk.DISABLED, text="Running…")
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        def err(msg):
            messagebox.showerror("Input Error", msg)
            self.master.after(0, lambda: self._run_btn.config(state=tk.NORMAL, text="▶  Run Simulation"))

        try:
            frames      = self._validate_int(self._frames_var, "Number of frames")
            disk_lat    = self._validate_int(self._disk_lat_var, "Disk latency", positive=False)
            ref_str     = self._parse_ref_str(self._ref_str_var.get())
            graph_type  = self._graph_type_var.get()
            trace_algo  = self._trace_algo_var.get()
            tlb_enabled = bool(self._tlb_var.get())
            tlb_size    = self._validate_int(self._tlb_size_var, "TLB size") if tlb_enabled else 0
            tlb_policy  = self._tlb_policy_var.get() if tlb_enabled else 'LRU'
            pf_enabled  = bool(self._prefetch_var.get())
            pf_count    = self._validate_int(self._prefetch_count_var, "Prefetch count", positive=False) if pf_enabled else 0
        except ValueError as e:
            self.master.after(0, lambda: err(str(e)))
            return

        # Build simulator
        sim = VirtualMemorySimulator(frames, tlb_enabled, tlb_size, tlb_policy)
        for name, cls in _ALL_ALGOS:
            sim.add_algorithm(name, cls)
        sim.set_disk_latency(disk_lat)
        sim.enable_prefetch(pf_enabled, pf_count)
        self.sim = sim

        # Run on user string
        sim.run(ref_str)
        reports = sim.report()

        # Generate synthetic workloads for comparison charts
        workloads = [[random.randint(0, max(ref_str) or 7) for _ in range(50)] for _ in range(5)]

        # Generate step-by-step trace
        trace = sim.run_trace(ref_str, trace_algo)

        # Schedule all UI updates on the main thread
        self.master.after(0, lambda: self._update_all(ref_str, reports, workloads, trace, trace_algo, graph_type))

    def _update_all(self, ref_str, reports, workloads, trace, trace_algo, graph_type):
        self._clear_results()
        self._draw_avg_chart(workloads, graph_type)
        self._draw_workload_chart(workloads)
        self._draw_fault_chart(reports)
        self._draw_residency_chart(reports)
        self._fill_trace(trace, trace_algo)
        self._fill_results(ref_str, reports)
        self._nb.select(self._tab_results)
        if self._run_btn:
            self._run_btn.config(state=tk.NORMAL, text="▶  Run Simulation")

    # ── clear ──────────────────────────────────────────────────

    def _clear_results(self):
        self._stats_text.config(state=tk.NORMAL)
        self._stats_text.delete("1.0", tk.END)
        self._stats_text.config(state=tk.DISABLED)
        for container in (self._avg_chart_frame, self._workload_chart_frame,
                          self._fault_chart_frame, self._residency_chart_frame):
            for w in container.winfo_children():
                w.destroy()
        for item in self._trace_tree.get_children():
            self._trace_tree.delete(item)

    # ── chart helpers ──────────────────────────────────────────

    @staticmethod
    def _embed(fig, container):
        canvas = FigureCanvasTkAgg(fig, master=container)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        plt.close(fig)

    def _draw_avg_chart(self, workloads, graph_type):
        avg = self.sim.compute_avg_hit_rates(workloads)
        names = list(avg.keys())
        rates = [avg[n] for n in names]

        fig, ax = plt.subplots(figsize=(5, 2.8), dpi=95)
        if graph_type == "Bar":
            bars = ax.bar(names, rates, edgecolor="black", color="#4c72b0")
            for b, r in zip(bars, rates):
                ax.text(b.get_x() + b.get_width() / 2, r + 0.01,
                        f"{r:.2f}", ha="center", va="bottom", fontsize=7)
            ax.set_ylim(0, 1.05)
            ax.set_ylabel("Avg Hit Rate")
            ax.tick_params(axis="x", labelrotation=35, labelsize=7)
        elif graph_type == "Line":
            ax.plot(names, rates, marker="o", color="#4c72b0")
            ax.set_ylim(0, 1.05)
            ax.set_ylabel("Avg Hit Rate")
            ax.tick_params(axis="x", labelrotation=35, labelsize=7)
        else:
            total = sum(rates) or 1
            ax.pie([r / total for r in rates], labels=names,
                   autopct="%1.1f%%", startangle=90)
        ax.set_title("Average Hit Rate", fontsize=9)
        ax.grid(axis="y", linestyle="--", alpha=0.5)
        fig.tight_layout()
        self._embed(fig, self._avg_chart_frame)

    def _draw_workload_chart(self, workloads):
        algs = list(self.sim.algorithms.keys())
        hit_rates = {a: [] for a in algs}
        for ref in workloads:
            self.sim.run(ref)
            st = self.sim.report()
            for a in algs:
                hit_rates[a].append(st[a]['hit_rate'])

        fig, ax = plt.subplots(figsize=(5, 2.8), dpi=95)
        x = list(range(len(workloads)))
        for a in algs:
            ax.plot(x, hit_rates[a], marker="o", label=a, linewidth=1.2)
        ax.set_xlabel("Workload Index", fontsize=8)
        ax.set_ylabel("Hit Rate", fontsize=8)
        ax.set_title("Hit Rate per Workload", fontsize=9)
        ax.legend(loc="upper right", fontsize=6, ncol=2)
        ax.grid(linestyle="--", alpha=0.5)
        fig.tight_layout()
        self._embed(fig, self._workload_chart_frame)

    def _draw_fault_chart(self, reports):
        names  = [n for n in reports if n != 'TLB']
        faults = [reports[n]['misses'] for n in names]
        fig, ax = plt.subplots(figsize=(5, 2.8), dpi=95)
        bars = ax.bar(names, faults, color="#e07b54", edgecolor="black")
        for b, f in zip(bars, faults):
            ax.text(b.get_x() + b.get_width() / 2, f + 0.2,
                    str(f), ha="center", va="bottom", fontsize=7)
        ax.set_ylabel("Page Faults")
        ax.set_title("Page Faults (user string)", fontsize=9)
        ax.tick_params(axis="x", labelrotation=35, labelsize=7)
        ax.grid(axis="y", linestyle="--", alpha=0.5)
        fig.tight_layout()
        self._embed(fig, self._fault_chart_frame)

    def _draw_residency_chart(self, reports):
        names = [n for n in reports if n != 'TLB']
        res   = [reports[n]['avg_residency'] for n in names]
        fig, ax = plt.subplots(figsize=(5, 2.8), dpi=95)
        ax.bar(names, res, color="#55a868", edgecolor="black")
        ax.set_ylabel("Avg Residency (steps)")
        ax.set_title("Avg Page Residency Time", fontsize=9)
        ax.tick_params(axis="x", labelrotation=35, labelsize=7)
        ax.grid(axis="y", linestyle="--", alpha=0.5)
        fig.tight_layout()
        self._embed(fig, self._residency_chart_frame)

    # ── trace fill ─────────────────────────────────────────────

    def _fill_trace(self, trace: list, algo_name: str):
        faults = 0
        for i, step in enumerate(trace):
            tag   = "fault" if step['fault'] else "hit"
            sym   = "★" if step['fault'] else "·"
            frames_str = "  [ " + "  ".join(str(p) for p in step['frames']) + " ]"
            self._trace_tree.insert("", tk.END,
                                    values=(i + 1, step['page'], frames_str, sym),
                                    tags=(tag,))
            if step['fault']:
                faults += 1
        hits = len(trace) - faults
        self._trace_summary_var.set(
            f"Algorithm: {algo_name}  |  "
            f"Total references: {len(trace)}  |  "
            f"Hits: {hits}  |  Page Faults: {faults}  |  "
            f"Hit Rate: {hits/len(trace)*100:.1f}%" if trace else ""
        )

    # ── results fill ───────────────────────────────────────────

    def _fill_results(self, ref_str: list, reports: dict):
        txt = self._stats_text
        txt.config(state=tk.NORMAL)

        offsets = [abs(ref_str[i] - ref_str[i-1]) for i in range(1, len(ref_str))]
        avg_off = sum(offsets) / len(offsets) if offsets else 0
        txt.insert(tk.END, "═" * 72 + "\n", "header")
        txt.insert(tk.END, " SIMULATION RESULTS\n", "header")
        txt.insert(tk.END, "═" * 72 + "\n", "header")
        txt.insert(tk.END,
            f" Reference string  : {' '.join(str(p) for p in ref_str)}\n"
            f" Length            : {len(ref_str)}\n"
            f" Unique pages      : {len(set(ref_str))}\n"
            f" Avg page offset   : {avg_off:.2f}\n"
            f" Frames allocated  : {self.sim.frame_count}\n"
        )
        txt.insert(tk.END, "═" * 72 + "\n\n", "header")

        total_refs = len(ref_str)
        for name, st in reports.items():
            txt.insert(tk.END, f" ── {name} ──\n", "algo")
            hits     = st['hits']
            misses   = st['misses']
            hit_rate = st['hit_rate']
            evictions= st.get('eviction_counts', {})
            total_ev = sum(evictions.values())
            most_ev  = max(evictions.items(), key=lambda kv: kv[1]) if evictions else (None, 0)
            algo_obj = self.sim.algorithms.get(name)
            resid_std = (statistics.stdev(algo_obj.residency_times)
                         if algo_obj and len(algo_obj.residency_times) > 1 else 0.0)

            txt.insert(tk.END,
                f"  Hits                  : {hits}\n"
                f"  Misses (Page Faults)  : {misses}\n"
                f"  Hit Rate              : {hit_rate*100:6.2f}%\n"
                f"  Page Fault Rate       : {misses/total_refs*100:6.2f}%  ({misses}/{total_refs})\n"
                f"  Avg Fault Latency(ms) : {st['avg_fault_latency_ms']:.2f}\n"
                f"  Avg Residency         : {st['avg_residency']:.2f}\n"
                f"  Residency StdDev      : {resid_std:.2f}\n"
                f"  Total Evictions       : {total_ev}\n"
                f"  Most Evicted Page     : {most_ev[0]} (×{most_ev[1]})\n"
                f"  Eviction Map          : {evictions}\n"
            )
            if name == 'TLB':
                txt.insert(tk.END,
                    f"  TLB Hits              : {st.get('tlb_hits', 0)}\n"
                    f"  TLB Misses            : {st.get('tlb_misses', 0)}\n"
                    f"  TLB Hit Rate          : {st.get('tlb_hit_rate', 0)*100:.2f}%\n"
                )
            txt.insert(tk.END, "  " + "─" * 60 + "\n")

        txt.config(state=tk.DISABLED)


# ──────────────────────────────────────────────────────────────
#  ENTRY POINT
# ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    random.seed(123)
    root = tk.Tk()
    PageReplacementUI(root)
    try:
        root.state('zoomed')          # Windows / some Linux WMs
    except tk.TclError:
        root.attributes('-zoomed', True)   # fallback (Linux)
    root.mainloop()
