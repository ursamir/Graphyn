
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


def test_metadata_does_not_claim_sandbox(installed_cls):
    """SEC-002: UI/metadata must not market AST filters as a sandbox."""
    meta = installed_cls.metadata
    blob = " ".join(
        str(x).lower()
        for x in (meta.description, meta.label, getattr(meta, "long_description", "") or "")
    )
    assert "sandbox" not in blob or "not a sandbox" in blob
    assert "trusted" in blob or "defense" in blob or "not a sandbox" in blob


def test_blocks_eval_exec_compile(installed_cls):
    for src in ("output = eval('1')", "exec('x=1')", "compile('1', '<x>', 'eval')"):
        node = installed_cls(config={"source": src}, seed=0)
        with pytest.raises(RuntimeError, match="not allowed"):
            node.process({"input": {}})


def test_blocks_dunder_attr(installed_cls):
    node = installed_cls(config={"source": "output = ().__class__"}, seed=0)
    with pytest.raises(RuntimeError, match="[Dd]under|not allowed"):
        node.process({"input": {}})


def test_trust_model_docstring():
    """SEC-002: module documents trusted-operator / not-a-sandbox posture."""
    from pathlib import Path
    # Source of truth after install is the package tree we ship.
    src = Path("PluginPackage/Common/python_code/nodes.py").read_text(encoding="utf-8")
    assert "not a security sandbox" in src.lower() or "not a sandbox" in src.lower()
    assert "trusted-operator" in src.lower() or "trusted operator" in src.lower()
    assert "AST-validated sandbox" not in src
