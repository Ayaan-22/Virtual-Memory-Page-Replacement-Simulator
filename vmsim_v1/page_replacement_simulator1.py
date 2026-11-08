#23K-2084 Ayaan Irfan
#23k-2082 Muneeb Ahmed
#23K-2064 Faizan Ashfaq

import random
import collections
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, StringVar, IntVar
from abc import ABC, abstractmethod
import matplotlib
matplotlib.use('TkAgg')
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
import statistics

# === Simulation Classes ===

class PageReplacementAlgorithm(ABC):
    """
    Abstract base class for page replacement algorithms.
    Provides common statistics gathering (hits, misses, latencies, residency).
    """
    def __init__(self, capacity):
        self.capacity = capacity
        self.frames = set()              # O(1) membership checks
        self.hits = 0
        self.misses = 0
        self.eviction_count = collections.Counter()  # track how often each page is evicted
        self.fault_latencies = []        # record disk latency on each fault
        self.residency_times = []        # record how long pages reside before eviction
        self._entry_time = {}            # page -> load time

    def reset(self):
        """
        Reset all counters and data structures for a fresh run.
        Subclasses should override and call super().reset().
        """
        self.hits = 0
        self.misses = 0
        self.frames.clear()
        self.fault_latencies.clear()
        self.residency_times.clear()
        self.eviction_count.clear()
        self._entry_time.clear()

    def base_access_check(self, page, time, disk_latency, prefetch=False):
        """
        Shared hit/miss bookkeeping.
        If prefetch=True, do not count hits or misses—just load pages silently.
        Return True if it was a hit (and counted), False otherwise.
        """
        if page in self.frames:
            if not prefetch:
                self.hits += 1
            return True
        else:
            if not prefetch:
                self.misses += 1
                self.fault_latencies.append(disk_latency)
            return False

    @abstractmethod
    def access(self, page, time, disk_latency=0, prefetch=False, prefetch_count=0, future_ref=None):
        """
        Access a page at given time. On miss, handle eviction if needed.
        Must call base_access_check(page, time, disk_latency, prefetch) first if not overriding.
        """
        pass

    def stats(self):
        """
        Return a dict of collected statistics:
          - hits, misses, hit_rate
          - avg_fault_latency_ms, avg_residency
          - eviction_counts (per page)
        """
        total = self.hits + self.misses
        avg_latency = (sum(self.fault_latencies) / len(self.fault_latencies)) if self.fault_latencies else 0
        avg_residency = (sum(self.residency_times) / len(self.residency_times)) if self.residency_times else 0

        return {
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': (self.hits / total) if total else 0,
            'avg_fault_latency_ms': avg_latency,
            'avg_residency': avg_residency,
            'eviction_counts': dict(self.eviction_count)
        }


class FIFO(PageReplacementAlgorithm):
    """
    First-In, First-Out page replacement.
    Maintains a queue of pages in arrival order.
    """
    def __init__(self, capacity):
        super().__init__(capacity)
        self.queue = collections.deque()

    def reset(self):
        super().reset()
        self.queue.clear()

    def access(self, page, time, disk_latency=0, prefetch=False, prefetch_count=0, future_ref=None):
        # 1) Hit/miss check (skip counting if prefetch)
        if self.base_access_check(page, time, disk_latency, prefetch=prefetch):
            return

        # 2) Miss (or prefetch insert): if space, add; else evict oldest
        if len(self.frames) < self.capacity:
            self.frames.add(page)
            self.queue.append(page)
            self._entry_time[page] = time
        else:
            evict = self.queue.popleft()
            self.eviction_count[evict] += 1
            self.residency_times.append(time - self._entry_time.pop(evict))
            self.frames.remove(evict)

            self.frames.add(page)
            self.queue.append(page)
            self._entry_time[page] = time


class LRU(PageReplacementAlgorithm):
    """
    Least Recently Used page replacement.
    Uses an OrderedDict to maintain recency.
    """
    def __init__(self, capacity):
        super().__init__(capacity)
        self.order = collections.OrderedDict()

    def reset(self):
        super().reset()
        self.order.clear()

    def access(self, page, time, disk_latency=0, prefetch=False, prefetch_count=0, future_ref=None):
        # 1) Hit/miss check
        hit = self.base_access_check(page, time, disk_latency, prefetch=prefetch)
        if hit:
            # Move to most recently used
            self.order.move_to_end(page)
            return

        # 2) Miss (or prefetch insert): eviction if needed
        if len(self.order) >= self.capacity:
            evict, _ = self.order.popitem(last=False)
            self.eviction_count[evict] += 1
            self.residency_times.append(time - self._entry_time.pop(evict))
            self.frames.remove(evict)

        # 3) Insert page as most recently used
        self.order[page] = True
        self.frames.add(page)
        self._entry_time[page] = time

    def stats(self):
        # Keep frames in sync with the OrderedDict keys
        self.frames = set(self.order.keys())
        return super().stats()


