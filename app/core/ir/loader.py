"""IR Loader — serialization, deserialization, and version validation.

No imports from app/core/pipeline.py, app/core/nodes/, or app/core/sdk.py.
Only pydantic, json, and the Python standard library.

Req 1.7 – 1.9
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import pydantic

from app.core.ir.models import GraphIR

# ── Version constant ──────────────────────────────────────────────────────────

CURRENT_IR_VERSION: str = "1.1"
"""The IR schema version implemented in this phase.

Format: "<major>.<minor>". The loader rejects documents whose major version
differs from this constant's major component.

Phase 3 bumped the minor version from 0 to 1 to reflect the addition of
``IREdge.condition`` and ``IRNode.event_trigger`` fields. Both ``"1.0"`` and
``"1.1"`` documents are accepted; ``"1.0"`` documents are treated as ``"1.1"``
with all new fields set to their defaults (``None``).
"""

SUPPORTED_MAJOR: int = 1
SUPPORTED_MINOR_MAX: int = 1  # accepts 1.0 and 1.1

# ── Error types ───────────────────────────────────────────────────────────────


class IRVersionError(ValueError):
    """Raised when a GraphIR document has an incompatible major schema version.

    Req 1.7.3, 1.7.5
    """


class IRValidationError(ValueError):
    """Raised when a GraphIR document fails structural validation beyond Pydantic.

    Reserved for future use — e.g. semantic checks such as detecting unreachable
    nodes, port-type mismatches at the IR level, or schema constraints that
    Pydantic field validators cannot express. Currently not raised by the loader;
    callers may raise it from custom validation passes.

    Req 1.9.3, 1.9.4
    """


# ── Version validation ────────────────────────────────────────────────────────


def _check_version(schema_version: str) -> None:
    """Validate schema_version against CURRENT_IR_VERSION.

    Accepts any document whose major version matches ``SUPPORTED_MAJOR`` and
    whose minor version is between 0 and ``SUPPORTED_MINOR_MAX`` (inclusive).
    ``"1.0"`` documents are treated as ``"1.1"`` — missing ``condition`` and
    ``event_trigger`` fields default to ``None`` via Pydantic field defaults.

    Raises:
        IRVersionError: if the major version component differs.

    Emits:
        UserWarning: if the minor version component is greater than SUPPORTED_MINOR_MAX.
    """
    try:
        doc_major, doc_minor = (int(x) for x in schema_version.split("."))
    except (ValueError, AttributeError) as exc:
        raise IRVersionError(
            f"Cannot parse schema_version '{schema_version}': {exc}"
        ) from exc

    if doc_major != SUPPORTED_MAJOR:
        raise IRVersionError(
            f"IR document schema_version '{schema_version}' is incompatible with "
            f"the supported version '{CURRENT_IR_VERSION}'. "
            f"Major version mismatch: document={doc_major}, supported={SUPPORTED_MAJOR}. "
            "Run 'graphyn migrate --config <path>' to convert to the current format."
        )

    if doc_minor > SUPPORTED_MINOR_MAX:
        warnings.warn(
            f"IR document schema_version '{schema_version}' has a higher minor version "
            f"than the supported '{CURRENT_IR_VERSION}'. "
            "Some features may not be available. Consider upgrading the platform.",
            UserWarning,
            stacklevel=3,
        )


# ── Public API ────────────────────────────────────────────────────────────────


def load_ir(data: dict[str, Any]) -> GraphIR:
    """Validate and return a GraphIR from a JSON-compatible dict.

    Performs:
    1. Pydantic schema validation (raises pydantic.ValidationError on failure)
    2. Schema version check (raises IRVersionError on major mismatch)

    Args:
        data: A JSON-compatible dict, typically from json.loads() or yaml.safe_load().

    Returns:
        A validated GraphIR object.

    Raises:
        pydantic.ValidationError: if the dict does not conform to the GraphIR schema.
        IRVersionError: if the major version is incompatible.

    Req 1.8.1
    """
    graph = GraphIR.model_validate(data)
    _check_version(graph.schema_version)
    return graph


def load_ir_from_file(path: str) -> GraphIR:
    """Read a JSON file and return a validated GraphIR.

    Args:
        path: Path to the IR JSON file.

    Returns:
        A validated GraphIR object.

    Raises:
        FileNotFoundError: if the file does not exist (Req 1.8.5).
        json.JSONDecodeError: if the file contains invalid JSON (Req 1.8.6).
        pydantic.ValidationError: if the JSON does not conform to GraphIR (Req 1.8.7).
        IRVersionError: if the major version is incompatible.

    Req 1.8.2
    """
    p = Path(path)
    if not p.is_file():
        if p.is_dir():
            raise FileNotFoundError(
                f"IR JSON path is a directory, not a file: {path}"
            )
        raise FileNotFoundError(f"IR JSON file not found: {path}")

    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)  # raises json.JSONDecodeError on invalid JSON

    return load_ir(data)


def dump_ir(graph: GraphIR) -> dict[str, Any]:
    """Return a JSON-serializable dict from a GraphIR.

    Uses model_dump(mode="json") to ensure all types are JSON-compatible.

    Args:
        graph: A GraphIR object.

    Returns:
        A JSON-serializable dict.

    Req 1.8.3
    """
    return graph.model_dump(mode="json")


def dump_ir_to_file(graph: GraphIR, path: str) -> None:
    """Write a GraphIR to a JSON file with 2-space indentation.

    Args:
        graph: A GraphIR object.
        path: Destination file path. Parent directories must exist.

    Req 1.8.4
    """
    data = dump_ir(graph)
    p = Path(path)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")  # trailing newline for POSIX compliance
