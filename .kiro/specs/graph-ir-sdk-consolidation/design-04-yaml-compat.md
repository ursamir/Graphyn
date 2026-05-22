# Design 04 — YAML Compatibility Shim, Migration Utility, CLI and API Updates

## Overview

This document covers the YAML compatibility layer (`app/core/ir/yaml_shim.py`), the migration utility (`app/core/ir/migrate.py`), and the updates to the CLI (`app/cli/main.py`) and REST API (`app/api/routers/pipelines.py`) to support IR JSON as the canonical input format while keeping YAML working via a deprecated path.

**Requirements addressed:** Req 4.1 – 4.9

---

## Design Rationale

### Zero-breakage migration

All existing YAML configs continue to work. The shim converts YAML → `GraphIR` transparently. The only observable change is a `DeprecationWarning` emitted when YAML is loaded.

### Separation of concerns

- `yaml_config_to_ir()` — pure conversion, no warnings, no file I/O.
- `load_yaml_with_deprecation()` — file I/O + warning + conversion.
- `migrate_yaml_to_ir_file()` — file I/O + conversion + write, no warning.

This separation allows `run_pipeline()` to call `yaml_config_to_ir()` without double-warning, while `Pipeline.from_yaml()` and `load_yaml_with_deprecation()` emit the warning at the right call site.

---

## `app/core/ir/yaml_shim.py`

### `yaml_config_to_ir(raw: dict) -> GraphIR`

Converts a raw YAML config dict (as produced by `yaml.safe_load`) to a `GraphIR` object.

**Supported formats:**

1. **Legacy linear format** (no `edges` key): nodes are auto-chained `output → input`.
2. **Explicit-edge format** (has `edges` key): edges are mapped directly.

**ID derivation:** `f"{node_type}_{index}"` (Req 4.1.5).

```python
# app/core/ir/yaml_shim.py
"""YAML compatibility shim — converts legacy YAML pipeline configs to GraphIR.

No DeprecationWarning is emitted here. That is the responsibility of
load_yaml_with_deprecation() and run_pipeline() (the legacy shim).
"""
from __future__ import annotations

import warnings
from typing import Any

from app.core.ir.loader import CURRENT_IR_VERSION
from app.core.ir.models import GraphIR, IREdge, IRMetadata, IRNode


def yaml_config_to_ir(raw: dict[str, Any]) -> GraphIR:
    """Convert a raw YAML config dict to a GraphIR object.

    Supports both the legacy linear format (no 'edges' key, auto-chained)
    and the explicit-edge format.

    Args:
        raw: A dict as produced by yaml.safe_load() of a pipeline YAML file.

    Returns:
        A validated GraphIR object.

    Req 4.1
    """
    pipeline = raw.get("pipeline", {})
    seed = pipeline.get("seed", 0)
    name = pipeline.get("name", "pipeline")  # Req 4.1.8
    raw_nodes = pipeline.get("nodes", [])

    # Build IRNode list
    ir_nodes: list[IRNode] = []
    for i, n in enumerate(raw_nodes):
        node_type = n["type"]
        node_id = n.get("id") or f"{node_type}_{i}"  # Req 4.1.5
        ir_nodes.append(IRNode(
            id=node_id,
            node_type=node_type,
            config=n.get("config", {}),
        ))

    # Build IREdge list
    raw_edges = pipeline.get("edges")
    if raw_edges:
        # Explicit-edge format (Req 4.1.3, 4.1.6)
        ir_edges: list[IREdge] = []
        for e in raw_edges:
            # Support both dict format and list format
            if isinstance(e, dict) and "from" in e and "to" in e:
                # List format: {"from": [src_id, src_port], "to": [dst_id, dst_port]}
                src_id, src_port = e["from"][0], e["from"][1]
                dst_id, dst_port = e["to"][0], e["to"][1]
            elif isinstance(e, dict) and "src_id" in e:
                # Dict format: {"src_id": ..., "src_port": ..., "dst_id": ..., "dst_port": ...}
                src_id = e["src_id"]
                src_port = e["src_port"]
                dst_id = e["dst_id"]
                dst_port = e["dst_port"]
            else:
                raise ValueError(f"Unrecognized edge format: {e!r}")
            ir_edges.append(IREdge(
                src_id=src_id,
                src_port=src_port,
                dst_id=dst_id,
                dst_port=dst_port,
            ))
    else:
        # Legacy linear format: auto-chain output → input (Req 4.1.3)
        ir_edges = [
            IREdge(
                src_id=ir_nodes[i].id,
                src_port="output",
                dst_id=ir_nodes[i + 1].id,
                dst_port="input",
            )
            for i in range(len(ir_nodes) - 1)
        ]

    return GraphIR(
        schema_version=CURRENT_IR_VERSION,  # Req 4.1.7
        metadata=IRMetadata(
            name=name,
            seed=seed,
        ),
        nodes=ir_nodes,
        edges=ir_edges,
    )


def load_yaml_with_deprecation(path: str) -> GraphIR:
    """Read a YAML file, convert to GraphIR, and emit a DeprecationWarning.

    Args:
        path: Path to the YAML pipeline config file.

    Returns:
        A validated GraphIR object.

    Req 4.2
    """
    import yaml

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    warnings.warn(
        f"YAML pipeline configs are deprecated. "
        f"Loading: {path}. "
        f"Run 'audiobuilder migrate --config {path}' to convert to IR JSON.",
        DeprecationWarning,
        stacklevel=2,  # Req 4.2.3 — points to the caller's code
    )

    return yaml_config_to_ir(raw)
```

