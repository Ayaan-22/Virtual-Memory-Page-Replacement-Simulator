"""Memory model + simulation loop.

One independent memory model is built per policy: its own frames, dirty bits,
TLB (invalidated on eviction) and prefetcher. Nothing is shared between
policies, which is what makes the comparison fair.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter, OrderedDict
from dataclasses import dataclass, field, asdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

from .algorithms import POLICIES, make

Ref = Union[int, str, Tuple[int, bool]]


@dataclass
class Config:
    frames: int = 4
    tlb_size: int = 0            # 0 = no TLB
    prefetch_depth: int = 0      # sequential prefetch of page+1..page+depth on a fault
    mem_ns: float = 100.0        # one memory access
    tlb_ns: float = 5.0          # one TLB lookup
    disk_ms: float = 8.0         # page-in or write-back service time

    def __post_init__(self):
        if self.frames < 1:
            raise ValueError("frames must be >= 1")
        if self.tlb_size < 0:
            raise ValueError("tlb_size must be >= 0 (0 disables the TLB)")
        if self.prefetch_depth < 0:
            raise ValueError("prefetch_depth must be >= 0 (0 disables prefetch)")
        if min(self.mem_ns, self.tlb_ns, self.disk_ms) < 0:
            raise ValueError("timing parameters cannot be negative")


@dataclass
class Event:
    t: int
    page: int
    write: bool
    kind: str                    # 'hit' | 'cold' | 'capacity'
    tlb_hit: Optional[bool]
    victim: Optional[int]
    victim_dirty: bool
    prefetched: Tuple[int, ...]
    frames: Tuple[Optional[int], ...]
    dirty: Tuple[bool, ...]          # per-frame dirty flag after this access

    @property
    def fault(self) -> bool:
        return self.kind != "hit"


@dataclass
class Result:
    policy: str
    config: Config
    events: List[Event]
    stats: dict

    def to_dict(self) -> dict:
        return {"policy": self.policy, "config": asdict(self.config), "stats": self.stats,
                "events": [{**asdict(e), "fault": e.fault} for e in self.events]}


_TOKEN = re.compile(r"(\d+)([rw]?)", re.IGNORECASE)


def _bad(r) -> ValueError:
    return ValueError(f"bad reference {r!r}: use a non-negative whole number such as 7, "
                      f"optionally followed by r or w (7w is a write)")


def normalize(trace: Iterable[Ref]) -> List[Tuple[int, bool]]:
    """Accepts ints, '7', '7w' / '7r', or (page, write) pairs. Pages must be >= 0."""
    out = []
    for r in trace:
        if isinstance(r, tuple):
            page, write = r[0], bool(r[1])
        elif isinstance(r, str):
            m = _TOKEN.fullmatch(r.strip())
            if not m:
                raise _bad(r)
            page, write = int(m.group(1)), m.group(2).lower() == "w"
        else:
            page, write = r, False
        try:
            page = int(page)
        except (TypeError, ValueError):
            raise _bad(r) from None
        if page < 0:
            raise _bad(r)
        out.append((page, write))
    return out


def simulate(trace: Iterable[Ref], policy: str, cfg: Config, seed: int = 0) -> Result:
    refs = normalize(trace)
    F = cfg.frames
    pol = make(policy, F, seed)
    pol.reset()
    pol.prepare([p for p, _ in refs])

    slots: List[Optional[int]] = [None] * F
    where: Dict[int, int] = {}
    dirty: Dict[int, bool] = {}
    loaded_at: Dict[int, int] = {}
    pending_pf: set = set()
    tlb: OrderedDict = OrderedDict()
    seen: set = set()
    c = Counter()
    evictions: Counter = Counter()
    residency: List[int] = []
    total_ns = 0.0
    events: List[Event] = []

    def evict(victim: int, t: int) -> bool:
        slot = where.pop(victim)
        slots[slot] = None
        was_dirty = dirty.pop(victim, False)
        residency.append(t - loaded_at.pop(victim))
        evictions[victim] += 1
        if was_dirty:
            c["writebacks"] += 1
        if tlb.pop(victim, None) is not None:
            c["tlb_shootdowns"] += 1                  # stale translation removed
        if victim in pending_pf:
            pending_pf.discard(victim)
            c["prefetch_wasted"] += 1
        pol.on_evict(victim)
        return was_dirty

    def load(page: int, t: int, write: bool, demand: bool) -> None:
        slot = slots.index(None)
        slots[slot] = page
        where[page] = slot
        dirty[page] = write and demand
        loaded_at[page] = t
        pol.on_load(page, t, write and demand, demand)

    for t, (page, write) in enumerate(refs):
        tlb_hit: Optional[bool] = None
        if cfg.tlb_size:
            tlb_hit = page in tlb
            c["tlb_hits" if tlb_hit else "tlb_misses"] += 1
            total_ns += cfg.tlb_ns + (0 if tlb_hit else cfg.mem_ns)   # miss => page-table walk
        else:
            total_ns += cfg.mem_ns                                    # page-table walk
        total_ns += cfg.mem_ns                                        # the data access itself

        victim, victim_dirty, pf_now = None, False, []
        if page in where:
            kind = "hit"
            c["hits"] += 1
            pol.on_hit(page, t, write)
            if write:
                dirty[page] = True
            if page in pending_pf:
                pending_pf.discard(page)
                c["prefetch_useful"] += 1
        else:
            kind = "capacity" if page in seen else "cold"
            c[kind] += 1
            total_ns += cfg.disk_ms * 1e6
            if len(where) >= F:
                victim = pol.choose_victim(t, frozenset())
                victim_dirty = evict(victim, t)
                if victim_dirty:
                    total_ns += cfg.disk_ms * 1e6
            load(page, t, write, True)
            if cfg.prefetch_depth:
                protect = {page}
                for d in range(1, cfg.prefetch_depth + 1):
                    q = page + d
                    if q == victim:                    # never re-fetch the page this fault just evicted
                        continue
                    if q in where:
                        protect.add(q)
                        continue
                    if len(where) >= F:
                        if not any(p not in protect for p in where):
                            break
                        evict(pol.choose_victim(t, frozenset(protect)), t)   # async: not charged
                    load(q, t, False, False)
                    pending_pf.add(q)
                    protect.add(q)
                    pf_now.append(q)
                    c["prefetch_issued"] += 1
        seen.add(page)

        if cfg.tlb_size:
            if page in tlb:
                tlb.move_to_end(page)
            else:
                if len(tlb) >= cfg.tlb_size:
                    tlb.popitem(last=False)
                tlb[page] = True

        events.append(Event(t, page, write, kind, tlb_hit, victim, victim_dirty,
                            tuple(pf_now), tuple(slots),
                            tuple(x is not None and dirty.get(x, False) for x in slots)))

    n = len(refs)
    faults = c["cold"] + c["capacity"]
    tl = c["tlb_hits"] + c["tlb_misses"]
    stats = {
        "refs": n, "hits": c["hits"], "faults": faults,
        "cold": c["cold"], "capacity": c["capacity"],
        "hit_rate": c["hits"] / n if n else 0.0,
        "fault_rate": faults / n if n else 0.0,
        "evictions": sum(evictions.values()), "writebacks": c["writebacks"],
        "tlb_hit_rate": (c["tlb_hits"] / tl) if tl else None,
        "tlb_shootdowns": c["tlb_shootdowns"],
        "prefetch_issued": c["prefetch_issued"], "prefetch_useful": c["prefetch_useful"],
        "prefetch_wasted": c["prefetch_wasted"],
        "avg_residency": statistics.fmean(residency) if residency else 0.0,
        "residency_std": statistics.stdev(residency) if len(residency) > 1 else 0.0,
        "eat_ns": total_ns / n if n else 0.0,
        "most_evicted": list(evictions.most_common(1)[0]) if evictions else None,
    }
    return Result(pol.name, cfg, events, stats)


def run_all(trace: Sequence[Ref], cfg: Config, policies: Optional[Sequence[str]] = None,
            seed: int = 0) -> Dict[str, Result]:
    names = list(policies) if policies else list(POLICIES)
    refs = normalize(trace)                      # normalise once, share across policies
    return {make(n, 1).name: simulate(refs, n, cfg, seed) for n in names}
