"""Command line: python -m vmsim <run|belady|sweep|workloads|report> ..."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import replace
from typing import List, Optional, Sequence

from . import experiments, workloads
from .algorithms import POLICIES
from .simulator import Config, Result, run_all, simulate, normalize


def table(rows: Sequence[Sequence], headers: Sequence[str]) -> str:
    cells = [[str(c) for c in r] for r in rows]
    w = [max([len(h)] + [len(r[i]) for r in cells]) for i, h in enumerate(headers)]
    line = lambda r: "  ".join(c.ljust(w[i]) if i == 0 else c.rjust(w[i]) for i, c in enumerate(r))
    return "\n".join([line(headers), "  ".join("-" * x for x in w)] + [line(r) for r in cells])


def md_table(rows, headers) -> str:
    return "\n".join(["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
                     + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def _pols(arg: Optional[str]) -> List[str]:
    return [p.strip() for p in arg.split(",")] if arg else list(POLICIES)


def _trace(a) -> list:
    if getattr(a, "file", None):
        refs = workloads.load_trace(a.file)
    elif getattr(a, "trace", None):
        refs = a.trace.replace(",", " ").split()
    elif getattr(a, "workload", None):
        refs = workloads.generate(a.workload, a.n, a.pages, a.seed)
    else:
        refs = list(workloads.TEXTBOOK)
    if getattr(a, "writes", 0):
        refs = workloads.with_writes([int(str(r).rstrip("rw")) for r in refs], a.writes, a.seed)
    return refs


def _cfg(a) -> Config:
    return Config(frames=a.frames, tlb_size=a.tlb, prefetch_depth=a.prefetch,
                  mem_ns=a.mem_ns, tlb_ns=a.tlb_ns, disk_ms=a.disk_ms)


def _summary(results) -> str:
    rows = []
    for n, r in results.items():
        s = r.stats
        rows.append([n, s["hits"], s["faults"], s["cold"], s["capacity"], f"{s['hit_rate']*100:.1f}%",
                     s["writebacks"], f"{s['eat_ns']/1e6:.3f}", f"{s['avg_residency']:.2f}"])
    return table(rows, ["policy", "hits", "faults", "cold", "capacity", "hit%", "wr-back", "EAT ms", "residency"])


def cmd_run(a) -> int:
    refs, cfg = _trace(a), _cfg(a)
    res = run_all(refs, cfg, _pols(a.policies), a.seed)
    print(f"{len(refs)} references, {len(set(normalize(refs)[i][0] for i in range(len(refs))))} distinct pages, "
          f"{cfg.frames} frames, TLB={cfg.tlb_size or 'off'}, prefetch={cfg.prefetch_depth or 'off'}\n")
    print(_summary(res))
    if cfg.tlb_size:
        print("\nTLB hit rate: " + "  ".join(f"{n}={r.stats['tlb_hit_rate']*100:.1f}%" for n, r in res.items()))
    if cfg.prefetch_depth:
        print("\nPrefetch (issued/useful/wasted): " + "  ".join(
            f"{n}={r.stats['prefetch_issued']}/{r.stats['prefetch_useful']}/{r.stats['prefetch_wasted']}" for n, r in res.items()))
    if a.steps:
        r = res[a.steps] if a.steps in res else simulate(refs, a.steps, cfg, a.seed)
        print(f"\nStep trace — {r.policy}  (F = fault, · = hit, victim shown as -page)\n")
        rows = [[e.t + 1, f"{e.page}{'w' if e.write else ''}", "F" if e.fault else "·",
                 e.kind, "-" + str(e.victim) if e.victim is not None else "",
                 " ".join("_" if p is None else str(p) for p in e.frames)] for e in r.events]
        print(table(rows, ["step", "page", "", "kind", "victim", "frames"]))
    if a.json:
        json.dump({n: r.to_dict() for n, r in res.items()}, open(a.json, "w"), indent=1)
        print(f"\nwrote {a.json}")
    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.writer(f)
            keys = list(next(iter(res.values())).stats)
            w.writerow(["policy"] + keys)
            for n, r in res.items():
                w.writerow([n] + [r.stats[k] for k in keys])
        print(f"wrote {a.csv}")
    return 0


def cmd_belady(a) -> int:
    if a.max_frames < 1:
        raise ValueError("--max-frames must be >= 1")
    refs = a.trace.replace(",", " ").split() if a.trace else workloads.BELADY
    fr = list(range(1, a.max_frames + 1))
    sw = experiments.frames_sweep(refs, _pols(a.policies), fr, _cfg(a), a.seed)
    print("Faults by frame count\n")
    print(table([[p] + v for p, v in sw.items()], ["policy"] + [f"{f}f" for f in fr]))
    an = experiments.belady_anomalies(sw, fr)
    print()
    for p, f0, f1, x0, x1 in an:
        print(f"Belady's anomaly: {p} faults {x0} -> {x1} when frames go {f0} -> {f1}")
    if not an:
        print("No anomaly on this string for the selected policies.")
    return 0


def cmd_sweep(a) -> int:
    if not 1 <= a.min_frames <= a.max_frames:
        raise ValueError("need 1 <= --min-frames <= --max-frames")
    refs, fr = _trace(a), list(range(a.min_frames, a.max_frames + 1))
    sw = experiments.frames_sweep(refs, _pols(a.policies), fr, _cfg(a), a.seed)
    print(table([[f] + [sw[p][i] for p in sw] for i, f in enumerate(fr)], ["frames"] + list(sw)))
    return 0


def cmd_workloads(a) -> int:
    pol = _pols(a.policies)
    m = experiments.compare_workloads(pol, _cfg(a), n=a.n, pages=a.pages, trials=a.trials, seed=a.seed)
    print(f"Mean hit rate (%), {a.n} refs x {a.trials} seeds, {a.frames} frames\n")
    print(table([[w] + [f"{m[w][p]*100:.1f}" for p in pol] for w in m], ["workload"] + pol))
    return 0


def cmd_report(a) -> int:
    pol = list(POLICIES)
    out = ["# Simulation results\n", "_Generated by `python -m vmsim report`; every number comes from a real run._\n"]
    for f in (3, 4):
        res = run_all(workloads.TEXTBOOK, Config(frames=f), pol)
        out += [f"## Textbook string, {f} frames\n", f"`{' '.join(map(str, workloads.TEXTBOOK))}`\n",
                md_table([[n, r.stats["hits"], r.stats["faults"], f"{r.stats['hit_rate']*100:.1f}%"]
                          for n, r in res.items()], ["Policy", "Hits", "Faults", "Hit rate"]), ""]
    fr = list(range(1, 8))
    sw = experiments.frames_sweep(workloads.BELADY, pol, fr)
    out += ["## Belady's anomaly\n", f"`{' '.join(map(str, workloads.BELADY))}` — faults by frame count\n",
            md_table([[p] + v for p, v in sw.items()], ["Policy"] + [f"{f}f" for f in fr]), ""]
    for p, f0, f1, x0, x1 in experiments.belady_anomalies(sw, fr):
        out.append(f"- **{p}**: {x0} faults at {f0} frames, {x1} faults at {f1} frames\n")
    cfg = Config(frames=a.frames)
    m = experiments.compare_workloads(pol, cfg, n=a.n, pages=a.pages, trials=a.trials, seed=a.seed)
    out += [f"\n## Workload comparison — mean hit rate (%), {a.frames} frames\n",
            f"{a.n} references x {a.trials} seeds, {a.pages} pages (`loop` uses frames+1).\n",
            md_table([[w] + [f"{m[w][p]*100:.1f}" for p in pol] for w in m], ["Workload"] + pol)]
    open(a.out, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"wrote {a.out}")
    return 0


def cmd_serve(a) -> int:
    from .server import make_server
    if a.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"WARNING: serving on {a.host} exposes the engine to other machines on your network.", file=sys.stderr)
    srv = make_server(a.host, a.port)
    print(f"vmsim engine listening on http://{a.host}:{a.port}  (Ctrl+C to stop)")
    print("Open visualizer.html and pick 'Python engine' under Engine.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        srv.server_close()
    return 0


def _common(p, trace=True) -> None:
    p.add_argument("--frames", type=int, default=4)
    p.add_argument("--policies", help="comma list, default all: " + ",".join(POLICIES))
    p.add_argument("--tlb", type=int, default=0, help="TLB entries (0 = off)")
    p.add_argument("--prefetch", type=int, default=0, help="sequential prefetch depth on a fault")
    p.add_argument("--mem-ns", type=float, default=100.0, dest="mem_ns")
    p.add_argument("--tlb-ns", type=float, default=5.0, dest="tlb_ns")
    p.add_argument("--disk-ms", type=float, default=8.0, dest="disk_ms")
    p.add_argument("--seed", type=int, default=0)
    if trace:
        p.add_argument("--trace", help='pages, e.g. "7 0 1 2 0 3" (suffix w = write: "3w")')
        p.add_argument("--file", help="trace file (whitespace/comma separated, # comments)")
        p.add_argument("--workload", choices=list(workloads.GENERATORS))
        p.add_argument("--n", type=int, default=500)
        p.add_argument("--pages", type=int, default=32)
        p.add_argument("--writes", type=float, default=0.0, help="fraction of references that are writes")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="vmsim", description="Virtual memory & page-replacement simulator")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run", help="run policies on one reference string")
    _common(p)
    p.add_argument("--steps", metavar="POLICY", help="print the step-by-step frame table for one policy")
    p.add_argument("--json"), p.add_argument("--csv")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("belady", help="faults vs frames; detect Belady's anomaly")
    _common(p, trace=False)
    p.add_argument("--trace")
    p.add_argument("--max-frames", type=int, default=7, dest="max_frames")
    p.set_defaults(fn=cmd_belady)
    p = sub.add_parser("sweep", help="faults vs frame count for any trace/workload")
    _common(p)
    p.add_argument("--min-frames", type=int, default=1, dest="min_frames")
    p.add_argument("--max-frames", type=int, default=12, dest="max_frames")
    p.set_defaults(fn=cmd_sweep)
    p = sub.add_parser("workloads", help="policy x workload hit-rate matrix")
    _common(p, trace=False)
    p.add_argument("--n", type=int, default=2000), p.add_argument("--pages", type=int, default=64)
    p.add_argument("--trials", type=int, default=5)
    p.set_defaults(fn=cmd_workloads)
    p = sub.add_parser("report", help="write a Markdown results file from real runs")
    p.add_argument("--out", default="RESULTS.md")
    p.add_argument("--frames", type=int, default=8)
    p.add_argument("--n", type=int, default=2000), p.add_argument("--pages", type=int, default=64)
    p.add_argument("--trials", type=int, default=5), p.add_argument("--seed", type=int, default=0)
    p.set_defaults(fn=cmd_report)
    p = sub.add_parser("serve", help="local engine for visualizer.html (prefetch, EAT)")
    p.add_argument("--host", default="127.0.0.1"), p.add_argument("--port", type=int, default=8765)
    p.set_defaults(fn=cmd_serve)
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        return a.fn(a)
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