class RandomReplacement(PageReplacementAlgorithm):
    """
    Random page replacement: evict a random page on miss when full.
    """
    def __init__(self, capacity):
        super().__init__(capacity)
        self._rand = random.Random(0)  # local RNG for reproducibility

    def access(self, page, time, disk_latency=0, prefetch=False, prefetch_count=0, future_ref=None):
        hit = self.base_access_check(page, time, disk_latency, prefetch=prefetch)
        if hit:
            return

        if len(self.frames) < self.capacity:
            self.frames.add(page)
            self._entry_time[page] = time
        else:
            evict = self._rand.choice(tuple(self.frames))
            self.eviction_count[evict] += 1
            self.residency_times.append(time - self._entry_time.pop(evict))
            self.frames.remove(evict)

            self.frames.add(page)
            self._entry_time[page] = time


class Clock(PageReplacementAlgorithm):
    """
    Clock (Second‑Chance) page replacement.
    Maintains a circular buffer of frames with use bits.
    """
    def __init__(self, capacity):
        super().__init__(capacity)
        self.frames_list = [None] * capacity   # fixed slot list
        self.use_bits = [0] * capacity         # parallel use bits
        self.pointer = 0
        self.page_to_index = {}                # page -> index for O(1) lookup

    def reset(self):
        super().reset()
        self.frames_list = [None] * self.capacity
        self.use_bits = [0] * self.capacity
        self.pointer = 0
        self.page_to_index.clear()

    def access(self, page, time, disk_latency=0, prefetch=False, prefetch_count=0, future_ref=None):
        # 1) Hit/miss check
        if page in self.frames:
            if not prefetch:
                self.hits += 1
            idx = self.page_to_index[page]
            self.use_bits[idx] = 1
            return
        else:
            if not prefetch:
                self.misses += 1
                self.fault_latencies.append(disk_latency)

        # 2) If any empty slot, place page there
        if None in self.frames_list:
            idx = self.frames_list.index(None)
            self.frames_list[idx] = page
            self.use_bits[idx] = 1
            self.frames.add(page)
            self._entry_time[page] = time
            self.page_to_index[page] = idx
            return

        # 3) Otherwise, scan for use_bit == 0
        while self.use_bits[self.pointer] == 1:
            self.use_bits[self.pointer] = 0
            self.pointer = (self.pointer + 1) % self.capacity

        victim = self.frames_list[self.pointer]
        self.eviction_count[victim] += 1
        self.residency_times.append(time - self._entry_time.pop(victim))
        self.frames.remove(victim)
        self.page_to_index.pop(victim, None)

        self.frames_list[self.pointer] = page
        self.use_bits[self.pointer] = 1
        self.frames.add(page)
        self._entry_time[page] = time
        self.page_to_index[page] = self.pointer

        self.pointer = (self.pointer + 1) % self.capacity


class SecondChance(Clock):
    """
    Alias for Clock (identical behavior).
    """
    pass


class Optimal(PageReplacementAlgorithm):
    """
    Ideal (Belady’s) page replacement. Requires future reference list.
    """
    def access(self, page, time, disk_latency=0, prefetch=False, prefetch_count=0, future_ref=None):
        # Build a map of next-use distances in one pass
        future_map = {}
        if future_ref is not None:
            for idx, p2 in enumerate(future_ref):
                if p2 not in future_map and p2 in self.frames:
                    future_map[p2] = idx

        # 1) Hit/miss check
        if page in self.frames:
            if not prefetch:
                self.hits += 1
            return
        else:
            if not prefetch:
                self.misses += 1
                self.fault_latencies.append(disk_latency)

        # 2) If space, add
        if len(self.frames) < self.capacity:
            self.frames.add(page)
            self._entry_time[page] = time
            return

        # 3) Evict page used farthest in future (or not at all)
        victim = None
        farthest = -1
        for p in self.frames:
            if p not in future_map:
                victim = p
                break
            if future_map[p] > farthest:
                farthest = future_map[p]
                victim = p

        self.eviction_count[victim] += 1
        self.residency_times.append(time - self._entry_time.pop(victim))
        self.frames.remove(victim)

        self.frames.add(page)
        self._entry_time[page] = time


