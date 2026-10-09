# app/cli/cmd_artifacts.py
"""
Bounded Context:  CLI Interface
Responsibility:   artifacts list/get/lineage/replay subcommands.
Owns:             cmd_artifacts_list, cmd_artifacts_get, cmd_artifacts_lineage, cmd_artifacts_replay
Public Surface:   cmd_artifacts_list, cmd_artifacts_get, cmd_artifacts_lineage, cmd_artifacts_replay
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

def cmd_artifacts_list(args):
    """List artifacts, optionally filtered by run ID and/or artifact type."""
    from app.core.artifacts.artifact_store import ArtifactStore

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
    from app.core.artifacts.artifact_store import ArtifactStore, ArtifactNotFoundError

    store = ArtifactStore()
    try:
        record = store.get(args.artifact_id)
        print(json.dumps(record.model_dump(mode="json"), indent=2))
    except ArtifactNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_artifacts_lineage(args):
    """Print the lineage tree for an artifact as formatted JSON."""
    from app.core.artifacts.provenance import ProvenanceStore

    store = ProvenanceStore()
    tree = store.get_lineage(args.artifact_id)
    print(json.dumps(tree, indent=2))


def cmd_artifacts_replay(args):
    """Re-execute a pipeline using the graph.json stored for a run."""
    from app.core.ir.loader import load_ir_from_file
    from app.core.runs.run_journal import RunManager
    from app.core.execution.runtime_backend import get_backend
    from app.core.config import runs_dir as _runs_dir

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
        get_backend().execute(graph, run_manager=run_manager)
    except Exception as exc:
        print(f"Replay failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Replayed as run {run_manager.run_id}")
