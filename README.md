# Virtual Memory & Page Replacement Simulator

[![CI](https://github.com/Ayaan-22/Virtual-Memory-Page-Replacement-Simulator/actions/workflows/ci.yml/badge.svg)](https://github.com/Ayaan-22/Virtual-Memory-Page-Replacement-Simulator/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-195%20passed-brightgreen.svg)](vmsim_v2/tests/)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-standard%20library-informational.svg)](vmsim_v2/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A comprehensive simulation and analysis suite for Virtual Memory management and Page Replacement Algorithms, developed for the Operating Systems course.

## 👥 Authors
| ID | Name |
|---|---|
| **23K-2084** | Ayaan Irfan |
| **23K-2082** | Muneeb Ahmed |
| **23K-2064** | Faizan Ashfaq |

---

## 📁 Repository Structure

The repository is organized into two versions: **v2** (current, re-engineered) and **v1** (legacy Tkinter implementation).

```
Virtual Memory & Page Replacement Simulator/
├── vmsim_v2/                       # Latest Version (v2.0)
│   ├── vmsim/                      # Core Python simulation package
│   │   ├── algorithms.py           # 8 Replacement policies (FIFO, LRU, OPT, Clock, etc.)
│   │   ├── simulator.py            # Hardware model (frames, dirty bits, TLB, prefetch, EAT)
│   │   ├── workloads.py            # Synthetic & custom workload generators
│   │   ├── experiments.py          # Belady's anomaly detector, sweeps, workload analysis
│   │   ├── server.py               # Lightweight local HTTP engine (127.0.0.1:8765)
│   │   └── cli.py                  # Full command-line interface
│   ├── tests/                      # 195 unit, golden-reference, invariant, & fuzz tests
│   ├── tools/                      # Cross-engine & v1-parity verification tools
│   ├── docs/                       # Technical audit (AUDIT.md) & documentation
│   ├── visualizer.html             # Standalone interactive web visualizer
│   ├── RESULTS.md                  # Benchmark results generated from live runs
│   └── pyproject.toml              # Package configuration
│
├── vmsim_v1/                       # Legacy Version (v1.0)
│   ├── Diagrams/                   # Architecture & class diagrams
│   ├── page_replacement_simulator.py  # Original Tkinter desktop application & engine
│   ├── page_replacement_simulator1.py # Early draft / revision
│   ├── Project Report.docx         # Original academic project report
│   └── README.md                   # v1 documentation
│
└── README.md                       # Repository guide (this file)
```

---

## 🚀 Version Comparison

| Capability | v2 (Latest) — [`vmsim_v2/`](vmsim_v2/) | v1 (Legacy) — [`vmsim_v1/`](vmsim_v1/) |
|---|---|---|
| **Interface** | Responsive Web Visualizer (`visualizer.html`) + CLI | Desktop Tkinter GUI + Matplotlib |
| **Dependencies** | Python standard library only (zero dependencies) | Tkinter, Matplotlib |
| **Supported Algorithms** | 8 policies: FIFO, LRU, OPT, Clock, EClock, LFU, MFU, Random | 7 distinct policies (Clock / SecondChance duplicated) |
| **Execution Modes** | Headless CLI, local HTTP REST backend, client-side JS | Desktop GUI only |
| **Testing** | 195 automated tests, fuzzing, property checks, parity verification | Manual testing |
| **Hardware Modeling** | Page faults, write-back dirty tracking, TLB + shootdowns, EAT, sequential prefetch | Basic TLB & prefetch heuristics |
| **Workload Generation** | Uniform, Zipfian, Loop, Scan, Phased, Mixed, custom trace files | Uniform random sequences |
| **Anomaly Analysis** | Automated Belady's anomaly sweep & detection | N/A |

---

## ⚡ Quick Start

### 1. Using v2 (Latest Version)

#### Option A: Web Visualizer
Open [`vmsim_v2/visualizer.html`](vmsim_v2/visualizer.html) in any modern web browser.
- Runs self-contained with its built-in JavaScript engine.
- For full prefetch and EAT calculation using the Python engine, launch the background server:
  ```bash
  python -m vmsim_v2.vmsim serve
  ```

#### Option B: Command Line Interface (CLI)
From the repository root or inside `vmsim_v2`:

```bash
# Run textbook string across all 8 policies
python -m vmsim_v2.vmsim run --frames 3 --steps LRU

# Run workload analysis (matrix of hit rates across policies)
python -m vmsim_v2.vmsim workloads --frames 4

# Detect Belady's anomaly
python -m vmsim_v2.vmsim belady

# Run simulation with Zipfian distribution, dirty writes, TLB, and prefetching
python -m vmsim_v2.vmsim run --workload zipf --writes 0.3 --tlb 8 --prefetch 2 --json out.json
```

#### Option C: Running Automated Tests
```bash
# Run all 195 unit, property, and fuzz tests
pytest
```

---

### 2. Using v1 (Legacy Version)

Requires `matplotlib` and `tkinter`:

```bash
cd vmsim_v1
python page_replacement_simulator.py
```

Refer to [`vmsim_v1/README.md`](vmsim_v1/README.md) and [`vmsim_v1/Project Report.docx`](vmsim_v1/Project%20Report.docx) for original implementation notes and reports.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
