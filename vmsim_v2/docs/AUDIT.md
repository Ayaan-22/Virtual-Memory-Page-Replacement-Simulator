# Audit

Two audits: what was wrong with the original (v1) simulator, and what an independent second pass found in v2.
Every number below came from a real run; the scripts and tests that reproduce them ship with the project.

## 1. v1 findings

| # | Severity | Finding | Evidence |
|---|---|---|---|
| 1 | Critical | A TLB hit made `run()` skip the replacement policies entirely, so recency, use bits and frequencies were never updated | 15-reference test with TLB on: LRU saw 9 of 15 accesses |
| 2 | Critical | TLB entries were never invalidated on eviction, and one TLB was shared by every policy although each has different frames resident | 1 frame, `1 2 1 2 1 2`: 6 faults expected, v1 reported 2 |
| 3 | Critical | "Prefetch" loaded `reference_string[t+i]`, the actual future references, which is an oracle rather than sequential prefetch | `10 50 10 90 10 70 30`, 3 frames, prefetch 1: 1 fault |
| 4 | High | The Results tab read residency standard deviation from the wrong run | FIFO: correct 1.22, displayed 1.63 |
| 5 | Medium | Random was not reproducible: `reset()` never re-seeded | Three identical runs: 40 / 46 / 43 faults |
| 6 | Medium | The Trace tab ran a fresh algorithm without the configured TLB, prefetch or latency | By inspection |
| 7 | Medium | Heavy simulation ran on the UI thread, twice per workload | By inspection |
| 8 | Medium | "Average fault latency" was always equal to the disk-latency input | By construction |
| 9 | Low | OPT rescanned the whole future per fault; ties broken arbitrarily | 8,000 references: about 1 s |
| 10 | Low | Clock and SecondChance were the same class, so "8 algorithms" was 7 | By inspection |

The v1 report also had a test table labelled "3 frames" whose numbers were the 4-frame results (real 3-frame
values: FIFO 15, LRU 12, OPT 9), and a chart section whose figures did not match the generator (uniform random
pages, so every online policy scores about the same, not the spread the report described).

## 2. v2 audit

### Engine correctness
- **Independent reference:** a separately written, list-based implementation of FIFO, LRU, OPT, Clock, LFU and MFU
  agrees with the engine victim by victim: 2,400 runs during the audit, 360 of them kept in the test suite.
- **Against v1:** `tools/check_against_v1.py` — 1,800 comparisons, 0 mismatches on hits, faults and residency
  (OPT residency excluded because tie-breaking is deliberately different).
- **Textbook values:** 15 / 12 / 9 at 3 frames; Belady's anomaly 9 → 10 for FIFO.
- **Invariant fuzz** (all 8 policies, random frames, TLB, prefetch, writes; 2,400 runs during the audit, 320 in the
  suite): hit if and only if the page was resident, one copy per page, victim was resident and is gone afterwards,
  dirty flags only on written pages, counters consistent, runs deterministic.

### Defects found in v2 and fixed
| Finding | Fix |
|---|---|
| Prefetch re-loaded the page the same fault had just evicted (8,948 occurrences in the fuzz run), so the visualizer could show "evicted 24" beside a frame holding 24 | Prefetch skips the demand victim; regression test added |
| Negative page numbers accepted silently | Rejected with a clear message |
| Unhelpful `invalid literal for int()` on bad references | Friendly message naming the token and the accepted forms |
| `--writes 2`, `--prefetch -1` silently accepted; `--tlb -3` raised a `KeyError` traceback | `Config` validates every field; CLI exits 2 with `error: …` |
| `sweep --min-frames 5 --max-frames 2` raised a `TypeError` traceback | Validated; table printing no longer fails on empty input |
| `--pages 0` surfaced `IndexError` / `empty range for randrange()` | Generators validate sizes |
| Server accepted requests that took 12 s (simulate) and 27 s (sweep) at the old caps | 5,000 references and 100,000 steps per request; worst case now 2.6 s; the visualizer's own sweep takes 0.16 s |
| No timeout on stalled connections | 10 s socket timeout |
| Binding to a non-loopback address was silent | Warning printed |

One apparent defect was a wrong check, not a bug: with prefetch on, cold faults can be fewer than distinct pages
because a first reference may be satisfied by an earlier prefetch. The invariant and the README now say so.

### Visualizer
| Check | Before | After |
|---|---|---|
| axe-core (WCAG 2.0/2.1 A and AA, best practices; **dark and light**; desktop and phone; initial, dropdown open, finished) | landmark, region ×15, `aria-allowed-attr` (critical), `aria-input-field-name` (serious), `scrollable-region-focusable` ×2 (serious) | 0 violations in all twelve theme/width/state combinations |
| html-validate | 2 errors (empty button, untyped input) | 0 |
| Text contrast measured from computed styles, gradients blended over the page colour, with a dropdown and a notification open | n/a | **dark: 0 failures; light: 0 failures** (4.5:1 for text, 3:1 for large text). The gradient-filled title is checked separately: 13.7:1 or better in dark, 4.9:1 or better in light |
| Theme switch (13 browser checks) | n/a | Auto resolves to the system and follows live changes; an explicit choice beats the system and survives reload; the theme is set while the page is still loading (no flash); chart lines, series dots, panels and captions all recolour; keyboard operable |
| Stress: 1 reference; 3 identical; 12 frames on 3 pages; 400 references on 12 frames; 401 (rejected); 6-digit pages; leading zeros | n/a | all correct, no overflow, no JS errors; stepping costs 3.8 ms at the largest size |
| JS engine vs Python engine | n/a | 1,750 comparisons (faults, cold, write-backs, shootdowns, every victim), 0 mismatches |
| Interaction suite (dropdowns by mouse and keyboard, toasts, engine switching, mid-session server loss, bad input) | n/a | 33 checks pass |
| Layout shift when a notification appears | text pushed the page down | 0 px, measured in a real browser |

axe still lists colour contrast as "needs review" because it cannot compute contrast over gradients; the measurement
above covers it. It also reports "unable to determine whether `aria-controls` target exists" for the open dropdown,
which is its standard response when `aria-haspopup` is present.

### Light theme audit
The first contrast run on the new light theme flagged six items. Five were a flaw in the measuring script (it replaced the
page's solid background colour with an average of its gradient stops, including transparent ones); fixing the script
cleared them. The sixth was real: the small "OPERATING SYSTEMS" eyebrow measured 4.33:1 against the tinted page corner,
below the 4.5:1 minimum, and its colour token was darkened.

## 3. What is not verified

- The browser-based checks (axe-core, contrast, the 33 interaction checks, the 13 theme checks, stress and layout-shift
  measurements) were run with scripts driving headless Chromium that are **not included** in this package; the Python
  tests and the two `tools/` cross-checks are, and can be re-run anywhere.
- Only Chromium was available. Firefox and Safari styling for the slider thumbs is written but untested.
- The code was run on Python 3.12 only. Static analysis (vermin) says Python 3.8 suffices; the package declares 3.9.
- Opening the visualizer inside a chat or preview pane may stop it reaching `127.0.0.1:8765`; open the downloaded file.
- The built-in JS engine has no prefetch or EAT, and its Random differs from Python's by design.
- `Project_Report.docx` still describes v1, including the wrong test table above. Regenerate it from
  `python -m vmsim report` before submitting.
