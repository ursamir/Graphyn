# Functional Review — PluginPackage/Common/multimodal_fusion/nodes.py

**Group:** 16 — Common Plugins  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Common/multimodal_fusion/nodes.py
FUNCTION:    MultimodalFusionNode._project
CATEGORY:    State Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Linear projection via random orthogonal matrix (deterministic seed). The
projection matrix is cached per (in_dim, out_dim) pair so it is only computed
once per unique shape combination."

WHAT IT ACTUALLY DOES:
The projection matrix is generated with `np.random.default_rng(seed=42)` every
time a new `(in_dim, out_dim)` pair is encountered. The seed is always 42,
regardless of which pair is being computed. This means:

1. The first new pair `(768, 512)` gets a matrix from `rng(seed=42)`.
2. The second new pair `(1536, 512)` also gets a matrix from `rng(seed=42)`.

Both matrices start from the same RNG state, so they are generated from the
same random sequence. This is deterministic (same matrix for same shape), which
is the stated goal. However, the matrices for different input dimensions are
NOT independent — they are all prefixes of the same random sequence. For
`concat` fusion where `in_dim = audio_dim + text_dim`, the projection matrix
is a prefix of the same sequence as the `audio_dim` matrix. This creates
correlations between projection matrices that could affect fusion quality.

More critically: the `_proj_cache` is an instance variable initialized in
`setup()`. If `setup()` is not called, `_project` falls back to
`if not hasattr(self, "_proj_cache"): self._proj_cache = {}`. This fallback
creates a new empty cache on every call to `_project` if `setup()` was not
called, because `hasattr` returns False only on the first call — after the
first call, `_proj_cache` exists. Wait — actually the fallback creates it once
and then it persists. This is safe.

The real issue is that the projection matrix is NOT orthogonal despite the
docstring claiming "random orthogonal matrix". The code normalizes rows:
```python
W /= np.linalg.norm(W, axis=1, keepdims=True) + 1e-8
```
This produces a matrix with unit-norm rows, but it is NOT orthogonal (columns
are not orthonormal). For a true orthogonal projection, QR decomposition or
SVD should be used. The current matrix may have poor conditioning for large
input dimensions.

THE BUG / RISK:
The docstring claims "random orthogonal matrix" but the implementation produces
a row-normalized random matrix, which is NOT orthogonal. For high-dimensional
inputs, this can cause information loss or amplification in the projection.
This is a contract mismatch.

EVIDENCE:
```python
W = rng.standard_normal((out_dim, in_dim)).astype(np.float32)
W /= np.linalg.norm(W, axis=1, keepdims=True) + 1e-8
# W has unit-norm rows but is NOT orthogonal
```

REPRODUCTION SCENARIO:
```python
node = MultimodalFusionNode(Config(audio_dim=768, output_dim=512))
node.setup()
W = node._proj_cache.get((768, 512))
# np.allclose(W @ W.T, np.eye(512)) → False (not orthogonal)
```

IMPACT:
Suboptimal projection quality. Not a crash, but a contract mismatch that could
affect downstream model quality. The docstring misleads users about the
mathematical properties of the projection.

FIX DIRECTION:
Either fix the docstring to say "row-normalized random matrix" or use a proper
random orthogonal projection:
```python
# True random orthogonal projection (Johnson-Lindenstrauss):
W = rng.standard_normal((out_dim, in_dim)).astype(np.float32)
W /= np.sqrt(out_dim)  # JL scaling, not row normalization
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/multimodal_fusion/nodes.py
FUNCTION:    MultimodalFusionNode.process
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Fuse audio representations with text, video, or sensor modalities."

WHAT IT ACTUALLY DOES:
When `audio_vecs` is non-empty but `text_vecs` and `video_vecs` are both empty,
the code calls `self._project(a_emb, self.config.output_dim)` for each audio
vector. This is correct. However, when `text_vecs` is shorter than `audio_vecs`
(e.g., 3 text vectors for 5 audio vectors), the last 2 audio vectors are fused
without text context (`other_embs` is empty for indices 3 and 4), and the first
3 are fused with text. This asymmetry is not documented and produces
inconsistent fusion across the batch.

THE BUG / RISK:
Mismatched list lengths between modalities produce silently inconsistent fusion:
some samples are fused with text, others are not. No warning is emitted.

EVIDENCE:
```python
for i, audio_ev in enumerate(audio_vecs):
    other_embs = []
    if i < len(text_vecs):
        other_embs.append(self._get_embedding(text_vecs[i]))
    # If i >= len(text_vecs), other_embs is empty → no text fusion
