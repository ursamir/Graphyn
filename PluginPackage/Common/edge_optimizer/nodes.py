# PluginPackage/Common/edge_optimizer/nodes.py
"""EdgeOptimizerNode — optimize models for edge deployment via TFLite or ONNX quantization.

Migrated from app/core/nodes/ml/tflite_exporter.py and expanded with:
  - ONNX export backend (via tf2onnx)
  - Auto backend selection (tflite if TF available, else onnx)
  - operator_fusion config flag (TFLite default optimizations)
  - prune config flag (reserved for future use)
  - Output is DeploymentArtifact instead of TFLiteArtifact (more general)

Supports three quantization modes for TFLite:
  - "float32": no quantization (full precision)
  - "float16": float16 weight quantization
  - "int8":    full integer quantization using representative dataset

Writes model.tflite (or model.onnx) and labels.txt to output_path.
"""
# NOTE: No `from __future__ import annotations` — avoids Pydantic forward-ref issues.

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, ClassVar, Literal
from pydantic import Field

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.artifact_ref import ArtifactRef
from app.models.deployment_artifact import DeploymentArtifact
from app.models.model_artifact import ModelArtifact

log = logging.getLogger(__name__)

# ── progress events (Runs UI) ─────────────────────────────────────────────────
try:
    from app.core.nodes.progress import emit_node_progress
except ImportError:  # pragma: no cover - host predates progress events
    def emit_node_progress(payload: dict) -> None:  # type: ignore[misc]
        return None


def _report_progress(payload: dict) -> None:
    """Best-effort progress event — never fails the export."""
    try:
        emit_node_progress(payload)
    except Exception:
        log.debug("EdgeOptimizerNode: progress emit failed", exc_info=True)


_FORMAT_DISPLAY = {"tflite": "TFLite", "onnx": "ONNX"}
_QUANT_DISPLAY = {
    "int8": "INT8",
    "float16": "FP16",
    "float32": "FP32",
    "dynamic_range": "dynamic-range",
}


def _labels_from_dir(directory: Path) -> list[str]:
    path = Path(directory) / "labels.txt"
    try:
        if path.is_file():
            return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError:
        pass
    return []


def _artifact_labels(artifact) -> list[str]:
    """Model class-index order: artifact.labels, else labels.txt beside the source."""
    labels = [str(x) for x in (getattr(artifact, "labels", None) or [])]
    if labels:
        return labels
    mp = Path(str(getattr(artifact, "model_path", "") or ""))
    for d in (mp if mp.is_dir() else mp.parent, mp.parent):
        found = _labels_from_dir(d)
        if found:
            return found
    return []


def _export_display_name(artifact, model_format: str, quantization: str) -> str:
    """e.g. 'DS-CNN (30 epochs) · TFLite INT8'."""
    base = str(((getattr(artifact, "metrics", None) or {}).get("display_name") or "")).strip()
    fmt = _FORMAT_DISPLAY.get(model_format, model_format.upper())
    quant = _QUANT_DISPLAY.get(quantization, quantization)
    tail = f"{fmt} {quant}".strip()
    return f"{base} · {tail}" if base else tail


def _tflite_tensor_details(tf: Any, model_content: bytes) -> dict | None:
    """Input/output shape, dtype and (scale, zero_point) of a TFLite model.

    Recorded in ``DeploymentArtifact.metadata["tensor_details"]`` so the
    deployment_packager can write preprocessing.json (int8 input scaling)
    without a TFLite runtime of its own. Best effort — ``None`` on failure.
    """
    try:
        interp = tf.lite.Interpreter(model_content=model_content)
        interp.allocate_tensors()

        def one(d: dict) -> dict:
            scale, zero = d.get("quantization") or (0.0, 0)
            return {
                "name": d.get("name"),
                "shape": [int(x) for x in d.get("shape", [])],
                "dtype": np.dtype(d.get("dtype")).name,
                "quantization": {"scale": float(scale), "zero_point": int(zero)} if scale else None,
            }

        return {
            "inputs": [one(d) for d in interp.get_input_details()],
            "outputs": [one(d) for d in interp.get_output_details()],
        }
    except Exception:
        log.debug("EdgeOptimizerNode: could not read TFLite tensor details", exc_info=True)
        return None


