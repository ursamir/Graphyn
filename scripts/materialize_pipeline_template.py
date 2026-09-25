#!/usr/bin/env python3
"""CLI: materialize one marketplace template id to a .graph.json file."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.pipeline_template_materializer import materialize_to_file

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("template_id")
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--catalog", type=Path, default=None)
    args = ap.parse_args()
    path = materialize_to_file(args.template_id, args.out, catalog_path=args.catalog)
    print(path)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
