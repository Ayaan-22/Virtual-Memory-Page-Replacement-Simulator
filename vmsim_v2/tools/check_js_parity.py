#!/usr/bin/env python3
"""Check that the JavaScript engine inside visualizer.html agrees with the Python engine (needs Node.js).

    python tools/check_js_parity.py [--runs 250]

For random traces (with writes and a TLB) every policy except Random must agree on faults, cold faults,
write-backs, TLB shootdowns and the victim chosen at every single step. Random uses a different generator
in each language, so it is excluded.
"""
import argparse
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vmsim import Config, simulate  # noqa: E402

DRIVER = """
const {sim,NAMES}=require(process.argv[2]);
const cases=JSON.parse(require('fs').readFileSync(process.argv[3],'utf8'));
const out=cases.map(c=>{const refs=c.refs.map(x=>[x[0],!!x[1]]),o={};
  for(const m of NAMES){if(m==='Random')continue;const r=sim(refs,m,c.F,c.T);
    o[m]={faults:r.faults,cold:r.st.cold,wb:r.st.wb,sd:r.st.sd,victims:r.ev.map(e=>e.victim)}}return o});
process.stdout.write(JSON.stringify(out));
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=250)
    a = ap.parse_args()
    node = shutil.which("node")
    if not node:
        print("Node.js not found; install it to run this check.", file=sys.stderr)
        return 2
    html = (ROOT / "visualizer.html").read_text(encoding="utf-8")
    marker = "/* ---------- UI state"
    js = next(b for b in re.findall(r"<script>(.*?)</script>", html, re.S) if marker in b)   # the page has two script blocks
    core = js[: js.index(marker)] + "\nmodule.exports={sim,NAMES};\n"
    cases = []
    for seed in range(a.runs):
        r = random.Random(seed)
        pg = r.randint(3, 20)
        cases.append({"refs": [[r.randrange(pg), 1 if r.random() < 0.3 else 0] for _ in range(r.randint(15, 150))],
                      "F": r.randint(1, 8), "T": r.choice([0, 0, 2, 4])})
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "core.js").write_text(core)
        (d / "driver.js").write_text(DRIVER)
        (d / "cases.json").write_text(json.dumps(cases))
        res = subprocess.run([node, str(d / "driver.js"), str(d / "core.js"), str(d / "cases.json")], capture_output=True, text=True)
    if res.returncode:
        print(res.stderr, file=sys.stderr)
        return 2
    bad = total = 0
    for case, got in zip(cases, json.loads(res.stdout)):
        trace = [(p, bool(w)) for p, w in case["refs"]]
        for name, g in got.items():
            py = simulate(trace, name, Config(frames=case["F"], tlb_size=case["T"]))
            s = py.stats
            total += 1
            if (g["faults"], g["cold"], g["wb"], g["sd"]) != (s["faults"], s["cold"], s["writebacks"], s["tlb_shootdowns"]) \
                    or g["victims"] != [e.victim for e in py.events]:
                bad += 1
                print(f"MISMATCH {name} frames={case['F']} tlb={case['T']}")
    print(f"{total} comparisons (faults, cold, write-backs, shootdowns, every victim): {bad} mismatches")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
