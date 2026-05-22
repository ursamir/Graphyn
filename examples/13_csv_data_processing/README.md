# Example 13 — CSV Data Processing Pipeline

Proves the platform is **domain-agnostic** — not just an audio tool, but a general-purpose workflow execution platform. This example builds a pure data processing pipeline that reads, filters, normalizes, and writes CSV data. No audio involved.

---

## What This Demonstrates

- `DataSample` as a domain-agnostic base type for any data domain
- Subclassing `PortDataType` to create a custom `CSVRow` data type
- Writing custom nodes (`csv_reader`, `row_filter`, `column_normalizer`, `csv_writer`) that work with non-audio data
- The node system, DAG executor, caching, and provenance all work identically for any data type
- `Pipeline([...]).run()` with no audio-specific nodes

---

## Pipeline

```
csv_reader → row_filter → column_normalizer → csv_writer
```

| Node | What it does |
|---|---|
| `csv_reader` | Reads a CSV file and emits `list[CSVRow]` |
| `row_filter` | Keeps rows where a numeric column is within `[min_value, max_value]` |
| `column_normalizer` | Min-max normalizes specified columns to `[0, 1]`, adds `{col}_norm` fields |
| `csv_writer` | Writes the processed rows to a new CSV file |

---

## How to Run

```bash
venv/bin/python examples/13_csv_data_processing/csv_pipeline.py
```

The script generates a sample CSV with 100 rows (id, score, age, category), filters rows where `score` is between 20 and 80, normalizes `score` and `age` columns, and writes the result.

---

## Expected Output

```
============================================================
Example 13 — CSV Data Processing Pipeline
============================================================
  Input:  .../data/sample.csv (100 rows)
  Output: .../output/processed.csv

  Pipeline: csv_reader → row_filter → column_normalizer → csv_writer
  Data type: CSVRow(PortDataType) — no audio involved

  ✓ Pipeline completed
    run_id: aa99488e
    Input rows:  100
    After filter (score 20–80): 62
    Columns added: score_norm, age_norm
    Sample row: score=63.94, score_norm=0.7672, age_norm=0.0

  Key point: the platform's node system, DAG executor,
  caching, and provenance work identically for any data type.
  CSVRow extends PortDataType — same typed port system as AudioSample.
```

---

## Custom Data Type

```python
from app.core.nodes.ports import PortDataType
from pydantic import Field
from typing import Any

class CSVRow(PortDataType):
    """A single CSV row as a typed data contract."""
    row_id: int = 0
    data: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

`CSVRow` extends `PortDataType` — the same base class used by `AudioSample`, `FeatureArray`, and all other platform data types. The typed port system enforces data contracts across nodes.

---

## Custom Node Pattern

```python
from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from typing import ClassVar

class RowFilterNode(Node):
    node_type: ClassVar[str] = "row_filter"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="row_filter",
        label="Row Filter",
        description="Keep rows where a numeric column is within a range.",
        category="Data Processing",
    )
    input_ports:  ClassVar[dict] = {"input":  InputPort(name="input",  data_type=list)}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}

    class Config(NodeConfig):
        column: str
        min_value: float = float("-inf")
        max_value: float = float("inf")

    def process(self, rows: list) -> list:
        return [r for r in rows
                if self.config.min_value <= float(r.data.get(self.config.column, 0))
                <= self.config.max_value]
```

---

## Extending to Other Domains

The same pattern works for any data domain:

| Domain | Data Type | Example Nodes |
|---|---|---|
| Text/NLP | `TextSample(DataSample)` | `text_reader`, `tokenizer`, `sentiment_analyzer` |
| Images | `ImageSample(DataSample)` | `image_loader`, `resize`, `augment_image` |
| Time series | `TimeSeriesSample(DataSample)` | `ts_reader`, `resample_ts`, `feature_extract_ts` |
| Tabular | `CSVRow(PortDataType)` | `csv_reader`, `row_filter`, `normalizer` |
