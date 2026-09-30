# app/cli/cmd_runs.py
"""
Bounded Context:  CLI Interface
Responsibility:   runs list/logs/pause/resume/cancel subcommands.
Owns:             cmd_runs_list, cmd_runs_logs, cmd_runs_pause, cmd_runs_resume, cmd_runs_cancel
Public Surface:   cmd_runs_list, cmd_runs_logs, cmd_runs_pause, cmd_runs_resume, cmd_runs_cancel
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

from app.cli.support import get_active_run_or_exit, list_cli_runs, load_cli_logs
from app.core.config import runs_dir as _runs_dir

def cmd_runs_list(args):
    """Print a table of recent pipeline runs."""
    limit = getattr(args, "limit", 50)
    runs = list_cli_runs(limit=limit)

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

    logs = load_cli_logs(run_id)
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


def cmd_runs_pause(args):
    """Pause an active pipeline run after its current node completes."""
    run = get_active_run_or_exit(args.run_id)
    run.pause()
    print(f"Run {args.run_id} paused.")


def cmd_runs_resume(args):
    """Resume a paused pipeline run."""
    run = get_active_run_or_exit(args.run_id)
    run.resume()
    print(f"Run {args.run_id} resumed.")


def cmd_runs_cancel(args):
    """Cancel an active pipeline run after its current node completes."""
    run = get_active_run_or_exit(args.run_id)
    run.cancel()
    print(f"Run {args.run_id} cancellation requested.")
