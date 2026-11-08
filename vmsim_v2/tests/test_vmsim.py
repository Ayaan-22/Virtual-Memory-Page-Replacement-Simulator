import random

import pytest

from vmsim import Config, POLICIES, experiments, simulate, run_all, workloads
from vmsim.cli import main

ONLINE = [p for p in POLICIES if p != "OPT"]


def faults(trace, policy, **cfg):
    return simulate(trace, policy, Config(**cfg)).stats["faults"]


# ---------- golden values (Silberschatz, 20-reference string) ----------
@pytest.mark.parametrize("policy,expected", [("FIFO", 15), ("LRU", 12), ("OPT", 9)])
def test_textbook_three_frames(policy, expected):
    assert faults(workloads.TEXTBOOK, policy, frames=3) == expected


@pytest.mark.parametrize("policy,expected", [("FIFO", 10), ("LRU", 8), ("OPT", 8)])
def test_textbook_four_frames(policy, expected):
    assert faults(workloads.TEXTBOOK, policy, frames=4) == expected


def test_belady_anomaly_fifo():
    assert faults(workloads.BELADY, "FIFO", frames=3) == 9
    assert faults(workloads.BELADY, "FIFO", frames=4) == 10
    sw = experiments.frames_sweep(workloads.BELADY, ["FIFO", "LRU", "OPT"], range(1, 6))
    assert [a[0] for a in experiments.belady_anomalies(sw, list(range(1, 6)))] == ["FIFO"]


# ---------- properties ----------
@pytest.mark.parametrize("seed", range(20))
def test_opt_never_loses(seed):
    refs = workloads.zipf(300, 20, seed)
    best = faults(refs, "OPT", frames=5)
    assert all(faults(refs, p, frames=5) >= best for p in ONLINE)


@pytest.mark.parametrize("seed", range(10))
def test_lru_stack_property(seed):
    refs = workloads.phases(400, 30, seed)
    f = [faults(refs, "LRU", frames=k) for k in range(1, 12)]
    assert f == sorted(f, reverse=True)           # more frames never hurts LRU


def test_cold_plus_capacity_equals_faults_and_cold_equals_distinct():
    refs = workloads.uniform(400, 25, 3)
    for p in POLICIES:
        s = simulate(refs, p, Config(frames=6)).stats
        assert s["cold"] + s["capacity"] == s["faults"]
        assert s["cold"] == len(set(refs))
        assert s["hits"] + s["faults"] == len(refs)


def test_random_is_reproducible():
    refs = workloads.uniform(300, 12, 1)
    a = [faults(refs, "Random", frames=3) for _ in range(3)]
    assert len(set(a)) == 1


# ---------- v1 bug regressions ----------
def test_tlb_does_not_change_fault_counts():
    """v1: TLB hits skipped the policy, corrupting hit/miss stats."""
    refs = workloads.phases(500, 20, 2)
    for p in POLICIES:
        assert faults(refs, p, frames=4) == faults(refs, p, frames=4, tlb_size=4)


def test_tlb_is_invalidated_on_eviction():
    """v1: 1 frame, alternating pages gave 2 faults because the TLB 'remembered' evicted pages."""
    r = simulate([1, 2, 1, 2, 1, 2], "FIFO", Config(frames=1, tlb_size=4))
    assert r.stats["faults"] == 6
    assert r.stats["tlb_shootdowns"] == 5
    assert r.stats["tlb_hit_rate"] == 0.0


def test_prefetch_is_not_an_oracle():
    refs = [10, 50, 10, 90, 10, 70, 30]
    assert simulate(refs, "FIFO", Config(frames=3, prefetch_depth=1)).stats["faults"] >= len(set(refs))


def test_prefetch_helps_sequential_scans():
    refs = list(range(20))
    r = simulate(refs, "FIFO", Config(frames=4, prefetch_depth=1)).stats
    assert r["faults"] == 10 and r["prefetch_useful"] == 10 and r["prefetch_wasted"] == 0


def test_prefetch_never_evicts_the_demanded_page():
    refs = workloads.mixed(500, 40, 1)
    for p in POLICIES:
        r = simulate(refs, p, Config(frames=3, prefetch_depth=2))
        assert all(e.page in e.frames for e in r.events)


# ---------- write-back & enhanced clock ----------
def test_dirty_eviction_counts_writeback():
    r = simulate(["0w", "1w", "2"], "FIFO", Config(frames=2))
    assert r.stats["writebacks"] == 1 and r.events[2].victim_dirty