---

## `app/core/ir/migrate.py`

### `migrate_yaml_to_ir_file(yaml_path, output_path=None) -> str`

Programmatic migration function (Req 4.4). Does NOT emit a `DeprecationWarning` (Req 4.4.5).

```python
# app/core/ir/migrate.py
"""Migration utility — converts YAML pipeline configs to IR JSON files.

No DeprecationWarning is emitted here. This is the migration tool itself.
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
        stem = yaml_p.stem
        if stem.endswith(".yaml"):
            stem = stem[:-5]
        elif stem.endswith(".yml"):
            stem = stem[:-4]
        output_path = str(yaml_p.parent / f"{stem}.graph.json")

    # Read and convert (Req 4.4.4)
    with open(yaml_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    graph = yaml_config_to_ir(raw)
    dump_ir_to_file(graph, output_path)  # Req 4.4.4

    return output_path
```

---

## CLI Updates (`app/cli/main.py`)

### New `migrate` subcommand (Req 4.3)

```python
def cmd_migrate(args):
    """Convert a YAML pipeline config to an IR JSON file."""
    from app.core.ir.migrate import migrate_yaml_to_ir_file

    yaml_path = args.config
    output_path = getattr(args, "output", None)

    if not os.path.isfile(yaml_path):
        print(f"Error: config file not found: {yaml_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(yaml_path) as f:
            import yaml as _yaml
            _yaml.safe_load(f)  # validate YAML syntax first
    except Exception as exc:
        print(f"YAML parse error: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        result_path = migrate_yaml_to_ir_file(yaml_path, output_path)
        print(f"✓ Migrated {yaml_path} → {result_path}")
        sys.exit(0)
    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        sys.exit(1)
```

Parser registration:

```python
# In build_parser():
migrate_parser = subparsers.add_parser(
    "migrate",
    help="Convert a YAML pipeline config to IR JSON",
    description="Convert a YAML pipeline config file to the canonical IR JSON format.",
)
migrate_parser.add_argument(
    "--config",
    required=True,
    metavar="PATH",
    help="Path to the YAML pipeline config file to convert",
)
migrate_parser.add_argument(
    "--output",
    default=None,
    metavar="PATH",
    help="Output path for the IR JSON file (default: same dir, .graph.json extension)",
)
migrate_parser.set_defaults(func=cmd_migrate)
```

### Updated `run` subcommand (Req 4.5)

The `run` command gains a `--graph` argument for IR JSON input. `--config` and `--graph` are mutually exclusive.

