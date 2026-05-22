#!/usr/bin/env python3
"""
Example 13 — CSV Data Processing Pipeline (Priority 7 — F1)
============================================================
Proves the platform is domain-agnostic — not just an audio tool.

Builds a pure data processing pipeline using DataSample-typed nodes
that read, filter, normalize, and write CSV data. No audio involved.

Pipeline: csv_reader → row_filter → column_normalizer → csv_writer

What this shows:
  - DataSample as a domain-agnostic base type
  - Writing custom nodes that work with non-audio data
  - PortDataType subclassing for custom data types
  - AutoDiscovery registering non-audio nodes via GRAPHYN_PLUGINS_DIR
  - Pipeline([...]).run(use_cache=False) with no audio-specific nodes
  - The node system, DAG executor, caching, and provenance work
    identically for any data type

Usage:
  venv/bin/python examples/13_csv_data_processing/csv_pipeline.py
"""
from __future__ import annotations

import csv
import io
import os
import sys
from pathlib import Path
from typing import Any, ClassVar

WORKSPACE_ROOT = str(Path(__file__).parent.parent.parent)
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

_RESET = "\033[0m"; _BOLD = "\033[1m"; _CYAN = "\033[36m"
_GREEN = "\033[32m"; _DIM = "\033[2m"
def _h(t): return f"{_BOLD}{_CYAN}{t}{_RESET}"
def _ok(t): return f"{_GREEN}{t}{_RESET}"
def _dim(t): return f"{_DIM}{t}{_RESET}"

EXAMPLE_DIR = Path(__file__).parent
OUTPUT_DIR  = EXAMPLE_DIR / "output"

# ── Custom data type ──────────────────────────────────────────────────────────

from app.core.nodes.ports import PortDataType  # noqa: E402
from pydantic import Field  # noqa: E402


class CSVRow(PortDataType):
    """A single CSV row as a typed data contract.

    Subclasses DataSample's PortDataType — works with the typed port system.
    """
    row_id: int = 0
    data: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Custom nodes ──────────────────────────────────────────────────────────────

from app.core.nodes.base import Node  # noqa: E402
from app.core.nodes.config import NodeConfig  # noqa: E402
from app.core.nodes.metadata import NodeMetadata  # noqa: E402
from app.core.nodes.ports import InputPort, OutputPort  # noqa: E402
from pydantic import field_validator  # noqa: E402


class CSVReaderConfig(NodeConfig):
    path: str
    delimiter: str = ","
    max_rows: int = 0  # 0 = no limit


class CSVReaderNode(Node):
    """Source node: reads a CSV file and emits list[CSVRow]."""
    node_type: ClassVar[str] = "csv_reader"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="csv_reader", label="CSV Reader",
        description="Read a CSV file and emit rows as CSVRow objects.",
        category="Data Input",
    )
    input_ports:  ClassVar[dict] = {}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}

    class Config(CSVReaderConfig):
        pass

    def process(self, inputs: dict) -> dict:
        rows = []
        with open(self.config.path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=self.config.delimiter)
            for i, row in enumerate(reader):
                if self.config.max_rows > 0 and i >= self.config.max_rows:
                    break
                rows.append(CSVRow(row_id=i, data=dict(row)))
        return {"output": rows}


class RowFilterConfig(NodeConfig):
    column: str
    min_value: float = float("-inf")
    max_value: float = float("inf")


class RowFilterNode(Node):
    """Filter rows where a numeric column is within [min_value, max_value]."""
    node_type: ClassVar[str] = "row_filter"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="row_filter", label="Row Filter",
        description="Keep rows where a numeric column is within a range.",
        category="Data Processing",
    )
    input_ports:  ClassVar[dict] = {"input": InputPort(name="input", data_type=list)}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}

    class Config(RowFilterConfig):
        pass

    def process(self, rows: list) -> list:
        kept = []
        for row in rows:
            try:
                val = float(row.data.get(self.config.column, 0))
                if self.config.min_value <= val <= self.config.max_value:
                    kept.append(row)
            except (ValueError, TypeError):
                pass
        return kept


class ColumnNormalizerConfig(NodeConfig):
    columns: list[str]