def test_eclock_prefers_clean_victim():
    r = simulate(["0w", "1", "2"], "EClock", Config(frames=2))
    assert r.events[2].victim == 1                 # clean page evicted, dirty page kept
    assert r.stats["writebacks"] == 0
    assert simulate(["0w", "1", "2"], "Clock", Config(frames=2)).stats["writebacks"] == 1


def test_eat_grows_with_faults():
    cfg = Config(frames=3)
    assert simulate(workloads.TEXTBOOK, "OPT", cfg).stats["eat_ns"] < simulate(workloads.TEXTBOOK, "FIFO", cfg).stats["eat_ns"]


# ---------- misc ----------
def test_single_frame_and_bad_input():
    assert faults([1, 1, 1, 2, 2], "LRU", frames=1) == 2
    with pytest.raises(ValueError):
        simulate([1], "LRU", Config(frames=0))
    with pytest.raises(ValueError):
        simulate([1], "nope", Config())


def test_cli_smoke(tmp_path, capsys):
    out = tmp_path / "r.md"
    assert main(["run", "--frames", "3", "--steps", "LRU"]) == 0
    assert main(["belady"]) == 0
    assert main(["report", "--out", str(out), "--n", "200", "--trials", "1"]) == 0
    assert "Belady" in out.read_text()
    assert main(["run", "--trace", "x y"]) == 2


# =====================================================================================
# Audit regression tests: independent references, invariants, input validation
# =====================================================================================
import re as _re
from pathlib import Path as _Path

from vmsim import normalize, __version__

INF = float("inf")


def _naive_reference(pages, F, pol):
    """Deliberately simple, list-based implementations, written independently of vmsim.algorithms."""
    fr, victims, order, cnt = [], [], [], {}
    slots, rb, hand = [None] * F, [0] * F, 0
    for t, p in enumerate(pages):
        if pol == "Clock":
            if p in slots:
                rb[slots.index(p)] = 1
                victims.append(None)
                continue
            if None in slots:
                i = slots.index(None)
                slots[i], rb[i] = p, 1
                victims.append(None)
                continue
            while rb[hand]:
                rb[hand] = 0
                hand = (hand + 1) % F
            victims.append(slots[hand])
            slots[hand], rb[hand] = p, 1
            hand = (hand + 1) % F
            continue
        if p in fr:
            victims.append(None)
            if pol == "LRU":
                fr.remove(p)
                fr.append(p)
            if pol in ("LFU", "MFU"):
                cnt[p] += 1
            continue
        v = None
        if len(fr) >= F:
            if pol in ("FIFO", "LRU"):
                v = fr[0]
            elif pol == "OPT":
                def nxt(q):
                    return next((j for j in range(t + 1, len(pages)) if pages[j] == q), INF)
                far = max(nxt(q) for q in fr)
                v = min(q for q in fr if nxt(q) == far)
            else:
                pick = min if pol == "LFU" else max
                m = pick(cnt[q] for q in fr)
                v = next(q for q in order if q in fr and cnt[q] == m)
            fr.remove(v)
            order.remove(v)
            cnt.pop(v, None)
        fr.append(p)
        order.append(p)
        cnt[p] = 1
        victims.append(v)
    return victims


@pytest.mark.parametrize("seed", range(60))
def test_matches_independent_naive_reference_victim_by_victim(seed):
    r = random.Random(seed)
    pages = [r.randrange(r.randint(1, 18)) for _ in range(r.randint(1, 140))]
    F = r.randint(1, 9)
    for pol in ("FIFO", "LRU", "OPT", "Clock", "LFU", "MFU"):
        got = [e.victim for e in simulate(pages, pol, Config(frames=F)).events]
        assert got == _naive_reference(pages, F, pol), (pol, F, seed)


