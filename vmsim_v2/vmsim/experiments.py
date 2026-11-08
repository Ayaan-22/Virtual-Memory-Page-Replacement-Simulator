"""Experiments that answer a question, not just print counters."""
from __future__ import annotations

import statistics
from dataclasses import replace
from typing import Dict, List, Optional, Sequence, Tuple

from .algorithms import POLICIES
from .simulator import Config, simulate, normalize
from . import workloads


def frames_sweep(trace, policies: Sequence[str], frame_range: Sequence[int],
                 cfg: Optional[Config] = None, seed: int = 0) -> Dict[str, List[int]]:
    """Faults for each policy at each frame count."""
    cfg, refs = cfg or Config(), normalize(trace)
    return {p: [simulate(refs, p, replace(cfg, frames=f), seed).stats["faults"] for f in frame_range]
            for p in policies}


def belady_anomalies(sweep: Dict[str, List[int]], frame_range: Sequence[int]) -> List[Tuple[str, int, int, int, int]]:
    """(policy, fewer_frames, more_frames, faults_at_fewer, faults_at_more) where MORE frames => MORE faults."""
    out = []
    for p, faults in sweep.items():
        for i in range(len(faults) - 1):
            if faults[i + 1] > faults[i]:
                out.append((p, frame_range[i], frame_range[i + 1], faults[i], faults[i + 1]))
    return out


def compare_workloads(policies: Sequence[str], cfg: Config, names: Optional[Sequence[str]] = None,
                      n: int = 2000, pages: int = 64, trials: int = 5, seed: int = 0) -> Dict[str, Dict[str, float]]:
    """Mean hit rate of each policy on each workload family, averaged over `trials` seeds."""
    out: Dict[str, Dict[str, float]] = {}
    for w in names or workloads.GENERATORS:
        pg = cfg.frames + 1 if w == "loop" else pages          # loop only makes sense just past capacity
        acc: Dict[str, List[float]] = {p: [] for p in policies}
        for k in range(trials):
            refs = workloads.generate(w, n, pg, seed + k)
            for p in policies:
                acc[p].append(simulate(refs, p, cfg, seed + k).stats["hit_rate"])
        out[w] = {p: statistics.fmean(v) for p, v in acc.items()}
    return out