```python
def cmd_run(args):
    """Execute a pipeline synchronously and print logs to stdout."""
    from app.core.logger import PipelineLogger

    # Validate mutual exclusivity (Req 4.5.5)
    has_graph = getattr(args, "graph", None) is not None
    has_config = getattr(args, "config", None) is not None

    if has_graph and has_config:
        print("Error: --graph and --config are mutually exclusive", file=sys.stderr)
        sys.exit(1)

    if not has_graph and not has_config:
        print("Error: one of --graph or --config is required", file=sys.stderr)
        sys.exit(1)

    if has_graph:
        # IR JSON path (Req 4.5.3)
        from app.core.ir.loader import load_ir_from_file
        from app.core.pipeline import run_pipeline_ir

        graph_path = args.graph
        if not os.path.isfile(graph_path):
            print(f"Error: graph file not found: {graph_path}", file=sys.stderr)
            sys.exit(1)

        try:
            graph = load_ir_from_file(graph_path)
        except Exception as exc:
            print(f"Error loading IR graph: {exc}", file=sys.stderr)
            sys.exit(1)

        # Apply seed override (Req 4.5.7)
        if args.seed is not None:
            from app.core.ir.models import GraphIR, IRMetadata
            graph = GraphIR(
                schema_version=graph.schema_version,
                metadata=IRMetadata(
                    name=graph.metadata.name,
                    seed=args.seed,
                    description=graph.metadata.description,
                    created_at=graph.metadata.created_at,
                    tags=graph.metadata.tags,
                ),
                nodes=graph.nodes,
                edges=graph.edges,
                parameters=graph.parameters,
            )

        logger = _make_stdout_logger(PipelineLogger)
        try:
            run_pipeline_ir(graph, logger=logger)
        except Exception as exc:
            print(f"\nPipeline failed: {exc}", file=sys.stderr)
            sys.exit(1)

    else:
        # YAML path (Req 4.5.4) — existing behavior preserved
        from app.core.ir.yaml_shim import load_yaml_with_deprecation
        from app.core.pipeline import run_pipeline_ir

        config_path = args.config
        if not os.path.isfile(config_path):
            print(f"Error: config file not found: {config_path}", file=sys.stderr)
            sys.exit(1)

        try:
            graph = load_yaml_with_deprecation(config_path)
        except Exception as exc:
            print(f"Error loading YAML config: {exc}", file=sys.stderr)
            sys.exit(1)

        # Apply seed override (Req 4.5.7)
        if args.seed is not None:
            from app.core.ir.models import GraphIR, IRMetadata
            graph = GraphIR(
                schema_version=graph.schema_version,
                metadata=IRMetadata(
                    name=graph.metadata.name,
                    seed=args.seed,
                    description=graph.metadata.description,
                    created_at=graph.metadata.created_at,
                    tags=graph.metadata.tags,
                ),
                nodes=graph.nodes,
                edges=graph.edges,
                parameters=graph.parameters,
            )

        logger = _make_stdout_logger(PipelineLogger)
        try:
            run_pipeline_ir(graph, logger=logger)
        except Exception as exc:
            print(f"\nPipeline failed: {exc}", file=sys.stderr)
            sys.exit(1)

    sys.exit(0)
```

**Note on `_make_stdout_logger`:** The existing `StdoutLogger` inner class in `cmd_run` is extracted to a helper function `_make_stdout_logger(base_class)` to avoid code duplication between the `--graph` and `--config` paths.

### Updated `validate` subcommand (Req 4.6)

```python
def cmd_validate(args):
    """Validate a pipeline YAML file or IR JSON file."""
    has_graph = getattr(args, "graph", None) is not None
    has_config = getattr(args, "config", None) is not None

    if has_graph:
        # IR JSON validation (Req 4.6.3)
        from app.core.ir.loader import load_ir_from_file, IRVersionError

        graph_path = args.graph
        if not os.path.isfile(graph_path):
            print(f"Error: graph file not found: {graph_path}", file=sys.stderr)
            sys.exit(1)

        try:
            graph = load_ir_from_file(graph_path)
            print(f"✓ Valid IR graph — {len(graph.nodes)} node(s):")
            for i, node in enumerate(graph.nodes):
                print(f"  [{i}] {node.id} ({node.node_type})")
            sys.exit(0)
        except IRVersionError as exc:
            print(f"✗ Version error: {exc}", file=sys.stderr)
            sys.exit(1)
        except Exception as exc:
            print(f"✗ Validation failed: {exc}", file=sys.stderr)
            sys.exit(1)

    else:
        # YAML validation (Req 4.6.4) — existing behavior preserved
        from app.core.validation import validate_pipeline
        from app.core.registry_runtime import get_registry

        config_path = args.config
        if not os.path.isfile(config_path):
            print(f"Error: config file not found: {config_path}", file=sys.stderr)
            sys.exit(1)

        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            print(f"YAML parse error: {exc}", file=sys.stderr)
            sys.exit(1)

        try:
            registry = get_registry()
            nodes = validate_pipeline(config, registry)
            print(f"✓ Valid pipeline — {len(nodes)} node(s):")
            for i, node in enumerate(nodes):
                print(f"  [{i}] {node['type']}")
            sys.exit(0)
        except ValueError as exc:
            print(f"✗ Validation failed: {exc}", file=sys.stderr)
            sys.exit(1)
```

