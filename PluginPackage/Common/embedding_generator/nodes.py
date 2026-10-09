"""EmbeddingGeneratorNode — pretrained audio embeddings.

Models:
    wav2vec2  — facebook/wav2vec2-base (transformers), pooled hidden states
    hubert    — facebook/hubert-base-ls960 (transformers), pooled hidden states
    clap      — laion/clap-htsat-unfused (transformers ClapModel.get_audio_features,
                512-d projected audio embedding at 48 kHz; shares the space with CLAP text)
    xvector   — speechbrain/spkrec-xvect-voxceleb speaker embeddings (512-d)
    ecapa     — speechbrain/spkrec-ecapa-voxceleb speaker embeddings (192-d)
    yamnet    — YAMNet frame embeddings (tensorflow + tensorflow_hub, 1024-d)

``model_name_or_path`` overrides the checkpoint for the transformers models.
Weights download once into the Hugging Face / TF-Hub caches.
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, ClassVar, Literal

import numpy as np
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample

try:
    from embedding_generator.types import EmbeddingVector  # type: ignore
except ImportError:
    from .types import EmbeddingVector  # type: ignore

log = logging.getLogger(__name__)

_HF_MODELS = {
    "wav2vec2": "facebook/wav2vec2-base",
    "hubert": "facebook/hubert-base-ls960",
    "clap": "laion/clap-htsat-unfused",
}
_SB_MODELS = {
    "xvector": "speechbrain/spkrec-xvect-voxceleb",
    "ecapa": "speechbrain/spkrec-ecapa-voxceleb",
}
_CACHE: dict[str, Any] = {}
_LOCK = threading.Lock()


def _resample(y: np.ndarray, sr: int, target: int) -> np.ndarray:
    if int(sr) == int(target):
        return y
    import librosa  # type: ignore

    return librosa.resample(y=y, orig_sr=int(sr), target_sr=int(target)).astype(np.float32)


def _mono(data: Any) -> np.ndarray:
    y = np.asarray(data, dtype=np.float32)
    if y.ndim > 1:
        y = y.mean(axis=1) if y.shape[0] >= y.shape[1] else y.mean(axis=0)
    return y


def _sb_savedir(source: str) -> str:
    base = os.environ.get("HF_HOME") or str(Path.home() / ".cache" / "huggingface")
    return str(Path(base) / "speechbrain" / source.replace("/", "--"))


def _cached(key: str, factory):
    with _LOCK:
        if key not in _CACHE:
            _CACHE[key] = factory()
        return _CACHE[key]


class EmbeddingGeneratorNode(Node):
    """Generate embedding vectors from audio with pretrained models."""

    node_type: ClassVar[str] = "embedding_generator"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="embedding_generator",
        label="Embedding Generator",
        description=(
            "Pretrained audio embeddings: wav2vec2, HuBERT, CLAP (audio projection), "
            "x-vector / ECAPA speaker embeddings, YAMNet."
        ),
        category="Features",
        version="2.0.0",
        tags=["audio", "embeddings", "wav2vec2", "hubert", "clap", "xvector", "ecapa", "yamnet"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=False,
        deterministic=True,
        cacheable=True,
        streaming_support=False,
        realtime_support=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=list[AudioSample],
            cardinality="single",
            required=True,
            description="Audio samples to embed",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=list[EmbeddingVector],
            description="One embedding vector per input sample",
        )
    }

    class Config(NodeConfig):
        model: Literal["wav2vec2", "hubert", "clap", "xvector", "ecapa", "yamnet"] = Field(
            default="wav2vec2", title="Model",
            description="Embedding model: wav2vec2, hubert, clap, xvector, ecapa, yamnet.")
        model_name_or_path: str = Field(
            default="", title="Model name or path",
            description="Override checkpoint (HF id or local path) for wav2vec2/hubert/clap.")
        pooling: Literal["mean", "max", "first", "last", "none"] = Field(
            default="mean", title="Pooling",
            description="How frame embeddings are pooled (wav2vec2/hubert/yamnet). none = flatten frames.")
        normalize: bool = Field(default=True, title="L2 normalize", description="L2-normalize each embedding.")
        layer: int = Field(default=-1, title="Layer",
                           description="Hidden layer to pool for wav2vec2/hubert (-1 = last).")

    def setup(self) -> None:
        self._resolved_model = self.config.model_name_or_path or self.config.model

    # ── process ───────────────────────────────────────────────────────────────

    def process(self, samples: list[AudioSample]) -> list[EmbeddingVector]:
        if samples is None:
            samples = []
        if not isinstance(samples, list):
            samples = [samples]
        key = self.config.model
        resolved = self.config.model_name_or_path or key
        embed = {
            "wav2vec2": self._embed_ssl, "hubert": self._embed_ssl, "clap": self._embed_clap,
            "xvector": self._embed_speechbrain, "ecapa": self._embed_speechbrain,
            "yamnet": self._embed_yamnet,
        }[key]
        results: list[EmbeddingVector] = []
        for sample in samples:
            if sample.data is None or len(sample.data) == 0:
                raise ValueError(f"EmbeddingGeneratorNode: empty audio in {sample.path}")
            emb = np.asarray(embed(_mono(sample.data), int(sample.sample_rate)), dtype=np.float32).reshape(-1)
            if self.config.normalize and emb.size:
                n = float(np.linalg.norm(emb))
                if n > 1e-8:
                    emb = emb / n
            pooling = "projection" if key in ("clap", "xvector", "ecapa") else self.config.pooling
            results.append(EmbeddingVector(
                embedding=emb,
                source_path=str(sample.path),
                label=sample.label,
                embedding_model=resolved,
                pooling=pooling,
                metadata={**(sample.metadata or {}), "embedding_model": resolved, "embedding_dim": int(emb.size)},
            ))
        return results

    # ── wav2vec2 / hubert ─────────────────────────────────────────────────────

    def _embed_ssl(self, y: np.ndarray, sr: int) -> np.ndarray:
        try:
            import torch  # type: ignore
            from transformers import AutoFeatureExtractor, AutoModel  # type: ignore
        except ImportError as exc:
            raise RuntimeError("EmbeddingGeneratorNode: wav2vec2/hubert need torch + transformers") from exc
        model_id = self.config.model_name_or_path or _HF_MODELS[self.config.model]
        fe, model = _cached(f"hf:{model_id}", lambda: (
            AutoFeatureExtractor.from_pretrained(model_id), AutoModel.from_pretrained(model_id).eval()))
        y = _resample(y, sr, 16000)
        inputs = fe(y, sampling_rate=16000, return_tensors="pt")
        with torch.inference_mode():
            out = model(**inputs, output_hidden_states=True)
        hidden = out.hidden_states[self.config.layer] if getattr(out, "hidden_states", None) else out.last_hidden_state
        return self._pool(hidden.squeeze(0).detach().cpu().numpy())

    # ── CLAP ──────────────────────────────────────────────────────────────────

    def _embed_clap(self, y: np.ndarray, sr: int) -> np.ndarray:
        try:
            import torch  # type: ignore
            from transformers import ClapModel, ClapProcessor  # type: ignore
        except ImportError as exc:
            raise RuntimeError("EmbeddingGeneratorNode: clap needs torch + transformers") from exc
        model_id = self.config.model_name_or_path or _HF_MODELS["clap"]
        proc, model = _cached(f"clap:{model_id}", lambda: (
            ClapProcessor.from_pretrained(model_id), ClapModel.from_pretrained(model_id).eval()))
        y = _resample(y, sr, 48000)
        inputs = proc(audio=[y], sampling_rate=48000, return_tensors="pt")
        with torch.inference_mode():
            feats = model.get_audio_features(**{k: v for k, v in inputs.items() if k in ("input_features", "is_longer")})
        if not torch.is_tensor(feats):  # newer transformers may return a model output
            feats = getattr(feats, "pooler_output", None) if getattr(feats, "pooler_output", None) is not None else feats[0]
        return feats[0].detach().cpu().numpy()

    # ── SpeechBrain speaker embeddings ────────────────────────────────────────

    def _embed_speechbrain(self, y: np.ndarray, sr: int) -> np.ndarray:
        try:
            import torch  # type: ignore
            from speechbrain.inference.speaker import EncoderClassifier  # type: ignore
        except ImportError as exc:
            raise RuntimeError(f"EmbeddingGeneratorNode: model={self.config.model!r} needs speechbrain + torch") from exc
        source = _SB_MODELS[self.config.model]
        enc = _cached(f"sb:{source}", lambda: EncoderClassifier.from_hparams(
            source=source, savedir=_sb_savedir(source), run_opts={"device": "cpu"}))
        y = _resample(y, sr, 16000)
        with torch.inference_mode():
            emb = enc.encode_batch(torch.from_numpy(np.ascontiguousarray(y)).unsqueeze(0))
        return emb.squeeze().detach().cpu().numpy()

    # ── YAMNet ────────────────────────────────────────────────────────────────

    def _embed_yamnet(self, y: np.ndarray, sr: int) -> np.ndarray:
        try:
            import tensorflow as tf  # type: ignore
            import tensorflow_hub as hub  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "EmbeddingGeneratorNode: model='yamnet' needs tensorflow + tensorflow_hub") from exc
        model = _cached("yamnet", lambda: hub.load("https://tfhub.dev/google/yamnet/1"))
        y = _resample(y, sr, 16000)
        _, embeddings, _ = model(tf.constant(y, dtype=tf.float32))
        return self._pool(embeddings.numpy())

    # ── pooling ───────────────────────────────────────────────────────────────

    def _pool(self, hidden: np.ndarray) -> np.ndarray:
        if hidden.ndim == 1:
            return hidden
        if hidden.shape[0] == 0:
            raise ValueError("EmbeddingGeneratorNode: audio too short — the model produced no frames")
        p = self.config.pooling
        if p == "mean":
            return hidden.mean(axis=0)
        if p == "max":
            return hidden.max(axis=0)
        if p == "first":
            return hidden[0]
        if p == "last":
            return hidden[-1]
        return hidden.reshape(-1)
