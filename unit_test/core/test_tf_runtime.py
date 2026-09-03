# unit_test/core/test_tf_runtime.py
"""VRAM-aware Keras device selection without importing real TensorFlow/CUDA."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.core.tf_runtime as tf_runtime


class _FakeGPU:
    name = "/physical_device:GPU:0"


def _fake_tf(*, gpus=None, cc=(8, 6), growth_error=None):
    gpus = [_FakeGPU()] if gpus is None else gpus
    experimental = MagicMock()
    if growth_error:
        experimental.set_memory_growth.side_effect = growth_error
    else:
        experimental.set_memory_growth.return_value = None
    experimental.get_device_details.return_value = {"compute_capability": cc}

    config = MagicMock()
    config.list_physical_devices.side_effect = lambda kind: list(gpus) if kind == "GPU" else []
    config.experimental = experimental
    config.set_logical_device_configuration = MagicMock()
    config.LogicalDeviceConfiguration = lambda memory_limit: SimpleNamespace(
        memory_limit=memory_limit
    )
    return SimpleNamespace(config=config)


@pytest.fixture
def reset_tf_runtime(monkeypatch):
    tf_runtime._configured = False
    tf_runtime._gpu_sharing_configured = False
    tf_runtime._memory_growth_enabled = False
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    monkeypatch.delenv("GRAPHYN_TF_DEVICE", raising=False)
    monkeypatch.delenv("GRAPHYN_TF_FORCE_GPU", raising=False)
    monkeypatch.delenv("GRAPHYN_TF_GPU_MIN_FREE_MIB", raising=False)
    monkeypatch.delenv("GRAPHYN_TF_GPU_MAX_MIB", raising=False)
    yield
    tf_runtime._configured = False
    tf_runtime._gpu_sharing_configured = False
    tf_runtime._memory_growth_enabled = False


def _fake_nvidia_smi(monkeypatch, stdout: str):
    completed = MagicMock()
    completed.returncode = 0
    completed.stdout = stdout
    completed.stderr = ""

    def fake_run(cmd, **kwargs):
        assert cmd[0] == "nvidia-smi"
        assert kwargs.get("timeout") == 2.0
        return completed

    monkeypatch.setattr(tf_runtime.subprocess, "run", fake_run)


def test_nvidia_smi_low_free_vram_selects_cpu(monkeypatch, reset_tf_runtime):
    fake = _fake_tf()
    monkeypatch.setitem(__import__("sys").modules, "tensorflow", fake)
    _fake_nvidia_smi(monkeypatch, "1024\n")
    monkeypatch.setenv("GRAPHYN_TF_GPU_MIN_FREE_MIB", "4096")
    assert tf_runtime.select_keras_device("auto") == "/CPU:0"
    assert __import__("os").environ.get("CUDA_VISIBLE_DEVICES") != "-1"


def test_nvidia_smi_high_free_vram_selects_gpu(monkeypatch, reset_tf_runtime):
    fake = _fake_tf()
    monkeypatch.setitem(__import__("sys").modules, "tensorflow", fake)
    _fake_nvidia_smi(monkeypatch, "8192\n")
    monkeypatch.setenv("GRAPHYN_TF_GPU_MIN_FREE_MIB", "4096")
    assert tf_runtime.select_keras_device("auto") == "/GPU:0"


def test_free_vram_parser_uses_nvidia_smi(monkeypatch, reset_tf_runtime):
    completed = MagicMock()
    completed.returncode = 0
    completed.stdout = "  512\n"
    completed.stderr = ""

    def fake_run(cmd, **kwargs):
        assert cmd[0] == "nvidia-smi"
        assert "--query-gpu=memory.free" in cmd
        assert kwargs.get("timeout") == 2.0
        return completed

    monkeypatch.setattr(tf_runtime.subprocess, "run", fake_run)
    assert tf_runtime._free_vram_mib() == 512


def test_cpu_device_is_only_path_setting_cuda_visible_negative_one(
    monkeypatch, reset_tf_runtime
):
    monkeypatch.setenv("GRAPHYN_TF_DEVICE", "cpu")
    tf_runtime.configure_tf_stable_defaults()
    assert __import__("os").environ.get("CUDA_VISIBLE_DEVICES") == "-1"


def test_auto_device_does_not_hide_gpus(monkeypatch, reset_tf_runtime):
    tf_runtime.configure_tf_stable_defaults()
    assert __import__("os").environ.get("CUDA_VISIBLE_DEVICES") != "-1"


def test_gpu_max_mib_skipped_when_memory_growth_enabled(monkeypatch, reset_tf_runtime):
    fake = _fake_tf()
    monkeypatch.setitem(__import__("sys").modules, "tensorflow", fake)
    monkeypatch.setenv("GRAPHYN_TF_GPU_MAX_MIB", "2048")
    monkeypatch.setattr(tf_runtime, "_free_vram_mib", lambda: 8192)
    assert tf_runtime.select_keras_device("auto") == "/GPU:0"
    fake.config.set_logical_device_configuration.assert_not_called()
    fake.config.experimental.set_memory_growth.assert_called()