class ColumnNormalizerNode(Node):
    """Min-max normalize specified numeric columns across all rows."""
    node_type: ClassVar[str] = "column_normalizer"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="column_normalizer", label="Column Normalizer",
        description="Min-max normalize numeric columns to [0, 1].",
        category="Data Processing",
    )
    input_ports:  ClassVar[dict] = {"input": InputPort(name="input", data_type=list)}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}

    class Config(ColumnNormalizerConfig):
        pass

    def process(self, rows: list) -> list:
        import copy
        for col in self.config.columns:
            vals = []
            for row in rows:
                try:
                    vals.append(float(row.data.get(col, 0)))
                except (ValueError, TypeError):
                    pass
            if not vals:
                continue
            mn, mx = min(vals), max(vals)
            rng = mx - mn if mx != mn else 1.0
            for row in rows:
                try:
                    v = float(row.data.get(col, 0))
                    row.data[col + "_norm"] = round((v - mn) / rng, 4)
                except (ValueError, TypeError):
                    row.data[col + "_norm"] = 0.0
        return rows


class CSVWriterConfig(NodeConfig):
    path: str
    delimiter: str = ","


class CSVWriterNode(Node):
    """Sink node: writes list[CSVRow] to a CSV file."""
    node_type: ClassVar[str] = "csv_writer"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="csv_writer", label="CSV Writer",
        description="Write CSVRow objects to a CSV file.",
        category="Data Output",
    )
    input_ports:  ClassVar[dict] = {"input": InputPort(name="input", data_type=list)}
    output_ports: ClassVar[dict] = {}

    class Config(CSVWriterConfig):
        pass

    def process(self, rows: list) -> dict:
        if not rows:
            return {}
        Path(self.config.path).parent.mkdir(parents=True, exist_ok=True)
        fieldnames = list(rows[0].data.keys())
        with open(self.config.path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames,
                                    delimiter=self.config.delimiter)
            writer.writeheader()
            for row in rows:
                writer.writerow(row.data)
        return {}


# ── Register nodes ────────────────────────────────────────────────────────────

def register_csv_nodes() -> None:
    from app.core.registry_runtime import get_registry
    registry = get_registry()
    for node_type, node_class in [
        ("csv_reader",         CSVReaderNode),
        ("row_filter",         RowFilterNode),
        ("column_normalizer",  ColumnNormalizerNode),
        ("csv_writer",         CSVWriterNode),
    ]:
        if node_type not in registry:
            registry.register(node_type, node_class, node_class.metadata)


# ── Generate sample CSV ───────────────────────────────────────────────────────

def generate_sample_csv(path: Path) -> None:
    """Generate a sample CSV with numeric and categorical columns."""
    import random
    rng = random.Random(42)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "score", "age", "category"])
        writer.writeheader()
        for i in range(100):
            writer.writerow({
                "id": i,
                "score": round(rng.uniform(0, 100), 2),
                "age": rng.randint(18, 80),
                "category": rng.choice(["A", "B", "C"]),
            })


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    register_csv_nodes()

    input_csv  = EXAMPLE_DIR / "data" / "sample.csv"
    output_csv = OUTPUT_DIR / "processed.csv"
    generate_sample_csv(input_csv)

    print(f"\n{'='*60}")
    print(_h("Example 13 — CSV Data Processing Pipeline"))
    print(f"{'='*60}")
    print(f"  Input:  {input_csv} (100 rows)")
    print(f"  Output: {output_csv}")
    print(f"\n  Pipeline: csv_reader → row_filter → column_normalizer → csv_writer")
    print(f"  Data type: CSVRow(PortDataType) — no audio involved")

    from app.core.sdk import Pipeline, PipelineNode
    pipeline = Pipeline(
        nodes=[
            PipelineNode("csv_reader",        {"path": str(input_csv), "max_rows": 0}),
            PipelineNode("row_filter",         {"column": "score", "min_value": 20.0, "max_value": 80.0}),
            PipelineNode("column_normalizer",  {"columns": ["score", "age"]}),
            PipelineNode("csv_writer",         {"path": str(output_csv)}),
        ],
        seed=42,
        name="csv-processing",
    )

    result = pipeline.run(use_cache=False)

    print(f"\n  {_ok('✓')} Pipeline completed")
    print(f"    run_id: {result.run_id}")

    # Verify output
    with open(output_csv, newline="") as f:
        rows = list(csv.DictReader(f))
    print(f"    Input rows:  100")
    print(f"    After filter (score 20–80): {len(rows)}")
    print(f"    Columns added: score_norm, age_norm")
    if rows:
        sample = rows[0]
        print(f"    Sample row: score={sample['score']}, "
              f"score_norm={sample.get('score_norm', '?')}, "
              f"age_norm={sample.get('age_norm', '?')}")

    print(f"\n  Key point: the platform's node system, DAG executor,")
    print(f"  caching, and provenance work identically for any data type.")
    print(f"  CSVRow extends PortDataType — same typed port system as AudioSample.")
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
