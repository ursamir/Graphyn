# Functional Review — PluginPackage/Common/embedding_generator/nodes.py

**Group:** 16 — Common Plugins  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Common/embedding_generator/nodes.py
FUNCTION:    EmbeddingGeneratorNode.process
CATEGORY:    State Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Generate semantic embedding vectors from audio using pretrained models."

WHAT IT ACTUALLY DOES:
The model and processor are cached in `self._model_obj` and `self._processor_obj`
(set in `_embed_transformers`). However, `setup()` sets `self._model_obj = None`
and `self._resolved_model = ...`. If `process()` is called with `model="wav2vec2"`,
the model is loaded and cached. If `process()` is then called again with a
different `model` config value (e.g., `model="hubert"`), the cached model from
the previous call is reused because the cache check is only `if self._model_obj is None`.

THE BUG / RISK:
The model cache does not key on the model name. If the node's config is mutated
between calls (or if the same node instance is reused with a different model),
the wrong model is used for embedding. This is a silent wrong result.

EVIDENCE:
```python
# In _embed_transformers:
if self._model_obj is None:
    self._processor_obj = AutoFeatureExtractor.from_pretrained(model_id)
    self._model_obj = AutoModel.from_pretrained(model_id)
    self._model_obj.eval()
# No check that self._model_obj matches model_id
```

REPRODUCTION SCENARIO:
```python
node = EmbeddingGeneratorNode(Config(model="wav2vec2"))
node.setup()
node.process(samples)  # loads wav2vec2, caches it
node.config.model = "hubert"  # config mutated
node.process(samples)  # reuses wav2vec2 model — wrong embeddings, no error
```

IMPACT:
Silent wrong result. Embeddings from the wrong model are returned without any
warning.

FIX DIRECTION:
Key the cache on the resolved model ID:
```python
if self._model_obj is None or self._cached_model_id != model_id:
    self._processor_obj = AutoFeatureExtractor.from_pretrained(model_id)
    self._model_obj = AutoModel.from_pretrained(model_id)
    self._model_obj.eval()
    self._cached_model_id = model_id
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/embedding_generator/nodes.py
FUNCTION:    EmbeddingGeneratorNode.process
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Generate semantic embedding vectors from audio using pretrained models."

WHAT IT ACTUALLY DOES:
Does not validate that `samples` is non-empty or that each `sample.data` is
non-empty before processing. If `sample.data` is an empty array (zero samples),
`y = sample.data.astype(np.float32)` produces an empty array. This is then
passed to the model processor. For wav2vec2/hubert, the HuggingFace processor
may raise a `ValueError` about empty input. For YAMNet, `tf.constant(y)` with
an empty array may produce a zero-frame output, and `_pool` on a zero-row array
returns `np.zeros(D)` (mean of empty = 0 via numpy), which is a silent wrong result.

THE BUG / RISK:
Empty audio input produces a zero embedding vector without any warning or error
for some backends (numpy mean of empty array returns 0 in some numpy versions,
or raises `RuntimeWarning: Mean of empty slice`).

EVIDENCE:
```python
for sample in samples:
    y = sample.data.astype(np.float32)   # may be empty
    # No check for len(y) == 0
    emb = self._embed_transformers(y, sr, model_key)
```

REPRODUCTION SCENARIO:
```python
sample = AudioSample(data=np.array([]), sample_rate=16000, ...)
node.process([sample])  # may crash or return zero embedding silently
```

IMPACT:
Silent wrong result (zero embedding) or crash depending on backend.

FIX DIRECTION:
```python
if len(y) == 0:
    log.warning("EmbeddingGeneratorNode: empty audio sample '%s' — skipping", sample.path)
    continue
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/embedding_generator/nodes.py
FUNCTION:    EmbeddingGeneratorNode._embed_transformers
CATEGORY:    State Bug
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Cache model + processor" for reuse across samples.

WHAT IT ACTUALLY DOES:
The YAMNet and x-vector backends also cache in `self._model_obj`, but the
transformers backend additionally caches `self._processor_obj`. If `setup()` is
called again (e.g., node is reused after teardown), `self._model_obj = None`
is reset but `self._processor_obj` is NOT reset in `setup()`. On the next
`_embed_transformers` call, `self._model_obj is None` triggers a reload, but
`self._processor_obj` still holds the old processor from the previous setup
cycle. If the model changed, the processor is stale.

THE BUG / RISK:
Stale processor from a previous setup cycle is used with a newly loaded model.
For models with compatible processors this is harmless; for models with
incompatible processors (e.g., wav2vec2 processor used with hubert model after
config change), this produces wrong embeddings silently.

EVIDENCE:
```python
def setup(self) -> None:
    self._model_obj = None        # reset
    self._processor_obj = None    # also reset — actually this IS reset
```
Wait — `setup()` does set `self._processor_obj = None`. So the stale processor
issue only applies if `_embed_transformers` is called without `setup()` being
called first (i.e., if the node is used without calling `setup()`). In that case,
`self._processor_obj` is not initialized and `self._model_obj` is also not
initialized, so `hasattr` checks would fail.

Revised finding: `process()` calls `_embed_transformers` which accesses
`self._model_obj` and `self._processor_obj`. If `setup()` was never called,
these attributes don't exist, and `if self._model_obj is None` raises
`AttributeError: 'EmbeddingGeneratorNode' object has no attribute '_model_obj'`.

EVIDENCE (revised):
```python
def setup(self) -> None:
    self._model_obj = None        # only set if setup() is called
    self._processor_obj = None

def _embed_transformers(self, y, sr, model_key):
    if self._model_obj is None:   # AttributeError if setup() not called
```

REPRODUCTION SCENARIO:
```python
node = EmbeddingGeneratorNode(Config(model="wav2vec2"))
# setup() not called
node.process(samples)  # AttributeError: '_model_obj'
```

IMPACT:
Crash if setup() is not called. The base class should call setup() but if the
node is instantiated and used directly in tests, this is a testability hazard.

FIX DIRECTION:
Initialize `_model_obj` and `_processor_obj` in `__init__` or add a guard:
```python
def _embed_transformers(self, y, sr, model_key):
    if not hasattr(self, "_model_obj") or self._model_obj is None:
        ...
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/embedding_generator/nodes.py
FUNCTION:    EmbeddingGeneratorNode._pool
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Pool a (T, D) hidden state array to (D,)."

WHAT IT ACTUALLY DOES:
For `pooling="cls"`, returns `hidden[0]` — the first token. For `pooling="last"`,
returns `hidden[-1]`. If `hidden` has zero rows (T=0), `hidden[0]` raises
`IndexError: index 0 is out of bounds for axis 0 with size 0`.

THE BUG / RISK:
Zero-frame audio (or very short audio that produces zero frames after feature
extraction) causes an `IndexError` in `_pool` for `cls` and `last` pooling modes.

EVIDENCE:
```python
elif pooling == "cls":
    return hidden[0]   # IndexError if T=0
elif pooling == "last":
    return hidden[-1]  # IndexError if T=0
```

REPRODUCTION SCENARIO:
Pass audio shorter than one model frame with `pooling="cls"`.

IMPACT:
Crash with IndexError.

FIX DIRECTION:
```python
if hidden.shape[0] == 0:
    return np.zeros(hidden.shape[1] if hidden.ndim > 1 else self.config.audio_dim, dtype=np.float32)
```
--------------------------------------------------------------------

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 2 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | UNSAFE |
| Resource Safety | SAFE |
| Test Hostile | PARTIAL |
| Top Risk | Model cache does not key on model name — wrong model silently reused if config is mutated between calls |