### Updated parser for `run` and `validate`

```python
# run command — add --graph, make --config optional
run_parser.add_argument(
    "--config",
    required=False,  # Changed from required=True
    default=None,
    metavar="PATH",
    help="Path to the pipeline YAML config file (deprecated)",
)
run_parser.add_argument(
    "--graph",
    required=False,
    default=None,
    metavar="PATH",
    help="Path to the IR JSON graph file (canonical format)",
)

# validate command — add --graph, make --config optional
validate_parser.add_argument(
    "--config",
    required=False,
    default=None,
    metavar="PATH",
    help="Path to the pipeline YAML config file",
)
validate_parser.add_argument(
    "--graph",
    required=False,
    default=None,
    metavar="PATH",
    help="Path to the IR JSON graph file",
)
```

---

## REST API Updates (`app/api/routers/pipelines.py`)

### Updated request models

```python
from pydantic import BaseModel
from typing import Any

class PipelinePayload(BaseModel):
    """Legacy YAML payload — preserved for backward compatibility."""
    yaml: str

class IRPipelinePayload(BaseModel):
    """IR JSON payload — canonical format.
    
    The presence of schema_version distinguishes this from YAML payloads (Req 4.7.5).
    """
    schema_version: str
    metadata: dict[str, Any]
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]] = []
    parameters: dict[str, Any] = {}
```

### Updated `/validate` endpoint (Req 4.8)

```python
@router.post("/validate", summary="Validate a pipeline YAML or IR JSON")
def validate_pipeline_config(request: Request, payload: dict = Body(...)):
    """Validate a pipeline config without executing it.
    
    Accepts both YAML format ({"yaml": "..."}) and IR JSON format
    ({"schema_version": "1.0", "metadata": {...}, "nodes": [...], "edges": [...]}).
    """
    from fastapi.responses import JSONResponse

    is_ir = "schema_version" in payload  # Req 4.7.5

    if is_ir:
        # IR JSON validation (Req 4.8.1, 4.8.3, 4.8.4)
        try:
            from app.core.ir.loader import load_ir
            graph = load_ir(payload)
            return {"valid": True, "node_count": len(graph.nodes)}
        except Exception as exc:
            return JSONResponse(
                status_code=422,
                content={"valid": False, "error": str(exc)},
            )
    else:
        # YAML validation (Req 4.8.2, 4.8.5)
        yaml_str = payload.get("yaml", "")
        try:
            config = yaml.safe_load(yaml_str)
        except yaml.YAMLError as exc:
            return {"valid": False, "error": f"YAML parse error: {exc}"}

        registry = get_registry()
        try:
            validate_pipeline(config, registry)
        except ValueError as exc:
            return {"valid": False, "error": str(exc)}

        headers = {"X-Deprecation-Warning": "YAML pipeline input is deprecated. Use IR JSON format."}
        return JSONResponse(
            content={"valid": True},
            headers=headers,
        )
```

### Updated `/run` endpoint (Req 4.7)

