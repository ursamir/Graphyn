# app/cli/main.py
"""
Bounded Context:  CLI Interface
Responsibility:   Command-line entry point for pipeline execution, validation,
                  migration, inspection, node listing, and run history.
Owns:             Argument parsing, subcommand dispatch, CLI output formatting,
                  domain serializer registration at startup.
Public Surface:   main() — invoked as ``python -m app.cli.main`` or ``graphyn``.
Must NOT:         Contain pipeline execution logic — delegate to SDK/orchestrator.
                  Must not import app.api.
Dependencies:     argparse, app.core.sdk, app.core.ir, app.core.nodes.registry,
                  app.core.run_journal, app.core.config,
                  app.models.audio_artifact_serializer (startup hook).
Reason To Change: New CLI subcommand added, or output format changes.

Subcommands:
  run      --graph PATH [--seed N]    Execute a pipeline from IR JSON (canonical)
  run      --config PATH [--seed N]   Execute a pipeline from YAML (deprecated)
  validate --graph PATH               Validate an IR JSON graph file
  validate --config PATH              Validate a pipeline YAML file
  migrate  --config PATH [--output P] Convert YAML config to IR JSON
  inspect  --graph PATH               Inspect an IR JSON graph file (summary)
  nodes    [--category CAT]           List registered node types
  runs     list                       List recent pipeline runs
  runs     logs <run_id>              Print log entries for a run
"""

import argparse
import json
import os
import sys
import yaml


# ─── Helpers ──────────────────────────────────────────────────────────────────

from app.core.config import runs_dir as _runs_dir

# NEW-18 fix: do NOT resolve RUNS_DIR at module import time.
# GRAPHYN_PROJECT_DIR may be set after this module is imported (e.g. in tests).
# Each function that needs the runs directory calls _runs_dir() at call time.

# ── Domain serializer registration ───────────────────────────────────────────
# Register the AudioSampleHandler so that artifact_store, pipeline_cache, and
# checkpoint can serialize/deserialize AudioSample objects without importing
# domain models themselves (ARCH-2 fix).
from app.models.audio_artifact_serializer import register_audio_serializer as _reg_audio
_reg_audio()

# ── Registry initialization ───────────────────────────────────────────────────
# Explicitly populate the NodeRegistry singleton after the domain serializer
# is registered so node imports that reference AudioSample work correctly.
from app.core.nodes import initialize_registry as _init_registry
_init_registry()


def _list_runs(limit: int = 50):
    """Return a list of run metadata dicts sorted by created_at descending.

    Reads at most ``limit`` entries to avoid O(n) file reads on large workspaces.
    Pass ``limit=0`` to read all entries.
    """
    runs_dir_path = str(_runs_dir())
    if not os.path.isdir(runs_dir_path):
        return []

    runs = []
    try:
        entries = list(os.scandir(runs_dir_path))
    except OSError:
        return []

    # Sort by mtime descending so we read the most recent entries first
    entries.sort(key=lambda e: e.stat().st_mtime, reverse=True)
    if limit > 0:
        entries = entries[:limit]

    for entry in entries:
        if not entry.is_dir():
            continue
        meta_path = os.path.join(entry.path, "meta.json")
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            runs.append(meta)
        except Exception:
            runs.append({"run_id": entry.name, "status": "unknown", "created_at": None, "duration_s": None})

    runs.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return runs