class LFU(PageReplacementAlgorithm):
    """
    Least‑Frequently‑Used page replacement.
    Evicts page with smallest reference count.
    """
    def __init__(self, capacity):
        super().__init__(capacity)
        self.access_count = collections.Counter()

    def reset(self):
        super().reset()
        self.access_count.clear()

    def access(self, page, time, disk_latency=0, prefetch=False, prefetch_count=0, future_ref=None):
        self.access_count[page] += 1

        hit = self.base_access_check(page, time, disk_latency, prefetch=prefetch)
        if hit:
            return

        if len(self.frames) < self.capacity:
            self.frames.add(page)
            self._entry_time[page] = time
            return

        min_count = min(self.access_count[p] for p in self.frames)
        candidates = [p for p in self.frames if self.access_count[p] == min_count]
        victim = min(candidates, key=lambda p: self._entry_time.get(p, time))

        self.eviction_count[victim] += 1
        self.residency_times.append(time - self._entry_time.pop(victim))
        self.frames.remove(victim)
        self.access_count.pop(victim, None)

        self.frames.add(page)
        self._entry_time[page] = time


class MFU(PageReplacementAlgorithm):
    """
    Most‑Frequently‑Used page replacement.
    Evicts page with largest reference count.
    """
    def __init__(self, capacity):
        super().__init__(capacity)
        self.access_count = collections.Counter()

    def reset(self):
        super().reset()
        self.access_count.clear()

    def access(self, page, time, disk_latency=0, prefetch=False, prefetch_count=0, future_ref=None):
        self.access_count[page] += 1

        hit = self.base_access_check(page, time, disk_latency, prefetch=prefetch)
        if hit:
            return

        if len(self.frames) < self.capacity:
            self.frames.add(page)
            self._entry_time[page] = time
            return

        max_count = max(self.access_count[p] for p in self.frames)
        candidates = [p for p in self.frames if self.access_count[p] == max_count]
        victim = min(candidates, key=lambda p: self._entry_time.get(p, time))

        self.eviction_count[victim] += 1
        self.residency_times.append(time - self._entry_time.pop(victim))
        self.frames.remove(victim)
        self.access_count.pop(victim, None)

        self.frames.add(page)
        self._entry_time[page] = time


class TLB:
    """
    Simple TLB wrapper. Delegates to a page replacement algorithm instance
    to manage a small cache of recently used pages, tracking TLB hits/misses.
    """
    def __init__(self, capacity, replacement_cls):
        self.capacity = capacity
        self.repl = replacement_cls(capacity)
        self.hits = 0
        self.misses = 0

    def reset(self):
        self.hits = 0
        self.misses = 0
        self.repl.reset()

    def access(self, page):
        """
        If page in TLB, record hit. Otherwise record miss and add.
        """
        if page in self.repl.frames:
            self.hits += 1
            return True
        else:
            self.misses += 1
            # Insert page into TLB’s backing algorithm without counting as a real “miss”
            self.repl.access(page, time=0, disk_latency=0, prefetch=True)
            return False

    def stats(self):
        base_stats = self.repl.stats()
        base_stats.update({
            'tlb_hits': self.hits,
            'tlb_misses': self.misses,
            'tlb_hit_rate': (self.hits / (self.hits + self.misses)) if (self.hits + self.misses) else 0
        })
        return base_stats


