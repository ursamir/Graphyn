# app/cli/cmd_graph.py
"""
Bounded Context:  CLI Interface
Responsibility:   inspect, nodes, migrate, run, and validate subcommands.
Owns:             cmd_inspect, cmd_nodes, cmd_migrate, cmd_run, cmd_validate
Public Surface:   cmd_inspect, cmd_nodes, cmd_migrate, cmd_run, cmd_validate
Must NOT:         Contain pipeline execution logic. Must not import app.api.
Dependencies:     app.core.sdk and the core package each command calls.
Reason To Change: That subcommand's flags or output change.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import yaml

from app.cli.support import cli_actor, make_stdout_logger, run_with_seed

def cmd_inspect(args):
    """Inspect an IR JSON graph file and print a human-readable summary."""
    from app.core.ir.loader import load_ir_from_file, IRVersionError
    from app.core.host.registry_runtime import get_registry, resolve_capability as _resolve_capability

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


def cmd_nodes(args):
    """List registered node types."""
    from app.core.host.registry_runtime import get_registry

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

    StdoutLogger = make_stdout_logger(PipelineLogger)
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

    # run.start audit attribution (the SDK records it for every run).
    pipeline._audit_actor = cli_actor()
    pipeline._audit_mode = "cli"

    # Apply seed override (Req 4.5.7) — rebuild IR with new seed via run_with_seed
    # so that Pipeline.run() is always used and the run is persisted to the journal.
    try:
        if args.seed is not None:
            run_with_seed(pipeline, args.seed, logger, **run_kwargs)
        else:
            pipeline.run(logger=logger, **run_kwargs)
    except Exception as exc:
        print(f"\nPipeline failed: {exc}", file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


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

    if not has_graph and not has_config:
        print(
            "Error: graphyn validate requires --graph PATH or --config PATH",
            file=sys.stderr,
        )
        sys.exit(2)

    if has_graph:
        from app.core.ir.loader import load_ir_from_file, IRVersionError
        from app.core.host.registry_runtime import get_registry

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

        # ── Steps 3–7: deep validation (shared with API/MCP) ─────────────────
        from app.core.execution.validation import validate_graph_ir

        registry = get_registry()
        node_classes: dict[str, type] = {}
        for line in validate_graph_ir(graph, registry):
            errors.append(f"  ✗ {line}")

        for node in graph.nodes:
            try:
                node_classes[node.id] = registry.get_class(node.node_type)
            except Exception:
                pass

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
        from app.core.host.registry_runtime import get_registry

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