def _first_shape(details: dict | None, key: str) -> list[int]:
    rows = (details or {}).get(key) or []
    return list(rows[0].get("shape") or []) if rows else []



def _deployment_artifact_with_refs(
    *,
    artifact_path: str,
    model_format: str,
    target_hardware: str = "cpu",
    quantization: str = "none",
    labels: list | None = None,
    input_shape: list | None = None,
    output_shape: list | None = None,
    file_size_bytes: int = 0,
    benchmark=None,
    metadata: dict | None = None,
    labels_path: str = "",
) -> DeploymentArtifact:
    """Build DeploymentArtifact with an explicit ArtifactRef role manifest.

    Roles: ``deployment_bundle`` (model file/dir) + ``labels`` when present.
    Local path fields remain for same-host execution; Mode B packs refs only.
    """
    labels = list(labels or [])
    metadata = dict(metadata or {})
    refs: list[ArtifactRef] = []
    ap = Path(artifact_path) if artifact_path else None
    if ap is not None and ap.exists():
        kind = "dir" if ap.is_dir() else "file"
        media = None
        if kind == "file" and ap.suffix.lower() == ".tflite":
            media = "application/x-tflite"
        elif kind == "file" and ap.suffix.lower() == ".onnx":
            media = "application/onnx"
        refs.append(
            ArtifactRef(
                role="deployment_bundle",
                kind=kind,  # type: ignore[arg-type]
                filename=ap.name or "bundle",
                relative_path=ap.name or "bundle",
                source_path=str(ap),
                media_type=media,
            )
        )
    lp = labels_path or str(metadata.get("labels_path") or "")
    if not lp and ap is not None:
        sibling = (ap if ap.is_dir() else ap.parent) / "labels.txt"
        if sibling.is_file():
            lp = str(sibling)
    if lp and Path(lp).is_file():
        metadata.setdefault("labels_path", lp)
        refs.append(
            ArtifactRef(
                role="labels",
                kind="file",
                filename="labels.txt",
                relative_path="labels.txt",
                source_path=str(lp),
                media_type="text/plain",
            )
        )
    return DeploymentArtifact(
        artifact_path=artifact_path,
        model_format=model_format,
        target_hardware=target_hardware,
        quantization=quantization,
        labels=labels,
        input_shape=list(input_shape or []),
        output_shape=list(output_shape or []),
        file_size_bytes=file_size_bytes,
        benchmark=benchmark,
        metadata=metadata,
        refs=refs,
    )


