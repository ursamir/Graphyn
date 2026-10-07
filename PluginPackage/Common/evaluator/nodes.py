# PluginPackage/Common/evaluator/nodes.py
"""EvaluatorNode — evaluate trained models with comprehensive metrics.

Migrated from app/core/nodes/ml/model_evaluator.py and expanded with:
  - ROC/AUC computation (sklearn roc_auc_score, multi_class="ovr", average="macro")
  - Fairness evaluation (per-group accuracy by metadata attribute)
  - Absorbs confusion_matrix_node.py and training_curves_node.py logic
  - Saves metrics.json to output_path

DatasetArtifact is the platform type ``app.models.dataset_artifact``.
"""
# NOTE: No `from __future__ import annotations` — avoids Pydantic forward-ref issues.

import json
import logging
from pathlib import Path
from typing import ClassVar
from pydantic import Field

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.dataset_artifact import DatasetArtifact
from app.models.artifact_ref import ArtifactRef
from app.models.model_artifact import ModelArtifact

log = logging.getLogger(__name__)

# ── progress events (Runs UI) ─────────────────────────────────────────────────
try:
    from app.core.nodes.progress import emit_node_progress
except ImportError:  # pragma: no cover - host predates progress events
    def emit_node_progress(payload: dict) -> None:  # type: ignore[misc]
        return None


def _report_progress(payload: dict) -> None:
    """Best-effort progress event — never fails evaluation."""
    try:
        emit_node_progress(payload)
    except Exception:
        log.debug("EvaluatorNode: progress emit failed", exc_info=True)


def _write_labels_txt(directory, labels) -> str | None:
    """Write labels.txt (class-index order) into an existing directory."""
    labels = [str(x) for x in (labels or [])]
    if not labels:
        return None
    path = Path(directory)
    try:
        if not path.is_dir():
            return None
        target = path / "labels.txt"
        target.write_text("\n".join(labels), encoding="utf-8")
        return str(target)
    except OSError as exc:
        log.warning("EvaluatorNode: could not write labels.txt in %s: %s", path, exc)
        return None


# ── Plot helpers ──────────────────────────────────────────────────────────────

def _plot_confusion_matrix(cm, labels, output_path, normalize=False):
    """Save a seaborn confusion matrix heatmap as PNG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns

    cm_array = np.array(cm, dtype=float)
    if normalize:
        row_sums = cm_array.sum(axis=1, keepdims=True)
        row_sums = np.where(row_sums == 0, 1, row_sums)
        cm_array = cm_array / row_sums
        fmt = ".2f"
    else:
        cm_array = cm_array.astype(int)
        fmt = "d"

    fig, ax = plt.subplots(figsize=(8, 6))
    sns.heatmap(
        cm_array,
        annot=True,
        fmt=fmt,
        xticklabels=labels,
        yticklabels=labels,
        cmap="Blues",
        ax=ax,
    )
    ax.set_xlabel("Predicted label")
    ax.set_ylabel("True label")
    ax.set_title("Confusion Matrix" + (" (normalised)" if normalize else ""))
    plt.tight_layout()
    plt.savefig(str(output_path), dpi=150)
    plt.close(fig)
    log.info("EvaluatorNode: confusion matrix saved to: %s", output_path)


def _plot_training_curves(history, output_path):
    """Save loss and accuracy training curves as PNG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(12, 4))

    # Loss subplot
    axes[0].plot(history.get("loss", []), label="train loss")
    axes[0].plot(history.get("val_loss", []), label="val loss")
    axes[0].set_xlabel("Epoch")
    axes[0].set_ylabel("Loss")
    axes[0].set_title("Training Loss")
    axes[0].legend()
    axes[0].grid(True)

    # Accuracy subplot
    axes[1].plot(history.get("accuracy", []), label="train acc")
    axes[1].plot(history.get("val_accuracy", []), label="val acc")
    axes[1].set_xlabel("Epoch")
    axes[1].set_ylabel("Accuracy")
    axes[1].set_title("Training Accuracy")
    axes[1].legend()
    axes[1].grid(True)

    plt.tight_layout()
    plt.savefig(str(output_path), dpi=150)
    plt.close(fig)
    log.info("EvaluatorNode: training curves saved to: %s", output_path)


