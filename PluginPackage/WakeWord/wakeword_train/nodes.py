"""WakewordTrainNode — train a wake-word classifier on extracted features.

Wraps livekit-wakeword's ``WakeWordTrainer``: a DNN / RNN / conv-attention
head over (16, 96) speech-embedding windows, trained in three phases
(warm-up + cosine decay, then two lower-LR refinements) with focal loss,
embedding mix-up, label smoothing and a negative-weight schedule that is
doubled when validation false-positives/hour exceed the target. The best
checkpoints are averaged and a detection threshold is chosen on the test
split. Writes ``<model_name>.pt`` and ``<model_name>_metrics.json``.

Negatives: adversarial clips (+ background clips when present). Optional
ACAV100M general-speech features (``acav_features``, ≈16 GB) reduce false
positives further; without them training still runs (upstream warns).
"""
from __future__ import annotations

import importlib
import json
import logging
import random
from pathlib import Path
from typing import Any, ClassVar, Literal

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


class WakewordTrainNode(Node):
    """3-phase PyTorch training of a wake-word classifier head."""

    node_type: ClassVar[str] = "wakeword_train"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="wakeword_train",
        label="Wake Word Train",
        description="Train a DNN/RNN/conv-attention wake-word head on speech embeddings (3-phase, focal loss, checkpoint averaging, threshold search).",
        category="ML",
        version="2.0.0",
        tags=["wakeword", "training", "pytorch", "livekit-wakeword"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=False,
        deterministic=False,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "run": InputPort(name="run", data_type=WakeWordRun | None, required=False,
                         description="Run from wakeword_feature_extract (or set config.model_dir)."),
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "run": OutputPort(name="run", data_type=WakeWordRun, description="Run with the trained .pt checkpoint, metrics and threshold."),
    }

    class Config(NodeConfig):
        model_dir: str = Field(default="", title="Model dir", description="Existing run directory when the input port is not connected.")
        model_type: Literal["conv_attention", "dnn", "rnn"] = Field(default="conv_attention", title="Architecture")
        model_size: Literal["tiny", "small", "medium", "large"] = Field(default="small", title="Size", description="tiny 16×1, small 32×1, medium 128×2, large 256×3 (layer dim × blocks).")
        steps: int = Field(default=2000, ge=10, le=500000, title="Steps", description="Phase-1 steps (phases 2 and 3 add 10% each).")
        learning_rate: float = Field(default=1e-4, gt=0, le=1.0, title="Learning rate")
        weight_decay: float = Field(default=1e-2, ge=0, title="Weight decay")
        label_smoothing: float = Field(default=0.05, ge=0, lt=0.5, title="Label smoothing")
        max_negative_weight: float = Field(default=50.0, ge=1.0, title="Max negative weight", description="End of the linear negative-class weight ramp. ~50 suits a few hundred synthetic negatives; upstream uses 1500 with ACAV100M-scale negatives.")
        target_fp_per_hour: float = Field(default=0.2, gt=0, title="Target FP/hour", description="Validation false positives per hour that trigger negative re-weighting; also the threshold-search target.")
        batch_positive: int = Field(default=50, ge=1, title="Positives / batch")
        batch_negative: int = Field(default=50, ge=1, title="Adversarial negatives / batch")
        batch_background: int = Field(default=50, ge=0, title="Background / batch")
        batch_acav: int = Field(default=1024, ge=0, title="ACAV100M / batch", description="Used only when ACAV100M features exist.")
        acav_features: str = Field(default="", title="ACAV100M features", description="Path to openwakeword_features_ACAV100M_2000_hrs_16bit.npy (empty → <data_dir>/features/ if present).")
        device: Literal["auto", "cpu", "cuda"] = Field(default="auto", title="Device")

    def process(self, inputs: dict) -> dict:
        cfg = self.config
        info = _ww.as_run((inputs or {}).get("run"), cfg.model_dir)
        model_dir = Path(info["model_dir"])
        for need in ("positive_features_train.npy", "negative_features_train.npy"):
            if not (model_dir / need).is_file():
                raise ValueError(f"wakeword_train: {model_dir / need} missing — run wakeword_feature_extract first")
        seed = int(getattr(self, "seed", 0) or 0)
        import torch  # type: ignore

        random.seed(seed)
        np.random.seed(seed % (2 ** 32))
        torch.manual_seed(seed)

        data_dir = Path(info.get("data_dir") or model_dir.parent / "_data")
        acav_note = "absent"
        if cfg.acav_features.strip():
            src = Path(cfg.acav_features)
            if not src.is_file():
                raise ValueError(f"wakeword_train: acav_features {src} not found")
            dst = data_dir / "features" / "openwakeword_features_ACAV100M_2000_hrs_16bit.npy"
            if src.resolve() != dst.resolve():
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists() or dst.is_symlink():
                    dst.unlink()
                dst.symlink_to(src.resolve())
            acav_note = str(src)
        elif (data_dir / "features" / "openwakeword_features_ACAV100M_2000_hrs_16bit.npy").is_file():
            acav_note = str(data_dir / "features")

        wcfg = _ww.ww_config(
            info, steps=cfg.steps, learning_rate=cfg.learning_rate, weight_decay=cfg.weight_decay,
            label_smoothing=cfg.label_smoothing, max_negative_weight=cfg.max_negative_weight,
            target_fp_per_hour=cfg.target_fp_per_hour,
            model={"model_type": cfg.model_type, "model_size": cfg.model_size},
            batch_n_per_class={"positive": cfg.batch_positive, "adversarial_negative": cfg.batch_negative,
                               "background_noise": cfg.batch_background, "ACAV100M_sample": cfg.batch_acav},
        )
        if cfg.device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("wakeword_train: device='cuda' but CUDA is not available")
        device = torch.device("cpu") if cfg.device == "cpu" else (
            torch.device("cuda") if cfg.device == "cuda" else _ww.lib("utils").get_device())

        trainer_mod = _ww.lib("training.trainer")
        trainer = trainer_mod.WakeWordTrainer(wcfg, device=device)
        trainer.train()
        ckpt = model_dir / f"{info['model_name']}.pt"
        trainer.save(ckpt)

        metrics_log: list[dict[str, Any]] = []
        mpath = model_dir / f"{info['model_name']}_metrics.json"
        if mpath.is_file():
            metrics_log = json.loads(mpath.read_text())
        final = next((m for m in reversed(metrics_log) if m.get("note") == "final_averaged"), {})
        optimal = next((m for m in reversed(metrics_log) if m.get("note") == "optimal_threshold"), {})
        keep = ("fpph", "recall", "accuracy", "threshold")
        info.update({
            "stage": "trained",
            "checkpoint_path": str(ckpt),
            "threshold": float(optimal.get("threshold", 0.5)),
            "metrics": {
                "final": {k: final[k] for k in keep if k in final},
                "at_optimal_threshold": {k: optimal[k] for k in keep if k in optimal},
                "steps_total": cfg.steps + 2 * (cfg.steps // 10),
                "device": str(device),
                "acav100m": acav_note,
            },
            "model": {"model_type": cfg.model_type, "model_size": cfg.model_size},
        })
        _ww.write_manifest(info)
        self.publish_files(model_dir, [ckpt.name, mpath.name] if mpath.is_file() else [ckpt.name])
        log.info("wakeword_train: %s metrics=%s", ckpt, info["metrics"])
        return {"run": WakeWordRun(**_ww.run_payload(info))}
