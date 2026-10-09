"""WakewordExportOnnxNode — export a trained wake-word head to ONNX (+ INT8).

Uses livekit-wakeword's exporter: the classifier head takes
``embeddings`` (batch, 16, 96) and returns ``score`` (batch, 1); weights are
bundled into a single .onnx file. ``quantize=True`` additionally writes an
INT8 dynamic-quantised ``<model>.int8.onnx``. Every written model is loaded
back with onnxruntime and checked against the PyTorch head on random input.
The exported file runs with the bundled mel + embedding front end
(``wakeword_infer`` or ``livekit.wakeword.WakeWordModel``).
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import ClassVar

import numpy as np
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

_pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
_types = importlib.import_module(f"{_pkg}.types")
_ww = importlib.import_module(f"{_pkg}._ww")
WakeWordRun = _types.WakeWordRun

log = logging.getLogger(__name__)


class WakewordExportOnnxNode(Node):
    """ONNX export (and optional INT8 quantisation) of a trained wake-word head."""

    node_type: ClassVar[str] = "wakeword_export_onnx"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="wakeword_export_onnx",
        label="Wake Word Export ONNX",
        description="Export the trained wake-word classifier to ONNX (optional INT8) and verify it against PyTorch with onnxruntime.",
        category="Deploy",
        version="2.0.0",
        tags=["wakeword", "onnx", "quantization", "export", "livekit-wakeword"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=True,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "run": InputPort(name="run", data_type=WakeWordRun | None, required=False,
                         description="Run from wakeword_train (or set config.model_dir)."),
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "run": OutputPort(name="run", data_type=WakeWordRun, description="Run with onnx_path (and onnx_int8_path)."),
    }

    class Config(NodeConfig):
        model_dir: str = Field(default="", title="Model dir", description="Existing run directory when the input port is not connected.")
        quantize: bool = Field(default=False, title="INT8 quantize", description="Also write <model>.int8.onnx (onnxruntime dynamic quantisation).")
        opset: int = Field(default=18, ge=13, le=21, title="ONNX opset")
        tolerance: float = Field(default=1e-3, gt=0, title="FP32 tolerance", description="Max |onnx − torch| score difference accepted for the FP32 export.")

    def process(self, inputs: dict) -> dict:
        cfg = self.config
        info = _ww.as_run((inputs or {}).get("run"), cfg.model_dir)
        model_dir = Path(info["model_dir"])
        ckpt = Path(info.get("checkpoint_path") or model_dir / f"{info['model_name']}.pt")
        if not ckpt.is_file():
            raise ValueError(f"wakeword_export_onnx: checkpoint {ckpt} not found — run wakeword_train first")
        import onnxruntime as ort  # type: ignore
        import torch  # type: ignore

        model_kw = info.get("model") or {}
        wcfg = _ww.ww_config(info, model=model_kw) if model_kw else _ww.ww_config(info)
        onnx_mod = _ww.lib("export.onnx")
        onnx_path = model_dir / f"{info['model_name']}.onnx"
        # Export with the legacy torch.onnx path ourselves. livekit-wakeword renamed its
        # helper across releases (export_classifier in 0.2.1 -> export_onnx in 0.2.3), and its
        # default dynamo export emits shapes that break onnxruntime's INT8 dynamic quantiser.
        import inspect
        import onnx as _onnx  # type: ignore

        def _export(config, model_path, output_path, opset_version=18):
            model = _ww.lib("models.pipeline").WakeWordClassifier(config)
            model.load_state_dict(torch.load(model_path, map_location="cpu", weights_only=True))
            model.eval()
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            kw = {"dynamo": False} if "dynamo" in inspect.signature(torch.onnx.export).parameters else {}
            torch.onnx.export(model, torch.randn(2, 16, 96), str(output_path), opset_version=opset_version,
                              input_names=["embeddings"], output_names=["score"],
                              dynamic_axes={"embeddings": {0: "batch"}, "score": {0: "batch"}}, **kw)
            m = _onnx.load(str(output_path), load_external_data=True)
            _onnx.save(m, str(output_path), save_as_external_data=False)
            ext = output_path.with_suffix(".onnx.data")
            if ext.exists():
                ext.unlink()
            return output_path

        _export(wcfg, ckpt, onnx_path, opset_version=cfg.opset)

        head = _ww.lib("models.pipeline").WakeWordClassifier(wcfg)
        head.load_state_dict(torch.load(ckpt, map_location="cpu", weights_only=True))
        head.eval()
        x = np.random.default_rng(0).standard_normal((4, 16, 96)).astype(np.float32)
        with torch.no_grad():
            ref = head(torch.from_numpy(x)).numpy().reshape(-1)

        def _check(path: Path) -> float:
            sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
            got = sess.run(None, {sess.get_inputs()[0].name: x})[0].reshape(-1)
            return float(np.max(np.abs(got - ref)))

        diff = _check(onnx_path)
        if diff > cfg.tolerance:
            raise RuntimeError(f"wakeword_export_onnx: ONNX output differs from PyTorch by {diff:.2e} (> {cfg.tolerance})")
        verify = {"fp32_max_abs_diff": diff, "fp32_bytes": onnx_path.stat().st_size}
        files = [onnx_path.name]
        if cfg.quantize:
            try:
                q = onnx_mod.quantize_onnx(onnx_path, model_dir / f"{info['model_name']}.int8.onnx")
            except Exception as exc:
                raise RuntimeError(
                    "wakeword_export_onnx: INT8 quantisation failed (onnxruntime dynamic quantize). "
                    "Torch's dynamo ONNX exporter can emit shapes onnxruntime cannot re-infer — "
                    "leave quantize=False (FP32 export still works) or pin torch/onnxruntime to a "
                    f"compatible pair. Underlying error: {exc}"
                ) from exc
            verify["int8_max_abs_diff"] = _check(Path(q))
            verify["int8_bytes"] = Path(q).stat().st_size
            info["onnx_int8_path"] = str(q)
            files.append(Path(q).name)
        info.update({"stage": "exported", "onnx_path": str(onnx_path), "onnx_verify": verify, "opset": cfg.opset})
        _ww.write_manifest(info)
        self.publish_files(model_dir, files)
        log.info("wakeword_export_onnx: %s %s", onnx_path, verify)
        return {"run": WakeWordRun(**_ww.run_payload(info))}
