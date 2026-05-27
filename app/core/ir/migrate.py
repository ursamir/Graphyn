# app/core/ir/migrate.py
"""
Bounded Context:  BC1 — Graph Language
Responsibility:   CLI-facing migration utility. Converts YAML pipeline config
                  files to IR JSON files on disk.
Owns:             migrate_yaml_to_ir_file() — reads YAML, converts via
                  yaml_shim, writes .graph.json.
Public Surface:   migrate_yaml_to_ir_file(yaml_path, output_path) → str
Must NOT:         Import from app.domain, app.api, or app.models.
                  Must not emit DeprecationWarning — this is the migration
                  tool itself, not a deprecated call site.
Dependencies:     app.core.ir.{yaml_shim, loader}, yaml, stdlib (pathlib).
Reason To Change: Output format changes, or new migration source formats
                  (e.g. JSON v0 → v1) are added.

No DeprecationWarning is emitted here. Req 4.4
"""
from __future__ import annotations

from pathlib import Path

import yaml
from app.core.ir.yaml_shim import yaml_config_to_ir
from app.core.ir.loader import dump_ir_to_file


def migrate_yaml_to_ir_file(
    yaml_path: str,
    output_path: str | None = None,
) -> str:
    """Convert a YAML pipeline config file to an IR JSON file.

    Args:
        yaml_path: Path to the YAML pipeline config file.
        output_path: Optional destination path for the IR JSON file.
            When None, derives the output path by replacing the .yaml/.yml
            extension with .graph.json (Req 4.4.3).

    Returns:
        The path of the written IR JSON file (Req 4.4.2).

    Raises:
        FileNotFoundError: If ``yaml_path`` does not exist.
        ValueError: If the YAML file is empty, contains only comments, or
            cannot be parsed as valid YAML.

    Req 4.4
    """
    yaml_p = Path(yaml_path)

    # Derive output path if not provided (Req 4.4.3)
    if output_path is None:
        # Handle both .yaml and .yml extensions
        stem = yaml_p.stem
        output_path = str(yaml_p.parent / f"{stem}.graph.json")

    # Ensure the output parent directory exists
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Read and convert (Req 4.4.4)
    with open(yaml_path, "r", encoding="utf-8") as f:
        try:
            raw = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML in '{yaml_path}': {exc}") from exc

    if raw is None:
        raise ValueError(
            f"YAML file '{yaml_path}' is empty or contains only comments."
        )

    graph = yaml_config_to_ir(raw)

    # Atomic-safe write: clean up partial output on failure (Req 4.4.4)
    try:
        dump_ir_to_file(graph, output_path)
    except Exception:
        Path(output_path).unlink(missing_ok=True)
        raise

    return output_path