```

REPRODUCTION SCENARIO:
```python
audio_vecs = [ev1, ev2, ev3, ev4, ev5]
text_vecs = [tv1, tv2, tv3]
node.process({"audio": audio_vecs, "text": text_vecs, "video": []})
# ev1-ev3 fused with text; ev4-ev5 fused without text — silent inconsistency
```

IMPACT:
Silent wrong result. Inconsistent embeddings in the output batch.

FIX DIRECTION:
Warn when list lengths differ:
```python
if text_vecs and len(text_vecs) != len(audio_vecs):
    log.warning(
        "MultimodalFusionNode: text_vecs length (%d) != audio_vecs length (%d). "
        "Samples beyond text_vecs length will be fused without text context.",
        len(text_vecs), len(audio_vecs)
    )
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/multimodal_fusion/nodes.py
FUNCTION:    MultimodalFusionNode._fuse_attention / _fuse_cross_attention
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Audio attends to other modalities via dot-product attention."

WHAT IT ACTUALLY DOES:
`_fuse_attention` computes `scores = np.array([np.dot(audio, o) / scale for o in others])`.
If `audio` and `o` have different dimensions (e.g., audio embedding is 768-D
but text embedding is 512-D), `np.dot(audio, o)` raises `ValueError: shapes
(768,) and (512,) not aligned`.

THE BUG / RISK:
Mismatched embedding dimensions between modalities cause a crash in attention
fusion. The `audio_dim` and `text_dim` config fields suggest different dimensions
are expected, but the attention implementation assumes they are the same.

EVIDENCE:
```python
scores = np.array([np.dot(audio, o) / scale for o in others])
# ValueError if len(audio) != len(o)
```

REPRODUCTION SCENARIO:
```python
audio_ev.embedding = np.zeros(768)
text_ev.embedding = np.zeros(512)
node.process({"audio": [audio_ev], "text": [text_ev]})
# ValueError: shapes (768,) and (512,) not aligned
```

IMPACT:
Crash when audio and text embeddings have different dimensions.

FIX DIRECTION:
Project all modalities to a common dimension before attention:
```python
a_emb = self._project(a_emb, self.config.output_dim)
other_embs = [self._project(o, self.config.output_dim) for o in other_embs]
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/multimodal_fusion/nodes.py
FUNCTION:    MultimodalFusionNode.process
CATEGORY:    Contract Mismatch
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Config field `backend` is documented as `"pytorch" | "numpy"` with a note that
`backend="pytorch"` is reserved for future implementation.

WHAT IT ACTUALLY DOES:
The `backend` config field is accepted but completely ignored. All fusion
strategies use pure numpy regardless of the `backend` setting. If a user sets
`backend="pytorch"`, they get numpy behavior with no warning.

THE BUG / RISK:
Silent contract mismatch. Users expecting PyTorch-accelerated fusion get numpy
behavior without any indication.

EVIDENCE:
```python
class Config(NodeConfig):
    backend: str = "numpy"   # "pytorch" | "numpy"
    # NOTE: backend="pytorch" is reserved for future implementation.
    # All fusion strategies currently use pure numpy regardless of this setting.
```
The note is in the config class but not surfaced at runtime.

REPRODUCTION SCENARIO:
Set `backend="pytorch"`. Fusion runs on numpy. No warning.

IMPACT:
User confusion. No data loss.

FIX DIRECTION:
```python
if self.config.backend == "pytorch":
    log.warning("MultimodalFusionNode: backend='pytorch' is not yet implemented. Using numpy.")
```
--------------------------------------------------------------------

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 2 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | Mismatched embedding dimensions between modalities crash attention fusion with a confusing numpy shape error |
