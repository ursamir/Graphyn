"""embedding_generator plugin — semantic audio embeddings (wav2vec2, HuBERT, CLAP, YAMNet, x-vector, OpenL3)."""
from .nodes import EmbeddingGeneratorNode
from .types import EmbeddingVector

__all__ = ["EmbeddingGeneratorNode", "EmbeddingVector"]
