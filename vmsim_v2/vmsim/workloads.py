"""Reference-string generators with real locality, plus trace-file loading.

v1 only produced uniform-random strings, on which every online policy scores
the same; these generators are what make a policy comparison meaningful.
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Callable, Dict, List, Sequence, Tuple

TEXTBOOK = [7, 0, 1, 2, 0, 3, 0, 4, 2, 3, 0, 3, 2, 1, 2, 0, 1, 7, 0, 1]   # Silberschatz
BELADY = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5]                                # FIFO anomaly


def uniform(n: int, pages: int, seed: int = 0) -> List[int]:
    r = random.Random(seed)
    return [r.randrange(pages) for _ in range(n)]


def zipf(n: int, pages: int, seed: int = 0, s: float = 1.1) -> List[int]:
    r = random.Random(seed)
    return r.choices(range(pages), weights=[1 / (i + 1) ** s for i in range(pages)], k=n)


def loop(n: int, pages: int, seed: int = 0) -> List[int]:
    """Cycle over `pages` pages. With pages = frames + 1, LRU/FIFO fault every time."""
    return [i % pages for i in range(n)]


def scan(n: int, pages: int = 0, seed: int = 0) -> List[int]:
    """Touch each page once: pure compulsory misses (prefetch's best case)."""
    return list(range(n))


def phases(n: int, pages: int, seed: int = 0, ws: int = 6, phase_len: int = 200, stay: float = 0.9) -> List[int]:
    """Working set that shifts every `phase_len` references; `stay` of refs hit it."""
    r = random.Random(seed)
    out, cur = [], r.sample(range(pages), min(ws, pages))
    for i in range(n):
        if i and i % phase_len == 0:
            cur = r.sample(range(pages), min(ws, pages))
        out.append(r.choice(cur) if r.random() < stay else r.randrange(pages))
    return out


def mixed(n: int, pages: int, seed: int = 0) -> List[int]:
    """Zipf hot set interleaved with sequential scan bursts (hurts LRU, helps Clock/LFU)."""
    r = random.Random(seed)
    hot, out, nxt = zipf(n, max(2, pages // 4), seed), [], pages // 4
    for i in range(n):
        if r.random() < 0.25:
            out.append(nxt)
            nxt = nxt + 1 if nxt + 1 < pages else pages // 4
        else:
            out.append(hot[i])
    return out


GENERATORS: Dict[str, Callable[[int, int, int], List[int]]] = {
    "uniform": uniform, "zipf": zipf, "loop": loop, "scan": scan, "phases": phases, "mixed": mixed,
}


def generate(name: str, n: int = 500, pages: int = 32, seed: int = 0) -> List[int]:
    if name not in GENERATORS:
        raise ValueError(f"unknown workload {name!r}; choose from {', '.join(GENERATORS)}")
    if n < 0 or pages < 1:
        raise ValueError("n must be >= 0 and pages must be >= 1")
    return GENERATORS[name](n, pages, seed)


def with_writes(trace: Sequence[int], ratio: float, seed: int = 0) -> List[Tuple[int, bool]]:
    if not 0.0 <= ratio <= 1.0:
        raise ValueError("write ratio must be between 0 and 1")
    r = random.Random(seed)
    return [(p, r.random() < ratio) for p in trace]


def load_trace(path: str) -> List[str]:
    """Whitespace/comma separated pages; '12w' marks a write; '#' starts a comment."""
    toks: List[str] = []
    for line in Path(path).read_text().splitlines():
        toks += line.split("#")[0].replace(",", " ").split()
    if not toks:
        raise ValueError(f"{path}: no references found")
    return toks
