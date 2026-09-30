# app/cli/support.py
"""
Bounded Context:  CLI Interface
Responsibility:   CLI helpers shared by subcommands.
Owns:             _list_runs, _load_logs, _make_stdout_logger, _run_with_seed
Public Surface:   _list_runs, _load_logs, _make_stdout_logger, _run_with_seed
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

from app.core.config import runs_dir as _runs_dir

def _list_runs(limit: int = 50):
    """Return run metadata dicts newest first (created_at desc, run_id tiebreak).

    Uses the shared lister (app.core.runs.run_listing) so ordering matches REST
    GET /runs and MCP list_runs. ``limit=0`` returns all runs. Corrupt
    meta.json entries are shown as ``status=unknown`` rows.
    """
    from app.core.runs.run_listing import list_runs

    page = list_runs(_runs_dir(), limit=limit if limit and limit > 0 else None, include_unreadable=True)
    return [meta for _entry, meta in page.rows]


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


def _cli_actor() -> str:
    """Actor for run.start audit: --actor / GRAPHYN_ACTOR, else ``cli``."""
    return (os.environ.get("GRAPHYN_ACTOR") or "").strip()[:128] or "cli"


def _run_with_seed(pipeline, seed, logger, **kwargs):
    """Re-run a pipeline with a seed override via Pipeline._from_ir().

    Copies the GraphIR metadata with only ``seed`` changed (project,
    version_tag, ui and every other metadata field are preserved) and wraps
    it in a fresh Pipeline so that Pipeline.run() creates a RunManager and
    persists the run to the run journal.
    """
    from app.core.sdk import Pipeline as _Pipeline

    graph = pipeline.to_ir()
    new_graph = graph.model_copy(
        update={"metadata": graph.metadata.model_copy(update={"seed": seed})}
    )
    seeded_pipeline = _Pipeline._from_ir(new_graph)
    seeded_pipeline._audit_actor = getattr(pipeline, "_audit_actor", None) or _cli_actor()
    seeded_pipeline._audit_mode = "cli"
    seeded_pipeline.run(logger=logger, **kwargs)


def _get_active_run_or_exit(run_id: str):
    """Return the active RunManager for run_id, or print an error and exit."""
    from app.core.runs.run_control import get_active_run
    run = get_active_run(run_id)
    if run is None:
        print(
            f"Error: run '{run_id}' is not currently active. "
            "Only in-progress runs can be paused, resumed, or cancelled.",
            file=sys.stderr,
        )
        sys.exit(1)
    return run

# Public names. A leading underscore stays private to this module.
list_cli_runs = _list_runs
load_cli_logs = _load_logs
make_stdout_logger = _make_stdout_logger
cli_actor = _cli_actor
run_with_seed = _run_with_seed
get_active_run_or_exit = _get_active_run_or_exit
