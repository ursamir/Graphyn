"""Isolated workers get seed-derived reproducibility env + seeded global RNGs."""
from __future__ import annotations

import random

import numpy as np

from app.core.plugins import worker
from app.core.plugins.isolated_executor import apply_determinism_env


def test_apply_determinism_env_sets_hashseed_and_tf_flags(monkeypatch) -> None:
    monkeypatch.delenv("GRAPHYN_ISOLATED_DETERMINISTIC", raising=False)
    env = apply_determinism_env({"PYTHONHASHSEED": "random"}, 1234)
    assert env["PYTHONHASHSEED"] == "1234"
    assert env["TF_DETERMINISTIC_OPS"] == "1"
    assert env["TF_CUDNN_DETERMINISTIC"] == "1"
    assert env["GRAPHYN_NODE_SEED"] == "1234"


def test_apply_determinism_env_wraps_large_seed_and_keeps_operator_tf_values(monkeypatch) -> None:
    monkeypatch.delenv("GRAPHYN_ISOLATED_DETERMINISTIC", raising=False)
    env = apply_determinism_env({"TF_DETERMINISTIC_OPS": "0"}, 2**32 + 5)
    assert env["PYTHONHASHSEED"] == "5"
    assert env["TF_DETERMINISTIC_OPS"] == "0"


def test_apply_determinism_env_opt_out(monkeypatch) -> None:
    monkeypatch.setenv("GRAPHYN_ISOLATED_DETERMINISTIC", "0")
    env = apply_determinism_env({}, 7)
    assert env == {}


def test_worker_seed_process_seeds_random_and_numpy(monkeypatch) -> None:
    monkeypatch.delenv("GRAPHYN_ISOLATED_DETERMINISTIC", raising=False)
    worker._seed_process(42)
    a = (random.random(), np.random.rand())
    worker._seed_process(42)
    b = (random.random(), np.random.rand())
    assert a == b


def test_run_isolated_node_passes_env_to_subprocess(monkeypatch, tmp_path) -> None:
    """The env handed to the worker subprocess carries the node seed."""
    import subprocess

    from app.core.plugins import isolated_executor as ie
    from app.core.plugins.runtime_registry import IsolatedPluginSpec

    monkeypatch.delenv("GRAPHYN_ISOLATED_DETERMINISTIC", raising=False)
    seen: dict = {}

    def fake_run(cmd, *, env, timeout, cancel_check=None, on_progress=None):
        seen.update(env)
        return subprocess.CompletedProcess(cmd, 1, "", "boom")

    monkeypatch.setattr(ie, "_run_isolated_subprocess", fake_run)
    spec = IsolatedPluginSpec(
        plugin_name="p", install_path=str(tmp_path), venv_python="python", node_types=("x",)
    )
    try:
        ie.run_isolated_node(spec, node_type="x", config={}, seed=99, inputs={})
    except Exception:
        pass
    assert seen["PYTHONHASHSEED"] == "99"
    assert seen["TF_DETERMINISTIC_OPS"] == "1"
