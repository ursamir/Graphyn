
"""Tests for the wait_delay plugin."""
from __future__ import annotations
from unit_test.plugins._helpers import materialize_isolated_class

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/wait_delay/"
NODE_TYPE = "wait_delay"


@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("wait_delay_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_dir))
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return materialize_isolated_class(reg.get_class(NODE_TYPE))


def test_registers(tmp_plugin_dir, fresh_registry):
    mgr = PluginManager(registry=fresh_registry, base_dir=str(tmp_plugin_dir))
    mgr._plugins_dir = str(tmp_plugin_dir)
    mgr.install(PLUGIN_SOURCE)
    assert NODE_TYPE in fresh_registry


def test_metadata(installed_cls):
    meta = installed_cls.metadata
    assert meta.label and meta.category and meta.version

def test_cap_no_sleep(installed_cls):
    node = installed_cls(config={"seconds": 100, "max_seconds": 0}, seed=0)
    out = node.process({"input": {"keep": 1}})
    assert out["output"]["keep"] == 1
    assert out["receipt"].slept_s == 0
    assert out["receipt"].capped is True


def test_sleep_stops_on_run_cancel(installed_cls, monkeypatch):
    import time as _time

    class _Run:
        is_cancelled = False

    run = _Run()
    import app.core.runs.run_control as rc
    monkeypatch.setattr(rc, "get_active_run", lambda rid: run if rid == "r-1" else None)
    node = installed_cls(config={"seconds": 30.0, "max_seconds": 60.0}, seed=0)
    node._run_id = "r-1"
    calls = {"n": 0}
    real_sleep = _time.sleep

    def _fake_sleep(dt):
        calls["n"] += 1
        if calls["n"] == 2:
            run.is_cancelled = True
        real_sleep(0)

    monkeypatch.setattr(_time, "sleep", _fake_sleep)
    t0 = _time.monotonic()
    with pytest.raises(RuntimeError, match="cancelled"):
        node.process({"input": {"x": 1}})
    assert _time.monotonic() - t0 < 5
