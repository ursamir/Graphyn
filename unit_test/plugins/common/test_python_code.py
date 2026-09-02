
"""Tests for the python_code plugin."""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/python_code/"
NODE_TYPE = "python_code"


@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("python_code_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_dir))
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


def test_registers(tmp_plugin_dir, fresh_registry):
    mgr = PluginManager(registry=fresh_registry, base_dir=str(tmp_plugin_dir))
    mgr._plugins_dir = str(tmp_plugin_dir)
    mgr.install(PLUGIN_SOURCE)
    assert NODE_TYPE in fresh_registry


def test_metadata(installed_cls):
    meta = installed_cls.metadata
    assert meta.label and meta.category and meta.version

def test_sets_output(installed_cls):
    node = installed_cls(config={"source": "output = inputs['input']['n'] * 2"}, seed=0)
    out = node.process({"input": {"n": 4}})["output"].data
    assert out == 8


def test_process_fn(installed_cls):
    src = "def process(inputs, config):\n    return inputs['input']['x'] + 1\n"
    node = installed_cls(config={"source": src}, seed=0)
    out = node.process({"input": {"x": 10}})["output"].data
    assert out == 11


def test_blocks_os_system(installed_cls):
    node = installed_cls(config={"source": "import os\nos.system('echo hi')"}, seed=0)
    with pytest.raises(RuntimeError, match="not allowed"):
        node.process({"input": {}})


def test_blocks_subprocess(installed_cls):
    node = installed_cls(config={"source": "import subprocess\nsubprocess.call(['true'])"}, seed=0)
    with pytest.raises(RuntimeError, match="not allowed"):
        node.process({"input": {}})


def test_open_requires_allowed_paths(installed_cls):
    node = installed_cls(config={"source": "output = open('/etc/passwd').read()"}, seed=0)
    with pytest.raises(RuntimeError):
        node.process({"input": {}})