def _load_logs(run_id):
    """Return the log entries for a run, or None if not found or corrupt."""
    logs_path = os.path.join(str(_runs_dir()), run_id, "logs.json")
    if not os.path.isfile(logs_path):
        return None
    try:
        with open(logs_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None  # caller handles None gracefully


def _make_stdout_logger(base_class):
    """Create a PipelineLogger subclass that prints events to stdout."""
    class StdoutLogger(base_class):
        def _emit(self, event: dict):
            super()._emit(event)
            etype = event.get("type", "")
            if etype == "node_start":
                idx = event.get("node_index", "?")
                total = event.get("total_nodes", "?")
                ntype = event.get("node_type", "?")
                print(f"[{idx + 1}/{total}] {ntype} starting…")
            elif etype == "node_end":
                ntype = event.get("node_type", "?")
                dur = event.get("duration_s", 0)
                out = event.get("output_count", "")
                count_str = f" → {out} samples" if out else ""
                print(f"  ✓ {ntype} done in {dur:.2f}s{count_str}")
            elif etype == "node_error":
                ntype = event.get("node_type", "?")
                msg = event.get("error_message", "")
                print(f"  ✗ {ntype} ERROR: {msg}", file=sys.stderr)
            elif etype == "pipeline_start":
                total = event.get("total_nodes", "?")
                print(f"Pipeline starting ({total} nodes)…")
            elif etype == "pipeline_summary":
                dur = event.get("total_duration_s", 0)
                out = event.get("total_samples_out", "?")
                print(f"\nPipeline complete in {dur:.2f}s — {out} samples produced.")
            elif etype == "info":
                msg = event.get("message", "")
                if msg:
                    print(f"  {msg}")
    return StdoutLogger


# ─── Subcommand: inspect ─────────────────────────────────────────────────────

def cmd_inspect(args):
    """Inspect an IR JSON graph file and print a human-readable summary."""
    from app.core.ir.loader import load_ir_from_file, IRVersionError
    from app.core.registry_runtime import get_registry, resolve_capability as _resolve_capability

    graph_path = args.graph
    if not os.path.isfile(graph_path):
        print(f"Error: graph file not found: {graph_path}", file=sys.stderr)
        sys.exit(1)

    try:
        graph = load_ir_from_file(graph_path)
    except IRVersionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Error loading graph: {exc}", file=sys.stderr)
        sys.exit(1)

    registry = get_registry()

    print(f"Graph: {graph.metadata.name}")
    print(f"  Schema version : {graph.schema_version}")
    print(f"  Seed           : {graph.metadata.seed}")
    if graph.metadata.description:
        print(f"  Description    : {graph.metadata.description}")
    if graph.metadata.tags:
        print(f"  Tags           : {', '.join(graph.metadata.tags)}")
    print(f"  Nodes          : {len(graph.nodes)}")
    print(f"  Edges          : {len(graph.edges)}")
    print()

    print("Nodes:")
    for i, node in enumerate(graph.nodes):
        label = f" ({node.label})" if node.label else ""
        print(f"  [{i}] {node.id} — {node.node_type}{label}")
    print()

    if graph.edges:
        print("Edges:")
        for edge in graph.edges:
            cond = f" [if: {edge.condition}]" if edge.condition else ""
            print(f"  {edge.src_id}.{edge.src_port} → {edge.dst_id}.{edge.dst_port}{cond}")
        print()

    # Capability summary
    caps = []
    for node in graph.nodes:
        cap = _resolve_capability(node, registry)
        caps.append(cap)

    if caps:
        print("Capability Summary:")
        print(f"  any_requires_gpu  : {any(c.requires_gpu for c in caps)}")
        print(f"  all_support_cpu   : {all(c.supports_cpu for c in caps)}")
        print(f"  all_support_edge  : {all(c.supports_edge for c in caps)}")
        print(f"  all_deterministic : {all(c.deterministic for c in caps)}")
        print(f"  any_batch_support : {any(c.batch_support for c in caps)}")

    sys.exit(0)


# ─── Subcommand: nodes ────────────────────────────────────────────────────────

def cmd_nodes(args):
    """List registered node types."""
    from app.core.registry_runtime import get_registry

    registry = get_registry()
    category = getattr(args, "category", None)
    nodes = registry.list_nodes(category=category)

    # Apply capability filter if provided
    cap_filter_raw = getattr(args, "capability", None)
    if cap_filter_raw:
        # Parse "key=value" pairs
        cap_filter = {}
        for pair in cap_filter_raw:
            if "=" not in pair:
                print(f"Error: capability filter must be key=value, got '{pair}'", file=sys.stderr)
                sys.exit(1)
            k, v = pair.split("=", 1)
            # Parse value as bool or string
            if v.lower() == "true":
                cap_filter[k] = True
            elif v.lower() == "false":
                cap_filter[k] = False
            else:
                cap_filter[k] = v

        filtered = []
        for meta in nodes:
            match = True
            for k, v in cap_filter.items():
                node_val = getattr(meta, k, None)
                if node_val != v:
                    match = False
                    break
            if match:
                filtered.append(meta)
        nodes = filtered

    if not nodes:
        print("No node types found.")
        sys.exit(0)

    col_type = 30
    col_cat = 15
    col_ver = 8
    header = f"{'NODE TYPE':<{col_type}}  {'CATEGORY':<{col_cat}}  {'VERSION':<{col_ver}}  DESCRIPTION"
    print(header)
    print("-" * len(header))
    for meta in sorted(nodes, key=lambda m: (m.category, m.node_type)):
        desc = meta.description[:50] + "…" if len(meta.description) > 50 else meta.description
        print(f"{meta.node_type:<{col_type}}  {meta.category:<{col_cat}}  {meta.version:<{col_ver}}  {desc}")

    print(f"\n{len(nodes)} node type(s) found.")
    sys.exit(0)


# ─── Subcommand: migrate ──────────────────────────────────────────────────────

def cmd_migrate(args):
    """Convert a YAML pipeline config to an IR JSON file."""
    from app.core.ir.migrate import migrate_yaml_to_ir_file

    yaml_path = args.config
    output_path = getattr(args, "output", None)

    # Validate file exists (Req 4.3.5)
    if not os.path.isfile(yaml_path):
        print(f"Error: config file not found: {yaml_path}", file=sys.stderr)
        sys.exit(1)

    # Validate YAML syntax (Req 4.3.6)
    try:
        with open(yaml_path) as f:
            yaml.safe_load(f)
    except yaml.YAMLError as exc:
        print(f"YAML parse error: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        result_path = migrate_yaml_to_ir_file(yaml_path, output_path)
        print(f"✓ Migrated {yaml_path} → {result_path}")
        sys.exit(0)
    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        sys.exit(1)


# ─── Subcommand: run ──────────────────────────────────────────────────────────

def _run_with_seed(pipeline, seed, logger, **kwargs):
    """Re-run a pipeline with a seed override via Pipeline._from_ir().

    Builds a new GraphIR with the overridden seed and wraps it in a fresh
    Pipeline so that Pipeline.run() creates a RunManager and persists the run
    to the run journal (fixes the seeded-run invisibility bug).
    """
    from app.core.ir.models import GraphIR, IRMetadata
    from app.core.sdk import Pipeline as _Pipeline

    graph = pipeline.to_ir()
    new_graph = GraphIR(
        schema_version=graph.schema_version,
        metadata=IRMetadata(
            name=graph.metadata.name,
            seed=seed,
            description=graph.metadata.description,
            created_at=graph.metadata.created_at,
            tags=graph.metadata.tags,
        ),
        nodes=graph.nodes,
        edges=graph.edges,
        parameters=graph.parameters,
    )
    seeded_pipeline = _Pipeline._from_ir(new_graph)
    seeded_pipeline.run(logger=logger, **kwargs)


def cmd_run(args):
    """Execute a pipeline synchronously and print logs to stdout."""
    from app.core.logger import PipelineLogger
    from app.core.sdk import Pipeline

    has_graph = getattr(args, "graph", None) is not None
    has_config = getattr(args, "config", None) is not None

    # Mutual exclusivity check (Req 4.5.5)
    if has_graph and has_config:
        print("Error: --graph and --config are mutually exclusive", file=sys.stderr)
        sys.exit(1)

    # At least one required (Req 4.5.6)
    if not has_graph and not has_config:
        print("Error: one of --graph or --config is required", file=sys.stderr)
        sys.exit(1)

    # Parse Phase 3 flags
    parallel = getattr(args, "parallel", False)
    resume_run_id = getattr(args, "resume_run_id", None)
    event_driven = getattr(args, "event_driven", False)
    include_nodes_raw = getattr(args, "include_nodes", None)
    exclude_nodes_raw = getattr(args, "exclude_nodes", None)
    include_nodes_list = [n.strip() for n in include_nodes_raw.split(",")] if include_nodes_raw else None
    exclude_nodes_list = [n.strip() for n in exclude_nodes_raw.split(",")] if exclude_nodes_raw else None

    run_kwargs = dict(
        parallel=parallel,
        resume_run_id=resume_run_id,
        include_nodes=include_nodes_list,
        exclude_nodes=exclude_nodes_list,
        event_driven=event_driven,
    )

    StdoutLogger = _make_stdout_logger(PipelineLogger)
    logger = StdoutLogger()

    if has_graph:
        # IR JSON path (Req 4.5.3) — canonical; use Pipeline.from_json (Req 2.9.1)
        graph_path = args.graph
        if not os.path.isfile(graph_path):
            print(f"Error: graph file not found: {graph_path}", file=sys.stderr)
            sys.exit(1)

        try:
            pipeline = Pipeline.from_json(graph_path)
        except Exception as exc:
            print(f"Error loading IR graph: {exc}", file=sys.stderr)
            sys.exit(1)

    else:
        # YAML path (Req 4.5.4) — deprecated; use Pipeline.from_yaml (Req 2.9.1)
        config_path = args.config
        if not os.path.isfile(config_path):
            print(f"Error: config file not found: {config_path}", file=sys.stderr)
            sys.exit(1)

        try:
            pipeline = Pipeline.from_yaml(config_path)
        except Exception as exc:
            print(f"Error loading YAML config: {exc}", file=sys.stderr)
            sys.exit(1)

    # Apply seed override (Req 4.5.7) — rebuild IR with new seed via _run_with_seed
    # so that Pipeline.run() is always used and the run is persisted to the journal.
    try:
        if args.seed is not None:
            _run_with_seed(pipeline, args.seed, logger, **run_kwargs)
        else:
            pipeline.run(logger=logger, **run_kwargs)
    except Exception as exc:
        print(f"\nPipeline failed: {exc}", file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


# ─── Subcommand: validate ─────────────────────────────────────────────────────

def cmd_validate(args):
    """Validate a pipeline YAML file or IR JSON graph file.

    For IR JSON graphs, performs deep validation:
      1. JSON parse + Pydantic schema (node IDs unique, edge refs valid)
      2. Schema version check
      3. Node type resolution against the registry
      4. Per-node config validation (Pydantic)
      5. Edge port existence (src_port on output_ports, dst_port on input_ports)
      6. Edge port type compatibility (CompatibilityChecker)
      7. DAG cycle detection (topological sort)
    """
    has_graph = getattr(args, "graph", None) is not None
    has_config = getattr(args, "config", None) is not None

    if has_graph:
        from app.core.ir.loader import load_ir_from_file, IRVersionError
        from app.core.registry_runtime import get_registry
        import pydantic

        graph_path = args.graph
        if not os.path.isfile(graph_path):
            print(f"Error: graph file not found: {graph_path}", file=sys.stderr)
            sys.exit(1)

        errors: list[str] = []

        # ── Step 1 & 2: JSON parse + Pydantic schema + version check ──────────
        try:
            graph = load_ir_from_file(graph_path)
        except IRVersionError as exc:
            print(f"✗ Version error: {exc}", file=sys.stderr)
            sys.exit(1)
        except Exception as exc:
            print(f"✗ Schema validation failed: {exc}", file=sys.stderr)
            sys.exit(1)

        # ── Step 3 & 4: node type resolution + config validation ──────────────
        registry = get_registry()
        node_classes: dict[str, type] = {}

        for node in graph.nodes:
            try:
                node_class = registry.get_class(node.node_type)
                node_classes[node.id] = node_class
            except Exception:
                available = sorted(m.node_type for m in registry.list_nodes())
                errors.append(
                    f"  ✗ [{node.id}] Unknown node type '{node.node_type}'. "
                    f"Available: {', '.join(available)}"
                )
                continue

            try:
                node_class.Config.model_validate(dict(node.config))
            except pydantic.ValidationError as exc:
                for e in exc.errors():
                    loc = ".".join(str(l) for l in e["loc"])
                    errors.append(
                        f"  ✗ [{node.id}] Config error at '{loc}': {e['msg']}"
                    )

        # ── Step 5 & 6: port existence + type compatibility ───────────────────
        from app.core.nodes.compat import CompatibilityChecker
        from app.core.nodes.errors import NodeTypeError
        from app.core.utils.hash import stable_hash
        import copy

        # Instantiate nodes (needed for port inspection)
        node_instances: dict[str, object] = {}
        for node in graph.nodes:
            if node.id not in node_classes:
                continue  # already flagged as unknown type
            try:
                node_class = node_classes[node.id]
                node_seed = stable_hash(graph.metadata.seed, node.node_type, 0) % (2 ** 32)
                instance = node_class(
                    config=copy.deepcopy(dict(node.config)),
                    seed=node_seed,
                )
                node_instances[node.id] = instance
            except Exception as exc:
                errors.append(f"  ✗ [{node.id}] Failed to instantiate node: {exc}")

        for edge in graph.edges:
            src_inst = node_instances.get(edge.src_id)
            dst_inst = node_instances.get(edge.dst_id)

            if src_inst is None or dst_inst is None:
                errors.append(
                    f"  ⚠ Edge {edge.src_id}.{edge.src_port} → {edge.dst_id}.{edge.dst_port}: "
                    f"skipped (node instantiation failed)"
                )
                continue  # node instantiation already failed — skip port check

            # Port existence
            if edge.src_port not in src_inst.__class__.output_ports:
                available = sorted(src_inst.__class__.output_ports)
                errors.append(
                    f"  ✗ Edge {edge.src_id}.{edge.src_port} → {edge.dst_id}.{edge.dst_port}: "
                    f"'{edge.src_id}' has no output port '{edge.src_port}'. "
                    f"Available: {available}"
                )
                continue

            if edge.dst_port not in dst_inst.__class__.input_ports:
                available = sorted(dst_inst.__class__.input_ports)
                errors.append(
                    f"  ✗ Edge {edge.src_id}.{edge.src_port} → {edge.dst_id}.{edge.dst_port}: "
                    f"'{edge.dst_id}' has no input port '{edge.dst_port}'. "
                    f"Available: {available}"
                )
                continue

            # Type compatibility
            try:
                CompatibilityChecker.check_connection(
                    src_inst, edge.src_port, dst_inst, edge.dst_port
                )
            except NodeTypeError as exc:
                errors.append(
                    f"  ✗ Edge {edge.src_id}.{edge.src_port} → {edge.dst_id}.{edge.dst_port}: "
                    f"Type mismatch — {exc}"
                )

        # ── Step 7: cycle detection ───────────────────────────────────────────
        from collections import defaultdict, deque as _deque
        in_degree: dict[str, int] = {n.id: 0 for n in graph.nodes}
        adjacency: dict[str, list[str]] = defaultdict(list)
        for edge in graph.edges:
            adjacency[edge.src_id].append(edge.dst_id)
            in_degree[edge.dst_id] += 1
        queue = _deque(nid for nid, deg in in_degree.items() if deg == 0)
        visited = 0
        while queue:
            nid = queue.popleft()
            visited += 1
            for succ in adjacency[nid]:
                in_degree[succ] -= 1
                if in_degree[succ] == 0:
                    queue.append(succ)
        if visited != len(graph.nodes):
            cycle_nodes = [n.id for n in graph.nodes if in_degree[n.id] > 0]
            errors.append(f"  ✗ Cycle detected — nodes involved: {cycle_nodes}")

        # ── Report ────────────────────────────────────────────────────────────
        if errors:
            print(f"✗ Validation failed — {len(errors)} error(s):", file=sys.stderr)
            for e in errors:
                print(e, file=sys.stderr)
            sys.exit(1)

        print(f"✓ Valid IR graph — {len(graph.nodes)} node(s):")
        for i, node in enumerate(graph.nodes):
            node_class = node_classes.get(node.id)
            in_ports = sorted(node_class.input_ports) if node_class else []
            out_ports = sorted(node_class.output_ports) if node_class else []
            print(f"  [{i}] {node.id} ({node.node_type})")
            if in_ports:
                print(f"       in:  {', '.join(in_ports)}")
            if out_ports:
                print(f"       out: {', '.join(out_ports)}")
        sys.exit(0)

    else:
        # YAML validation (Req 4.6.4) — load via shim, validate the resulting GraphIR
        from app.core.ir.yaml_shim import load_yaml_with_deprecation
        from app.core.registry_runtime import get_registry

        config_path = args.config
        if not os.path.isfile(config_path):
            print(f"Error: config file not found: {config_path}", file=sys.stderr)
            sys.exit(1)

        try:
            graph = load_yaml_with_deprecation(config_path)
        except Exception as exc:
            print(f"✗ Validation failed: {exc}", file=sys.stderr)
            sys.exit(1)

        # Validate node types against the registry (unknown types → exit 1)
        try:
            registry = get_registry()
            errors: list[str] = []
            node_classes: dict[str, type] = {}

            for node in graph.nodes:
                try:
                    node_class = registry.get_class(node.node_type)
                    node_classes[node.id] = node_class
                except Exception:
                    available = sorted(m.node_type for m in registry.list_nodes())
                    errors.append(
                        f"  ✗ [{node.id}] Unknown node type '{node.node_type}'. "
                        f"Available types: {', '.join(available)}"
                    )
                    continue
                # Also validate config against the node's Pydantic Config model
                import pydantic
                try:
                    node_class.Config.model_validate(dict(node.config))
                except pydantic.ValidationError as exc:
                    for e in exc.errors():
                        loc = ".".join(str(l) for l in e["loc"])
                        errors.append(
                            f"  ✗ [{node.id}] Config error at '{loc}': {e['msg']}"
                        )

            # ── Steps 5 & 6: port existence + type compatibility ──────────────
            from app.core.nodes.compat import CompatibilityChecker
            from app.core.nodes.errors import NodeTypeError
            from app.core.utils.hash import stable_hash
            import copy as _copy

            node_instances: dict[str, object] = {}
            for node in graph.nodes:
                if node.id not in node_classes:
                    continue
                try:
                    node_class = node_classes[node.id]
                    node_seed = stable_hash(graph.metadata.seed, node.node_type, 0) % (2 ** 32)
                    instance = node_class(
                        config=_copy.deepcopy(dict(node.config)),
                        seed=node_seed,
                    )
                    node_instances[node.id] = instance
                except Exception as exc:
                    errors.append(f"  ✗ [{node.id}] Failed to instantiate node: {exc}")

            for edge in graph.edges:
                src_inst = node_instances.get(edge.src_id)
                dst_inst = node_instances.get(edge.dst_id)

                if src_inst is None or dst_inst is None:
                    errors.append(
                        f"  ⚠ Edge {edge.src_id}.{edge.src_port} → {edge.dst_id}.{edge.dst_port}: "
                        f"skipped (node instantiation failed)"
                    )
                    continue

                if edge.src_port not in src_inst.__class__.output_ports:
                    available = sorted(src_inst.__class__.output_ports)
                    errors.append(
                        f"  ✗ Edge {edge.src_id}.{edge.src_port} → {edge.dst_id}.{edge.dst_port}: "
                        f"'{edge.src_id}' has no output port '{edge.src_port}'. "
                        f"Available: {available}"
                    )
                    continue

                if edge.dst_port not in dst_inst.__class__.input_ports:
                    available = sorted(dst_inst.__class__.input_ports)
                    errors.append(
                        f"  ✗ Edge {edge.src_id}.{edge.src_port} → {edge.dst_id}.{edge.dst_port}: "
                        f"'{edge.dst_id}' has no input port '{edge.dst_port}'. "
                        f"Available: {available}"
                    )
                    continue

                try:
                    CompatibilityChecker.check_connection(
                        src_inst, edge.src_port, dst_inst, edge.dst_port
                    )
                except NodeTypeError as exc:
                    errors.append(
                        f"  ✗ Edge {edge.src_id}.{edge.src_port} → {edge.dst_id}.{edge.dst_port}: "
                        f"Type mismatch — {exc}"
                    )

            # ── Step 7: cycle detection ───────────────────────────────────────
            from collections import defaultdict, deque as _deque
            in_degree: dict[str, int] = {n.id: 0 for n in graph.nodes}
            adjacency: dict[str, list[str]] = defaultdict(list)
            for edge in graph.edges:
                adjacency[edge.src_id].append(edge.dst_id)
                in_degree[edge.dst_id] += 1
            queue = _deque(nid for nid, deg in in_degree.items() if deg == 0)
            visited = 0
            while queue:
                nid = queue.popleft()
                visited += 1
                for succ in adjacency[nid]:
                    in_degree[succ] -= 1
                    if in_degree[succ] == 0:
                        queue.append(succ)
            if visited != len(graph.nodes):
                cycle_nodes = [n.id for n in graph.nodes if in_degree[n.id] > 0]
                errors.append(f"  ✗ Cycle detected — nodes involved: {cycle_nodes}")

            if errors:
                print(f"✗ Validation failed — {len(errors)} error(s):", file=sys.stderr)
                for e in errors:
                    print(e, file=sys.stderr)
                sys.exit(1)

            print(f"✓ Valid pipeline — {len(graph.nodes)} node(s):")
            for i, node in enumerate(graph.nodes):
                print(f"  [{i}] {node.node_type}")
            sys.exit(0)
        except ValueError as exc:
            print(f"✗ Validation failed: {exc}", file=sys.stderr)
            sys.exit(1)


# ─── Subcommand: runs list ────────────────────────────────────────────────────

def cmd_runs_list(args):
    """Print a table of recent pipeline runs."""
    limit = getattr(args, "limit", 50)
    runs = _list_runs(limit=limit)

    if not runs:
        print("No runs found.")
        sys.exit(0)

    col_id = 12
    col_status = 10
    col_date = 24
    col_dur = 10

    header = (
        f"{'RUN ID':<{col_id}}  "
        f"{'STATUS':<{col_status}}  "
        f"{'CREATED AT':<{col_date}}  "
        f"{'DURATION':>{col_dur}}"
    )
    sep = "-" * len(header)
    print(header)
    print(sep)

    for run in runs:
        run_id = str(run.get("run_id", ""))[:col_id]
        status = str(run.get("status", "unknown"))[:col_status]
        created = str(run.get("created_at") or "—")[:col_date]
        dur = run.get("duration_s")
        dur_str = f"{dur:.1f}s" if dur is not None else "—"

        if sys.stdout.isatty():
            if status == "completed":
                status_display = f"\033[32m{status:<{col_status}}\033[0m"
            elif status == "failed":
                status_display = f"\033[31m{status:<{col_status}}\033[0m"
            else:
                status_display = f"\033[33m{status:<{col_status}}\033[0m"
        else:
            status_display = f"{status:<{col_status}}"

        print(
            f"{run_id:<{col_id}}  "
            f"{status_display}  "
            f"{created:<{col_date}}  "
            f"{dur_str:>{col_dur}}"
        )

    sys.exit(0)


# ─── Subcommand: runs logs ────────────────────────────────────────────────────

def cmd_runs_logs(args):
    """Print log entries for a specific run."""
    run_id = args.run_id
    runs_dir_path = str(_runs_dir())

    if not os.path.isdir(os.path.join(runs_dir_path, run_id)):
        if not os.path.isdir(runs_dir_path):
            print(f"Error: runs directory not found: {runs_dir_path}", file=sys.stderr)
            sys.exit(1)
        matches = [d for d in os.listdir(runs_dir_path) if d.startswith(run_id)]
        if len(matches) == 1:
            run_id = matches[0]
        elif len(matches) > 1:
            print(f"Ambiguous run ID prefix '{run_id}': {', '.join(matches)}", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"Run not found: {run_id}", file=sys.stderr)
            sys.exit(1)

    logs = _load_logs(run_id)
    if logs is None:
        print(f"No logs found for run: {run_id}", file=sys.stderr)
        sys.exit(1)

    if not logs:
        print(f"Run {run_id} has no log entries.")
        sys.exit(0)

    for entry in logs:
        level = entry.get("level", "INFO")
        msg = entry.get("message", "")
        ts = entry.get("time", "")
        ts_str = f"[{ts}] " if ts else ""

        if sys.stdout.isatty():
            if level == "ERROR":
                colour = "\033[31m"
            elif level == "WARNING":
                colour = "\033[33m"
            else:
                colour = "\033[0m"
            print(f"{colour}{ts_str}[{level}] {msg}\033[0m")
        else:
            print(f"{ts_str}[{level}] {msg}")

    sys.exit(0)


# ─── Subcommand: runs pause / resume / cancel ─────────────────────────────────

def _get_active_run_or_exit(run_id: str):
    """Return the active RunManager for run_id, or print an error and exit."""
    from app.core.run_control import get_active_run
    run = get_active_run(run_id)
    if run is None:
        print(
            f"Error: run '{run_id}' is not currently active. "
            "Only in-progress runs can be paused, resumed, or cancelled.",
            file=sys.stderr,
        )
        sys.exit(1)
    return run


def cmd_runs_pause(args):
    """Pause an active pipeline run after its current node completes."""
    run = _get_active_run_or_exit(args.run_id)
    run.pause()
    print(f"Run {args.run_id} paused.")


def cmd_runs_resume(args):
    """Resume a paused pipeline run."""
    run = _get_active_run_or_exit(args.run_id)
    run.resume()
    print(f"Run {args.run_id} resumed.")


def cmd_runs_cancel(args):
    """Cancel an active pipeline run after its current node completes."""
    run = _get_active_run_or_exit(args.run_id)
    run.cancel()
    print(f"Run {args.run_id} cancellation requested.")


# ─── Subcommand: artifacts ───────────────────────────────────────────────────

def cmd_artifacts_list(args):
    """List artifacts, optionally filtered by run ID and/or artifact type."""
    from app.core.artifact_store import ArtifactStore

    store = ArtifactStore()
    records = store.list(
        run_id=getattr(args, "run", None),
        artifact_type=getattr(args, "type", None),
    )

    if not records:
        print("No artifacts found.")
        return

    col_id = 12
    col_type = 16
    col_node = 10
    col_run = 10
    col_date = 26

    header = (
        f"{'ARTIFACT ID':<{col_id}}  "
        f"{'TYPE':<{col_type}}  "
        f"{'NODE TYPE':<{col_node}}  "
        f"{'RUN ID':<{col_run}}  "
        f"{'CREATED AT':<{col_date}}"
    )
    print(header)
    print("-" * len(header))

    for record in records:
        artifact_id = str(record.artifact_id)[:col_id]
        artifact_type = str(record.artifact_type)[:col_type]
        node_type = str(record.node_type)[:col_node]
        run_id = str(record.run_id)[:col_run]
        created_at = str(record.created_at)[:col_date]
        print(
            f"{artifact_id:<{col_id}}  "
            f"{artifact_type:<{col_type}}  "
            f"{node_type:<{col_node}}  "
            f"{run_id:<{col_run}}  "
            f"{created_at:<{col_date}}"
        )


def cmd_artifacts_get(args):
    """Print the full ArtifactRecord as formatted JSON."""
    from app.core.artifact_store import ArtifactStore, ArtifactNotFoundError

    store = ArtifactStore()
    try:
        record = store.get(args.artifact_id)
        print(json.dumps(record.model_dump(mode="json"), indent=2))
    except ArtifactNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_artifacts_lineage(args):
    """Print the lineage tree for an artifact as formatted JSON."""
    from app.core.provenance import ProvenanceStore

    store = ProvenanceStore()
    tree = store.get_lineage(args.artifact_id)
    print(json.dumps(tree, indent=2))


def cmd_artifacts_replay(args):
    """Re-execute a pipeline using the graph.json stored for a run."""
    from app.core.ir.loader import load_ir_from_file
    from app.core.run_journal import RunManager
    from app.core.orchestrator import run_pipeline_ir

    run_id = args.run_id
    runs_dir_path = str(_runs_dir())

    # Apply the same prefix-matching logic as cmd_runs_logs for consistency.
    if not os.path.isdir(os.path.join(runs_dir_path, run_id)):
        if not os.path.isdir(runs_dir_path):
            print(f"Error: runs directory not found: {runs_dir_path}", file=sys.stderr)
            sys.exit(1)
        matches = [d for d in os.listdir(runs_dir_path) if d.startswith(run_id)]
        if len(matches) == 1:
            run_id = matches[0]
        elif len(matches) > 1:
            print(f"Ambiguous run ID prefix '{run_id}': {', '.join(matches)}", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"Run not found: {run_id}", file=sys.stderr)
            sys.exit(1)

    graph_path = os.path.join(runs_dir_path, run_id, "graph.json")

    if not os.path.isfile(graph_path):
        print(
            f"Error: graph.json not found for run {run_id!r}: {graph_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        graph = load_ir_from_file(graph_path)
    except Exception as exc:
        print(f"Error loading graph.json: {exc}", file=sys.stderr)
        sys.exit(1)

    run_manager = RunManager()
    try:
        run_pipeline_ir(graph, run_manager=run_manager)
    except Exception as exc:
        print(f"Replay failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Replayed as run {run_manager.run_id}")


# ─── Subcommand: plugin ──────────────────────────────────────────────────────

def cmd_plugin_install(args):
    """Install a plugin from a source string."""
    from app.core.plugins.manager import PluginManager
    from app.core.plugins.errors import PluginError

    try:
        record = PluginManager().install(args.source, upgrade=args.upgrade)
        print(f"✓ Installed {record.name} v{record.version}")
    except PluginError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_plugin_list(args):
    """Print a table of installed plugins."""
    from app.core.plugins.manager import PluginManager
    from app.core.plugins.errors import PluginError

    try:
        records = PluginManager().list_installed()
    except PluginError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "enabled", False):
        records = [r for r in records if r.enabled]

    if not records:
        print("No plugins installed.")
        return

    col_name = 20
    col_ver = 10
    col_status = 10
    col_source = 30

    header = (
        f"{'NAME':<{col_name}}  "
        f"{'VERSION':<{col_ver}}  "
        f"{'STATUS':<{col_status}}  "
        f"{'SOURCE':<{col_source}}"
    )
    print(header)
    print("-" * len(header))

    for record in records:
        name = str(record.name)[:col_name]
        version = str(record.version)[:col_ver]
        status = "enabled" if record.enabled else "disabled"
        source = str(record.source)[:col_source]
        print(
            f"{name:<{col_name}}  "
            f"{version:<{col_ver}}  "
            f"{status:<{col_status}}  "
            f"{source:<{col_source}}"
        )


def cmd_plugin_enable(args):
    """Enable an installed plugin."""
    from app.core.plugins.manager import PluginManager
    from app.core.plugins.errors import PluginError

    try:
        PluginManager().enable(args.name)
        print(f"✓ Enabled {args.name}")
    except PluginError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_plugin_disable(args):
    """Disable an installed plugin."""
    from app.core.plugins.manager import PluginManager
    from app.core.plugins.errors import PluginError

    try:
        PluginManager().disable(args.name)
        print(f"✓ Disabled {args.name}")
    except PluginError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_plugin_remove(args):
    """Uninstall an installed plugin."""
    from app.core.plugins.manager import PluginManager
    from app.core.plugins.errors import PluginError

    try:
        PluginManager().uninstall(args.name)
        print(f"✓ Removed {args.name}")
    except PluginError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_plugin_search(args):
    """Search the plugin index."""
    from app.core.plugins.index import PluginIndexClient
    from app.core.plugins.errors import PluginError

    try:
        results = PluginIndexClient().search(args.query)
    except PluginError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if not results:
        print("No plugins found.")
        return

    col_name = 20
    col_ver = 10
    col_desc = 40
    col_tags = 30

    header = (
        f"{'NAME':<{col_name}}  "
        f"{'VERSION':<{col_ver}}  "
        f"{'DESCRIPTION':<{col_desc}}  "
        f"{'TAGS':<{col_tags}}"
    )
    print(header)
    print("-" * len(header))

    for entry in results:
        name = str(entry.name)[:col_name]
        version = str(entry.version)[:col_ver]
        desc = str(entry.description)
        desc = (desc[:col_desc - 1] + "…") if len(desc) > col_desc else desc
        tags = ", ".join(entry.tags)[:col_tags]
        print(
            f"{name:<{col_name}}  "
            f"{version:<{col_ver}}  "
            f"{desc:<{col_desc}}  "
            f"{tags:<{col_tags}}"
        )


def cmd_plugin_info(args):
    """Print full info for a plugin (installed or from index)."""
    from app.core.plugins.manager import PluginManager
    from app.core.plugins.index import PluginIndexClient
    from app.core.plugins.errors import PluginError, PluginNotFoundError

    # Try installed first
    try:
        record = PluginManager().get(args.name)
        print(json.dumps(record.model_dump(mode="json"), indent=2))
        return
    except PluginNotFoundError:
        pass
    except PluginError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Fall back to index lookup
    try:
        entry = PluginIndexClient().lookup(args.name)
        print(json.dumps(entry.model_dump(mode="json"), indent=2))
    except PluginNotFoundError:
        print(f"Error: Plugin '{args.name}' not found (not installed and not in index).", file=sys.stderr)
        sys.exit(1)
    except PluginError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


# ─── Subcommand: mcp ─────────────────────────────────────────────────────────

def cmd_mcp(args):
    """Launch the MCP server (stdio transport) in-process."""
    from app.mcp.server import main
    main()


# ─── Argument parser ──────────────────────────────────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(
        prog="graphyn",
        description="Graphyn CLI — build and manage AI/workflow pipelines",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.required = True

    # ── inspect ── (V1.md §9 — graph inspection)
    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect an IR JSON graph file",
        description="Print a human-readable summary of an IR JSON graph file.",
    )
    inspect_parser.add_argument(
        "--graph",
        required=True,
        metavar="PATH",
        help="Path to the IR JSON graph file",
    )
    inspect_parser.set_defaults(func=cmd_inspect)

    # ── nodes ── (V1.md §9 — registry inspection)
    nodes_parser = subparsers.add_parser(
        "nodes",
        help="List registered node types",
        description="List all registered node types with optional filtering.",
    )
    nodes_parser.add_argument(
        "--category",
        default=None,
        metavar="CATEGORY",
        help="Filter by category (e.g. 'audio', 'ml')",
    )
    nodes_parser.add_argument(
        "--capability",
        nargs="*",
        metavar="KEY=VALUE",
        help="Filter by capability (e.g. --capability requires_gpu=false supports_edge=true)",
    )
    nodes_parser.set_defaults(func=cmd_nodes)

    # ── migrate ── (Req 4.3)
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

    # ── run ── (Req 4.5)
    run_parser = subparsers.add_parser(
        "run",
        help="Execute a pipeline synchronously",
        description="Execute a pipeline from an IR JSON file (canonical) or YAML config (deprecated).",
    )
    run_parser.add_argument(
        "--graph",
        required=False,
        default=None,
        metavar="PATH",
        help="Path to the IR JSON graph file (canonical format)",
    )
    run_parser.add_argument(
        "--config",
        required=False,
        default=None,
        metavar="PATH",
        help="Path to the pipeline YAML config file (deprecated — use --graph)",
    )
    run_parser.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help="Override the pipeline seed (integer)",
    )
    run_parser.add_argument(
        "--parallel",
        action="store_true",
        default=False,
        help="Enable parallel wave execution.",
    )
    run_parser.add_argument(
        "--resume",
        dest="resume_run_id",
        default=None,
        metavar="RUN_ID",
        help="Resume from a prior run ID.",
    )
    run_parser.add_argument(
        "--include-nodes",
        dest="include_nodes",
        default=None,
        metavar="ID,...",
        help="Comma-separated node IDs to include (partial execution).",
    )
    run_parser.add_argument(
        "--exclude-nodes",
        dest="exclude_nodes",
        default=None,
        metavar="ID,...",
        help="Comma-separated node IDs to exclude (partial execution).",
    )
    run_parser.add_argument(
        "--event-driven",
        dest="event_driven",
        action="store_true",
        default=False,
        help="Run in event-driven mode.",
    )
    run_parser.set_defaults(func=cmd_run)

    # ── validate ── (Req 4.6)
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate a pipeline YAML file or IR JSON graph",
        description="Validate a pipeline config against the node registry.",
    )
    validate_parser.add_argument(
        "--graph",
        required=False,
        default=None,
        metavar="PATH",
        help="Path to the IR JSON graph file",
    )
    validate_parser.add_argument(
        "--config",
        required=False,
        default=None,
        metavar="PATH",
        help="Path to the pipeline YAML config file",
    )
    validate_parser.set_defaults(func=cmd_validate)

    # ── runs ──
    runs_parser = subparsers.add_parser(
        "runs",
        help="Manage pipeline run history",
        description="List and inspect past pipeline runs.",
    )
    runs_subparsers = runs_parser.add_subparsers(dest="runs_command", metavar="ACTION")
    runs_subparsers.required = True

    runs_list_parser = runs_subparsers.add_parser(
        "list",
        help="Print a table of recent runs",
    )
    runs_list_parser.add_argument(
        "--limit",
        type=int,
        default=50,
        metavar="N",
        help="Maximum number of runs to show (default: 50; 0 = all)",
    )
    runs_list_parser.set_defaults(func=cmd_runs_list)

    runs_logs_parser = runs_subparsers.add_parser(
        "logs",
        help="Print log entries for a run",
    )
    runs_logs_parser.add_argument(
        "run_id",
        metavar="RUN_ID",
        help="Run ID (or unique prefix) to fetch logs for",
    )
    runs_logs_parser.set_defaults(func=cmd_runs_logs)

    # pause
    runs_pause_parser = runs_subparsers.add_parser(
        "pause",
        help="Pause an active run after its current node completes",
    )
    runs_pause_parser.add_argument(
        "run_id",
        metavar="RUN_ID",
        help="Run ID of the active run to pause",
    )
    runs_pause_parser.set_defaults(func=cmd_runs_pause)

    # resume
    runs_resume_parser = runs_subparsers.add_parser(
        "resume",
        help="Resume a paused run",
    )
    runs_resume_parser.add_argument(
        "run_id",
        metavar="RUN_ID",
        help="Run ID of the paused run to resume",
    )
    runs_resume_parser.set_defaults(func=cmd_runs_resume)

    # cancel
    runs_cancel_parser = runs_subparsers.add_parser(
        "cancel",
        help="Cancel an active run after its current node completes",
    )
    runs_cancel_parser.add_argument(
        "run_id",
        metavar="RUN_ID",
        help="Run ID of the active run to cancel",
    )
    runs_cancel_parser.set_defaults(func=cmd_runs_cancel)

    # ── artifacts ──
    artifacts_parser = subparsers.add_parser(
        "artifacts",
        help="Manage artifacts",
        description="List, inspect, and replay pipeline artifacts.",
    )
    artifacts_subparsers = artifacts_parser.add_subparsers(dest="artifacts_command", metavar="ACTION")
    artifacts_subparsers.required = True

    # list subcommand
    list_parser = artifacts_subparsers.add_parser("list", help="List artifacts")
    list_parser.add_argument("--run", default=None, metavar="RUN_ID", help="Filter by run ID")
    list_parser.add_argument("--type", default=None, metavar="TYPE", help="Filter by artifact type")
    list_parser.set_defaults(func=cmd_artifacts_list)

    # get subcommand
    get_parser = artifacts_subparsers.add_parser("get", help="Get artifact by ID")
    get_parser.add_argument("artifact_id", metavar="ARTIFACT_ID")
    get_parser.set_defaults(func=cmd_artifacts_get)

    # lineage subcommand
    lineage_parser = artifacts_subparsers.add_parser("lineage", help="Get artifact lineage")
    lineage_parser.add_argument("artifact_id", metavar="ARTIFACT_ID")
    lineage_parser.set_defaults(func=cmd_artifacts_lineage)

    # replay subcommand
    replay_parser = artifacts_subparsers.add_parser("replay", help="Replay a run")
    replay_parser.add_argument("run_id", metavar="RUN_ID")
    replay_parser.set_defaults(func=cmd_artifacts_replay)

    # ── plugin ── (req-06 §7.1–§7.11)
    plugin_parser = subparsers.add_parser(
        "plugin",
        help="Manage plugins",
        description="Install, list, enable, disable, remove, search, and inspect plugins.",
    )
    plugin_subparsers = plugin_parser.add_subparsers(dest="plugin_command", metavar="ACTION")
    plugin_subparsers.required = True

    # install
    plugin_install_parser = plugin_subparsers.add_parser(
        "install",
        help="Install a plugin from a source",
    )
    plugin_install_parser.add_argument(
        "source",
        metavar="SOURCE",
        help="Plugin source: local path, Git URL, HTTP archive URL, or plugin name",
    )
    plugin_install_parser.add_argument(
        "--upgrade",
        action="store_true",
        default=False,
        help="Replace an existing installation with the same name",
    )
    plugin_install_parser.set_defaults(func=cmd_plugin_install)

    # list
    plugin_list_parser = plugin_subparsers.add_parser(
        "list",
        help="List installed plugins",
    )
    plugin_list_parser.add_argument(
        "--enabled",
        action="store_true",
        default=False,
        help="Show only enabled plugins",
    )
    plugin_list_parser.set_defaults(func=cmd_plugin_list)

    # enable
    plugin_enable_parser = plugin_subparsers.add_parser(
        "enable",
        help="Enable an installed plugin",
    )
    plugin_enable_parser.add_argument(
        "name",
        metavar="NAME",
        help="Plugin name to enable",
    )
    plugin_enable_parser.set_defaults(func=cmd_plugin_enable)

    # disable
    plugin_disable_parser = plugin_subparsers.add_parser(
        "disable",
        help="Disable an installed plugin",
    )
    plugin_disable_parser.add_argument(
        "name",
        metavar="NAME",
        help="Plugin name to disable",
    )
    plugin_disable_parser.set_defaults(func=cmd_plugin_disable)

    # remove
    plugin_remove_parser = plugin_subparsers.add_parser(
        "remove",
        help="Uninstall a plugin",
    )
    plugin_remove_parser.add_argument(
        "name",
        metavar="NAME",
        help="Plugin name to remove",
    )
    plugin_remove_parser.set_defaults(func=cmd_plugin_remove)

    # search
    plugin_search_parser = plugin_subparsers.add_parser(
        "search",
        help="Search the plugin index",
    )
    plugin_search_parser.add_argument(
        "query",
        metavar="QUERY",
        help="Search query string",
    )
    plugin_search_parser.set_defaults(func=cmd_plugin_search)

    # info
    plugin_info_parser = plugin_subparsers.add_parser(
        "info",
        help="Show full info for a plugin",
    )
    plugin_info_parser.add_argument(
        "name",
        metavar="NAME",
        help="Plugin name to inspect",
    )
    plugin_info_parser.set_defaults(func=cmd_plugin_info)

    # ── mcp ── (Req 1.6, 8.1)
    mcp_parser = subparsers.add_parser(
        "mcp",
        help="Start the MCP server (stdio transport)",
        description=(
            "Start the Graphyn MCP server. "
            "Reads JSON-RPC from stdin, writes responses to stdout. "
            "Set GRAPHYN_API_TOKEN to require authentication."
        ),
    )
    mcp_parser.set_defaults(func=cmd_mcp)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
