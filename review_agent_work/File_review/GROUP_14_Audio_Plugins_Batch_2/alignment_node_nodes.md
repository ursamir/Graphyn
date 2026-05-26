# Functional Review — PluginPackage/Audio/alignment_node/nodes.py

**Group:** 14 — Audio Plugins Batch 2
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/alignment_node/nodes.py
FUNCTION:    AlignmentNode.setup
CATEGORY:    Silent Failure
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Pre-load the CTC model once so it is not reloaded on every process() call.

WHAT IT ACTUALLY DOES:
On ImportError (ctc-forced-aligner not installed) it silently passes with `pass`,
setting `self._ctc_model = None`. When `process()` is later called with
`backend="ctc"`, `_align_ctc()` is invoked, which re-imports the library and
raises ImportError at that point — but only after the pipeline has already
started processing samples.

THE BUG / RISK:
The silent `pass` in `setup()` means the node appears healthy at startup even
when its required dependency is missing. The error surfaces mid-pipeline during
`process()` rather than at setup time, potentially after partial results have
been written. For `backend="ctc"` (the default), this is a guaranteed runtime
crash on any system without ctc-forced-aligner installed.

EVIDENCE:
```python
# Lines ~107-115
try:
    from ctc_forced_aligner import load_alignment_model
    ...
except ImportError:
    pass  # ctc-forced-aligner not installed — will raise at align time if needed
```

REPRODUCTION SCENARIO:
1. Create AlignmentNode with default config (backend="ctc")
2. ctc-forced-aligner not installed
3. Call setup() — no error raised
4. Call process() with audio — ImportError raised mid-pipeline

IMPACT:
Silent wrong state at setup; crash during execution. Partial pipeline results
may be committed before the crash.

FIX DIRECTION:
```python
except ImportError:
    if self.config.backend == "ctc":
        raise ImportError(
            "AlignmentNode: 'ctc-forced-aligner' required for backend='ctc'. "
            "Install with: pip install ctc-forced-aligner>=2.0"
        )
    # else: auto/mfa — ok to defer
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/alignment_node/nodes.py
FUNCTION:    AlignmentNode._align_ctc
CATEGORY:    Async Bug / Resource Leak
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
CTC forced alignment via ctc-forced-aligner library, using cached model from setup().

WHAT IT ACTUALLY DOES:
Loads the model inside `_align_ctc()` when `self._ctc_model is None` (i.e., when
`setup()` was not called or failed silently). This means every call to `process()`
on a fresh node instance (without setup()) reloads the model from disk/network,
which is a blocking I/O operation inside what may be an async execution context.
The model is also never released — no teardown/cleanup method exists.

THE BUG / RISK:
1. If `setup()` was not called (e.g., node instantiated directly in tests), every
   `process()` call downloads/loads the model — O(N) model loads for N samples.
2. The loaded model tensors are held in `self._ctc_model` indefinitely with no
   `teardown()` to release GPU memory.

EVIDENCE:
```python
# Lines ~196-202
if getattr(self, "_ctc_model", None) is not None:
    alignment_model = self._ctc_model
    ...
else:
    alignment_model, alignment_tokenizer = load_alignment_model(
        model_path, device=device,
    )
```
No `teardown()` method defined anywhere in the class.

REPRODUCTION SCENARIO:
node = AlignmentNode()  # no setup() call
node.process({"audio": [sample1], "transcripts": [...]})  # loads model
node.process({"audio": [sample2], "transcripts": [...]})  # loads model again

IMPACT:
Performance degradation (repeated model loads); GPU memory leak on CUDA.

FIX DIRECTION:
Add a `teardown()` method:
```python
def teardown(self) -> None:
    self._ctc_model = None
    self._ctc_tokenizer = None
```
And document that `setup()` must be called before `process()`.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/alignment_node/nodes.py
FUNCTION:    AlignmentNode._align_ctc
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Performs CTC forced alignment; handles empty audio by passing it to the model.

WHAT IT ACTUALLY DOES:
Does not validate that `sample.data` is non-empty or non-None before constructing
the audio tensor. An empty array (zero samples) or a None data field will cause
a crash inside `torch.from_numpy()` or inside the CTC model's forward pass with
an opaque error message.

THE BUG / RISK:
Zero-length audio (e.g., from a failed load that returned an empty array) will
crash with a PyTorch error rather than a clear domain error. The error message
will not mention "empty audio" — it will be a tensor shape error deep in the model.

EVIDENCE:
```python
# Lines ~185-192
y = sample.data.astype(np.float32)
sr = sample.sample_rate
if sr != 16000:
    y = librosa.resample(y=y, orig_sr=sr, target_sr=16000)
audio_tensor = torch.from_numpy(y).unsqueeze(0).to(device)
# No length check before this point
```

REPRODUCTION SCENARIO:
sample.data = np.array([], dtype=np.float32)
node._align_ctc(sample, "hello world")
# → crash in torch.from_numpy or model forward

IMPACT:
Opaque crash; no clear error message; pipeline aborts without useful diagnostics.

FIX DIRECTION:
```python
if sample.data is None or len(sample.data) == 0:
    raise ValueError(
        f"AlignmentNode: empty audio for sample '{sample.path}'"
    )
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/alignment_node/nodes.py
FUNCTION:    AlignmentNode._align_ctc
CATEGORY:    Contract Mismatch
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Calls `preprocess_text()` twice — once without `star_frequency` and once with
`star_frequency="edges"` — and uses the second call's return value for alignment.

