"""MultimodalFusionNode — fuse audio representations with other modalities.

Fusion strategies:
    concat          — concatenate modality vectors, project to output_dim
    attention       — cross-modal attention (audio attends to text/video)
    late            — separate predictions per modality, weighted average
    cross_attention — bidirectional cross-attention between modalities
"""
from __future__ import annotations

import logging
from typing import ClassVar

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

log = logging.getLogger(__name__)

# Import EmbeddingVector — available when embedding_generator plugin is installed
try:
    from embedding_generator.types import EmbeddingVector  # type: ignore
except ImportError:
    # Fallback: use object type if embedding_generator not installed
    EmbeddingVector = object  # type: ignore


class MultimodalFusionNode(Node):
    """Fuse audio representations with text, video, or sensor modalities.

    Input ports:
        audio  — list[EmbeddingVector] (required)
        text   — list[EmbeddingVector] (optional)
        video  — list[EmbeddingVector] (optional)

    Output port:
        output — list[EmbeddingVector] (fused representations)

    Config:
        fusion_type (str): "concat" | "attention" | "late" | "cross_attention"
        audio_dim (int): audio embedding dimension (default 768)
        text_dim (int): text embedding dimension (default 768)
        output_dim (int): output embedding dimension (default 512)
        backend (str): "pytorch" | "numpy" (default "numpy" — no deps)
        normalize (bool): L2-normalize output embeddings (default True)
    """

    node_type: ClassVar[str] = "multimodal_fusion"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="multimodal_fusion",
        label="Multimodal Fusion",
        description=(
            "Fuse audio embeddings with text, video, or sensor modalities. "
            "Strategies: concat, attention, late fusion, cross-attention."
        ),
        category="Features",
        version="1.0.0",
        tags=["multimodal", "fusion", "embeddings", "audio", "text", "video", "clap"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=False,
        deterministic=True,
        cacheable=True,
        streaming_support=False,
        realtime_support=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "audio": InputPort(
            name="audio",
            data_type=list,
            cardinality="single",
            required=True,
            description="Audio embedding vectors",
        ),
        "text": InputPort(
            name="text",
            data_type=list,
            cardinality="single",
            required=False,
            description="Text embedding vectors (optional)",
        ),
        "video": InputPort(
            name="video",
            data_type=list,
            cardinality="single",
            required=False,
            description="Video embedding vectors (optional)",
        ),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=list,
            description="Fused embedding vectors",
        )
    }

    class Config(NodeConfig):
        fusion_type: str = "concat"     # "concat" | "attention" | "late" | "cross_attention"
        audio_dim: int = 768
        text_dim: int = 768             # reserved: used when PyTorch backend is implemented
        output_dim: int = 512
        backend: str = "numpy"          # "pytorch" | "numpy"
        # NOTE: backend="pytorch" is reserved for future implementation.
        # All fusion strategies currently use pure numpy regardless of this setting.
        normalize: bool = True

    # ── multi-port process ────────────────────────────────────────────────────

    def process(self, inputs: dict) -> dict:
        audio_vecs: list = inputs.get("audio") or []
        text_vecs: list = inputs.get("text") or []
        video_vecs: list = inputs.get("video") or []

        if not audio_vecs:
            return {"output": []}

        if self.config.backend == "pytorch":
            log.warning(
                "MultimodalFusionNode: backend='pytorch' is not yet implemented. Using numpy."
            )

        fusion_type = self.config.fusion_type

        # Warn when modality list lengths differ — produces inconsistent fusion
        if text_vecs and len(text_vecs) != len(audio_vecs):
            log.warning(
                "MultimodalFusionNode: text_vecs length (%d) != audio_vecs length (%d). "
                "Samples beyond text_vecs length will be fused without text context.",
                len(text_vecs), len(audio_vecs),
            )
        if video_vecs and len(video_vecs) != len(audio_vecs):
            log.warning(
                "MultimodalFusionNode: video_vecs length (%d) != audio_vecs length (%d). "
                "Samples beyond video_vecs length will be fused without video context.",
                len(video_vecs), len(audio_vecs),
            )

        output: list = []

        for i, audio_ev in enumerate(audio_vecs):
            a_emb = self._get_embedding(audio_ev)

            # Collect other modality embeddings at same index
            other_embs: list[np.ndarray] = []
            if i < len(text_vecs):
                other_embs.append(self._get_embedding(text_vecs[i]))
            if i < len(video_vecs):
                other_embs.append(self._get_embedding(video_vecs[i]))

            if not other_embs:
                # No other modalities — pass audio through with projection
                fused = self._project(a_emb, self.config.output_dim)
            elif fusion_type == "concat":
                fused = self._fuse_concat(a_emb, other_embs)
            elif fusion_type == "attention":
                fused = self._fuse_attention(a_emb, other_embs)
            elif fusion_type == "late":
                fused = self._fuse_late(a_emb, other_embs)
            elif fusion_type == "cross_attention":
                fused = self._fuse_cross_attention(a_emb, other_embs)
            else:
                raise ValueError(
                    f"MultimodalFusionNode: unknown fusion_type '{fusion_type}'. "
                    "Choose from: concat, attention, late, cross_attention"
                )

            if self.config.normalize:
                norm = np.linalg.norm(fused)
                if norm > 1e-8:
                    fused = fused / norm

            # Wrap in EmbeddingVector if available
            try:
                source_path = getattr(audio_ev, "source_path", "")
                label = getattr(audio_ev, "label", "")
                meta = dict(getattr(audio_ev, "metadata", {}))
                meta["multimodal_fusion"] = {
                    "fusion_type": fusion_type,
                    "modalities": ["audio"] + (["text"] if text_vecs else []) + (["video"] if video_vecs else []),
                }
                from embedding_generator.types import EmbeddingVector as EV  # type: ignore
                result = EV(
                    embedding=fused.astype(np.float32),
                    source_path=source_path,
                    label=label,
                    embedding_model=f"multimodal_fusion_{fusion_type}",
                    pooling="none",
                    metadata=meta,
                )
            except ImportError:
                result = fused.astype(np.float32)

            output.append(result)

        return {"output": output}

    # ── fusion strategies ─────────────────────────────────────────────────────

    def _fuse_concat(self, audio: np.ndarray, others: list[np.ndarray]) -> np.ndarray:
        """Concatenate all modality vectors, then project to output_dim."""
        all_vecs = [audio] + others
        concatenated = np.concatenate(all_vecs, axis=0)
        return self._project(concatenated, self.config.output_dim)

    def _fuse_attention(self, audio: np.ndarray, others: list[np.ndarray]) -> np.ndarray:
        """Audio attends to other modalities via dot-product attention.

        All modality vectors are projected to output_dim before attention so
        that mismatched embedding dimensions do not cause shape errors.
        """
        out_dim = self.config.output_dim
        # Project all to common dimension first
        a_proj = self._project(audio, out_dim)
        o_proj = [self._project(o, out_dim) for o in others]
        scale = np.sqrt(max(out_dim, 1))
        scores = np.array([np.dot(a_proj, o) / scale for o in o_proj])
        weights = self._softmax(scores)
        attended = sum(w * o for w, o in zip(weights, o_proj))
        fused = a_proj + attended  # residual connection
        return fused

    def _fuse_late(self, audio: np.ndarray, others: list[np.ndarray]) -> np.ndarray:
        """Late fusion: mean of all modality vectors (equal weights)."""
        all_vecs = [audio] + others
        # Project each to output_dim first, then average
        projected = [self._project(v, self.config.output_dim) for v in all_vecs]
        return np.mean(projected, axis=0)

    def _fuse_cross_attention(self, audio: np.ndarray, others: list[np.ndarray]) -> np.ndarray:
        """Bidirectional cross-attention: audio→others and others→audio, then concat+project.

        All modality vectors are projected to output_dim before attention so
        that mismatched embedding dimensions do not cause shape errors.
        """
        out_dim = self.config.output_dim
        # Project all to common dimension first
        a_proj = self._project(audio, out_dim)
        o_proj = [self._project(o, out_dim) for o in others]
        scale = np.sqrt(max(out_dim, 1))

        # Audio attends to others
        scores_a = np.array([np.dot(a_proj, o) / scale for o in o_proj])
        weights_a = self._softmax(scores_a)
        ctx_a = sum(w * o for w, o in zip(weights_a, o_proj))

        # Others attend to audio
        ctx_o_list = []
        for o in o_proj:
            score = np.dot(o, a_proj) / scale
            ctx_o_list.append(o + score * a_proj)

        ctx_o = np.mean(ctx_o_list, axis=0) if ctx_o_list else np.zeros(out_dim, dtype=np.float32)

        fused = np.concatenate([a_proj + ctx_a, ctx_o], axis=0)
        return self._project(fused, out_dim)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _get_embedding(self, ev) -> np.ndarray:
        """Extract numpy embedding from EmbeddingVector or raw ndarray."""
        if hasattr(ev, "embedding") and ev.embedding is not None:
            return np.asarray(ev.embedding, dtype=np.float32)
        if isinstance(ev, np.ndarray):
            return ev.astype(np.float32)
        return np.zeros(self.config.audio_dim, dtype=np.float32)

    def setup(self) -> None:
        """Initialise projection matrix cache."""
        self._proj_cache: dict = {}

    def _project(self, vec: np.ndarray, out_dim: int) -> np.ndarray:
        """Linear projection via row-normalized random matrix (deterministic seed).

        Uses Johnson-Lindenstrauss scaling (divide by sqrt(out_dim)) rather than
        per-row normalization. The matrix is NOT orthogonal — it is a scaled
        random Gaussian matrix suitable for dimensionality reduction.

        The projection matrix is cached per (in_dim, out_dim) pair so it is
        only computed once per unique shape combination.
        """
        in_dim = len(vec)
        if in_dim == out_dim:
            return vec
        cache_key = (in_dim, out_dim)
        if not hasattr(self, "_proj_cache"):
            self._proj_cache = {}
        if cache_key not in self._proj_cache:
            # Use a seed derived from the shape pair for independence between pairs
            seed = hash(cache_key) & 0xFFFFFFFF
            rng = np.random.default_rng(seed=seed)
            W = rng.standard_normal((out_dim, in_dim)).astype(np.float32)
            W /= np.sqrt(out_dim)  # JL scaling
            self._proj_cache[cache_key] = W
        return self._proj_cache[cache_key] @ vec

    def _softmax(self, x: np.ndarray) -> np.ndarray:
        e = np.exp(x - np.max(x))
        return e / (e.sum() + 1e-8)
