#!/usr/bin/env python3
"""Compare vmsim v2 with the original v1 engine on random traces.

    python tools/check_against_v1.py PATH/TO/page_replacement_simulator.py [--runs 300]

Hits and faults must match for FIFO, LRU, OPT, Clock, LFU and MFU (no TLB or prefetch, which v1 got wrong).
Average residency must match too, except for OPT: v1 breaks ties between never-used-again pages in set order,
v2 breaks them on the smallest page number, so the same faults can evict different (equally good) victims.
The v1 file imports tkinter and matplotlib; they are stripped here so this runs on a headless machine.
"""
import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vmsim import Config, simulate  # noqa: E402


def load_v1_engine(path: str) -> dict:
    src = Path(path).read_text(encoding="utf-8").replace("\r\n", "\n")
    cut = src.find("USER INTERFACE")
    if cut < 0:
        cut = src.index("class PageReplacementUI")
    keep = [l for l in src[:cut].split("\n") if not any(k in l for k in ("tkinter", "matplotlib"))]
    ns: dict = {"__name__": "v1_engine"}
    exec(compile("\n".join(keep), path, "exec"), ns)
    return ns


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("v1_file")
    ap.add_argument("--runs", type=int, default=300)
    a = ap.parse_args()
    v1 = load_v1_engine(a.v1_file)
    pairs = {"FIFO": v1["FIFO"], "LRU": v1["LRU"], "OPT": v1["Optimal"], "Clock": v1["Clock"], "LFU": v1["LFU"], "MFU": v1["MFU"]}
    bad = total = 0
    for seed in range(a.runs):
        r = random.Random(seed)
        pages, n, F = r.randint(3, 25), r.randint(20, 200), r.randint(1, 8)
        trace = [r.randrange(pages) for _ in range(n)]
        for name, cls in pairs.items():
            old = v1["VirtualMemorySimulator"](F)
            old.add_algorithm(name, cls)
            old.run(trace)
            o = old.report()[name]
            new = simulate(trace, name, Config(frames=F)).stats
            total += 1
            ok = (o["hits"], o["misses"]) == (new["hits"], new["faults"])
            if ok and name != "OPT":
                ok = abs(o["avg_residency"] - new["avg_residency"]) < 1e-9
            if not ok:
                bad += 1
                print(f"MISMATCH {name} frames={F} seed={seed}: v1 {o['hits']}/{o['misses']} vs v2 {new['hits']}/{new['faults']}")
    print(f"{total} comparisons across {a.runs} random traces: {bad} mismatches")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
