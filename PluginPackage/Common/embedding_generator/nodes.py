"""EmbeddingGeneratorNode — generate semantic embedding vectors from audio.

Models:
    wav2vec2  — facebook/wav2vec2-base (transformers, PyTorch)
    hubert    — facebook/hubert-base-ls960 (transformers, PyTorch)
    clap      — laion/clap-htsat-unfused (transformers, PyTorch)
    yamnet    — YAMNet embeddings (tensorflow_hub)
    xvector   — speechbrain x-vector speaker embeddings
    openl3    — OpenL3 audio embeddings (openl3, optional)

Absorbs: speaker_embedder.py (as model="xvector")
"""
from __future__ import annotations

import logging
from typing import ClassVar

import numpy as np

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
    "hubert":   "facebook/hubert-base-ls960",
    "clap":     "laion/clap-htsat-unfused",
}


class EmbeddingGeneratorNode(Node):
    """Generate semantic embedding vectors from audio using pretrained models.

    Config:
        model (str): "wav2vec2" | "hubert" | "clap" | "yamnet" | "xvector" | "openl3"
        model_name_or_path (str): HuggingFace model ID or local path (overrides model)
        backend (str): "pytorch" | "tensorflow" | "auto"
        pooling (str): "mean" | "cls" | "last" | "none"
        normalize (bool): L2-normalize the output embedding (default True)
        layer (int): transformer layer to extract from (-1 = last hidden state)
    """

    node_type: ClassVar[str] = "embedding_generator"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="embedding_generator",
        label="Embedding Generator",
        description=(
            "Generate semantic embedding vectors from audio using pretrained models: "
            "wav2vec2, HuBERT, CLAP, YAMNet, x-vector, OpenL3."
        ),
        category="Features",
        version="1.0.0",
        tags=["audio", "embeddings", "wav2vec2", "hubert", "clap", "xvector", "ssl"],
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
            description="Embedding vectors",
        )
    }

    class Config(NodeConfig):
        model: str = "wav2vec2"         # "wav2vec2"|"hubert"|"clap"|"yamnet"|"xvector"|"openl3"
        model_name_or_path: str = ""    # overrides model if set
        backend: str = "auto"           # "pytorch" | "tensorflow" | "auto"
        pooling: str = "mean"           # "mean" | "cls" | "last" | "none"
        normalize: bool = True
        layer: int = -1                 # -1 = last hidden state

    # ── setup ─────────────────────────────────────────────────────────────────

    def setup(self) -> None:
        self._model_obj = None
        self._processor_obj = None
        self._resolved_model = self.config.model_name_or_path or self.config.model
        log.debug("EmbeddingGeneratorNode: model='%s'", self._resolved_model)

    # ── SISO process ──────────────────────────────────────────────────────────

    def process(self, samples: list[AudioSample]) -> list[EmbeddingVector]:
        model_key = self.config.model.lower()
        results: list[EmbeddingVector] = []

        for sample in samples:
            y = sample.data.astype(np.float32)
            sr = sample.sample_rate

            if model_key in ("wav2vec2", "hubert", "clap"):
                emb = self._embed_transformers(y, sr, model_key)
            elif model_key == "yamnet":
                emb = self._embed_yamnet(y, sr)
            elif model_key == "xvector":
                emb = self._embed_xvector(y, sr)
            elif model_key == "openl3":
                emb = self._embed_openl3(y, sr)
            else:
                raise ValueError(
                    f"EmbeddingGeneratorNode: unknown model '{model_key}'. "
                    "Choose from: wav2vec2, hubert, clap, yamnet, xvector, openl3"
                )

            if self.config.normalize and emb is not None and len(emb) > 0:
                norm = np.linalg.norm(emb)
                if norm > 1e-8:
                    emb = emb / norm

            results.append(EmbeddingVector(
                embedding=emb.astype(np.float32),
                source_path=str(sample.path),
                label=sample.label,
                embedding_model=self._resolved_model,
                pooling=self.config.pooling,
                metadata={**sample.metadata, "embedding_model": self._resolved_model},
            ))

        return results

    # ── transformers backend (wav2vec2 / hubert / clap) ───────────────────────

    def _embed_transformers(self, y: np.ndarray, sr: int, model_key: str) -> np.ndarray:
        try:
            import torch  # type: ignore
            from transformers import AutoFeatureExtractor, AutoModel  # type: ignore
        except ImportError:
            raise ImportError(
                "EmbeddingGeneratorNode: 'transformers' and 'torch' required. "
                "Install with: pip install transformers>=4.30 torch>=2.0"
            )

        model_id = self.config.model_name_or_path or _HF_MODELS.get(model_key, model_key)

        # Cache model + processor
        if self._model_obj is None:
            self._processor_obj = AutoFeatureExtractor.from_pretrained(model_id)
            self._model_obj = AutoModel.from_pretrained(model_id)
            self._model_obj.eval()

        # Resample to model-specific expected rate
        target_sr = 16000
        if model_key in ("wav2vec2", "hubert"):
            # Speech models expect 16kHz
            if sr != target_sr:
                import librosa  # type: ignore
                y = librosa.resample(y=y, orig_sr=sr, target_sr=target_sr)
                sr = target_sr
        elif model_key == "clap":
            # CLAP (laion/clap-htsat-unfused) expects 48kHz for audio, 16kHz for speech
            # Use 48kHz as the safe default for the general audio CLAP model
            clap_sr = 48000
            if sr != clap_sr:
                import librosa  # type: ignore
                y = librosa.resample(y=y, orig_sr=sr, target_sr=clap_sr)
                sr = clap_sr

        inputs = self._processor_obj(y, sampling_rate=sr, return_tensors="pt")

        with torch.no_grad():
            outputs = self._model_obj(**inputs, output_hidden_states=True)

        # Extract hidden states from specified layer
        if hasattr(outputs, "hidden_states") and outputs.hidden_states:
            layer_idx = self.config.layer  # -1 = last
            hidden = outputs.hidden_states[layer_idx]  # (1, T, D)
        else:
            hidden = outputs.last_hidden_state  # (1, T, D)

        return self._pool(hidden.squeeze(0).numpy())  # (T, D) → (D,)

    # ── YAMNet backend ────────────────────────────────────────────────────────

    def _embed_yamnet(self, y: np.ndarray, sr: int) -> np.ndarray:
        try:
            import tensorflow_hub as hub  # type: ignore
            import tensorflow as tf  # type: ignore
        except ImportError:
            raise ImportError(
                "EmbeddingGeneratorNode: 'tensorflow' and 'tensorflow_hub' required for model='yamnet'. "
                "Install with: pip install tensorflow>=2.12 tensorflow-hub>=0.14"
            )

        if self._model_obj is None:
            self._model_obj = hub.load("https://tfhub.dev/google/yamnet/1")

        # YAMNet expects 16kHz mono float32
        if sr != 16000:
            import librosa  # type: ignore
            y = librosa.resample(y=y, orig_sr=sr, target_sr=16000)

        waveform = tf.constant(y, dtype=tf.float32)
        _, embeddings, _ = self._model_obj(waveform)
        # embeddings shape: (N_frames, 1024)
        return self._pool(embeddings.numpy())

    # ── x-vector (SpeechBrain) ────────────────────────────────────────────────

    def _embed_xvector(self, y: np.ndarray, sr: int) -> np.ndarray:
        try:
            import torch  # type: ignore
            from speechbrain.inference.speaker import EncoderClassifier  # type: ignore
        except ImportError:
            raise ImportError(
                "EmbeddingGeneratorNode: 'speechbrain' required for model='xvector'. "
                "Install with: pip install speechbrain>=0.5"
            )

        if self._model_obj is None:
            self._model_obj = EncoderClassifier.from_hparams(
                source="speechbrain/spkrec-xvect-voxceleb",
                savedir="pretrained_models/spkrec-xvect-voxceleb",
            )

        # x-vector expects 16kHz
        if sr != 16000:
            import librosa  # type: ignore
            y = librosa.resample(y=y, orig_sr=sr, target_sr=16000)

        import torch  # type: ignore
        wav_tensor = torch.from_numpy(y).unsqueeze(0)  # (1, N)
        with torch.no_grad():
            emb = self._model_obj.encode_batch(wav_tensor)  # (1, 1, D)
        return emb.squeeze().numpy()

    # ── OpenL3 ────────────────────────────────────────────────────────────────

    def _embed_openl3(self, y: np.ndarray, sr: int) -> np.ndarray:
        try:
            import openl3  # type: ignore
        except ImportError:
            raise ImportError(
                "EmbeddingGeneratorNode: 'openl3' required for model='openl3'. "
                "Install with: pip install openl3>=0.4"
            )

        emb, _ = openl3.get_audio_embedding(y, sr, content_type="music", embedding_size=512)
        # emb shape: (N_frames, 512)
        return self._pool(emb)

    # ── pooling ───────────────────────────────────────────────────────────────

    def _pool(self, hidden: np.ndarray) -> np.ndarray:
        """Pool a (T, D) hidden state array to (D,)."""
        if hidden.ndim == 1:
            return hidden
        pooling = self.config.pooling
        if pooling == "mean":
            return hidden.mean(axis=0)
        elif pooling == "cls":
            return hidden[0]
        elif pooling == "last":
            return hidden[-1]
        elif pooling == "none":
            return hidden.flatten()
        else:
            return hidden.mean(axis=0)
