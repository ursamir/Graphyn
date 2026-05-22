# unit_test/cli/test_cli.py
"""CLI tests — Req 13.

Tests the Graphyn CLI (app/cli/main.py) using subprocess so that argparse
exit codes and stdout/stderr are captured faithfully.

The CLI uses argparse (not Click), so we invoke it via:
    venv/bin/python -m app.cli.main <args>

Command reference:
  nodes                     List registered node types
  validate --graph PATH     Validate an IR JSON graph file
  validate --config PATH    Validate a YAML pipeline config (checks registry)
  plugin list               List installed plugins
  migrate --config PATH     Convert YAML → IR JSON
  run --graph PATH          Execute a pipeline from IR JSON
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PYTHON = sys.executable  # venv/bin/python (same interpreter running pytest)
_CLI_MODULE = "app.cli.main"


def _run_cli(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Invoke the CLI as a subprocess and return the CompletedProcess."""
    return subprocess.run(
        [_PYTHON, "-m", _CLI_MODULE, *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


# ---------------------------------------------------------------------------
# Test: nodes command (list-nodes equivalent)
# ---------------------------------------------------------------------------

def test_nodes_exits_zero():
    """'nodes' command exits 0 and produces non-empty output. Req 13."""
    result = _run_cli("nodes")
    assert result.returncode == 0, (
        f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert len(result.stdout.strip()) > 0, "Expected non-empty output from 'nodes'"


# ---------------------------------------------------------------------------
# Test: validate --graph with valid IR JSON
# ---------------------------------------------------------------------------

def test_validate_valid_ir_exits_zero(tmp_path: Path):
    """'validate --graph' with a valid IR JSON exits 0. Req 13."""
    from app.core.ir.loader import CURRENT_IR_VERSION

    graph = {
        "schema_version": CURRENT_IR_VERSION,
        "metadata": {"name": "test", "seed": 0},
        "nodes": [{"id": "n0", "node_type": "audio_conditioner", "config": {}}],
        "edges": [],
    }
    p = tmp_path / "test.graph.json"
    p.write_text(json.dumps(graph))

    result = _run_cli("validate", "--graph", str(p))
    assert result.returncode == 0, (
        f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Test: validate with unknown node type exits non-zero
# ---------------------------------------------------------------------------

def test_validate_unknown_node_type_exits_nonzero(tmp_path: Path):
    """'validate --config' with an unknown node type exits non-zero. Req 13.

    The --config path triggers registry validation (unlike --graph which only
    does structural/Pydantic validation). An unknown node_type causes exit 1.
    """
    yaml_content = """\
pipeline:
  name: bad_pipeline
  seed: 0
  nodes:
    - type: nonexistent_xyz_node_type_abc
"""
    yaml_path = tmp_path / "bad.yaml"
    yaml_path.write_text(yaml_content)

    result = _run_cli("validate", "--config", str(yaml_path))
    assert result.returncode != 0, (
        f"Expected non-zero exit for unknown node type, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Test: plugin list exits 0
# ---------------------------------------------------------------------------

def test_plugin_list_exits_zero():
    """'plugin list' exits 0. Req 13."""
    result = _run_cli("plugin", "list")
    assert result.returncode == 0, (
        f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Test: migrate with valid YAML exits 0 and writes .graph.json
# ---------------------------------------------------------------------------

def test_migrate_valid_yaml_exits_zero(tmp_path: Path):
    """'migrate --config' with valid YAML exits 0 and writes .graph.json. Req 13."""
    yaml_content = """\
pipeline:
  name: test
  seed: 0
  nodes:
    - type: audio_conditioner
"""
    yaml_path = tmp_path / "pipeline.yaml"
    yaml_path.write_text(yaml_content)

    result = _run_cli("migrate", "--config", str(yaml_path))
    assert result.returncode == 0, (
        f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )

    # migrate derives output path: <stem>.graph.json in the same directory
    graph_json = tmp_path / "pipeline.graph.json"
    assert graph_json.exists(), (
        f".graph.json was not written to {graph_json}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Test: run with a valid IR JSON exits 0 (pipeline mocked via thread patch)
# ---------------------------------------------------------------------------

def test_run_valid_ir_exits_zero(tmp_path: Path):
    """'run --graph' with a valid IR JSON exits 0 when pipeline.run is mocked. Req 13."""
    from app.core.ir.loader import CURRENT_IR_VERSION
    from unittest.mock import patch, MagicMock
    import types

    graph = {
        "schema_version": CURRENT_IR_VERSION,
        "metadata": {"name": "cli_run_test", "seed": 0},
        "nodes": [{"id": "n0", "node_type": "audio_conditioner", "config": {}}],
        "edges": [],
    }
    graph_path = tmp_path / "run_test.graph.json"
    graph_path.write_text(json.dumps(graph))

    # Build minimal args namespace matching what argparse produces for 'run --graph PATH'
    args = types.SimpleNamespace(
        graph=str(graph_path),
        config=None,
        seed=None,
        parallel=False,
        resume_run_id=None,
        event_driven=False,
        include_nodes=None,
        exclude_nodes=None,
        use_cache=True,
        checkpoint=False,
        max_retries=None,
    )

    # Mock Pipeline.run so no real execution happens
    with patch("app.core.sdk.Pipeline.run", return_value=None):
        from app.cli.main import cmd_run
        try:
            cmd_run(args)
            exit_code = 0
        except SystemExit as e:
            exit_code = e.code if e.code is not None else 0

    assert exit_code == 0, f"Expected exit 0, got {exit_code}"