WHAT IT ACTUALLY DOES:
The first call to `preprocess_text()` (line ~196) stores its result in
`text_preprocessed` but this variable is never used. The second call (line ~205)
is the one actually used. This is dead code that wastes a call to the library
and may indicate a copy-paste error where the first call was intended to be used
for something (e.g., validation or logging).

EVIDENCE:
```python
text_preprocessed = preprocess_text(
    text, language=language, split_size=self.config.level,
)
# text_preprocessed is never referenced again

tokens_starred, text_starred = preprocess_text(
    text, language=language, split_size=self.config.level,
    star_frequency="edges",
)
```

REPRODUCTION SCENARIO:
Any call to `_align_ctc()` — the first `preprocess_text` result is silently discarded.

IMPACT:
Wasted computation; potential confusion if the first call was intended for
validation (e.g., checking that the text is non-empty after preprocessing).

FIX DIRECTION:
Remove the first `preprocess_text()` call entirely, or use its result for
pre-flight validation before the more expensive `generate_emissions()` call.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/alignment_node/nodes.py
FUNCTION:    AlignmentNode._parse_textgrid
CATEGORY:    Silent Failure
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Minimal TextGrid parser — extracts intervals from the named tier.

WHAT IT ACTUALLY DOES:
The parser uses a simple line-by-line state machine. Once `in_tier = True` is
set, it never resets to `False` when a new tier begins. If the target tier
appears before other tiers in the file, the parser will correctly extract only
that tier's intervals. But if the file has multiple tiers and the target tier
is not the last one, the parser will continue reading into the next tier's
intervals after the target tier ends, silently mixing intervals from different
tiers.

THE BUG / RISK:
TextGrid files from MFA typically have a "words" tier followed by a "phones"
tier. If `tier="word"` is requested, the parser sets `in_tier=True` on the
"words" tier name line and never resets it, so it will also parse the "phones"
tier intervals and append them to the word list.

EVIDENCE:
```python
in_tier = False
for line in content.splitlines():
    line = line.strip()
    if not in_tier:
        for candidate in tier_candidates:
            if f'name = "{candidate}"' in line:
                in_tier = True
                break
    if not in_tier:
        continue
    # in_tier is never set back to False
```

REPRODUCTION SCENARIO:
TextGrid with "words" tier followed by "phones" tier.
_parse_textgrid(tg_path, tier="word") → returns word + phone intervals mixed.

IMPACT:
Silent wrong result — alignment timestamps include phoneme intervals mixed with
word intervals. Downstream consumers (e.g., training data alignment) get
corrupted timestamps.

FIX DIRECTION:
Track tier boundaries using `item [N]:` markers or reset `in_tier` when a new
`name = "..."` line is encountered that does not match the target tier:
```python
elif line.startswith('name = "') and in_tier:
    in_tier = False  # entered a different tier
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/alignment_node/nodes.py
FUNCTION:    AlignmentNode._align_mfa
CATEGORY:    Error Handling
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Runs MFA alignment via subprocess; raises RuntimeError on failure.

WHAT IT ACTUALLY DOES:
The `subprocess.run(..., check=True)` call raises `subprocess.CalledProcessError`
on non-zero exit, which is caught and re-raised as `RuntimeError`. However, the
`mfa version` check at the top uses `result.returncode != 0` to detect failure,
but does NOT check for `subprocess.TimeoutExpired` — if `mfa version` hangs for
more than 10 seconds, `TimeoutExpired` propagates uncaught and surfaces as an
unhandled exception rather than the expected `ImportError`.

EVIDENCE:
```python
result = subprocess.run(
    ["mfa", "version"],
    capture_output=True, text=True, timeout=10,
)
if result.returncode != 0:
    raise FileNotFoundError("mfa returned non-zero exit code")
# TimeoutExpired not caught here
```

REPRODUCTION SCENARIO:
`mfa version` hangs (e.g., on a slow NFS mount or misconfigured conda env).
After 10s, `subprocess.TimeoutExpired` propagates uncaught.

IMPACT:
Unhandled exception type — callers expecting `ImportError` or `RuntimeError`
will not catch it.

FIX DIRECTION:
```python
except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
    raise ImportError("AlignmentNode: MFA not found or unresponsive.") from exc
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/alignment_node/nodes.py
FUNCTION:    AlignmentNode._align_ctc
CATEGORY:    Type Safety
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Normalises CTC output to the schema {"word": str, "start": float, "end": float, "score": float}.

WHAT IT ACTUALLY DOES:
Uses `entry.get("label", "")`, `entry.get("start", 0.0)`, `entry.get("end", 0.0)`,
`entry.get("score", 1.0)` — but the actual keys returned by `postprocess_results()`
depend on the ctc-forced-aligner version. If the library changes its output schema
(e.g., "text" instead of "label"), all words will silently have `word=""`.

EVIDENCE:
```python
words.append({
    "word": entry.get("label", ""),  # key name version-dependent
    "start": float(entry.get("start", 0.0)),
    ...
})
```

REPRODUCTION SCENARIO:
ctc-forced-aligner >= 3.0 changes output key from "label" to "text".
All word entries have word="" silently.

IMPACT:
Silent wrong result — alignment data is structurally valid but semantically empty.

FIX DIRECTION:
Add a fallback: `entry.get("label") or entry.get("text", "")`.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 3 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | UNSAFE |
| Test Hostile | PARTIAL |
| Top Risk | `_parse_textgrid` silently mixes intervals from multiple tiers, producing corrupted word-level timestamps without any error or warning. |
