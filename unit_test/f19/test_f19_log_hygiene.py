"""F19.30/31: clean container logs — the live log errors Samir asked about.

* mcp_tool_call failed in the API with "No module named 'mcp'": the in-process
  tool catalog must not need the optional MCP SDK (only the stdio server does).
* A cancelled/fenced Mode B completion (409) is an expected drop, not "failed".
* An isolated plugin failure logs one WARNING line; the traceback stays in the
  run journal (not repeated in the container log).
* python_code got csv_table's CsvTableResult and iterating it yielded tuples
  ("'tuple' object has no attribute 'get'"): table results reach user code as rows.
"""
from __future__ import annotations

import importlib
import logging
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]


def test_mcp_tool_catalog_imports_without_sdk():
    code = textwrap.dedent(
        """
        import importlib.abc, sys
        class _Block(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path=None, target=None):
                if name == "mcp" or name.startswith("mcp."):
                    raise ModuleNotFoundError(f"No module named {name!r}")
                return None
        sys.meta_path.insert(0, _Block())
        import app.mcp.server as srv
        assert srv.MCP_SDK_IMPORT_ERROR is not None
        tool = srv.get_tool("list_nodes")
        assert tool is not None and callable(tool["handler"]), sorted(srv._TOOLS)[:5]
        try:
            srv.main()
        except RuntimeError as exc:
            assert "MCP SDK" in str(exc), exc
            print("OK", len(srv._TOOLS))
        else:
            raise SystemExit("main() must refuse without the SDK")
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=180,
        env={**__import__("os").environ, "CUDA_VISIBLE_DEVICES": ""},
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    assert "OK" in proc.stdout


def test_mcp_server_with_sdk_still_wires_protocol():
    pytest.importorskip("mcp")
    import app.mcp.server as srv

    assert srv.MCP_SDK_IMPORT_ERROR is None
    assert callable(srv.handle_call_tool) and callable(srv.handle_list_tools)


def test_worker_409_completion_is_a_drop_not_a_failure():
    from app.cli.cmd_worker import WorkerHTTPError, _complete_report_message

    exc = WorkerHTTPError(409, 'HTTP 409 /jobs/j1/complete: {"error":{"code":"run_cancelled"}}')
    msg = _complete_report_message("j1", exc)
    assert "dropped" in msg and "run_cancelled" in msg
    assert "failed" not in msg.lower() and "error" not in msg.lower()
    fenced = _complete_report_message("j2", WorkerHTTPError(409, "HTTP 409 /jobs/j2/complete: lease fenced"))
    assert "dropped" in fenced and "failed" not in fenced
    real = _complete_report_message("j3", WorkerHTTPError(500, "HTTP 500 boom"))
    assert "failed" in real


def test_isolated_failure_warning_has_no_traceback(monkeypatch, caplog, tmp_path):
    import app.core.plugins.isolated_executor as iso

    src = Path(iso.__file__).read_text()
    # The WARNING format no longer appends the traceback; DEBUG carries it.
    assert '"Isolated plugin worker failed for \'%s\' (plugin=%s, exit=%s): %s",' in src
    assert "Isolated worker traceback for" in src


@pytest.fixture()
def pycode(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "PluginPackage" / "Common"))
    for m in [k for k in sys.modules if k == "python_code" or k.startswith("python_code.")]:
        monkeypatch.delitem(sys.modules, m)
    return importlib.import_module("python_code.nodes")


def _run(mod, source, payload):
    cfg = mod.PythonCodeNode.Config(source=source)
    try:
        node = mod.PythonCodeNode(config=cfg)
    except TypeError:
        node = mod.PythonCodeNode(cfg)
    return node.process({"input": payload})["output"].data


class _Csv(BaseModel):
    rows: list
    row_count: int = 0
    path: str = "x.csv"


def test_python_code_iterates_csv_rows(pycode):
    src = (
        "rows = inputs.get('input') or []\n"
        "output = [dict(r, score_band=('high' if float(r.get('score') or 0) >= 50 else 'low')) for r in rows]\n"
    )
    out = _run(pycode, src, _Csv(rows=[{"score": "70"}, {"score": "3"}], row_count=2))
    assert out == [{"score": "70", "score_band": "high"}, {"score": "3", "score_band": "low"}]


def test_python_code_keeps_attribute_access_and_plain_output(pycode):
    out = _run(pycode, "x = inputs['input']\noutput = {'n': x.row_count, 'p': x.path, 'r': len(x.rows), 'l': len(x)}", _Csv(rows=[{"a": 1}], row_count=1))
    assert out == {"n": 1, "p": "x.csv", "r": 1, "l": 1}
    passthrough = _run(pycode, "output = inputs['input']", _Csv(rows=[{"a": 1}]))
    assert type(passthrough) is list and passthrough == [{"a": 1}]


def test_python_code_leaves_plain_values_alone(pycode):
    assert _run(pycode, "output = inputs['input']", {"k": 1}) == {"k": 1}
    assert _run(pycode, "output = inputs['input']", [1, 2]) == [1, 2]
