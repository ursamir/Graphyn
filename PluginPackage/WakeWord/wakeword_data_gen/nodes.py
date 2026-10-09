"""WakewordDataGenNode — synthetic wake-word training clips (livekit-wakeword).

Writes positive clips of the target phrase(s), adversarial negatives
(phonetically similar phrases found through CMUdict regex search, plus
partial phrases and any ``custom_negative_phrases``) and, when background
audio is given, background-noise clips — all 16 kHz mono WAV in the
livekit-wakeword layout under ``<output_dir>/<model_name>/``.

TTS engines:

* ``piper_vits`` — Piper VITS LibriTTS (904 speakers) with SLERP speaker
  blending, the upstream default. Needs the ``espeak-ng`` binary; the
  checkpoint (≈174 MB) is downloaded once from the livekit-wakeword GitHub
  release into ``data_dir/piper/``.
* ``mms`` — Meta MMS-TTS (VITS) via transformers, no system binary needed;
  diversity comes from speaking-rate / noise-scale sweeps and per-clip seeds.
* ``auto`` — piper_vits when espeak-ng is on PATH, else mms (recorded in the
  run manifest).
"""
from __future__ import annotations

import importlib
import itertools as it
import logging
import random
import shutil
import threading
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
_MMS: dict[str, Any] = {}
_MMS_LOCK = threading.Lock()


def _mms(model_id: str):
    try:
        import torch  # type: ignore  # noqa: F401
        from transformers import AutoTokenizer, VitsModel  # type: ignore
    except ImportError as exc:
        raise RuntimeError("wakeword_data_gen: tts_backend='mms' needs torch + transformers") from exc
    with _MMS_LOCK:
        if model_id not in _MMS:
            _MMS[model_id] = (AutoTokenizer.from_pretrained(model_id), VitsModel.from_pretrained(model_id).eval())
    return _MMS[model_id]


