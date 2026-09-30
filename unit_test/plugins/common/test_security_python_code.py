"""Regression tests: python_code namespace escape via injected real modules."""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager
from unit_test.plugins._helpers import materialize_isolated_class

PLUGIN_SOURCE = "PluginPackage/Common/python_code/"


@pytest.fixture(scope="module")
def cls(tmp_path_factory):
    from app.core.nodes.registry import NodeRegistry

    tmp_dir = tmp_path_factory.mktemp("python_code_sec")
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_dir))
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return materialize_isolated_class(reg.get_class("python_code"))


def _run(cls, src, **cfg):
    node = cls(config={"source": src, **cfg}, seed=0)
    return node.process({"input": {}})["output"].data


@pytest.mark.parametrize(
    "src",
    [
        "output = json.codecs.sys.modules['os'].getpid()",
        "output = json.codecs.open('/etc/hostname').read()",
        "output = json.decoder.re",
        "output = json._default_encoder",
        "import json\noutput = json.codecs",
        "g = (x for x in [1])\noutput = g.gi_frame.f_globals",
        "output = math.os",
        "output = inputs.posix_spawn",
        "import re",
        "import httpx",
        "from json import codecs",
    ],
)
def test_escape_attempts_rejected(cls, src):
    # RestrictedCodeError (AST/import filter) or AttributeError (wrapper lacks it)
    with pytest.raises((RuntimeError, AttributeError)):
        _run(cls, src)


def test_escape_rejected_even_with_allow_network_trusted(cls, monkeypatch):
    monkeypatch.setenv("GRAPHYN_HTTP_EGRESS_MODE", "trusted")
    with pytest.raises(RuntimeError):
        _run(cls, "import httpx\noutput = httpx", allow_network=True)


def test_json_and_math_wrappers_still_work(cls):
    src = (
        "import json\nfrom math import sqrt\n"
        "output = [json.loads(json.dumps({'a': 1})), math.floor(math.pi), sqrt(16)]"
    )
    assert _run(cls, src) == [{"a": 1}, 3, 4.0]


def test_injected_json_is_not_real_module(cls):
    import types

    out = _run(cls, "output = json")
    assert not isinstance(out, types.ModuleType)
    assert not hasattr(out, "codecs")