@pytest.mark.parametrize("seed", range(40))
def test_event_log_invariants_hold_for_every_policy_and_config(seed):
    r = random.Random(1000 + seed)
    pg, n, F = r.randint(1, 25), r.randint(1, 160), r.randint(1, 8)
    cfg = Config(frames=F, tlb_size=r.choice([0, 1, 3, 6]), prefetch_depth=r.choice([0, 0, 1, 2, 4]))
    trace = [(r.randrange(pg), r.random() < 0.35) for _ in range(n)]
    for pol in POLICIES:
        res = simulate(trace, pol, cfg, seed)
        assert [e.frames for e in res.events] == [e.frames for e in simulate(trace, pol, cfg, seed).events]
        prev, written = (None,) * F, set()
        for e in res.events:
            resident = [x for x in e.frames if x is not None]
            assert len(e.frames) == F and len(resident) == len(set(resident))
            assert (e.kind == "hit") == (e.page in prev)                 # hit <=> page was resident
            assert e.page in e.frames                                     # always resident afterwards
            if e.victim is not None:
                assert e.kind != "hit" and e.victim in prev and e.victim not in e.frames
            assert all(q in e.frames for q in e.prefetched)
            assert not (e.kind == "hit" and e.prefetched)                 # prefetch only on faults
            if e.write:
                written.add(e.page)
            assert all(not d or (x is not None and x in written) for d, x in zip(e.dirty, e.frames))
            prev = e.frames
        s = res.stats
        assert s["hits"] + s["faults"] == n and s["cold"] + s["capacity"] == s["faults"]
        distinct = len({p for p, _ in trace})
        assert s["cold"] <= distinct and (cfg.prefetch_depth > 0 or s["cold"] == distinct)
        assert s["writebacks"] <= s["evictions"] and s["tlb_shootdowns"] <= s["evictions"]
        assert s["prefetch_useful"] + s["prefetch_wasted"] <= s["prefetch_issued"]
        assert (s["prefetch_issued"] == 0) or cfg.prefetch_depth > 0
        assert (s["tlb_hit_rate"] is None) == (cfg.tlb_size == 0)
        assert s["eat_ns"] >= 2 * cfg.mem_ns - 1e-9


def test_prefetch_does_not_refetch_the_page_it_just_evicted():
    """Audit finding: a fault evicted page 24 and its own prefetch immediately re-loaded it."""
    trace = [24, 100, 23, 24, 23, 24]
    r = simulate(trace, "FIFO", Config(frames=2, prefetch_depth=1))
    assert all(e.victim not in e.frames for e in r.events if e.victim is not None)


def test_first_reference_satisfied_by_prefetch_is_a_hit_not_a_cold_fault():
    s = simulate(list(range(10)), "FIFO", Config(frames=4, prefetch_depth=1)).stats
    assert s["cold"] == 5 and s["cold"] < 10 and s["hits"] == 5


# ---------- input validation (audit: these used to traceback or be silently accepted) ----------
@pytest.mark.parametrize("kwargs", [dict(frames=0), dict(tlb_size=-1), dict(prefetch_depth=-1), dict(disk_ms=-1)])
def test_config_rejects_nonsense(kwargs):
    with pytest.raises(ValueError):
        Config(**kwargs)


@pytest.mark.parametrize("bad", [-1, "-1", "3x", "x", "", "7ww", "w", 1.5j, None])
def test_normalize_rejects_bad_references_with_a_helpful_message(bad):
    with pytest.raises(ValueError, match="bad reference"):
        normalize([bad])


def test_normalize_accepts_all_documented_forms():
    assert normalize([3, "4", " 5W ", "6r", (7, 1), (8, False)]) == [(3, False), (4, False), (5, True), (6, False), (7, True), (8, False)]


def test_empty_trace_is_fine():
    s = simulate([], "LRU", Config()).stats
    assert s["refs"] == 0 and s["hit_rate"] == 0.0 and s["eat_ns"] == 0.0


def test_generators_reject_bad_sizes_and_survive_tiny_ones():
    for bad in (dict(pages=0), dict(n=-1)):
        with pytest.raises(ValueError):
            workloads.generate("zipf", **{"n": 10, "pages": 5, **bad})
    for name in workloads.GENERATORS:
        assert len(workloads.generate(name, 25, 1)) == 25
    with pytest.raises(ValueError):
        workloads.with_writes([1], 1.5)


@pytest.mark.parametrize("argv", [
    ["run", "--frames", "0"], ["run", "--writes", "2"], ["run", "--writes", "-0.1"], ["run", "--tlb", "-3"],
    ["run", "--prefetch", "-1"], ["run", "--policies", "nope"], ["run", "--file", "/nonexistent/x.txt"],
    ["run", "--trace", "1 -2 3"], ["sweep", "--min-frames", "5", "--max-frames", "2"],
    ["workloads", "--pages", "0"], ["belady", "--max-frames", "0"],
])
def test_cli_bad_arguments_exit_2_with_a_message_not_a_traceback(argv, capsys):
    assert main(argv) == 2
    assert capsys.readouterr().err.startswith("error:")


def test_version_is_consistent():
    text = (_Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    assert _re.search(r'^version\s*=\s*"%s"' % _re.escape(__version__), text, _re.M)
