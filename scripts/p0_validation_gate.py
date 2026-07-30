#!/usr/bin/env python3
"""
P0 validation gate for Graphyn runtime hardening.

Runs a focused example suite and fails fast on regressions.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / "venv" / "bin" / "python")

CASES = [
    ("examples/prepare_real_data.py", 600),
    ("examples/13_csv_data_processing/csv_pipeline.py", 120),
    ("examples/07_mcp_agent_pipeline/agent.py", 180),
    ("examples/15_event_driven_pipeline/event_driven_demo.py", 180),
    ("examples/17_partial_execution/partial_demo.py", 300),
    ("examples/21_runtime_control_api/runtime_control_demo.py", 300),
]


def run_case(script: str, timeout_s: int) -> tuple[int, str]:
    cmd = [PY, script]
    start = time.time()
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    elapsed = time.time() - start
    status = "PASS" if proc.returncode == 0 else "FAIL"
    print(f"{status} {script} ({elapsed:.1f}s)")
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout)[-1200:]
        return 1, tail
    return 0, ""


def main() -> int:
    print("Graphyn P0 Validation Gate")
    print("=" * 60)
    failures: list[tuple[str, str]] = []
    for script, timeout_s in CASES:
        try:
            code, details = run_case(script, timeout_s)
        except subprocess.TimeoutExpired:
            code = 1
            details = f"Timed out after {timeout_s}s"
            print(f"FAIL {script} (timeout)")
        if code != 0:
            failures.append((script, details))

    print("=" * 60)
    if failures:
        print(f"FAIL {len(failures)}/{len(CASES)}")
        for script, details in failures:
            print(f"\n--- {script} ---\n{details}")
        return 1
    print(f"PASS {len(CASES)}/{len(CASES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
