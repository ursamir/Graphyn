"""WakewordFeatureExtractNode — augment clips and extract frozen speech embeddings.

Runs the livekit-wakeword data stage on a run directory:

1. **Augment** (``augment=True``): every ``clip_######.wav`` gets per-sample
   EQ / tanh distortion (audiomentations), optional room-impulse convolution
   and background-noise mixing at 5–15 dB SNR, then is aligned to a
   ``clip_duration`` window (end-aligned with 0–200 ms jitter; negatives too
   unless ``align_negatives="center"``) → ``clip_######_r<round>.wav``. With ``augment=False``
   clips are only aligned/padded.
2. **Extract**: each window goes through the bundled ONNX mel-spectrogram and
   Google speech-embedding models → ``(N, 16, 96)`` arrays saved as
   ``<split>_features_<train|test>.npy`` — the classifier's input.

Room impulse responses: ``rir_dirs`` and/or ``download_rirs`` (MIT
environmental IRs, ≈8 MB from huggingface.co).
"""
from __future__ import annotations

import importlib
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


def download_mit_rirs(dest: Path) -> Path:
    """MIT environmental impulse responses (16 kHz subset) from huggingface.co."""
    try:
        from huggingface_hub import snapshot_download  # type: ignore
    except ImportError as exc:
        raise RuntimeError("wakeword_feature_extract: download_rirs needs huggingface-hub") from exc
    if not any(dest.glob("**/*.wav")):
        snapshot_download(repo_id="davidscripka/MIT_environmental_impulse_responses", repo_type="dataset",
                          allow_patterns="16khz/*.wav", local_dir=str(dest))
    return dest


class WakewordFeatureExtractNode(Node):
    """Augment wake-word clips and extract (N, 16, 96) speech-embedding features."""

    node_type: ClassVar[str] = "wakeword_feature_extract"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="wakeword_feature_extract",
        label="Wake Word Features",
        description="Augment clips (EQ, distortion, RIR, background SNR mix) and extract frozen mel + speech-embedding features (ONNX).",
        category="Features",
        version="2.0.0",
        tags=["wakeword", "augmentation", "features", "onnx", "livekit-wakeword"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=False,
        deterministic=False,
        cacheable=True,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "run": InputPort(name="run", data_type=WakeWordRun | None, required=False,
                         description="Run from wakeword_data_gen (or set config.model_dir)."),
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "run": OutputPort(name="run", data_type=WakeWordRun, description="Run with *_features_*.npy written."),
    }

    class Config(NodeConfig):
        model_dir: str = Field(default="", title="Model dir", description="Existing run directory when the input port is not connected.")
        augment: bool = Field(default=True, title="Augment", description="Apply EQ / distortion / RIR / background mixing before extraction (False = align only).")
        rounds: int = Field(default=1, ge=1, le=10, title="Rounds", description="Augmentation rounds (each compounds on the previous).")
        clip_duration: float = Field(default=2.0, ge=1.3, le=5.0, title="Clip duration (s)", description="Training window; ≥1.3 s gives the 16 embedding steps the classifier needs.")
        background_dirs: list[str] = Field(default_factory=list, title="Background dirs", description="Extra folders of background WAVs for mixing (added to the run's own).")
        rir_dirs: list[str] = Field(default_factory=list, title="RIR dirs", description="Folders of room-impulse-response WAVs.")
        align_negatives: Literal["end", "center"] = Field(default="end", title="Align negatives", description="end: negatives are end-aligned like positives (word position is no cue — recommended without ACAV100M); center: upstream behaviour.")
        download_rirs: bool = Field(default=False, title="Download RIRs", description="Fetch MIT environmental impulse responses (≈8 MB, huggingface.co) into <data_dir>/rirs.")

    def process(self, inputs: dict) -> dict:
        cfg = self.config
        info = _ww.as_run((inputs or {}).get("run"), cfg.model_dir)
        model_dir = Path(info["model_dir"])
        seed = int(getattr(self, "seed", 0) or 0)
        random.seed(seed)
        np.random.seed(seed % (2 ** 32))

        aug_info = dict(info.get("augmentation") or {})
        bgs = list(aug_info.get("background_paths") or []) + list(cfg.background_dirs)
        rirs = list(cfg.rir_dirs)
        if cfg.download_rirs:
            rirs.append(str(download_mit_rirs(Path(info.get("data_dir") or model_dir.parent / "_data") / "rirs")))
        aug_info.update({"background_paths": bgs, "rir_paths": rirs, "clip_duration": cfg.clip_duration,
                         "rounds": cfg.rounds})
        wcfg = _ww.ww_config(info, augmentation=aug_info)

        augment = _ww.lib("data.augment")
        self._augment(augment, wcfg, plain=not cfg.augment, negatives_end=cfg.align_negatives == "end")

        features = _ww.lib("data.features")
        features.run_extraction(wcfg)

        shapes: dict[str, list[int]] = {}
        for split, fname in _ww.FEATURE_FILES.items():
            p = model_dir / fname
            if p.is_file():
                shapes[split] = list(np.load(str(p), mmap_mode="r").shape)
        if not shapes.get("positive_train") or shapes["positive_train"][0] == 0:
            raise RuntimeError("wakeword_feature_extract: no positive_train features were produced")
        info["augmentation"] = aug_info
        info["augmented"] = bool(cfg.augment)
        info["n_backgrounds"] = sum(len(list(Path(d).glob("**/*.wav"))) for d in bgs if Path(d).is_dir())
        info["n_rirs"] = sum(len(list(Path(d).glob("**/*.wav"))) for d in rirs if Path(d).is_dir())
        info["features"] = shapes
        info["stage"] = "features"
        _ww.write_manifest(info)
        self.publish_files(model_dir, [_ww.FEATURE_FILES[s] for s in shapes], total=len(shapes))
        log.info("wakeword_feature_extract: %s features=%s", model_dir, shapes)
        return {"run": WakeWordRun(**_ww.run_payload(info))}

    @staticmethod
    def _augment(augment: Any, wcfg: Any, *, plain: bool, negatives_end: bool) -> None:
        """livekit-wakeword's augmentation loop (``run_augment``) with two options:
        ``plain`` skips the random transforms (align/pad only) and
        ``negatives_end`` end-aligns negatives like positives, so the word's
        position in the window is not a shortcut cue for the classifier."""
        import re

        class _Plain(augment.AudioAugmentor):
            def augment_clip(self, audio):
                return audio

            def apply_rir(self, audio, p=0.5):
                return audio

            def mix_with_background(self, audio, snr_db_range=(5.0, 15.0)):
                return audio

        aug_cfg = wcfg.augmentation
        cls = _Plain if plain else augment.AudioAugmentor
        augmentor = cls(background_paths=[Path(p) for p in ([] if plain else aug_cfg.background_paths)],
                        rir_paths=[Path(p) for p in ([] if plain else aug_cfg.rir_paths)])
        rx = re.compile(r"^clip_\d{6}_r\d+\.wav$")
        rounds = 1 if plain else int(aug_cfg.rounds)
        for split in _ww.SPLITS:
            d = wcfg.model_output_dir / split
            if not d.is_dir():
                continue
            for old in [p for p in d.glob("*.wav") if rx.match(p.name)]:
                old.unlink()
            for round_idx in range(rounds):
                augment._augment_directory(
                    d, augmentor, is_positive=("positive" in split) or negatives_end,
                    round_idx=round_idx, target_duration_s=aug_cfg.clip_duration,
                )
