"""ExperimentTrackerNode — log experiment parameters, metrics, and artifacts.

Backends:
    json   — write to workspace/runs/{run_id}/experiment.json (default, no deps)
    mlflow — call mlflow.log_params/metrics/artifact (requires mlflow)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

# Import ExperimentArtifact using the plugin package prefix (loaded by AutoDiscovery)
try:
    from experiment_tracker.types import ExperimentArtifact  # type: ignore
except ImportError:
    from .types import ExperimentArtifact  # type: ignore

log = logging.getLogger(__name__)


class ExperimentTrackerNode(Node):
    """Log experiment parameters, metrics, and artifacts for reproducibility.

    Accepts a ModelArtifact or DatasetArtifact (or any object with a .metadata dict)
    and logs its contents to a JSON file or MLflow.

    Config:
        backend (str): "json" | "mlflow"
        experiment_name (str): experiment name (default "default")
        tracking_uri (str): MLflow tracking URI (mlflow backend only)
        log_artifacts (bool): log artifact file paths (default True)
        output_dir (str): base directory for JSON backend run files
    """

    node_type: ClassVar[str] = "experiment_tracker"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="experiment_tracker",
        label="Experiment Tracker",
        description=(
            "Log experiment parameters, metrics, and artifacts. "
            "JSON backend (default) or MLflow."
        ),
        category="ML",
        version="1.0.0",
        tags=["ml", "experiment", "tracking", "mlflow", "governance"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=False,
        deterministic=True,
        cacheable=False,
        streaming_support=False,
        realtime_support=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=object,
            cardinality="single",
            required=True,
            description="ModelArtifact or DatasetArtifact to log",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=object,
            description="ExperimentArtifact with run_id, parameters, metrics, artifact_paths",
        )
    }

    class Config(NodeConfig):
        backend: str = "json"           # "json" | "mlflow"
        experiment_name: str = "default"
        tracking_uri: str = ""          # MLflow tracking URI
        log_artifacts: bool = True
        output_dir: str = "workspace/runs"

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def setup(self) -> None:
        """Capture environment info once at setup time."""
        self._env_meta = self._capture_env()

    # ── SISO process ──────────────────────────────────────────────────────────

    def process(self, artifact):
        run_id = self._make_run_id()
        params, metrics, artifact_paths = self._extract(artifact)

        # Use pre-captured env from setup(); fall back if setup() was not called
        env_meta = getattr(self, "_env_meta", None) or self._capture_env()

        if self.config.backend == "mlflow":
            try:
                self._log_mlflow(run_id, params, metrics, artifact_paths)
            except Exception as exc:
                log.warning(
                    "ExperimentTrackerNode: MLflow logging failed (%s). "
                    "Falling back to JSON backend.",
                    exc,
                )
                self._log_json(run_id, params, metrics, artifact_paths, env_meta)
        else:
            self._log_json(run_id, params, metrics, artifact_paths, env_meta)

        return ExperimentArtifact(
            run_id=run_id,
            experiment_name=self.config.experiment_name,
            parameters=params,
            metrics=metrics,
            artifact_paths=artifact_paths,
            backend=self.config.backend,
            metadata={**env_meta, "source_type": type(artifact).__name__},
        )

    # ── extraction ────────────────────────────────────────────────────────────

    def _extract(self, artifact) -> tuple[dict, dict, dict]:
        """Extract parameters, metrics, and artifact paths from any artifact object."""
        meta = getattr(artifact, "metadata", {}) or {}
        params: dict = {}
        metrics: dict = {}
        artifact_paths: dict = {}

        # ModelArtifact fields
        if hasattr(artifact, "model_path") and artifact.model_path:
            artifact_paths["model"] = str(artifact.model_path)
        if hasattr(artifact, "history") and artifact.history:
            history = artifact.history
            if isinstance(history, dict):
                for k, v in history.items():
                    metrics[k] = v
        if hasattr(artifact, "metrics") and artifact.metrics:
            for k, v in artifact.metrics.items():
                metrics[k] = v
        if hasattr(artifact, "labels") and artifact.labels:
            params["labels"] = artifact.labels
            params["n_classes"] = len(artifact.labels)

        # DatasetArtifact fields
        if hasattr(artifact, "n_classes"):
            params["n_classes"] = artifact.n_classes
        if hasattr(artifact, "input_shape") and artifact.input_shape:
            params["input_shape"] = list(artifact.input_shape)
        if hasattr(artifact, "version") and artifact.version:
            params["dataset_version"] = artifact.version
        if hasattr(artifact, "content_hash") and artifact.content_hash:
            params["dataset_hash"] = artifact.content_hash
        elif hasattr(artifact, "hash") and artifact.hash:
            # backward compat with older DatasetArtifact instances
            params["dataset_hash"] = artifact.hash

        # Metadata extras
        for k, v in meta.items():
            if isinstance(v, (int, float, str, bool)):
                params[k] = v
            elif isinstance(v, dict):
                for kk, vv in v.items():
                    if isinstance(vv, (int, float, str, bool)):
                        metrics[f"{k}.{kk}"] = vv

        if self.config.log_artifacts:
            if hasattr(artifact, "manifest_path") and artifact.manifest_path:
                artifact_paths["manifest"] = str(artifact.manifest_path)

        return params, metrics, artifact_paths

    # ── JSON backend ──────────────────────────────────────────────────────────

    def _log_json(
        self,
        run_id: str,
        params: dict,
        metrics: dict,
        artifact_paths: dict,
        env_meta: dict,
    ) -> None:
        run_dir = Path(self.config.output_dir) / run_id
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise OSError(
                f"ExperimentTrackerNode: cannot create run directory '{run_dir}': {e}"
            ) from e
        record = {
            "run_id": run_id,
            "experiment_name": self.config.experiment_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "parameters": params,
            "metrics": metrics,
            "artifact_paths": artifact_paths,
            "environment": env_meta,
        }
        out_path = run_dir / "experiment.json"
        with open(out_path, "w") as f:
            json.dump(record, f, indent=2, default=str)
        log.info("ExperimentTrackerNode: logged run %s → %s", run_id, out_path)

    # ── MLflow backend ────────────────────────────────────────────────────────

    def _log_mlflow(
        self,
        run_id: str,
        params: dict,
        metrics: dict,
        artifact_paths: dict,
    ) -> None:
        try:
            import mlflow  # type: ignore
        except ImportError:
            raise ImportError(
                "ExperimentTrackerNode: 'mlflow' required for backend='mlflow'. "
                "Install with: pip install mlflow>=2.0"
            )

        if self.config.tracking_uri:
            mlflow.set_tracking_uri(self.config.tracking_uri)

        mlflow.set_experiment(self.config.experiment_name)

        with mlflow.start_run(run_name=run_id):
            # Log params (mlflow requires string values, max 500 chars per value)
            flat_params = {k: str(v)[:500] for k, v in params.items()}
            if flat_params:
                mlflow.log_params(flat_params)

            # Log metrics (must be numeric)
            for k, v in metrics.items():
                if isinstance(v, (int, float)):
                    mlflow.log_metric(k, float(v))
                elif isinstance(v, list) and all(isinstance(x, (int, float)) for x in v):
                    for step, val in enumerate(v):
                        mlflow.log_metric(k, float(val), step=step)
                else:
                    log.debug(
                        "ExperimentTrackerNode: skipping non-numeric metric '%s' (type=%s) "
                        "from MLflow — present in JSON backend only",
                        k, type(v).__name__,
                    )

            # Log artifacts
            if self.config.log_artifacts:
                for name, path in artifact_paths.items():
                    if Path(path).exists():
                        mlflow.log_artifact(path, artifact_path=name)

        log.info("ExperimentTrackerNode: MLflow run %s logged", run_id)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _make_run_id(self) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        suffix = hashlib.sha256(ts.encode()).hexdigest()[:6]
        return f"{self.config.experiment_name}_{ts}_{suffix}"

    def _capture_env(self) -> dict:
        env: dict = {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
        }
        # Git hash (best-effort)
        try:
            git_hash = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
                timeout=1,
            ).decode().strip()
            env["git_hash"] = git_hash
        except Exception:
            pass
        return env
