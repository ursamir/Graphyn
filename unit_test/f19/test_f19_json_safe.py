# unit_test/f19/test_f19_json_safe.py
"""F19 (found live): one run's evaluator wrote ``roc_auc: NaN`` into meta.json and
logs.json, and every ``GET /api/v1/runs`` page containing it returned 500
(``Out of range float values are not JSON compliant: nan``).
"""
from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pytest

from app.api.safe_json import SafeJSONResponse
from app.core.utils.json_safe import has_non_finite, json_safe

ROOT = Path(__file__).resolve().parents[2]


def test_json_safe_replaces_non_finite_everywhere():
    data = {"a": float("nan"), "b": [1.0, float("inf"), (np.float64("nan"), -float("inf"))],
            "c": {"ok": 0.5, "s": "NaN", "n": None, "i": 3}}
    out = json_safe(data)
    assert out == {"a": None, "b": [1.0, None, [None, None]], "c": {"ok": 0.5, "s": "NaN", "n": None, "i": 3}}
    assert has_non_finite(data) and not has_non_finite(out)
    json.dumps(out, allow_nan=False)


def test_safe_response_renders_null_and_is_the_app_default():
    body = SafeJSONResponse({"roc_auc": float("nan"), "acc": 0.9}).body
    assert json.loads(body) == {"roc_auc": None, "acc": 0.9}
    from app.api.main import app

    dflt = app.router.default_response_class
    assert getattr(dflt, "value", dflt) is SafeJSONResponse


def _write_run(root: Path, run_id: str) -> None:
    d = root / run_id
    d.mkdir(parents=True)
    meta = {"run_id": run_id, "status": "succeeded", "graph_name": "nan-run",
            "created_at": "2026-10-08T11:55:01+00:00",
            "node_progress": {"evaluator_0": {"accuracy": 0.5, "roc_auc": float("nan")}}}
    (d / "meta.json").write_text(json.dumps(meta))  # Python writes bare NaN, like the old journal
    (d / "logs.json").write_text(json.dumps([{"node": "evaluator_0", "roc_auc": float("nan")}]))


def test_runs_list_and_detail_survive_nan_meta(api_client, tmp_path, monkeypatch, real_threads):
    runs = tmp_path / "runs"
    rid = "4d18af75770a4d31a00e0bdb67bcaf94"
    _write_run(runs, rid)
    monkeypatch.setattr("app.api.routers.runs._get_runs_root", lambda: runs)
    for q in ("?limit=12", "?limit=60&offset=0"):
        r = api_client.get(f"/api/v1/runs{q}")
        assert r.status_code == 200, r.text
        row = next(x for x in r.json() if x["run_id"] == rid)
        assert row["node_progress"]["evaluator_0"]["roc_auc"] is None
    d = api_client.get(f"/api/v1/runs/{rid}")
    assert d.status_code == 200, d.text
    assert "NaN" not in d.text


def test_run_journal_never_writes_nan(tmp_path):
    from app.core.runs import run_journal as rj

    cls = next(c for c in vars(rj).values() if isinstance(c, type) and hasattr(c, "_write_meta_unlocked"))
    path = tmp_path / "meta.json"
    cls._write_meta_unlocked(object(), {"m": {"roc_auc": float("nan")}}, str(path), str(path) + ".tmp")
    text = path.read_text()
    assert "NaN" not in text and json.loads(text) == {"m": {"roc_auc": None}}


def test_evaluator_omits_undefined_roc_auc(monkeypatch):
    pytest.importorskip("sklearn")
    spec = importlib.util.spec_from_file_location(
        "f19_eval_nodes", ROOT / "PluginPackage/Common/evaluator/nodes.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import sklearn.metrics

    node_cls = next(v for k, v in vars(mod).items() if isinstance(v, type) and hasattr(v, "_compute_roc_auc"))
    monkeypatch.setattr(sklearn.metrics, "roc_auc_score", lambda *a, **k: float("nan"))
    probs = np.array([[0.2, 0.8], [0.6, 0.4]])
    assert node_cls._compute_roc_auc(None, np.array([1, 1]), probs, 2) is None
    monkeypatch.setattr(sklearn.metrics, "roc_auc_score", lambda *a, **k: 0.75)
    assert math.isclose(node_cls._compute_roc_auc(None, np.array([0, 1]), probs, 2), 0.75)
