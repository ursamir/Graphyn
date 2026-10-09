# unit_test/f19/test_f19_needs_credentials_log.py
"""F19: a node that fails only because a connection/secret is not configured
(NeedsCredentialsError — the catalog's "needs-credentials" state) logs a WARNING,
not ERROR, in the server log. The run still fails with the full message; real
failures still log ERROR."""
from __future__ import annotations

import logging

from app.core.credentials.errors import NeedsCredentialsError
from app.core.logger import PipelineLogger, _needs_credentials


def _levels(caplog):
    return [(r.levelno, r.getMessage()) for r in caplog.records if r.name == "app.core.logger"]


def _log(caplog, exc):
    with caplog.at_level(logging.DEBUG, logger="app.core.logger"):
        PipelineLogger().node_error("mcp_tool_call", 2, exc, node_id="n2")
    return _levels(caplog)


def test_needs_credentials_logs_warning(caplog):
    lv = _log(caplog, NeedsCredentialsError("needs-credentials: no connection for kind='graphyn_mcp'"))
    assert any(l == logging.WARNING and "FAILED (needs credentials)" in m for l, m in lv)
    assert not any(l >= logging.ERROR for l, _ in lv)


def test_chained_needs_credentials_logs_warning(caplog):
    try:
        try:
            raise NeedsCredentialsError("no key")
        except NeedsCredentialsError as inner:
            raise RuntimeError("asr_transcribe: provider needs OPENAI_API_KEY") from inner
    except RuntimeError as outer:
        lv = _log(caplog, outer)
    assert not any(l >= logging.ERROR for l, _ in lv)


def test_isolated_needs_credentials_traceback_logs_warning():
    exc = RuntimeError("provider='openai_compat' requires a connection")
    exc.error_type = "RuntimeError"
    exc.traceback_text = (
        "Traceback (most recent call last):\n"
        "app.core.credentials.errors.NeedsCredentialsError: needs-credentials\n\n"
        "The above exception was the direct cause of the following exception:\n"
        "RuntimeError: provider='openai_compat' requires a connection\n"
    )
    assert _needs_credentials(exc)


def test_other_failures_still_error(caplog):
    lv = _log(caplog, RuntimeError("needs credentials mentioned in text only"))
    assert any(l == logging.ERROR for l, _ in lv)
    assert not _needs_credentials(ValueError("x"))
