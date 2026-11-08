# Contributing to Virtual Memory & Page Replacement Simulator

Thank you for your interest in contributing! This project is maintained for Operating Systems coursework and research on virtual memory algorithms.

---

## 🛠️ Development Setup

The project uses Python's standard library with zero external runtime dependencies.

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Ayaan-22/Virtual-Memory-Page-Replacement-Simulator.git
   cd Virtual-Memory-Page-Replacement-Simulator
   ```

2. **Install development dependencies:**
   ```bash
   pip install pytest
   ```

3. **Run the test suite:**
   ```bash
   # Runs all 195 unit, property, and fuzz tests
   pytest
   ```

---

## 🧪 Testing Guidelines

Before submitting any code changes or pull requests:

1. **Ensure all existing tests pass:**
   ```bash
   pytest -v
   ```

2. **Verify parity with legacy v1 engine:**
   ```bash
   python vmsim_v2/tools/check_against_v1.py vmsim_v1/page_replacement_simulator.py --runs 10
   ```

3. **Verify parity with the JavaScript frontend engine:**
   ```bash
   python vmsim_v2/tools/check_js_parity.py --runs 10
   ```

4. **Verify CLI smoke test:**
   ```bash
   python -m vmsim_v2.vmsim run --frames 3 --steps LRU
   ```

---

## 📜 Pull Request Process

1. Fork the repository and create your branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. Write clean, self-documenting code with meaningful commit messages.
3. Add tests in [`vmsim_v2/tests/`](vmsim_v2/tests/) covering any new functionality or edge cases.
4. Open a pull request against `main`. Ensure all GitHub Actions CI checks pass.
