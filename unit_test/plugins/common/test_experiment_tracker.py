# unit_test/plugins/common/test_experiment_tracker.py
"""Tests for the experiment_tracker plugin.

Covers:
  - Registration (Req 8.8)
  - Metadata (Req 8.12)
  - Construction and smoke process
  - Req 10.7: artifact creation — non-empty run_id
"""
from __future__ import annotations
from unit_test.plugins._helpers import materialize_isolated_class

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/experiment_tracker/"
NODE_TYPE = "experiment_tracker"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("experiment_tracker_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_dir))
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return materialize_isolated_class(reg.get_class(NODE_TYPE))


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 8.8 — experiment_tracker registers in a fresh registry."""
    mgr = PluginManager(registry=fresh_registry, base_dir=str(tmp_plugin_dir))
    mgr._plugins_dir = str(tmp_plugin_dir)
    mgr.install(PLUGIN_SOURCE)
    assert NODE_TYPE in fresh_registry


# ── metadata ─────────────────────────────────────────────────────────────────

def test_metadata(installed_cls):
    """Req 8.12 — metadata fields are non-empty."""
    meta = installed_cls.metadata
    assert meta.label
    assert meta.category
    assert meta.version


# ── construction ─────────────────────────────────────────────────────────────

def test_construct(installed_cls):
    node = installed_cls(config={}, seed=0)
    assert node is not None


# ── smoke process ─────────────────────────────────────────────────────────────

def test_process_smoke(installed_cls, tmp_path):
    from app.models.model_artifact import ModelArtifact
    artifact = ModelArtifact(
        model_path="/fake/model",
        labels=["a", "b"],
        history={"loss": [0.5], "val_loss": [0.4]},
        metrics={"test_accuracy": 0.9},
    )
    node = installed_cls(
        config={
            "backend": "json",
            "output_dir": str(tmp_path / "runs"),
        },
        seed=0,
    )
    result = node.process({"input": artifact})
    assert result is not None


# ── Req 10.7: artifact creation — non-empty run_id ───────────────────────────

def test_run_id_non_empty(installed_cls, tmp_path):
    """Req 10.7 — ExperimentTrackerNode produces ExperimentArtifact with non-empty run_id."""
    from app.models.model_artifact import ModelArtifact
    artifact = ModelArtifact(
        model_path="/fake/model",
        labels=["a", "b"],
        history={"loss": [0.5]},
        metrics={"test_accuracy": 0.85},
    )
    node = installed_cls(
        config={"backend": "json", "output_dir": str(tmp_path / "runs")},
        seed=0,
    )
    result = node.process({"input": artifact})["output"]
    assert result.run_id, (
        f"ExperimentArtifact.run_id should be non-empty, got {result.run_id!r}"
    )


def test_run_id_unique_per_call(installed_cls, tmp_path):
    """Each call to process() should produce a unique run_id."""
    from app.models.model_artifact import ModelArtifact
    artifact = ModelArtifact(model_path="/fake/model", labels=["a"])

    node = installed_cls(
        config={"backend": "json", "output_dir": str(tmp_path / "runs")},
        seed=0,
    )
    result1 = node.process({"input": artifact})["output"]
    result2 = node.process({"input": artifact})["output"]

    assert result1.run_id != result2.run_id, (
        "Each process() call should produce a unique run_id"
    )


def test_experiment_name_propagated(installed_cls, tmp_path):
    """experiment_name config is reflected in the output artifact."""
    from app.models.model_artifact import ModelArtifact
    artifact = ModelArtifact(model_path="/fake/model", labels=["a"])

    node = installed_cls(
        config={
            "backend": "json",
            "experiment_name": "my_experiment",
            "output_dir": str(tmp_path / "runs"),
        },
        seed=0,
    )
    result = node.process({"input": artifact})["output"]
    assert result.experiment_name == "my_experiment"


# ── JSON record content + MLflow (no silent fallback) ────────────────────────

def test_json_record_written(installed_cls, tmp_path):
    import json
    from app.models.model_artifact import ModelArtifact

    node = installed_cls(config={"backend": "json", "output_dir": str(tmp_path / "runs")}, seed=0)
    out = node.process({"input": ModelArtifact(model_path="/m", labels=["a", "b"],
                                               metrics={"test_accuracy": 0.9})})["output"]
    rec = json.loads(open(out.metadata["record_path"]).read())
    assert rec["run_id"] == out.run_id and rec["metrics"]["test_accuracy"] == 0.9
    assert rec["parameters"]["n_classes"] == 2


class _FakeMlflow:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    def set_tracking_uri(self, uri):
        self.calls.append(("uri", uri))

    def set_experiment(self, name):
        if self.fail:
            raise ConnectionError("tracking server down")
        self.calls.append(("exp", name))

    def start_run(self, run_name):
        fake = self

        class _Run:
            info = type("I", (), {"run_id": "mlf-123"})()

            def __enter__(self):
                fake.calls.append(("run", run_name))
                return self

            def __exit__(self, *a):
                return False
        return _Run()

    def log_params(self, p):
        self.calls.append(("params", p))

    def log_metric(self, k, v, step=None):
        self.calls.append(("metric", k, v, step))

    def log_artifact(self, path, artifact_path=None):
        self.calls.append(("artifact", artifact_path))

    def log_artifacts(self, path, artifact_path=None):
        self.calls.append(("artifacts", artifact_path))


def test_mlflow_backend_logs_to_local_store(installed_cls, tmp_path, monkeypatch):
    import sys
    from app.models.model_artifact import ModelArtifact

    fake = _FakeMlflow()
    monkeypatch.setitem(sys.modules, "mlflow", fake)
    node = installed_cls(config={"backend": "mlflow", "output_dir": str(tmp_path / "runs")}, seed=0)
    out = node.process({"input": ModelArtifact(model_path="/m", labels=["a"],
                                               history={"loss": [0.5, 0.25]})})["output"]
    assert out.metadata["mlflow_run_id"] == "mlf-123"
    assert out.metadata["tracking_uri"].startswith("file://") and "mlruns" in out.metadata["tracking_uri"]
    assert ("metric", "loss", 0.25, 1) in fake.calls
    assert not (tmp_path / "runs" / out.run_id / "experiment.json").exists()


def test_mlflow_failure_raises_no_json_fallback(installed_cls, tmp_path, monkeypatch):
    import sys
    from app.models.model_artifact import ModelArtifact

    monkeypatch.setitem(sys.modules, "mlflow", _FakeMlflow(fail=True))
    node = installed_cls(config={"backend": "mlflow", "output_dir": str(tmp_path / "runs")}, seed=0)
    with pytest.raises(RuntimeError, match="MLflow logging .* failed"):
        node.process({"input": ModelArtifact(model_path="/m", labels=["a"])})
    assert not list((tmp_path / "runs").glob("*/experiment.json"))


def test_mlflow_missing_package_is_clear(installed_cls, tmp_path, monkeypatch):
    import sys
    from app.models.model_artifact import ModelArtifact

    monkeypatch.setitem(sys.modules, "mlflow", None)
    node = installed_cls(config={"backend": "mlflow", "output_dir": str(tmp_path / "runs")}, seed=0)
    with pytest.raises(RuntimeError, match="mlflow-skinny"):
        node.process({"input": ModelArtifact(model_path="/m", labels=["a"])})