class VirtualMemorySimulator:
    """
    Simulator tying together multiple page replacement algorithms (plus optional TLB).
    Supports:
      - variable frame count
      - optional TLB (size + replacement policy)
      - disk latency (ms)
      - prefetching next N pages (silent, no stat updates)
      - collecting per-algorithm stats
      - computing average hit rates
    """
    def __init__(self, frame_count, tlb_enabled=False, tlb_size=0, tlb_algo='LRU'):
        self.frame_count = frame_count
        algo_map = {
            'FIFO': FIFO, 'LRU': LRU, 'Random': RandomReplacement,
            'Clock': Clock, 'SecondChance': SecondChance,
            'Optimal': Optimal, 'LFU': LFU, 'MFU': MFU
        }
        if tlb_enabled and tlb_size > 0 and tlb_algo in algo_map:
            self.tlb = TLB(tlb_size, algo_map[tlb_algo])
        else:
            self.tlb = None

        self.algorithms = {}   # name -> instance
        self.disk_latency = 0
        self.prefetch = False
        self.prefetch_count = 0

    def reset_all(self):
        """
        Reset TLB (if any) and all algorithm instances.
        """
        for algo in self.algorithms.values():
            algo.reset()
        if self.tlb is not None:
            self.tlb.reset()

    def enable_prefetch(self, prefetch=False, prefetch_count=0):
        self.prefetch = prefetch
        self.prefetch_count = prefetch_count

    def set_disk_latency(self, ms):
        self.disk_latency = ms

    def add_algorithm(self, name, algo_cls):
        self.algorithms[name] = algo_cls(self.frame_count)

    def run(self, reference_string):
        """
        Run simulation on a single reference string (list of page numbers).
        Reset stats for each algorithm (and TLB) before processing.
        """
        # Reset everything
        self.reset_all()

        # Process each page reference
        for time, page in enumerate(reference_string):
            # TLB lookup
            if self.tlb is not None and self.tlb.access(page):
                continue

            # Run each page-replacement algorithm
            for name, algo in self.algorithms.items():
                future = reference_string[time+1:] if isinstance(algo, Optimal) else None
                algo.access(
                    page,
                    time,
                    disk_latency=self.disk_latency,
                    prefetch=False,
                    prefetch_count=self.prefetch_count,
                    future_ref=future
                )

            # Prefetch next N pages if enabled (silent insert)
            if self.prefetch:
                for i in range(1, self.prefetch_count + 1):
                    if time + i < len(reference_string):
                        nxt = reference_string[time + i]
                        for algo in self.algorithms.values():
                            algo.access(
                                nxt,
                                time + i,
                                disk_latency=0,
                                prefetch=True,
                                prefetch_count=0,
                                future_ref=None
                            )

    def report(self):
        """
        Return a dict mapping each algorithm name to its stats.
        If TLB is enabled, include a 'TLB' entry.
        """
        reports = {}
        for name, algo in self.algorithms.items():
            reports[name] = algo.stats()

        if self.tlb is not None:
            reports['TLB'] = self.tlb.stats()

        return reports

    def compute_avg_hit_rates(self, workloads):
        """
        Given a list of reference-string workloads, run each algorithm and
        return a dict of average hit rates (including TLB if present).
        """
        algs = list(self.algorithms.keys())
        if self.tlb is not None:
            algs.append('TLB')

        avg_hit_rates = {alg: 0.0 for alg in algs}

        for ref in workloads:
            self.run(ref)
            stats = self.report()
            for alg in algs:
                if alg == 'TLB':
                    avg_hit_rates['TLB'] += stats['TLB']['tlb_hit_rate']
                else:
                    avg_hit_rates[alg] += stats[alg]['hit_rate']

        for alg in avg_hit_rates:
            avg_hit_rates[alg] /= len(workloads)

        return avg_hit_rates


# === UI Code (Tkinter) ===

