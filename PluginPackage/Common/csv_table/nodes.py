"""CsvTableNode — read/write CSV to path as list[dict]."""
from __future__ import annotations

import csv
import importlib
import logging
from pathlib import Path
from typing import Any, ClassVar

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("csv_table.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

CsvTableResult = _types.CsvTableResult
log = logging.getLogger(__name__)


def _rows_of(value: Any) -> list[dict]:
    if value is None:
        return []
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        if isinstance(dumped, dict) and isinstance(dumped.get("rows"), list):
            value = dumped["rows"]
        elif isinstance(dumped, dict) and isinstance(dumped.get("data"), list):
            value = dumped["data"]
        elif isinstance(dumped, list):
            value = dumped
    if isinstance(value, dict):
        if isinstance(value.get("rows"), list):
            value = value["rows"]
        elif isinstance(value.get("data"), list):
            value = value["data"]
        else:
            return [value]
    if not isinstance(value, list):
        return [{"value": value}]
    rows = []
    for item in value:
        if isinstance(item, dict):
            rows.append({str(k): v for k, v in item.items()})
        elif hasattr(item, "model_dump"):
            dumped = item.model_dump()
            rows.append(dumped if isinstance(dumped, dict) else {"value": dumped})
        else:
            rows.append({"value": item})
    return rows


class CsvTableNode(Node):
    node_type: ClassVar[str] = "csv_table"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="csv_table",
        label="CSV Table",
        description="Read or write a CSV file as list[dict] rows.",
        category="Output",
        version="1.0.0",
        tags=["csv", "table", "workflow", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )
    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object | None, required=False, description="list[dict] for write"),
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="CsvTableResult"),
    }

    class Config(NodeConfig):
        operation: str = "read"  # read | write
        path: str = ""
        encoding: str = "utf-8"

    def process(self, inputs):
        payload = inputs.get("input") if isinstance(inputs, dict) else inputs
        op = (self.config.operation or "read").strip().lower()
        path = Path(self.config.path or "")
        if not str(path):
            raise RuntimeError("CsvTableNode: config.path is required.")
        encoding = self.config.encoding or "utf-8"
        if op == "write":
            rows = _rows_of(payload)
            path.parent.mkdir(parents=True, exist_ok=True)
            fieldnames: list[str] = []
            for row in rows:
                for k in row.keys():
                    if k not in fieldnames:
                        fieldnames.append(k)
            if not fieldnames:
                fieldnames = ["value"]
            with path.open("w", encoding=encoding, newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                for row in rows:
                    writer.writerow({k: row.get(k, "") for k in fieldnames})
            return {"output": CsvTableResult(
                path=str(path),
                operation="write",
                rows=rows,
                row_count=len(rows),
                metadata={"columns": fieldnames},
            )}
        if not path.exists():
            raise RuntimeError(f"CsvTableNode: CSV path not found: {path}")
        with path.open("r", encoding=encoding, newline="") as fh:
            reader = csv.DictReader(fh)
            rows = [dict(r) for r in reader]
        return {"output": CsvTableResult(
            path=str(path),
            operation="read",
            rows=rows,
            row_count=len(rows),
            metadata={"columns": list(rows[0].keys()) if rows else []},
        )}