def synthesize_mms(phrases: list[str], out_dir: Path, n: int, *, model_id: str,
                   length_scales: list[float], noise_scales: list[float], seed: int) -> list[Path]:
    """MMS-TTS clips ``clip_%06d.wav`` (16 kHz int16), cycling phrases × prosody settings."""
    import torch  # type: ignore
    import soundfile as sf  # type: ignore
    from scipy.signal import resample_poly  # type: ignore

    tok, model = _mms(model_id)
    sr = int(model.config.sampling_rate)
    out_dir.mkdir(parents=True, exist_ok=True)
    settings = it.cycle(it.product(length_scales or [1.0], noise_scales or [0.667]))
    texts = it.cycle(phrases)
    paths: list[Path] = []
    for i in range(n):
        ls, ns = next(settings)
        text = next(texts)
        model.speaking_rate = 1.0 / max(0.2, float(ls))
        model.noise_scale = float(ns)
        torch.manual_seed(seed + i)
        with torch.inference_mode():
            wav = model(**tok(text, return_tensors="pt")).waveform[0].cpu().numpy().astype(np.float32)
        y = resample_poly(wav, 160, sr // 100) if sr != 16000 else wav
        peak = float(np.max(np.abs(y))) if y.size else 0.0
        if peak > 0:
            y = 0.9 * y / peak
        p = out_dir / f"clip_{i:06d}.wav"
        sf.write(str(p), y.astype(np.float32), 16000, subtype="PCM_16")
        paths.append(p)
    return paths


class WakewordDataGenNode(Node):
    """Synthesise positive / adversarial-negative / background wake-word clips."""

    node_type: ClassVar[str] = "wakeword_data_gen"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="wakeword_data_gen",
        label="Wake Word Data Gen",
        description="Synthetic wake-word clips: Piper VITS (SLERP speakers) or MMS-TTS positives, CMUdict adversarial negatives, background-noise clips.",
        category="Data",
        version="2.0.0",
        tags=["wakeword", "tts", "synthetic-data", "piper", "livekit-wakeword"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=False,
        deterministic=False,
        cacheable=True,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "background": InputPort(
            name="background", data_type=list | None, required=False,
            description="Optional background audio (AudioSample list, e.g. from dataset_ingest) for noise clips and augmentation.",
        ),
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "run": OutputPort(name="run", data_type=WakeWordRun, description="Wake-word run directory with generated clips."),
    }

    class Config(NodeConfig):
        model_name: str = Field(default="hey_graphyn", min_length=1, pattern=r"^[A-Za-z0-9_\-]+$", title="Model name", description="Directory / model file stem (letters, digits, _ and -).")
        target_phrases: list[str] = Field(default=["hey graphyn"], min_length=1, title="Target phrases", description="Wake phrase(s) to synthesise as positives.")
        custom_negative_phrases: list[str] = Field(default_factory=list, title="Extra negatives", description="Phrases added to the generated adversarial negatives.")
        n_samples: int = Field(default=200, ge=1, le=200000, title="Train clips", description="Positive and negative clips per train split.")
        n_samples_val: int = Field(default=50, ge=1, le=50000, title="Test clips", description="Positive and negative clips per test split.")
        n_background_samples: int = Field(default=50, ge=0, title="Background train clips", description="Background-noise clips (needs background audio).")
        n_background_samples_val: int = Field(default=10, ge=0, title="Background test clips")
        tts_backend: Literal["auto", "piper_vits", "mms"] = Field(default="auto", title="TTS", description="piper_vits: Piper VITS LibriTTS + SLERP (needs espeak-ng); mms: Meta MMS-TTS via transformers; auto: piper when espeak-ng is installed, else mms.")
        piper_checkpoint: str = Field(default="", title="Piper checkpoint", description="Path to en-us-libritts-high.pt (empty → <data_dir>/piper/, downloaded from the livekit-wakeword GitHub release when missing).")
        max_speakers: int = Field(default=0, ge=0, title="Max speakers", description="piper: limit LibriTTS speakers (0 = all 904).")
        mms_model: str = Field(default="facebook/mms-tts-eng", title="MMS model", description="mms: Hugging Face MMS-TTS checkpoint.")
        length_scales: list[float] = Field(default=[0.75, 1.0, 1.25], min_length=1, title="Length scales", description="Speaking-rate sweep (>1 = slower).")
        noise_scales: list[float] = Field(default=[0.667, 0.98], min_length=1, title="Noise scales", description="VITS prosody-noise sweep.")
        batch_size: int = Field(default=25, ge=1, le=512, title="TTS batch size")
        output_dir: str = Field(default="workspace/artifacts/wakeword", title="Output dir", description="Runs are written to <output_dir>/<model_name>/.")
        data_dir: str = Field(default="workspace/models/wakeword", title="Data dir", description="Shared downloads (Piper checkpoint, optional ACAV100M features).")
        overwrite: bool = Field(default=False, title="Overwrite", description="Delete an existing <model_name> directory first (otherwise complete splits are reused and partial ones resumed).")

    def _backend(self) -> str:
        if self.config.tts_backend != "auto":
            return self.config.tts_backend
        return "piper_vits" if shutil.which("espeak-ng") else "mms"

    def _write_backgrounds(self, items: list, dest: Path) -> list[str]:
        import soundfile as sf  # type: ignore

        dest.mkdir(parents=True, exist_ok=True)
        out = []
        for i, item in enumerate(items or []):
            y = _ww.pcm16k(item)
            if y.size == 0:
                continue
            p = dest / f"bg_{i:05d}.wav"
            sf.write(str(p), y, 16000)
            out.append(str(p))
        return out

    def process(self, inputs: dict) -> dict:
        cfg = self.config
        seed = int(getattr(self, "seed", 0) or 0)
        random.seed(seed)
        np.random.seed(seed % (2 ** 32))
        model_dir = Path(cfg.output_dir) / cfg.model_name
        if cfg.overwrite and model_dir.exists():
            shutil.rmtree(model_dir)
        model_dir.mkdir(parents=True, exist_ok=True)

        bg_files = self._write_backgrounds((inputs or {}).get("background") or [], model_dir / "_backgrounds")
        backend = self._backend()
        info: dict[str, Any] = {
            "model_name": cfg.model_name,
            "model_dir": str(model_dir),
            "target_phrases": list(cfg.target_phrases),
            "custom_negative_phrases": list(cfg.custom_negative_phrases),
            "data_dir": str(Path(cfg.data_dir)),
            "tts_backend": backend,
            "augmentation": {"background_paths": [str(model_dir / "_backgrounds")] if bg_files else [], "rir_paths": []},
            "seed": seed,
        }
        _ww.patch_cmudict()
        gen = _ww.lib("data.generate")
        wcfg = _ww.ww_config(
            info, n_samples=cfg.n_samples, n_samples_val=cfg.n_samples_val,
            n_background_samples=cfg.n_background_samples if bg_files else 0,
            n_background_samples_val=cfg.n_background_samples_val if bg_files else 0,
            tts_batch_size=cfg.batch_size, length_scales=list(cfg.length_scales),
            noise_scales=list(cfg.noise_scales), noise_scale_ws=list(cfg.noise_scales),
            max_speakers=cfg.max_speakers or None,
        )

        adversarial = gen.generate_adversarial_phrases(target_phrases=list(cfg.target_phrases))
        adversarial.extend(cfg.custom_negative_phrases)
        if not adversarial:
            raise ValueError("wakeword_data_gen: no adversarial phrases could be derived — add custom_negative_phrases")
        info["adversarial_phrases_sample"] = sorted(adversarial)[:50]
        info["n_adversarial_phrases"] = len(adversarial)

        jobs = [
            ("positive_train", list(cfg.target_phrases), cfg.n_samples),
            ("positive_test", list(cfg.target_phrases), cfg.n_samples_val),
            ("negative_train", adversarial, cfg.n_samples),
            ("negative_test", adversarial, cfg.n_samples_val),
        ]
        counts = _ww.count_clips(model_dir)
        if backend == "piper_vits":
            if not shutil.which("espeak-ng"):
                raise RuntimeError("wakeword_data_gen: tts_backend='piper_vits' needs the espeak-ng binary (apt install espeak-ng) — or use tts_backend='mms'")
            ckpt = Path(cfg.piper_checkpoint) if cfg.piper_checkpoint.strip() else Path(cfg.data_dir) / "piper" / f"{_ww.PIPER_STEM}.pt"
            ckpt = _ww.ensure_piper_checkpoint(ckpt)
            info["piper_checkpoint"] = str(ckpt)
            tts = _ww.lib("data.tts.piper_backend").PiperVitsBackend(
                model_path=ckpt, noise_scales=list(cfg.noise_scales), noise_scale_ws=list(cfg.noise_scales),
                length_scales=list(cfg.length_scales), slerp_weights=[0.2, 0.35, 0.5, 0.65, 0.8],
                max_speakers=cfg.max_speakers or None,
            )
            for split, phrases, n in jobs:
                if counts[split] < n:
                    tts.synthesize_clips(phrases=phrases, output_dir=model_dir / split, n_samples=n,
                                         start_index=counts[split], batch_size=cfg.batch_size)
        else:
            info["mms_model"] = cfg.mms_model
            for k, (split, phrases, n) in enumerate(jobs):
                if counts[split] < n:
                    synthesize_mms(phrases, model_dir / split, n, model_id=cfg.mms_model,
                                   length_scales=list(cfg.length_scales), noise_scales=list(cfg.noise_scales),
                                   seed=seed + 100003 * k)
        if bg_files:
            gen._generate_background_clips(wcfg, "background_train", cfg.n_background_samples)
            if cfg.n_background_samples_val:
                gen._generate_background_clips(wcfg, "background_test", cfg.n_background_samples_val)

        info["clip_counts"] = _ww.count_clips(model_dir)
        missing = [s for s in ("positive_train", "negative_train") if info["clip_counts"][s] == 0]
        if missing:
            raise RuntimeError(f"wakeword_data_gen: synthesis produced no clips for {missing}")
        info["stage"] = "clips"
        _ww.write_manifest(info)
        files = [f"{s}/clip_{i:06d}.wav" for s in _ww.SPLITS for i in range(min(info["clip_counts"][s], 5))]
        self.publish_files(model_dir, files, total=sum(info["clip_counts"].values()))
        log.info("wakeword_data_gen: %s backend=%s clips=%s", model_dir, backend, info["clip_counts"])
        return {"run": WakeWordRun(**_ww.run_payload(info))}