class PageReplacementUI:
    def __init__(self, master):
        self.master = master
        master.protocol("WM_DELETE_WINDOW", master.destroy)

        master.title("Page Replacement Simulator")
        master.geometry("900x650")
        master.resizable(False, False)

        self.notebook = ttk.Notebook(master)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Configuration Tab
        self.tab_config = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_config, text="Configuration")
        self.build_config_tab()

        # Graphs Tab
        self.tab_graphs = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_graphs, text="Graphs")
        self.build_graphs_tab()

        # Results Tab
        self.tab_results = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_results, text="Results")
        self.build_results_tab()

        self.sim = None
        self.run_button = None  # Ensure attribute exists

    def build_config_tab(self):
        frame = ttk.Frame(self.tab_config, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)

        # Number of frames
        ttk.Label(frame, text="Number of Frames:", font=("Segoe UI", 10)).grid(row=0, column=0, sticky="w", pady=5)
        self.frames_var = StringVar(value="4")
        ttk.Entry(frame, textvariable=self.frames_var, width=10).grid(row=0, column=1, sticky="w", pady=5)

        # Enable TLB
        self.tlb_var = IntVar(value=0)
        chk_tlb = ttk.Checkbutton(frame, text="Enable TLB", variable=self.tlb_var, command=self.toggle_tlb)
        chk_tlb.grid(row=1, column=0, sticky="w", pady=5)

        # TLB Size
        ttk.Label(frame, text="TLB Size:", font=("Segoe UI", 10)).grid(row=1, column=1, sticky="e", pady=5)
        self.tlb_size_var = StringVar(value="2")
        self.entry_tlb_size = ttk.Entry(frame, textvariable=self.tlb_size_var, width=10, state="disabled")
        self.entry_tlb_size.grid(row=1, column=2, sticky="w", pady=5)

        # TLB Replacement Policy
        ttk.Label(frame, text="TLB Replacement:", font=("Segoe UI", 10)).grid(row=2, column=0, sticky="w", pady=5)
        self.tlb_policy_var = StringVar(value="LRU")
        self.combo_tlb_policy = ttk.Combobox(
            frame,
            textvariable=self.tlb_policy_var,
            values=["FIFO", "LRU", "Random", "Clock", "SecondChance", "LFU", "MFU"],
            state="disabled",
            width=12
        )
        self.combo_tlb_policy.grid(row=2, column=1, sticky="w", pady=5)

        # Disk Latency
        ttk.Label(frame, text="Disk Latency (ms):", font=("Segoe UI", 10)).grid(row=3, column=0, sticky="w", pady=5)
        self.disk_latency_var = StringVar(value="10")
        ttk.Entry(frame, textvariable=self.disk_latency_var, width=10).grid(row=3, column=1, sticky="w", pady=5)

        # Prefetch checkbox
        self.prefetch_var = IntVar(value=0)
        chk_prefetch = ttk.Checkbutton(frame, text="Enable Prefetch", variable=self.prefetch_var, command=self.toggle_prefetch)
        chk_prefetch.grid(row=4, column=0, sticky="w", pady=5)

        # Prefetch count
        ttk.Label(frame, text="Prefetch Count:", font=("Segoe UI", 10)).grid(row=4, column=1, sticky="e", pady=5)
        self.prefetch_count_var = StringVar(value="1")
        self.entry_prefetch_count = ttk.Entry(frame, textvariable=self.prefetch_count_var, width=10, state="disabled")
        self.entry_prefetch_count.grid(row=4, column=2, sticky="w", pady=5)

        # Reference string
        ttk.Label(frame, text="Reference String:", font=("Segoe UI", 10)).grid(row=5, column=0, sticky="nw", pady=5)
        self.ref_str_var = StringVar()
        ttk.Entry(frame, textvariable=self.ref_str_var, width=60).grid(row=5, column=1, columnspan=2, sticky="w", pady=5)
        ttk.Label(
            frame,
            text="(Either space-separated ints, e.g. 3 7 2, or 'random N M')",
            font=("Segoe UI", 8),
            foreground="gray"
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(0, 5))

        # Graph Type selection
        ttk.Label(frame, text="Graph Type:", font=("Segoe UI", 10)).grid(row=7, column=0, sticky="w", pady=5)
        self.graph_type_var = StringVar(value="Bar")
        self.combo_graph_type = ttk.Combobox(
            frame,
            textvariable=self.graph_type_var,
            values=["Bar", "Line", "Pie"],
            state="readonly",
            width=12
        )
        self.combo_graph_type.grid(row=7, column=1, sticky="w", pady=5)

        # Run Simulation button
        self.run_button = ttk.Button(frame, text="Run Simulation", command=self.run_simulation_thread)
        self.run_button.grid(row=8, column=0, columnspan=3, pady=15)

        # Grid padding
        frame.columnconfigure(0, pad=10)
        frame.columnconfigure(1, pad=10)
        frame.columnconfigure(2, pad=10)

    def build_graphs_tab(self):
        frame = ttk.Frame(self.tab_graphs, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)

        frame.rowconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

        # Average Hit Rate Chart container
        self.avg_plot_container = ttk.LabelFrame(frame, text="Average Hit Rates", padding="5")
        self.avg_plot_container.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        ttk.Label(self.avg_plot_container, text="Chart will appear here", foreground="gray").pack(expand=True)

        # Placeholder for symmetry (unused)
        placeholder = ttk.LabelFrame(frame, text="(Unused)", padding="5")
        placeholder.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        ttk.Label(placeholder, text="(No chart here)", foreground="gray").pack(expand=True)

    def build_results_tab(self):
        frame = ttk.Frame(self.tab_results, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)

        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(0, weight=1)

        # Left: stats text
        self.stats_text = scrolledtext.ScrolledText(frame, width=60, wrap=tk.WORD)
        self.stats_text.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.stats_text.config(state=tk.DISABLED)

        # Right: per-workload line plot container
        self.results_plot_container = ttk.LabelFrame(frame, text="Hit Rate per Workload", padding="5")
        self.results_plot_container.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        ttk.Label(self.results_plot_container, text="Chart will appear here", foreground="gray").pack(expand=True)

    def toggle_tlb(self):
        if self.tlb_var.get():
            self.entry_tlb_size.config(state="normal")
            self.combo_tlb_policy.config(state="readonly")
        else:
            self.entry_tlb_size.delete(0, tk.END)
            self.entry_tlb_size.insert(0, "2")
            self.entry_tlb_size.config(state="disabled")
            self.combo_tlb_policy.set("LRU")
            self.combo_tlb_policy.config(state="disabled")

    def toggle_prefetch(self):
        if self.prefetch_var.get():
            self.entry_prefetch_count.config(state="normal")
        else:
            self.entry_prefetch_count.delete(0, tk.END)
            self.entry_prefetch_count.insert(0, "1")
            self.entry_prefetch_count.config(state="disabled")

    def parse_reference_string(self, text):
        tokens = text.strip().split()
        if not tokens:
            raise ValueError("Reference string cannot be empty.")
        if tokens[0].lower() == 'random':
            if len(tokens) != 3:
                raise ValueError("To generate random: 'random <length> <max_page>'.")
            length = int(tokens[1])
            max_page = int(tokens[2])
            if length <= 0 or max_page <= 0:
                raise ValueError("Length and max_page must be positive.")
            return [random.randint(0, max_page - 1) for _ in range(length)]
        else:
            try:
                return [int(x) for x in tokens]
            except:
                raise ValueError("All reference string tokens must be integers or 'random <length> <max_page>'.")

    def clear_previous_results(self):
        # Clear stats text
        self.stats_text.config(state=tk.NORMAL)
        self.stats_text.delete("1.0", tk.END)
        self.stats_text.config(state=tk.DISABLED)

        # Clear average chart area
        for widget in self.avg_plot_container.winfo_children():
            widget.destroy()

        # Clear per-workload plot area
        for widget in self.results_plot_container.winfo_children():
            widget.destroy()

    def run_simulation_thread(self):
        """Run simulation in a separate thread to keep UI responsive."""
        if self.run_button:
            self.run_button.config(state=tk.DISABLED)
        threading.Thread(target=self.run_simulation, daemon=True).start()

    def run_simulation(self):
        def on_error(msg):
            messagebox.showerror("Simulation Error", msg)
            if self.run_button:
                self.master.after(0, lambda: self.run_button.config(state=tk.NORMAL))

        try:
            self.master.after(0, self.clear_previous_results)

            # 1) Read/validate number of frames
            try:
                frames = int(self.frames_var.get().strip())
                if frames <= 0:
                    raise ValueError
            except ValueError:
                self.master.after(0, lambda: messagebox.showerror("Invalid Input", "Number of frames must be a positive integer."))
                if self.run_button:
                    self.master.after(0, lambda: self.run_button.config(state=tk.NORMAL))
                return

            # 2) TLB settings
            tlb_enabled = bool(self.tlb_var.get())
            try:
                if tlb_enabled:
                    tlb_size = int(self.tlb_size_var.get().strip())
                    if tlb_size <= 0:
                        raise ValueError
                else:
                    tlb_size = 0
            except ValueError:
                self.master.after(0, lambda: messagebox.showerror("Invalid Input", "TLB size must be a positive integer."))
                if self.run_button:
                    self.master.after(0, lambda: self.run_button.config(state=tk.NORMAL))
                return

            tlb_policy = self.tlb_policy_var.get() if tlb_enabled else "LRU"

            # 3) Disk latency
            try:
                dl = int(self.disk_latency_var.get().strip())
                if dl < 0:
                    raise ValueError
            except ValueError:
                self.master.after(0, lambda: messagebox.showerror("Invalid Input", "Disk latency must be a nonnegative integer."))
                if self.run_button:
                    self.master.after(0, lambda: self.run_button.config(state=tk.NORMAL))
                return

            # 4) Prefetch settings
            prefetch_enabled = bool(self.prefetch_var.get())
            try:
                if prefetch_enabled:
                    pref_count = int(self.prefetch_count_var.get().strip())
                    if pref_count < 0:
                        raise ValueError
                else:
                    pref_count = 0
            except ValueError:
                self.master.after(0, lambda: messagebox.showerror("Invalid Input", "Prefetch count must be a nonnegative integer."))
                if self.run_button:
                    self.master.after(0, lambda: self.run_button.config(state=tk.NORMAL))
                return

            # 5) Reference string
            try:
                ref_str = self.parse_reference_string(self.ref_str_var.get().strip())
            except ValueError as e:
                self.master.after(0, lambda: messagebox.showerror("Invalid Input", str(e)))
                if self.run_button:
                    self.master.after(0, lambda: self.run_button.config(state=tk.NORMAL))
                return

            # 6) Graph type choice
            graph_type = self.graph_type_var.get()

            # 7) Build and configure simulator
            self.sim = VirtualMemorySimulator(
                frame_count=frames,
                tlb_enabled=tlb_enabled,
                tlb_size=tlb_size,
                tlb_algo=tlb_policy
            )
            # Register algorithms
            for algo_name, algo_cls in [
                ("FIFO", FIFO), ("LRU", LRU), ("Random", RandomReplacement),
                ("Clock", Clock), ("SecondChance", SecondChance),
                ("Optimal", Optimal), ("LFU", LFU), ("MFU", MFU)
            ]:
                self.sim.add_algorithm(algo_name, algo_cls)

            self.sim.set_disk_latency(dl)
            self.sim.enable_prefetch(prefetch=prefetch_enabled, prefetch_count=pref_count)

            # 8) Synthetic workloads for plots
            workloads = [[random.randint(0, 7) for _ in range(50)] for _ in range(3)]

            # 8a) Show average‑hit‑rate chart in the Graphs tab
            self.master.after(0, lambda: self.display_avg_hit_rate_chart(workloads, graph_type))

            # 8b) Show per‑workload hit‑rate line chart in the Results tab
            self.master.after(0, lambda: self.display_workload_line_plot(workloads))

            # 9) Run on user string and display stats
            try:
                self.sim.run(ref_str)
                reports = self.sim.report()
            except Exception as e:
                on_error(f"Simulation failed:\n{e}")
                return

            self.master.after(0, lambda: self.display_stats(ref_str, reports))
            self.master.after(0, lambda: self.notebook.select(self.tab_results))
            if self.run_button:
                self.master.after(0, lambda: self.run_button.config(state=tk.NORMAL))

        except Exception as e:
            on_error(str(e))

    def display_avg_hit_rate_chart(self, workloads, graph_type):
        """
        Draw average hit-rate chart (Bar/Line/Pie) in the avg_plot_container.
        """
        for widget in self.avg_plot_container.winfo_children():
            widget.destroy()

        avg_hit_rates = self.sim.compute_avg_hit_rates(workloads)
        names = list(avg_hit_rates.keys())
        rates = [avg_hit_rates[n] for n in names]

        fig, ax = plt.subplots(figsize=(6, 3), dpi=100)

        if graph_type == "Bar":
            ax.bar(names, rates, edgecolor='black')
            ax.set_xlabel('Algorithm')
            ax.set_ylabel('Average Hit Rate')
            ax.set_title('Avg Hit Rates Across Workloads')
            ax.set_ylim(0, 1.0)
            ax.grid(axis='y', linestyle='--', alpha=0.6)

        elif graph_type == "Line":
            ax.plot(names, rates, marker='o', linestyle='-')
            ax.set_xlabel('Algorithm')
            ax.set_ylabel('Average Hit Rate')
            ax.set_title('Avg Hit Rates (Line) Across Workloads')
            ax.set_ylim(0, 1.0)
            ax.grid(axis='both', linestyle='--', alpha=0.6)

        elif graph_type == "Pie":
            total = sum(rates)
            if total > 0:
                fractions = [r / total for r in rates]
            else:
                fractions = [1/len(rates)] * len(rates)
            ax.pie(fractions, labels=names, autopct='%1.1f%%', startangle=90)
            ax.set_title('Avg Hit Rate Distribution (Pie)')

        canvas = FigureCanvasTkAgg(fig, master=self.avg_plot_container)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        plt.close(fig)

    def display_workload_line_plot(self, workloads):
        """
        Draw a multi‑line chart in the results_plot_container where each line is one
        algorithm’s hit rate across the given list of workloads. Includes 'TLB' if enabled.
        """
        for widget in self.results_plot_container.winfo_children():
            widget.destroy()

        algs = list(self.sim.algorithms.keys())
        if self.sim.tlb is not None:
            algs.append('TLB')

        num_workloads = len(workloads)
        x = list(range(num_workloads))  # [0, 1, 2, …]

        hit_rates_per_alg = {alg: [] for alg in algs}
        for ref in workloads:
            self.sim.run(ref)
            stats = self.sim.report()
            for alg in algs:
                if alg == 'TLB':
                    hit_rates_per_alg['TLB'].append(stats['TLB']['tlb_hit_rate'])
                else:
                    hit_rates_per_alg[alg].append(stats[alg]['hit_rate'])

        all_rates = []
        for alg in algs:
            all_rates.extend(hit_rates_per_alg[alg])
        if all_rates:
            min_rate = min(all_rates)
            max_rate = max(all_rates)
            margin = 0.02
            y_min = max(0.0, min_rate - margin)
            y_max = min(1.0, max_rate + margin)
        else:
            y_min, y_max = 0.0, 1.0

        fig, ax = plt.subplots(figsize=(6, 3), dpi=100)
        for alg in algs:
            ax.plot(
                x,
                hit_rates_per_alg[alg],
                marker='o',
                linestyle='-',
                label=alg
            )

        ax.set_xlabel('Workload Index')
        ax.set_ylabel('Hit Rate')
        ax.set_title('Hit Rate per Workload')
        ax.set_xticks(x)
        ax.set_xticklabels([str(i) for i in x])
        ax.set_ylim(y_min, y_max)
        ax.legend(loc='center left', bbox_to_anchor=(1, 0.5), fontsize='small', frameon=True)

        canvas = FigureCanvasTkAgg(fig, master=self.results_plot_container)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        plt.close(fig)

    def display_stats(self, ref_str, reports):
        self.stats_text.config(state=tk.NORMAL)
        self.stats_text.insert(tk.END, f"Reference string: {' '.join(str(p) for p in ref_str)}\n")

        offsets = [abs(ref_str[i] - ref_str[i-1]) for i in range(1, len(ref_str))]
        if offsets:
            avg_offset = sum(offsets) / len(offsets)
            max_offset = max(offsets)
            min_offset = min(offsets)
        else:
            avg_offset = max_offset = min_offset = 0

        unique_pages = len(set(ref_str))

        self.stats_text.insert(
            tk.END,
            f"Offset sequence: {offsets}\n" +
            f"Number of offsets: {len(offsets)}\n"
        )
        self.stats_text.insert(
            tk.END,
            f"Unique pages referenced: {unique_pages}\n"
            f"Page‑offset stats: avg={avg_offset:.2f}, min={min_offset}, max={max_offset}\n"
        )
        self.stats_text.insert(tk.END, "=" * 80 + "\n")

        total_references = len(ref_str)

        for name, stats in reports.items():
            self.stats_text.insert(tk.END, f"Algorithm: {name}\n")
            hits = stats['hits']
            misses = stats['misses']
            hit_rate = stats['hit_rate']
            avg_latency = stats['avg_fault_latency_ms']
            avg_res = stats['avg_residency']
            eviction_counts = stats['eviction_counts']

            page_faults = misses
            page_fault_rate = (page_faults / total_references) if total_references else 0
            total_evictions = sum(eviction_counts.values())
            if eviction_counts:
                most_evicted_page, most_evicted_count = max(eviction_counts.items(), key=lambda kv: kv[1])
            else:
                most_evicted_page, most_evicted_count = (None, 0)

            algo_obj = self.sim.algorithms.get(name, None)
            resid_times = algo_obj.residency_times if algo_obj is not None else []
            if len(resid_times) > 1:
                std_residency = statistics.stdev(resid_times)
            else:
                std_residency = 0.0

            self.stats_text.insert(tk.END, f"  Hits:                     {hits}\n")
            self.stats_text.insert(tk.END, f"  Misses (Page Faults):     {misses}\n")
            self.stats_text.insert(tk.END, f"  Hit rate:                 {hit_rate*100:6.2f}%\n")
            self.stats_text.insert(tk.END, f"  Page Fault Rate:          {page_fault_rate*100:6.2f}%  ({page_faults}/{total_references})\n")
            self.stats_text.insert(tk.END, f"  Avg. fault latency (ms):  {avg_latency:.2f}\n")
            self.stats_text.insert(tk.END, f"  Avg. residency:           {avg_res:.2f}\n")
            self.stats_text.insert(tk.END, f"  Residency StdDev:         {std_residency:.2f}\n")
            self.stats_text.insert(tk.END, f"  Total evictions:          {total_evictions}\n")
            if most_evicted_page is not None:
                self.stats_text.insert(
                    tk.END,
                    f"  Most evicted page:        {most_evicted_page} (evicted {most_evicted_count} times)\n"
                )
            else:
                self.stats_text.insert(tk.END, f"  Most evicted page:        None\n")
            self.stats_text.insert(tk.END, f"  Eviction counts:          {eviction_counts}\n")

            if name == 'TLB':
                tlb_hits = stats['tlb_hits']
                tlb_misses = stats['tlb_misses']
                tlb_hit_rate = stats['tlb_hit_rate']
                self.stats_text.insert(
                    tk.END,
                    f"  TLB Hits:                 {tlb_hits}\n"
                    f"  TLB Misses:               {tlb_misses}\n"
                    f"  TLB Hit rate:             {tlb_hit_rate*100:6.2f}%\n"
                )

            self.stats_text.insert(tk.END, "-" * 80 + "\n")

        self.stats_text.config(state=tk.DISABLED)


if __name__ == '__main__':
    random.seed(123)
    root = tk.Tk()
    app = PageReplacementUI(root)
    root.state('zoomed')  # Maximizes the window
    root.mainloop()
