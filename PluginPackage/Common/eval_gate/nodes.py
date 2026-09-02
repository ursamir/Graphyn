"""EvalGateNode — hard-fail the DAG when quality checks do not pass."""
from __future__ import annotations

import importlib
import logging
import re
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
        _types = importlib.import_module("eval_gate.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

EvalReport = _types.EvalReport

log = logging.getLogger(__name__)


class EvalGateError(RuntimeError):
    """Raised when eval_gate checks fail — stops DAG execution."""


def _as_mapping(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        if isinstance(value.get("data"), dict):
            return value["data"]
        return value
    data = getattr(value, "data", None)
    if isinstance(data, dict):
        return data
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        if isinstance(dumped.get("data"), dict):
            return dumped["data"]
        return dumped
    return {}


def _text_of(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            t = _text_of(item)
            if t:
                parts.append(t)
        return "\n".join(parts)
    if isinstance(value, dict):
        if "text" in value:
            return str(value.get("text") or "")
        if "data" in value:
            return str(value.get("data") or "")
        return ""
    return str(getattr(value, "text", "") or "")


class EvalGateNode(Node):
    """Fail the DAG on empty transcript, missing required keys, or residual PII."""

    node_type: ClassVar[str] = "eval_gate"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="eval_gate",
        label="Eval Gate",
        description=(
            "Hard-fail execution on empty transcript, missing schema keys, "
            "or residual PII regex matches. Passes input through on success."
        ),
        category="Quality",
        version="1.0.0",
        tags=["eval", "quality", "gate", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
        streaming_support=False,
        realtime_support=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=object,
            cardinality="single",
            required=True,
            description="Transcript, StructuredDocument, chunks, or any payload",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=object,
            description="Pass-through input on success",
        ),
        "report": OutputPort(
            name="report",
            data_type=object,
            description="EvalReport with checks and failures",
        ),
    }

    class Config(NodeConfig):
        check_empty_transcript: bool = True
        required_keys: list = []
        pii_regex: str = ""
        fail_if_empty_list: bool = True

    def process(self, inputs: dict) -> dict:
        value = (inputs or {}).get("input")
        failures: list[str] = []
        checks: list[str] = []

        if self.config.check_empty_transcript:
            checks.append("empty_transcript")
            text = _text_of(value)
            is_structured = isinstance(_as_mapping(value), dict) and (
                hasattr(value, "data") or (isinstance(value, dict) and "data" in value)
            )
            is_list = isinstance(value, list)
            if not is_structured and not is_list and not str(text).strip():
                failures.append("empty transcript")

        if self.config.fail_if_empty_list:
            checks.append("empty_list")
            if isinstance(value, list) and len(value) == 0:
                failures.append("empty list")

        keys = list(self.config.required_keys or [])
        if keys:
            checks.append("required_keys")
            mapping = _as_mapping(value)
            missing = [k for k in keys if k not in mapping or mapping.get(k) in (None, "")]
            if missing:
                failures.append("missing required keys: " + ", ".join(missing))

        pattern = (self.config.pii_regex or "").strip()
        if pattern:
            checks.append("pii_residual")
            try:
                rx = re.compile(pattern)
            except re.error as exc:
                raise EvalGateError(
                    f"EvalGateNode: invalid pii_regex {pattern!r}: {exc}"
                ) from exc
            blob = _text_of(value) or str(_as_mapping(value))
            if rx.search(blob or ""):
                failures.append(f"residual PII matched /{pattern}/")

        if failures:
            raise EvalGateError(
                "EvalGateNode: gate failed — " + "; ".join(failures)
            )

        report = EvalReport(passed=True, checks=checks, failures=[], metadata={})
        return {"output": value, "report": report}
