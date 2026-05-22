# PluginPackage/Common/evaluator/nodes.py
"""EvaluatorNode — evaluate trained models with comprehensive metrics.

Migrated from app/core/nodes/ml/model_evaluator.py and expanded with:
  - ROC/AUC computation (sklearn roc_auc_score, multi_class="ovr", average="macro")
  - Fairness evaluation (per-group accuracy by metadata attribute)
  - Absorbs confusion_matrix_node.py and training_curves_node.py logic
  - Saves metrics.json to output_path

Import note: DatasetArtifact is accessed at runtime via attribute access on the
dataset input — we do NOT import it at module level to avoid coupling to the
dataset_builder plugin. The dataset port uses data_type=object.
"""
# NOTE: No `from __future__ import annotations` — avoids Pydantic forward-ref issues.

import json
import logging
from pathlib import Path
from typing import ClassVar

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.model_artifact import ModelArtifact

log = logging.getLogger(__name__)


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
            data_type=object,
            cardinality="single",
            required=True,
            description="DatasetArtifact from DatasetBuilderNode (accessed by attribute at runtime).",
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
        output_path: str = "workspace/artifacts/evaluation"
        plot_confusion_matrix: bool = True
        plot_training_curves: bool = True
        compute_roc: bool = True
        compute_fairness: bool = False
        fairness_attribute_key: str = "speaker_id"  # metadata key for fairness grouping

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

    def _load_model(self, artifact: ModelArtifact):
        """Load a model from the artifact. Supports Keras (.keras, SavedModel) and
        PyTorch (.pt / .pth) formats, detected from the model_path extension."""
        model_path = artifact.model_path
        keras_model_path = artifact.metrics.get("keras_model_path", "")

        # Try Keras first (prefer .keras format)
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
                state_dict = torch.load(model_path, map_location="cpu")
                log.info("EvaluatorNode: loaded PyTorch state dict from %s", model_path)
                # Return the state dict — caller must handle inference
                return state_dict
            except ImportError:
                raise ImportError(
                    "EvaluatorNode: 'torch' required to load PyTorch model. "
                    "Install with: pip install torch>=2.0"
                )

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
        labels = list(artifact.labels) if artifact.labels else list(dataset.labels)
        n_classes = len(labels)

        log.info("EvaluatorNode: evaluating on %d test samples...", len(X_test))

        # ── Predict ───────────────────────────────────────────────────────────
        if is_pytorch_state_dict:
            # Cannot run inference without the model architecture — return empty metrics
            return {"output": ModelArtifact(
                model_path=artifact.model_path,
                labels=labels,
                history=artifact.history,
                metrics={"error": "PyTorch state dict loaded — architecture required for inference"},
            )}

        y_pred_probs = model.predict(X_test, verbose=0)
        y_pred = np.argmax(y_pred_probs, axis=1)

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

        # ── Return enriched artifact ──────────────────────────────────────────
        return {
            "output": ModelArtifact(
                model_path=artifact.model_path,
                labels=labels,
                history=artifact.history,
                metrics=metrics,
            )
        }