```python
@router.post("/run", summary="Run a pipeline and stream log events")
def run_pipeline_stream(request: Request, payload: dict = Body(...)):
    """Execute a pipeline and stream NDJSON log events.
    
    Accepts both YAML format and IR JSON format.
    """
    from fastapi.responses import StreamingResponse, Response
    import threading
    from queue import Queue

    is_ir = "schema_version" in payload  # Req 4.7.5

    queue: Queue = Queue()
    logger = PipelineLogger(queue=queue)
    deprecation_header = None

    if is_ir:
        # IR JSON path (Req 4.7.1, 4.7.3)
        from app.core.ir.loader import load_ir
        from app.core.pipeline import run_pipeline_ir

        try:
            graph = load_ir(payload)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        def _run():
            try:
                run_pipeline_ir(graph, logger=logger)
                queue.put({"type": "done", "timestamp": _ts()})
            except Exception as exc:
                queue.put({"type": "error", "timestamp": _ts(),
                           "error_type": type(exc).__name__, "message": str(exc)})
            finally:
                queue.put(None)

    else:
        # YAML path (Req 4.7.2, 4.7.4)
        from app.core.ir.yaml_shim import yaml_config_to_ir
        from app.core.pipeline import run_pipeline_ir

        yaml_str = payload.get("yaml", "")
        try:
            raw = yaml.safe_load(yaml_str)
            graph = yaml_config_to_ir(raw)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        deprecation_header = "YAML pipeline input is deprecated. Use IR JSON format."

        def _run():
            try:
                run_pipeline_ir(graph, logger=logger)
                queue.put({"type": "done", "timestamp": _ts()})
            except Exception as exc:
                queue.put({"type": "error", "timestamp": _ts(),
                           "error_type": type(exc).__name__, "message": str(exc)})
            finally:
                queue.put(None)

    threading.Thread(target=_run, daemon=True).start()

    def stream():
        while True:
            item = queue.get()
            if item is None:
                break
            yield json.dumps(item) + "\n"

    headers = {}
    if deprecation_header:
        headers["X-Deprecation-Warning"] = deprecation_header

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        headers=headers,
    )
```

**Note:** The existing `PipelinePayload` model and `run_pipeline_stream(payload: PipelinePayload)` signature is replaced with `payload: dict = Body(...)` to accept both formats. The `schema_version` field distinguishes IR JSON from YAML (Req 4.7.5).

---

## YAML Format Support Matrix

| Format | `yaml_config_to_ir` | `load_yaml_with_deprecation` | `migrate_yaml_to_ir_file` |
|---|---|---|---|
| Legacy linear (no `edges`) | ✓ | ✓ | ✓ |
| Explicit-edge (`edges` list format) | ✓ | ✓ | ✓ |
| Explicit-edge (`edges` dict format) | ✓ | ✓ | ✓ |
| Named pipeline (`pipeline.name`) | ✓ | ✓ | ✓ |

---

## Deprecation Warning Message Format

The `DeprecationWarning` emitted by `load_yaml_with_deprecation()` follows this format (Req 4.2.2):

```
YAML pipeline configs are deprecated. Loading: {path}. Run 'audiobuilder migrate --config {path}' to convert to IR JSON.
```

The `X-Deprecation-Warning` response header for YAML API requests (Req 4.7.4, 4.8.5):

```
YAML pipeline input is deprecated. Use IR JSON format.
```

---

## Existing YAML Examples Compatibility (Req 4.9)

The existing YAML examples in `examples/` continue to work:

```bash
audiobuilder run --config examples/01_wake_word/pipeline.yaml
```

This emits a `DeprecationWarning` but does not fail. The warning is not treated as an error in the test suite (Req 4.9.2). To suppress the warning in tests:

```python
import warnings
with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    result = run_pipeline(config_path)
```

---

## Error Handling

| Scenario | Behavior | Req |
|---|---|---|
| YAML file not found (CLI migrate) | Print error, exit 1 | 4.3.5 |
| Invalid YAML (CLI migrate) | Print parse error, exit 1 | 4.3.6 |
| Both `--graph` and `--config` | Print mutual exclusivity error, exit 1 | 4.5.5 |
| Neither `--graph` nor `--config` | Print usage error, exit 1 | 4.5.6 |
| IR JSON with incompatible version (CLI validate) | Print `IRVersionError` message, exit 1 | 4.6.6 |
| IR JSON validation failure (API) | HTTP 422 with error body | 4.8.4 |

---

## References

- [req-04-yaml-compat.md](req-04-yaml-compat.md) — Requirements 4.1 – 4.9
- [design-01-graph-ir.md](design-01-graph-ir.md) — `GraphIR`, `IRNode`, `IREdge`
- [design-03-executor-wiring.md](design-03-executor-wiring.md) — `run_pipeline_ir()`
- [design-06-correctness-properties.md](design-06-correctness-properties.md) — YAML shim equivalence property
