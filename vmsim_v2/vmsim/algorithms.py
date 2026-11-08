"""Page-replacement policies.

A policy only keeps *ordering metadata*. The simulator owns residency, dirty
bits, the TLB and all statistics, so every policy sees every access (the v1
TLB short-circuit bug cannot happen) and policies stay small and testable.

Hooks, called by the simulator:
    on_hit(page, t, write)             page was resident when referenced
    on_load(page, t, write, demand)    page was brought in (demand or prefetch)
    choose_victim(t, protect)          pick a resident page not in `protect`
    on_evict(page)                     page left memory
"""
from __future__ import annotations

import random
from bisect import bisect_right
from collections import OrderedDict
from typing import Dict, FrozenSet, List, Optional, Sequence

INF = float("inf")


class Policy:
    name = "base"
    needs_future = False

    def __init__(self, capacity: int, seed: int = 0):
        self.capacity = capacity
        self.seed = seed
        self.reset()

    def reset(self) -> None: ...
    def prepare(self, pages: Sequence[int]) -> None: ...
    def on_hit(self, page, t, write) -> None: ...
    def on_load(self, page, t, write, demand=True) -> None: ...
    def on_evict(self, page) -> None: ...

    def choose_victim(self, t: int, protect: FrozenSet[int]) -> int:
        raise NotImplementedError


class FIFO(Policy):
    name = "FIFO"

    def reset(self):
        self.q: OrderedDict = OrderedDict()

    def on_load(self, page, t, write, demand=True):
        self.q[page] = t

    def on_evict(self, page):
        self.q.pop(page, None)

    def choose_victim(self, t, protect):
        return next(p for p in self.q if p not in protect)


class LRU(FIFO):
    name = "LRU"

    def on_hit(self, page, t, write):
        self.q.move_to_end(page)


class Optimal(Policy):
    """Belady's OPT: evict the page whose next use is farthest away.

    Next-use is a bisect into per-page position lists: O(frames * log n) per
    fault instead of v1's full rescan of the future. Ties (pages never used
    again) break on the smallest page number, so results are deterministic.
    """
    name = "OPT"
    needs_future = True

    def reset(self):
        self.res: set = set()
        self.pos: Dict[int, List[int]] = {}

    def prepare(self, pages):
        self.pos = {}
        for i, p in enumerate(pages):
            self.pos.setdefault(p, []).append(i)

    def _next(self, p, t):
        lst = self.pos.get(p, ())          # prefetched pages may never be referenced
        k = bisect_right(lst, t)
        return lst[k] if k < len(lst) else INF

    def on_load(self, page, t, write, demand=True):
        self.res.add(page)

    def on_evict(self, page):
        self.res.discard(page)

    def choose_victim(self, t, protect):
        return max((p for p in self.res if p not in protect),
                   key=lambda p: (self._next(p, t), -p))


class Clock(Policy):
    """Second chance: circular buffer, one use bit per frame."""
    name = "Clock"

    def reset(self):
        n = self.capacity
        self.slots: List[Optional[int]] = [None] * n
        self.ref = [0] * n
        self.where: Dict[int, int] = {}
        self.hand = 0
        self._replacing = False

    def on_hit(self, page, t, write):
        self.ref[self.where[page]] = 1

    def on_load(self, page, t, write, demand=True):
        i = self.slots.index(None)
        self.slots[i], self.ref[i], self.where[page] = page, 1, i
        if self._replacing:
            self.hand = (i + 1) % self.capacity
            self._replacing = False

    def on_evict(self, page):
        self.slots[self.where.pop(page)] = None

    def _take(self, j):
        self.hand = j
        self._replacing = True
        return self.slots[j]

    def choose_victim(self, t, protect):
        n = self.capacity
        while True:
            j = self.hand
            if self.slots[j] in protect:
                pass
            elif self.ref[j]:
                self.ref[j] = 0
            else:
                return self._take(j)
            self.hand = (j + 1) % n


class EnhancedClock(Clock):
    """Clock over (reference, modified) pairs: prefers clean, unreferenced
    pages so evictions avoid a write-back. This is the NRU-style variant used
    by real kernels; it only differs from Clock when writes are present."""
    name = "EClock"

    def reset(self):
        super().reset()
        self.mod = [0] * self.capacity

    def on_hit(self, page, t, write):
        i = self.where[page]
        self.ref[i] = 1
        if write:
            self.mod[i] = 1

    def on_load(self, page, t, write, demand=True):
        super().on_load(page, t, write, demand)
        self.mod[self.where[page]] = 1 if write else 0

    def choose_victim(self, t, protect):
        n = self.capacity
        while True:
            order = [(self.hand + i) % n for i in range(n)]
            for j in order:                      # pass 1: (ref=0, mod=0)
                if self.slots[j] not in protect and not self.ref[j] and not self.mod[j]:
                    return self._take(j)
            for j in order:                      # pass 2: (0,1), clearing ref bits
                if self.slots[j] in protect:
                    continue
                if not self.ref[j] and self.mod[j]:
                    return self._take(j)
                self.ref[j] = 0


class LFU(Policy):
    """Evict the least-referenced resident page; ties go to the oldest load.
    Counts reset on eviction (in-memory LFU), so history is not kept."""
    name = "LFU"
    sign = 1

    def reset(self):
        self.cnt: OrderedDict = OrderedDict()

    def on_hit(self, page, t, write):
        self.cnt[page] += 1

    def on_load(self, page, t, write, demand=True):
        self.cnt[page] = 1

    def on_evict(self, page):
        self.cnt.pop(page, None)

    def choose_victim(self, t, protect):
        cands = [p for p in self.cnt if p not in protect]
        return min(enumerate(cands), key=lambda ip: (self.sign * self.cnt[ip[1]], ip[0]))[1]


class MFU(LFU):
    name = "MFU"
    sign = -1


class RandomPolicy(Policy):
    """Uniform random victim. Re-seeded on every reset => reproducible runs."""
    name = "Random"

    def reset(self):
        self.rng = random.Random(self.seed)
        self.res: List[int] = []

    def on_load(self, page, t, write, demand=True):
        self.res.append(page)

    def on_evict(self, page):
        self.res.remove(page)

    def choose_victim(self, t, protect):
        return self.rng.choice([p for p in self.res if p not in protect])


POLICIES = {c.name: c for c in (FIFO, LRU, Optimal, Clock, EnhancedClock, LFU, MFU, RandomPolicy)}


def make(name: str, capacity: int, seed: int = 0) -> Policy:
    key = {k.lower(): k for k in POLICIES}.get(name.lower(), "OPT" if name.lower() == "optimal" else None)
    if key is None:
        raise ValueError(f"unknown policy {name!r}; choose from {', '.join(POLICIES)}")
    return POLICIES[key](capacity, seed)
