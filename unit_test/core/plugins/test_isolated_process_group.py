# unit_test/core/plugins/test_isolated_process_group.py
"""Isolated worker subprocess uses a process group and reaps it on timeout."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from app.core.plugins import isolated_executor as iso


def test_run_isolated_subprocess_start_new_session():
    proc = MagicMock()
    proc.pid = 4242
    proc.returncode = 0
    proc.communicate.return_value = ("", "")
    with patch("app.core.plugins.isolated_executor.subprocess.Popen", return_value=proc) as popen:
        result = iso._run_isolated_subprocess(["python", "-m", "app.core.plugins.worker"], env={}, timeout=12)
    popen.assert_called_once()
    assert popen.call_args.kwargs["start_new_session"] is True
    assert result.returncode == 0
    proc.communicate.assert_called_once_with(timeout=12)


def test_run_isolated_subprocess_kills_group_on_timeout():
    proc = MagicMock()
    proc.pid = 777
    proc.returncode = None
    proc.communicate.side_effect = [
        subprocess.TimeoutExpired(cmd="x", timeout=1),
        ("", ""),
    ]
    with patch("app.core.plugins.isolated_executor.subprocess.Popen", return_value=proc):
        with patch("app.core.plugins.isolated_executor.terminate_process_group") as term:
            with pytest.raises(RuntimeError, match="timed out"):
                iso._run_isolated_subprocess(["python"], env={}, timeout=1)
            term.assert_called_with(777)


def test_run_isolated_subprocess_kills_group_on_nonzero():
    proc = MagicMock()
    proc.pid = 9
    proc.returncode = 1
    proc.communicate.return_value = ("", "boom")
    with patch("app.core.plugins.isolated_executor.subprocess.Popen", return_value=proc):
        with patch("app.core.plugins.isolated_executor.terminate_process_group") as term:
            result = iso._run_isolated_subprocess(["python"], env={}, timeout=5)
    assert result.returncode == 1
    term.assert_called_with(9)
