#!/usr/bin/env python3
"""Verify template graphs: IR load, registered node types, ingest paths exist."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.example_templates import templates_dir  # noqa: E402
from app.core.ir.loader import load_ir  # noqa: E402


def main() -> int:
    registered: set[str] = set()
    try:
        from app.core.nodes import initialize_registry
        from app.core.registry_runtime import get_registry

        initialize_registry()
        reg = get_registry()
        if hasattr(reg, "list_types"):
            registered = set(reg.list_types())
        elif hasattr(reg, "_nodes"):
            registered = set(reg._nodes.keys())  # noqa: SLF001
    except Exception as exc:
        print(f"warn: registry init failed ({exc}); path/IR checks only")

    root = ROOT
    tdir = templates_dir()
    failures: list[str] = []
    checked = 0
    for path in sorted(tdir.glob("*.graph.json")):
        # Focus starters + examples; skip nothing — verify all
        checked += 1
        try:
            graph = load_ir(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:
            failures.append(f"{path.name}: IR load failed: {exc}")
            continue
        for node in graph.nodes:
            if registered and node.node_type not in registered:
                failures.append(f"{path.name}: unregistered node_type {node.node_type}")
            if node.node_type == "dataset_ingest":
                p = str((node.config or {}).get("path", ""))
                if p and not (root / p).exists() and not Path(p).exists():
                    failures.append(f"{path.name}: missing ingest path {p}")

    print(f"checked={checked} registered={len(registered)} failures={len(failures)}")
    for f in failures[:80]:
        print(" -", f)
    if len(failures) > 80:
        print(f" ... and {len(failures) - 80} more")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