class EdgeOptimizerNode(Node):
    """Optimize a Keras SavedModel for edge deployment via TFLite or ONNX.

    SISO node: reads ModelArtifact, produces DeploymentArtifact.

    Config options:
        backend                (str):  "tflite" | "onnx" | "auto". Default: "tflite"
        quantization           (str):  "float32" | "float16" | "int8". Default: "int8"
        output_path            (str):  Directory for output model and labels.txt.
        representative_samples (int):  Number of calibration batches for INT8. Default: 100
        prune                  (bool): Reserved for future pruning support. Default: False
        operator_fusion        (bool): Enable TFLite default optimizations. Default: True
    """

    node_type: ClassVar[str] = "edge_optimizer"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="edge_optimizer",
        label="Edge Optimizer",
        description="Optimize models for edge deployment via TFLite or ONNX quantization.",
        category="Export",
        version="1.1.0",
        tags=["ml", "edge", "tflite", "onnx", "quantization", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=True,
        streaming_support=False,
        realtime_support=False,
        memory_requirements="medium",
        batch_support=False,
    )

    input_ports: ClassVar[dict] = {
        "input": InputPort(
            name="input",
            data_type=ModelArtifact,
            cardinality="single",
            required=True,
            description="ModelArtifact from TrainerNode or EvaluatorNode.",
        )
    }

    output_ports: ClassVar[dict] = {
        "output": OutputPort(
            name="output",
            data_type=DeploymentArtifact,
            description="DeploymentArtifact with artifact_path, model_format, quantization, labels.",
        )
    }

    class Config(NodeConfig):
        backend: Literal["tflite", "onnx", "tflm", "executorch", "ultralytics_export", "auto"] = Field(default='tflite', title="Backend", description="Export format. tflite = TensorFlow Lite (supports quantization); onnx = ONNX (float32 only); tflm, executorch, ultralytics_export = placeholder only, use the dedicated export nodes; auto = tflite when available, else onnx.")
        quantization: Literal["float32", "float16", "int8"] = Field(default='int8', title="Quantization", description="float32 = no quantization; float16 = half-precision weights; int8 = full integer model (uint8 input/output), calibrated on training samples. TFLite only.")
        output_path: str = Field(default='workspace/artifacts/optimized', title="Output path", description="Folder for the exported model and its labels.txt.")
        representative_samples: int = Field(default=100, ge=1, title="Representative samples", description="Number of training samples used to calibrate int8 quantization.")
        prune: bool = Field(default=False, title="Prune", description="Not implemented yet: On only logs a warning.")
        operator_fusion: bool = Field(default=True, title="Weight optimization", description="float32 only: On stores weights as int8 for a smaller file (activations stay float); Off keeps a pure float32 model.")

    def __init__(self, config=None, seed: int = 0, observer=None) -> None:
        super().__init__(config=config, seed=seed, observer=observer)
        allowed_backends = {"tflite", "onnx", "tflm", "executorch", "ultralytics_export", "auto"}
        if self.config.backend not in allowed_backends:
            raise ValueError(
                f"EdgeOptimizerNode: backend must be one of {allowed_backends}, "
                f"got '{self.config.backend}'"
            )
        allowed_quant = {"float32", "float16", "int8"}
        if self.config.quantization not in allowed_quant:
            raise ValueError(
                f"EdgeOptimizerNode: quantization must be one of {allowed_quant}, "
                f"got '{self.config.quantization}'"
            )

    # ── backend detection ─────────────────────────────────────────────────────

    def _detect_backend(self) -> str:
        """Resolve the effective backend to use.

        Returns a concrete backend name. Raises ImportError if neither tflite
        nor onnx is available and backend="auto".
        """
        if self.config.backend in ("tflite", "onnx", "tflm", "executorch", "ultralytics_export"):
            return self.config.backend
        # auto: prefer tflite if tensorflow available, else onnx
        try:
            import tensorflow  # noqa: F401
            return "tflite"
        except ImportError:
            pass
        try:
            import onnx  # noqa: F401
            return "onnx"
        except ImportError:
            pass
        raise ImportError(
            "EdgeOptimizerNode: no export framework found. "
            "Install tensorflow (venv/bin/pip install tensorflow) or "
            "onnx+tf2onnx (venv/bin/pip install onnx tf2onnx)."
        )

    # ── TFLite export ─────────────────────────────────────────────────────────


    @staticmethod
    def _resolve_role_path(artifact: ModelArtifact, role: str) -> str:
        """Local path for *role* from hydrated refs / metrics (Mode B)."""
        metrics = getattr(artifact, "metrics", None) or {}
        if role == "keras_model":
            val = str(metrics.get("keras_model_path") or "").strip()
            if val and Path(val).exists():
                return val
            mp = str(getattr(artifact, "model_path", "") or "")
            if mp:
                p = Path(mp)
                if p.is_file() and p.suffix.lower() == ".keras":
                    return str(p)
                # Not ``p.parent / "model.keras"``: a shared parent may hold another run's model.
                if p.is_dir() and (p / "model.keras").is_file():
                    return str(p / "model.keras")
            for ref in getattr(artifact, "refs", None) or []:
                if getattr(ref, "role", None) == "keras_model":
                    sp = str(getattr(ref, "source_path", "") or "")
                    if sp and Path(sp).exists():
                        return sp
            return ""
        if role == "saved_model":
            mp = str(getattr(artifact, "model_path", "") or "").strip()
            if mp and Path(mp).is_dir():
                return mp
            val = str(metrics.get("saved_model_path") or "").strip()
            if val and Path(val).exists():
                return val
            for ref in getattr(artifact, "refs", None) or []:
                if getattr(ref, "role", None) == "saved_model":
                    sp = str(getattr(ref, "source_path", "") or "")
                    if sp and Path(sp).is_dir():
                        return sp
            return ""
        if role == "pytorch_model":
            mp = str(getattr(artifact, "model_path", "") or "").strip()
            if mp and mp.lower().endswith((".pt", ".pth")) and Path(mp).exists():
                return mp
            for ref in getattr(artifact, "refs", None) or []:
                if getattr(ref, "role", None) == "pytorch_model":
                    sp = str(getattr(ref, "source_path", "") or "")
                    if sp and Path(sp).is_file():
                        return sp
            return ""
        for ref in getattr(artifact, "refs", None) or []:
            if getattr(ref, "role", None) == role:
                sp = str(getattr(ref, "source_path", "") or "")
                if sp and Path(sp).exists():
                    return sp
        return ""

    @staticmethod
    def _int8_repr_path(artifact: ModelArtifact) -> Path:
        """Locate X_train_repr.npy next to a SavedModel dir or a .keras file."""
        mp = Path(artifact.model_path)
        candidates: list[Path] = []
        if mp.is_dir():
            candidates.append(mp / "X_train_repr.npy")
        else:
            candidates.append(mp.parent / "saved_model" / "X_train_repr.npy")
            candidates.append(mp.parent / "X_train_repr.npy")
        keras_path = (artifact.metrics or {}).get("keras_model_path") or ""
        if keras_path:
            kp = Path(str(keras_path))
            candidates.append(kp.parent / "saved_model" / "X_train_repr.npy")
        for path in candidates:
            if path.exists():
                return path
        return candidates[0] if candidates else mp / "X_train_repr.npy"

    @staticmethod
    def _tflite_converter(tf, artifact: ModelArtifact):
        """Build a TFLiteConverter from a SavedModel directory or a Keras file.

        Does not assume a live keras object in pickle/IPC — loads from disk.
        """
        mp = Path(artifact.model_path)
        if mp.is_file():
            import keras

            model = keras.models.load_model(str(mp))
            log.info("EdgeOptimizerNode: converting Keras file %s via from_keras_model", mp)
            return tf.lite.TFLiteConverter.from_keras_model(model)
        log.info("EdgeOptimizerNode: converting SavedModel dir %s via from_saved_model", mp)
        return tf.lite.TFLiteConverter.from_saved_model(str(mp))

    def _copy_tflite(self, artifact, out_path: Path, src: Path) -> DeploymentArtifact:
        """Pass an existing .tflite through when no Keras source sits beside it."""
        import shutil

        dest = out_path / "model.tflite"
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        labels = _artifact_labels(artifact)
        labels_path = out_path / "labels.txt"
        labels_path.write_text("\n".join(labels), encoding="utf-8")
        file_size = dest.stat().st_size
        quant = str(self.config.quantization)
        try:
            import tensorflow as tf

            tensor_details = _tflite_tensor_details(tf, dest.read_bytes())
        except Exception:
            tensor_details = None
        return _deployment_artifact_with_refs(
            artifact_path=str(dest),
            model_format="tflite",
            target_hardware="cpu",
            quantization=quant,
            labels=labels,
            input_shape=_first_shape(tensor_details, "inputs"),
            output_shape=_first_shape(tensor_details, "outputs"),
            file_size_bytes=file_size,
            metadata={
                "source": str(src),
                "source_model_path": str(src),
                "tensor_details": tensor_details,
                "copied": True,
                "labels": list(labels),
                "labels_path": str(labels_path),
                "display_name": _export_display_name(artifact, "tflite", quant),
            },
            labels_path=str(labels_path),
        )

    def _export_tflite(self, artifact: ModelArtifact, out_path: Path) -> DeploymentArtifact:
        """Convert SavedModel to TFLite with the configured quantization.

        Args:
            artifact: ModelArtifact with model_path and labels.
            out_path: Directory to write model.tflite and labels.txt.

        Returns:
            DeploymentArtifact describing the exported TFLite model.
        """
        mp = Path(artifact.model_path)
        if mp.is_file() and mp.suffix.lower() == ".tflite":
            log.info("EdgeOptimizerNode: source is already TFLite; copying %s", mp)
            return self._copy_tflite(artifact, out_path, mp)

        try:
            import tensorflow as tf
        except ImportError:
            raise ImportError(
                "EdgeOptimizerNode: TFLite export requires TensorFlow. "
                "Install with: venv/bin/pip install tensorflow"
            )

        quantization = self.config.quantization
        log.info("EdgeOptimizerNode: converting SavedModel to TFLite (%s)...", quantization)
        _report_progress({"phase": "convert", "backend": "tflite", "quantization": quantization, "pct": 0.0})

        converter = self._tflite_converter(tf, artifact)

        effective_quant = quantization
        if self.config.operator_fusion:
            # Optimize.DEFAULT: for float32 this is dynamic-range weight
            # quantization (int8 weights, float activations).
            converter.optimizations = [tf.lite.Optimize.DEFAULT]
            if quantization == "float32":
                effective_quant = "dynamic_range"

        if quantization == "float16":
            if not self.config.operator_fusion:
                converter.optimizations = [tf.lite.Optimize.DEFAULT]
            converter.target_spec.supported_types = [tf.float16]

        elif quantization == "int8":
            if not self.config.operator_fusion:
                converter.optimizations = [tf.lite.Optimize.DEFAULT]

            # Load representative dataset from saved_model/X_train_repr.npy
            # (or sibling saved_model/ when model_path is a .keras file).
            repr_path = self._int8_repr_path(artifact)
            if repr_path.exists():
                X_repr = np.load(str(repr_path))
            else:
                # No representative data available — INT8 calibration requires it.
                # Silently using wrong-shape zeros would produce a model with
                # incorrect quantization parameters and silent accuracy degradation.
                raise ValueError(
                    f"EdgeOptimizerNode: INT8 quantization requires a representative "
                    f"dataset at '{repr_path}'. TrainerNode saves this file automatically. "
                    "Cannot proceed with INT8 calibration without representative data. "
                    "Use quantization='float32' or 'float16' to skip calibration."
                )

            n_samples = min(self.config.representative_samples, len(X_repr))
            indices = np.linspace(0, len(X_repr) - 1, n_samples, dtype=int)
            repr_data = X_repr[indices]

            n_cal = len(repr_data)
            every = max(1, n_cal // 10)

            def representative_dataset():
                for i in range(n_cal):
                    sample = repr_data[i : i + 1].astype(np.float32)
                    yield [sample]
                    done = i + 1
                    if done == n_cal or done % every == 0:
                        _report_progress({
                            "phase": "calibrate",
                            "done": done,
                            "total": n_cal,
                            "pct": round(100.0 * done / n_cal, 1),
                        })

            converter.representative_dataset = representative_dataset
            converter.inference_input_type = tf.uint8
            converter.inference_output_type = tf.uint8

        tflite_model = converter.convert()

        tflite_path = str(out_path / "model.tflite")
        with open(tflite_path, "wb") as f:
            f.write(tflite_model)

        labels = _artifact_labels(artifact)
        labels_path = out_path / "labels.txt"
        with open(labels_path, "w", encoding="utf-8") as f:
            f.write("\n".join(labels))

        file_size = len(tflite_model)
        tensor_details = _tflite_tensor_details(tf, tflite_model)
        log.info("EdgeOptimizerNode: TFLite model saved to: %s (%d KB)", tflite_path, file_size // 1024)
        log.info("EdgeOptimizerNode: labels saved to: %s", labels_path)
        _report_progress({
            "phase": "convert", "backend": "tflite", "quantization": effective_quant,
            "file_size_bytes": int(file_size), "pct": 100.0,
            "message": f"Saved model.tflite ({max(1, file_size // 1024)} KB, {effective_quant})",
        })

        return _deployment_artifact_with_refs(
            artifact_path=tflite_path,
            model_format="tflite",
            target_hardware="cpu",
            quantization=effective_quant,
            labels=list(labels),
            input_shape=_first_shape(tensor_details, "inputs"),
            output_shape=_first_shape(tensor_details, "outputs"),
            file_size_bytes=file_size,
            metadata={
                "requested_quantization": quantization,
                "source_model_path": str(artifact.model_path),
                "tensor_details": tensor_details,
                "labels": list(labels),
                "labels_path": str(labels_path),
                "display_name": _export_display_name(artifact, "tflite", effective_quant),
            },
            labels_path=str(labels_path),
        )

    # ── ONNX export ───────────────────────────────────────────────────────────

    def _export_onnx(self, artifact: ModelArtifact, out_path: Path) -> DeploymentArtifact:
        """Convert SavedModel or PyTorch model to ONNX.

        - TF SavedModel: uses tf2onnx subprocess
        - PyTorch .pt/.pth: uses torch.onnx.export
        """
        onnx_path = str(out_path / "model.onnx")
        model_path = artifact.model_path
        _report_progress({"phase": "convert", "backend": "onnx", "pct": 0.0})

        # Detect PyTorch model by extension
        if model_path.lower().endswith((".pt", ".pth")):
            try:
                import torch  # type: ignore
            except ImportError:
                raise ImportError(
                    "EdgeOptimizerNode: 'torch' required to export PyTorch model to ONNX. "
                    "Install with: pip install torch>=2.0 onnx>=1.14"
                )
            log.info("EdgeOptimizerNode: exporting PyTorch model to ONNX...")
            model = torch.jit.load(model_path, map_location="cpu")
            model.eval()
            # Use input_shape from artifact if available; fall back to a 4-D shape
            # that the caller must verify matches the model's expected input.
            raw_shape = getattr(artifact, "input_shape", None)
            if raw_shape and len(raw_shape) >= 3:
                # input_shape is typically (T, F, C) without batch dim
                dummy_input = torch.zeros(1, *raw_shape)
            else:
                log.warning(
                    "EdgeOptimizerNode: artifact.input_shape not set — "
                    "cannot determine PyTorch model input shape for ONNX export. "
                    "Set artifact.input_shape on the ModelArtifact for correct export."
                )
                dummy_input = torch.zeros(1, 101, 40, 1)
            torch.onnx.export(
                model,
                dummy_input,
                onnx_path,
                opset_version=17,
                input_names=["input"],
                output_names=["output"],
            )
        else:
            # TF SavedModel path via tf2onnx
            try:
                import tf2onnx  # noqa: F401
                import tensorflow as tf  # noqa: F401
            except ImportError:
                raise ImportError(
                    "EdgeOptimizerNode: ONNX export requires tf2onnx. "
                    "Install with: pip install tf2onnx onnx"
                )
            log.info("EdgeOptimizerNode: converting SavedModel to ONNX...")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tf2onnx.convert",
                    "--saved-model",
                    model_path,
                    "--output",
                    onnx_path,
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"tf2onnx conversion failed:\n{result.stderr}")

        file_size = Path(onnx_path).stat().st_size

        # Save labels.txt (model class-index order)
        labels = _artifact_labels(artifact)
        labels_path = out_path / "labels.txt"
        with open(labels_path, "w", encoding="utf-8") as f:
            f.write("\n".join(labels))

        log.info("EdgeOptimizerNode: ONNX model saved to: %s (%d KB)", onnx_path, file_size // 1024)
        log.info("EdgeOptimizerNode: labels saved to: %s", labels_path)
        _report_progress({
            "phase": "convert", "backend": "onnx", "file_size_bytes": int(file_size), "pct": 100.0,
            "message": f"Saved model.onnx ({max(1, file_size // 1024)} KB)",
        })

        return _deployment_artifact_with_refs(
            artifact_path=onnx_path,
            model_format="onnx",
            target_hardware="cpu",
            quantization="float32",
            labels=list(labels),
            file_size_bytes=file_size,
            metadata={
                "labels": list(labels),
                "labels_path": str(labels_path),
                "display_name": _export_display_name(artifact, "onnx", "float32"),
            },
            labels_path=str(labels_path),
        )

    @staticmethod
    def _resolve_model_path(raw: str) -> Path:
        """Find a model path the download jail would accept.

        Ship verifies ``artifacts/...`` via the workspace root. The isolated
        worker's cwd is the repo root, so that relative path misses
        ``workspace/artifacts/...`` unless we try the same candidates.
        """
        text = (raw or "").strip()
        if not text:
            return Path(text)
        path = Path(text)
        candidates: list[Path] = []
        if path.is_absolute():
            candidates.append(path)
        else:
            candidates.append(Path.cwd() / path)
            try:
                from app.core.config import project_dir

                root = project_dir()
            except Exception:
                root = None
            if root is not None:
                candidates.append(root / path)
                parts = path.parts
                if parts and parts[0] == "workspace":
                    candidates.append(root / Path(*parts[1:]))
                if parts and parts[0] == "artifacts":
                    candidates.append(Path.cwd() / "workspace" / path)
        seen: set[str] = set()
        for cand in candidates:
            key = str(cand)
            if key in seen:
                continue
            seen.add(key)
            try:
                if cand.exists():
                    return cand
            except OSError:
                continue
        return path

    @staticmethod
    def _prefer_trainable_source(path: Path) -> Path:
        """Use a Keras SavedModel or ``.keras`` beside an exported file.

        A picked ``.../tflite/model.tflite`` is already an export. Conversion
        and int8 calibration need the sibling ``saved_model`` or ``model.keras``.
        """
        try:
            if not path.exists() or path.is_dir():
                return path
        except OSError:
            return path
        if path.suffix.lower() in {".keras", ".h5"}:
            return path
        if path.suffix.lower() not in {".tflite", ".onnx"}:
            return path
        parents = [path.parent]
        if path.parent.parent != path.parent:
            parents.append(path.parent.parent)
        for parent in parents:
            for cand in (parent / "saved_model", parent / "model.keras"):
                try:
                    if cand.exists():
                        return cand
                except OSError:
                    continue
        return path

    # ── main process ─────────────────────────────────────────────────────────

    def process(self, artifact) -> DeploymentArtifact:
        """Optimize a SavedModel for edge deployment.

        Args:
            artifact: ModelArtifact with model_path and labels.

        Returns:
            DeploymentArtifact with artifact_path, model_format, quantization,
            labels, and file_size_bytes.
        """
        if isinstance(artifact, dict):
            artifact = (
                artifact.get("model_artifact")
                or artifact.get("input")
                or artifact.get("model")
                or artifact.get("output")
            )
        if artifact is None or isinstance(artifact, dict):
            raise FileNotFoundError("EdgeOptimizerNode: expected a ModelArtifact input")
        if self.config.prune:
            log.warning(
                "EdgeOptimizerNode: prune=True is set but pruning is not yet "
                "implemented. Proceeding without pruning."
            )

        # Prefer hydrated ArtifactRef roles (Mode B) before legacy model_path.
        role_path = self._resolve_role_path(artifact, "saved_model") or self._resolve_role_path(
            artifact, "keras_model"
        ) or self._resolve_role_path(artifact, "pytorch_model")
        raw_mp = role_path or (getattr(artifact, "model_path", "") or "")
        resolved = self._resolve_model_path(raw_mp)
        trainable = self._prefer_trainable_source(resolved)
        if not trainable.exists():
            raise FileNotFoundError(
                f"EdgeOptimizerNode: model not found at '{artifact.model_path}'"
            )
        updates: dict = {}
        if str(trainable) != (artifact.model_path or ""):
            updates["model_path"] = str(trainable)
        # Keep keras_model_path metrics in sync with hydrated layout for int8 repr lookup.
        metrics = dict(getattr(artifact, "metrics", None) or {})
        keras_role = self._resolve_role_path(artifact, "keras_model")
        if keras_role and metrics.get("keras_model_path") != keras_role:
            metrics["keras_model_path"] = keras_role
            updates["metrics"] = metrics
        if updates:
            try:
                artifact = artifact.model_copy(update=updates)
            except Exception:
                for k, v in updates.items():
                    setattr(artifact, k, v)

        out_path = Path(self.config.output_path)
        out_path.mkdir(parents=True, exist_ok=True)

        backend = self._detect_backend()
        log.info("EdgeOptimizerNode: using backend: %s", backend)

        if backend == "tflite":
            result = self._export_tflite(artifact, out_path)
        elif backend == "onnx":
            result = self._export_onnx(artifact, out_path)
        else:
            # Additive backends (tflm / executorch / ultralytics_export): stub package
            # unless optional deps present — prefer dedicated TinyML/Vision nodes.
            result = self._export_stub_backend(artifact, out_path, backend)
        self._publish_opt_tree(out_path)
        return result

    def _publish_opt_tree(self, out_path: Path) -> None:
        """Announce optimized model files via Node.publish_files."""
        files: list[dict] = []
        if not out_path.is_dir():
            return
        for sub in out_path.rglob("*"):
            if not sub.is_file():
                continue
            rel = str(sub.relative_to(out_path)).replace("\\", "/")
            try:
                files.append({"path": rel, "size": int(sub.stat().st_size)})
            except OSError:
                files.append({"path": rel})
        if not files:
            return
        try:
            self.publish_files(out_path, files, total=len(files))
        except Exception as exc:
            log.warning("EdgeOptimizerNode: publish_files failed: %s", exc)

    def _export_stub_backend(self, artifact, out_path: Path, backend: str):
        """Minimal DeploymentArtifact for additive backends without heavy deps."""
        from app.models.deployment_artifact import DeploymentArtifact
        dest = out_path / f"optimized_{backend}"
        dest.mkdir(parents=True, exist_ok=True)
        marker = dest / "BACKEND_STUB.txt"
        marker.write_text(
            f"EdgeOptimizerNode backend={backend} stub.\n"
            f"Prefer dedicated nodes (tflm_quantize / executorch_export / yolo_export).\n"
            f"source={artifact.model_path}\n",
            encoding="utf-8",
        )
        labels = _artifact_labels(artifact)
        if labels:
            (dest / "labels.txt").write_text("\n".join(labels), encoding="utf-8")
        labels_file = dest / "labels.txt"
        return _deployment_artifact_with_refs(
            artifact_path=str(dest),
            model_format=backend,
            target_hardware="mcu" if backend in ("tflm", "executorch") else "cpu",
            quantization=str(self.config.quantization),
            labels=labels,
            metadata={
                "backend": backend,
                "stub": True,
                "source": artifact.model_path,
                "labels": list(labels),
                "display_name": _export_display_name(artifact, backend, str(self.config.quantization)),
            },
            labels_path=str(labels_file) if labels_file.is_file() else "",
        )