def _plot_roc_curves(y_test, y_pred_probs, labels, output_path):
    """Save per-class ROC curves and macro-average as PNG.

    Handles both binary (n_classes=2) and multi-class cases.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.preprocessing import label_binarize
    from sklearn.metrics import roc_curve, auc

    n_classes = len(labels)
    fig, ax = plt.subplots(figsize=(10, 7))

    if n_classes == 2:
        # Binary classification — use probability of positive class directly
        fpr, tpr, _ = roc_curve(y_test, y_pred_probs[:, 1])
        roc_auc = auc(fpr, tpr)
        ax.plot(fpr, tpr, lw=2, label=f"{labels[1]} (AUC={roc_auc:.2f})")
    else:
        # Multi-class OvR
        y_bin = label_binarize(y_test, classes=list(range(n_classes)))
        all_fpr = np.unique(np.concatenate([
            roc_curve(y_bin[:, i], y_pred_probs[:, i])[0]
            for i in range(n_classes)
        ]))
        mean_tpr = np.zeros_like(all_fpr)
        for i in range(n_classes):
            fpr, tpr, _ = roc_curve(y_bin[:, i], y_pred_probs[:, i])
            roc_auc_i = auc(fpr, tpr)
            ax.plot(fpr, tpr, lw=1, alpha=0.5,
                    label=f"{labels[i]} (AUC={roc_auc_i:.2f})")
            mean_tpr += np.interp(all_fpr, fpr, tpr)
        mean_tpr /= n_classes
        macro_auc = auc(all_fpr, mean_tpr)
        ax.plot(all_fpr, mean_tpr, "k--", lw=2,
                label=f"Macro-avg (AUC={macro_auc:.2f})")

    ax.plot([0, 1], [0, 1], "r:", lw=1)
    ax.set_xlabel("False Positive Rate")
    ax.set_ylabel("True Positive Rate")
    ax.set_title("ROC Curves (One-vs-Rest)")
    ax.legend(loc="lower right", fontsize="small")
    plt.tight_layout()
    plt.savefig(str(output_path), dpi=150)
    plt.close(fig)
    log.info("EvaluatorNode: ROC curves saved to: %s", output_path)


# ── Node ──────────────────────────────────────────────────────────────────────

class EvaluatorNode(Node):
    """Evaluate a trained model on the held-out test set.

    Multi-port node: reads ModelArtifact from 'model_artifact' port and a
    DatasetArtifact from 'dataset' port. Produces an enriched ModelArtifact
    on 'output' port with metrics populated.

    Supports Keras models (loaded via keras.saving.load_model) and any model
    that exposes a .predict() method returning class probabilities.

    Config options:
        output_path           (str):  Directory for metrics.json and plots.
        plot_confusion_matrix (bool): Save confusion matrix PNG. Default: True
        plot_training_curves  (bool): Save training curves PNG. Default: True
        compute_roc           (bool): Compute ROC/AUC and save plot. Default: True
        compute_fairness      (bool): Compute per-group accuracy. Default: False
        fairness_attribute_key (str): metadata key for fairness grouping. Default: "speaker_id"
    """

    node_type: ClassVar[str] = "evaluator"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="evaluator",
        label="Evaluator",
        description=(
            "Evaluate trained models with accuracy, F1, ROC/AUC, confusion matrix, "
            "and optional fairness metrics."
        ),
        category="ML",
        version="1.0.0",
        tags=["ml", "evaluation", "metrics", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=False,
        deterministic=True,
        cacheable=False,
        streaming_support=False,
        realtime_support=False,
        memory_requirements="medium",
        batch_support=True,
    )

    input_ports: ClassVar[dict] = {
        "model_artifact": InputPort(
            name="model_artifact",
            data_type=ModelArtifact,
            cardinality="single",
            required=True,
            description="ModelArtifact from TrainerNode.",
        ),
        "dataset": InputPort(
            name="dataset",
            data_type=DatasetArtifact,
            cardinality="single",
            required=True,
            description="DatasetArtifact from DatasetBuilderNode.",
        ),
    }

    output_ports: ClassVar[dict] = {
        "output": OutputPort(
            name="output",
            data_type=ModelArtifact,
            description="ModelArtifact with metrics field populated.",
        )
    }

    class Config(NodeConfig):
        output_path: str = Field(default='workspace/artifacts/evaluation', title="Output path", description="Folder for metrics.json, labels.txt and the plots.")
        plot_confusion_matrix: bool = Field(default=True, title="Plot Confusion Matrix", description="Save a confusion-matrix image (On/Off).")
        plot_training_curves: bool = Field(default=True, title="Plot Training Curves", description="Save training_curves.png from the trainer history (On/Off).")
        compute_roc: bool = Field(default=True, title="Compute ROC", description="Compute macro ROC AUC (OvR for multi-class) and save roc_curves.png (On/Off).")
        compute_fairness: bool = Field(default=False, title="Compute Fairness", description="Report test accuracy per group (see Fairness attribute key) and warn when a group is more than 10% off (On/Off).")
        fairness_attribute_key: str = Field(default='speaker_id', title="Fairness attribute key", description="Metadata key used to slice fairness metrics (e.g. gender).")

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def setup(self) -> None:
        """Verify that at least one supported ML framework is available."""
        _keras_ok = False
        try:
            import keras  # noqa: F401
            _keras_ok = True
        except ImportError:
            pass

        if not _keras_ok:
            log.warning(
                "EvaluatorNode: keras not found. "
                "Keras model loading will fail at runtime. "
                "Install with: venv/bin/pip install keras tensorflow"
            )

    def teardown(self) -> None:
        if hasattr(self, "_model"):
            del self._model

    # ── helpers ───────────────────────────────────────────────────────────────

    def _resolve_role_path(self, artifact: ModelArtifact, role: str) -> str:
        """Local path for *role* from hydrated refs, else legacy metrics/fields."""
        for ref in getattr(artifact, "refs", None) or []:
            r = getattr(ref, "role", None)
            if r != role:
                continue
            # After hydrate, path fields are rewritten; prefer metrics hand-off
            # keys and model_path that materialize_refs_onto set.
            break
        metrics = artifact.metrics or {}
        if role == "keras_model":
            for key in ("keras_model_path",):
                val = str(metrics.get(key) or "").strip()
                if val and Path(val).exists():
                    return val
            # refs may point at relative layout already written next to model_path
            mp = str(getattr(artifact, "model_path", "") or "")
            if mp:
                sibling = Path(mp)
                # saved_model dir sibling model.keras, or model_path itself .keras
                if sibling.is_file() and sibling.suffix.lower() == ".keras":
                    return str(sibling)
                cand = sibling.parent / "model.keras"
                if cand.is_file():
                    return str(cand)
                if sibling.is_dir():
                    cand2 = sibling / "model.keras"
                    if cand2.is_file():
                        return str(cand2)
            for ref in getattr(artifact, "refs", None) or []:
                if getattr(ref, "role", None) == "keras_model":
                    sp = str(getattr(ref, "source_path", "") or "")
                    if sp and Path(sp).exists():
                        return sp
        if role == "saved_model":
            mp = str(getattr(artifact, "model_path", "") or "").strip()
            if mp and Path(mp).is_dir():
                return mp
            val = str(metrics.get("saved_model_path") or "").strip()
            if val and Path(val).exists():
                return val
        if role == "pytorch_model":
            mp = str(getattr(artifact, "model_path", "") or "").strip()
            if mp and mp.lower().endswith((".pt", ".pth")) and Path(mp).exists():
                return mp
        return ""

    def _load_model(self, artifact: ModelArtifact):
        """Load a model from the artifact. Supports Keras (.keras, SavedModel) and
        PyTorch (.pt / .pth) formats via ArtifactRef roles + local path fields."""
        metrics = artifact.metrics or {}
        keras_model_path = self._resolve_role_path(artifact, "keras_model") or str(
            metrics.get("keras_model_path") or ""
        )
        model_path = (
            self._resolve_role_path(artifact, "pytorch_model")
            or self._resolve_role_path(artifact, "saved_model")
            or artifact.model_path
        )

        # Try Keras first (prefer .keras format) — Keras 3 loads .keras reliably;
        # SavedModel directories are the fallback.
        if keras_model_path and Path(keras_model_path).exists():
            try:
                import keras  # type: ignore
                model = keras.saving.load_model(keras_model_path)
                log.info("EvaluatorNode: loaded Keras model from %s", keras_model_path)
                return model
            except ImportError:
                pass

        # Detect PyTorch by extension
        if model_path and model_path.lower().endswith((".pt", ".pth")):
            try:
                import torch  # type: ignore
            except ImportError:
                raise ImportError(
                    "EvaluatorNode: 'torch' required to load PyTorch model. "
                    "Install with: pip install torch>=2.0"
                )
            # Try TorchScript first (torch.jit.save), then plain state dict
            try:
                model = torch.jit.load(model_path, map_location="cpu")
                model.eval()
                log.info("EvaluatorNode: loaded TorchScript model from %s", model_path)
                return model
            except Exception:
                state_dict = torch.load(model_path, map_location="cpu")
                log.info("EvaluatorNode: loaded PyTorch state dict from %s", model_path)
                return state_dict

        # Fall back to Keras SavedModel
        try:
            import keras  # type: ignore
            model = keras.saving.load_model(model_path)
            log.info("EvaluatorNode: loaded Keras model from %s", model_path)
            return model
        except ImportError:
            raise ImportError(
                "EvaluatorNode: 'keras' required to load Keras model. "
                "Install with: pip install keras tensorflow"
            )

    def _compute_roc_auc(self, y_test, y_pred_probs, n_classes: int) -> float:
        """Compute macro-average ROC AUC using OvR strategy."""
        from sklearn.metrics import roc_auc_score

        if n_classes == 2:
            # Binary: use probability of positive class
            return float(roc_auc_score(y_test, y_pred_probs[:, 1]))
        else:
            return float(
                roc_auc_score(
                    y_test,
                    y_pred_probs,
                    multi_class="ovr",
                    average="macro",
                )
            )

    def _compute_fairness(
        self,
        y_test,
        y_pred,
        dataset,
        overall_accuracy: float,
    ) -> dict:
        """Compute per-group accuracy grouped by fairness_attribute_key.

        Groups are derived from dataset.metadata["test_metadata"] if available.
        Each entry in test_metadata should be a dict with the fairness_attribute_key.

        Returns a dict mapping group_value → accuracy.
        Logs a warning if any group deviates >10% from overall accuracy.
        """
        key = self.config.fairness_attribute_key
        test_metadata = []

        # Try to get per-sample metadata from dataset
        if hasattr(dataset, "metadata") and isinstance(dataset.metadata, dict):
            test_metadata = dataset.metadata.get("test_metadata", [])

        if not test_metadata:
            log.warning(
                "EvaluatorNode: fairness evaluation requested but "
                "'test_metadata' not found in dataset.metadata. "
                "Skipping fairness computation."
            )
            return {}

        if len(test_metadata) != len(y_test):
            log.warning(
                "EvaluatorNode: test_metadata length (%d) != test set size (%d). "
                "Skipping fairness computation.",
                len(test_metadata),
                len(y_test),
            )
            return {}

        # Group indices by attribute value
        groups: dict = {}
        for idx, meta in enumerate(test_metadata):
            if not isinstance(meta, dict):
                continue
            group_val = meta.get(key)
            if group_val is None:
                continue
            group_val = str(group_val)
            groups.setdefault(group_val, []).append(idx)

        if not groups:
            log.warning(
                "EvaluatorNode: no samples found with fairness_attribute_key='%s'. "
                "Skipping fairness computation.",
                key,
            )
            return {}

        fairness: dict = {}
        for group_val, indices in groups.items():
            group_y_true = y_test[indices]
            group_y_pred = y_pred[indices]
            group_acc = float(np.mean(group_y_true == group_y_pred))
            fairness[group_val] = group_acc

            deviation = abs(group_acc - overall_accuracy)
            if deviation > 0.10:
                log.warning(
                    "EvaluatorNode: fairness warning — group '%s' accuracy %.4f "
                    "deviates %.4f (>10%%) from overall accuracy %.4f.",
                    group_val,
                    group_acc,
                    deviation,
                    overall_accuracy,
                )

        return fairness

    # ── main process ─────────────────────────────────────────────────────────

    def process(self, inputs: dict) -> dict:
        """Evaluate the model and save metrics/plots.

        Args:
            inputs: dict with:
                "model_artifact" — ModelArtifact from TrainerNode
                "dataset"        — DatasetArtifact (accessed by attribute at runtime)

        Returns:
            dict with "output" key → ModelArtifact with metrics populated
        """
        from sklearn.metrics import (
            precision_recall_fscore_support,
            confusion_matrix,
        )

        artifact: ModelArtifact = inputs["model_artifact"]
        dataset = inputs["dataset"]

        # ── Load model ────────────────────────────────────────────────────────
        model_path = str(getattr(artifact, "model_path", "") or "").strip()
        if not model_path or model_path in {".", "/", "./"}:
            # Fail loudly: returning a metrics={"error": ...} artifact would let the run
            # finish green on a model that was never evaluated.
            raise ValueError(
                f"EvaluatorNode: no usable model_path ({model_path!r}) on the input ModelArtifact "
                "— wire a trainer (or a loaded model) upstream of evaluate"
            )
        log.info("EvaluatorNode: loading model from: %s", artifact.model_path)
        model = self._load_model(artifact)
        self._model = model  # store for teardown

        # Detect if this is a PyTorch state dict (not directly callable)
        is_pytorch_state_dict = isinstance(model, dict)
        if is_pytorch_state_dict:
            log.warning(
                "EvaluatorNode: loaded a PyTorch state dict. Full evaluation requires "
                "the model architecture. Only basic metrics will be computed."
            )

        # ── Resolve test data ─────────────────────────────────────────────────
        X_test = dataset.X_test
        y_test = np.asarray(dataset.y_test, dtype=np.int64)
        # Class-index order of the model (trainer copies dataset.labels).
        labels = list(artifact.labels) if artifact.labels else list(dataset.labels)
        ds_labels = [str(x) for x in (getattr(dataset, "labels", None) or [])]
        if ds_labels and [str(x) for x in labels] != ds_labels:
            log.warning(
                "EvaluatorNode: model labels %s differ from dataset labels %s — "
                "per-class metrics follow the model order.", labels, ds_labels,
            )
        n_classes = len(labels)

        log.info("EvaluatorNode: evaluating on %d test samples...", len(X_test))

        # Guard: empty test set
        if X_test is None or len(X_test) == 0:
            log.warning("EvaluatorNode: test set is empty — skipping evaluation")
            return {"output": ModelArtifact(
                model_path=artifact.model_path,
                labels=labels,
                history=artifact.history,
                metrics={"error": "empty test set"},
                refs=list(getattr(artifact, "refs", None) or []),
            )}

        # ── Predict ───────────────────────────────────────────────────────────
        if is_pytorch_state_dict:
            # Cannot run inference without the model architecture — return empty metrics
            return {"output": ModelArtifact(
                model_path=artifact.model_path,
                labels=labels,
                history=artifact.history,
                metrics={"error": "PyTorch state dict loaded — architecture required for inference"},
                refs=list(getattr(artifact, "refs", None) or []),
            )}

        _report_progress({"phase": "evaluate", "n_test": int(len(X_test)), "pct": 0.0})
        y_pred_probs = model.predict(X_test, verbose=0)
        y_pred = np.argmax(y_pred_probs, axis=1)

        # Guard: model output dimension must match label count
        K = y_pred_probs.shape[1] if y_pred_probs.ndim > 1 else 1
        if K != n_classes:
            raise ValueError(
                f"EvaluatorNode: model output dimension {K} != n_classes {n_classes}. "
                "Ensure the model and dataset are compatible."
            )

        # ── Core metrics ──────────────────────────────────────────────────────
        test_acc = float(np.mean(y_pred == y_test))
        log.info("EvaluatorNode: test accuracy: %.4f", test_acc)

        prec, rec, f1, _ = precision_recall_fscore_support(
            y_test,
            y_pred,
            average=None,
            labels=list(range(n_classes)),
            zero_division=0,
        )
        cm = confusion_matrix(
            y_test, y_pred, labels=list(range(n_classes))
        ).tolist()

        metrics: dict = {
            "test_accuracy": test_acc,
            "per_class": {
                labels[i]: {
                    "precision": float(prec[i]),
                    "recall": float(rec[i]),
                    "f1": float(f1[i]),
                }
                for i in range(n_classes)
            },
            "confusion_matrix": cm,
        }

        # ── ROC / AUC ─────────────────────────────────────────────────────────
        if self.config.compute_roc:
            try:
                roc_auc = self._compute_roc_auc(y_test, y_pred_probs, n_classes)
                metrics["roc_auc"] = roc_auc
                log.info("EvaluatorNode: ROC AUC (macro): %.4f", roc_auc)
            except Exception as exc:
                log.warning("EvaluatorNode: ROC AUC computation failed: %s", exc)

        # ── Fairness ──────────────────────────────────────────────────────────
        if self.config.compute_fairness:
            fairness = self._compute_fairness(y_test, y_pred, dataset, test_acc)
            if fairness:
                metrics["fairness"] = fairness
                log.info("EvaluatorNode: fairness groups evaluated: %s", list(fairness.keys()))

        # ── Output directory ──────────────────────────────────────────────────
        out_path = Path(self.config.output_path)
        out_path.mkdir(parents=True, exist_ok=True)

        # ── Save metrics.json ─────────────────────────────────────────────────
        metrics_path = out_path / "metrics.json"
        with open(metrics_path, "w") as f:
            json.dump(metrics, f, indent=2)
        log.info("EvaluatorNode: metrics saved to: %s", metrics_path)

        # ── Plots ─────────────────────────────────────────────────────────────
        if self.config.plot_confusion_matrix:
            try:
                _plot_confusion_matrix(
                    cm, labels, out_path / "confusion_matrix.png"
                )
            except Exception as exc:
                log.warning(
                    "EvaluatorNode: confusion matrix plot failed (matplotlib/seaborn missing?): %s",
                    exc,
                )

        if self.config.plot_training_curves:
            try:
                _plot_training_curves(
                    artifact.history, out_path / "training_curves.png"
                )
            except Exception as exc:
                log.warning(
                    "EvaluatorNode: training curves plot failed (matplotlib missing?): %s",
                    exc,
                )

        if self.config.compute_roc and "roc_auc" in metrics:
            try:
                _plot_roc_curves(
                    y_test,
                    y_pred_probs,
                    labels,
                    out_path / "roc_curves.png",
                )
            except Exception as exc:
                log.warning(
                    "EvaluatorNode: ROC curves plot failed (matplotlib missing?): %s",
                    exc,
                )

        # labels.txt next to every model file of this artifact (class-index order)
        # and next to metrics.json so the confusion matrix can be read standalone.
        self._write_model_labels(artifact, labels)
        _write_labels_txt(out_path, labels)

        self._publish_eval_tree(out_path)

        _report_progress({
            "phase": "evaluate",
            "n_test": int(len(X_test)),
            "test_accuracy": round(float(test_acc), 6),
            "roc_auc": metrics.get("roc_auc"),
            "pct": 100.0,
            "message": f"Test accuracy {float(test_acc):.1%} on {int(len(X_test))} held-out samples",
        })

        # ── Return enriched artifact ──────────────────────────────────────────
        # Keep upstream hand-off keys (e.g. keras_model_path) so edge_optimizer
        # can still locate the .keras / calibration data next to the model.
        upstream_metrics = artifact.metrics or {}
        upstream = {
            k: v for k, v in upstream_metrics.items()
            if k.endswith("_path") and k not in metrics
        }
        metrics.update(upstream)
        for key in ("display_name", "epochs_run", "best_val_accuracy", "architecture"):
            if key in upstream_metrics and key not in metrics:
                metrics[key] = upstream_metrics[key]
        metrics["labels"] = list(labels)
        return {
            "output": ModelArtifact(
                model_path=artifact.model_path,
                labels=labels,
                history=artifact.history,
                metrics=metrics,
                refs=list(getattr(artifact, "refs", None) or []),
            )
        }

    @staticmethod
    def _write_model_labels(artifact, labels) -> None:
        """Ensure labels.txt sits next to the SavedModel / .keras of the artifact."""
        dirs: list[Path] = []
        mp = Path(str(getattr(artifact, "model_path", "") or ""))
        if str(mp) not in ("", "."):
            dirs.append(mp if mp.is_dir() else mp.parent)
        keras_path = str((getattr(artifact, "metrics", None) or {}).get("keras_model_path") or "")
        if keras_path:
            dirs.append(Path(keras_path).parent)
        seen: set[str] = set()
        for d in dirs:
            key = str(d)
            if key in seen:
                continue
            seen.add(key)
            _write_labels_txt(d, labels)

    def _publish_eval_tree(self, out_path: Path) -> None:
        """Announce metrics/plots via Node.publish_files (generic inventory)."""
        names = (
            "metrics.json",
            "confusion_matrix.png",
            "training_curves.png",
            "roc_curves.png",
            "labels.txt",
        )
        files: list[dict] = []
        for name in names:
            p = out_path / name
            if p.is_file():
                try:
                    files.append({"path": name, "size": int(p.stat().st_size)})
                except OSError:
                    files.append({"path": name})
        if not files:
            return
        try:
            self.publish_files(out_path, files, total=len(files))
        except Exception as exc:
            log.warning("EvaluatorNode: publish_files failed: %s", exc)
