# unit_test/f19/test_f19_cancel_log_level.py
"""F19: a requested cancel of a Mode B run logged ``ERROR ... FAILED`` in the API
container log. Cancellation is an expected outcome: INFO ``CANCELLED``; real
failures still log ERROR."""
from __future__ import annotations

import logging

from app.core.logger import PipelineLogger


def _levels(caplog):
    return [(r.levelno, r.getMessage()) for r in caplog.records if r.name == "app.core.logger"]


def test_cancelled_remote_job_logs_info(caplog):
    exc = RuntimeError("Distributed job j1 (node=ff) ended with status=cancelled: cancelled by control plane")
    exc.cancelled = True
    with caplog.at_level(logging.DEBUG, logger="app.core.logger"):
        PipelineLogger().node_error("feature_frontend", 1, exc, node_id="ff")
    lv = _levels(caplog)
    assert any(l == logging.INFO and "CANCELLED" in m for l, m in lv)
    assert not any(l >= logging.ERROR for l, _ in lv)


def test_real_failure_still_logs_error(caplog):
    with caplog.at_level(logging.DEBUG, logger="app.core.logger"):
        PipelineLogger().node_error("trainer", 4, ValueError("boom"), node_id="tr")
    assert any(l == logging.ERROR and "FAILED: boom" in m for l, m in _levels(caplog))
