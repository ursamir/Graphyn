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

    Req 4.4
    """
    import yaml
    from app.core.ir.yaml_shim import yaml_config_to_ir
    from app.core.ir.loader import dump_ir_to_file

    yaml_p = Path(yaml_path)

    # Derive output path if not provided (Req 4.4.3)
    if output_path is None:
        # Handle both .yaml and .yml extensions
        stem = yaml_p.stem
        output_path = str(yaml_p.parent / f"{stem}.graph.json")

    # Read and convert (Req 4.4.4)
    with open(yaml_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    graph = yaml_config_to_ir(raw)
    dump_ir_to_file(graph, output_path)  # Req 4.4.4

    return output_path
