#!/usr/bin/env python3
"""Import all examples/**/*.graph.json into workspace/configs/templates/."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.example_templates import sync_example_templates  # noqa: E402


def main() -> int:
    result = sync_example_templates(force=True)
    print(json.dumps(result, indent=2))
    return 0 if not result.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())
