# Functional Review — PluginPackage/Audio/augmentation_pipeline/nodes.py

**Group:** 14 — Audio Plugins Batch 2
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/augmentation_pipeline/nodes.py
FUNCTION:    AugmentationPipelineNode.__init__
CATEGORY:    State Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Initialises the node with a seeded RNG for reproducible augmentation.

WHAT IT ACTUALLY DOES:
`self.rng = np.random.default_rng(seed)` is set at `__init__` time with
`seed=0` as the default. The RNG is a stateful object stored on the instance.
If the same node instance is used across multiple `process()` calls (which is
the normal execution model — nodes are instantiated once and `process()` is
called repeatedly), the RNG state advances across calls. This means:

1. The augmentation sequence is NOT reproducible per-call — it depends on
   how many prior calls have been made.
2. If two pipeline runs share the same node instance (e.g., via caching or
   re-use), the second run gets a different augmentation sequence than the first.
3. The `deterministic=False` metadata flag acknowledges non-determinism, but
   the seed parameter implies reproducibility — this contract is broken across
   calls.

THE BUG / RISK:
The seed only guarantees reproducibility for the very first `process()` call.
Subsequent calls produce different augmentations depending on call history.
This makes experiment reproduction impossible unless the node is re-instantiated
for each run.

EVIDENCE:
```python
def __init__(self, config=None, seed: int = 0, observer=None):
    super().__init__(config=config, seed=seed, observer=observer)
    self.rng = np.random.default_rng(seed)  # shared mutable state
```

REPRODUCTION SCENARIO:
node = AugmentationPipelineNode(seed=42)
out1 = node.process([sample])  # uses rng state starting at seed 42
out2 = node.process([sample])  # uses rng state AFTER first call — different result
# out1 != out2 even with same input and same seed

IMPACT:
Experiment irreproducibility; augmentation sequences cannot be replicated
across pipeline runs without re-instantiating the node.

FIX DIRECTION:
Either document clearly that seed only applies to the first call, or reset
the RNG at the start of each `process()` call if reproducibility per-call
is desired:
```python
def process(self, samples):
    self.rng = np.random.default_rng(self._seed)  # reset per call
    ...
```
Store `self._seed = seed` in `__init__`.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/augmentation_pipeline/nodes.py
FUNCTION:    AugmentationPipelineNode._aug_pitch_shift
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
librosa.effects.pitch_shift with random semitones.

WHAT IT ACTUALLY DOES:
Does not validate that `s.data` is non-empty before calling
`librosa.effects.pitch_shift()`. An empty array (zero samples) will cause
librosa to raise a cryptic error deep in its STFT implementation rather than
a clear domain error. The same applies to `_aug_time_stretch()` and
`_aug_speed_perturb()`.

THE BUG / RISK:
Zero-length audio crashes with an opaque librosa/numpy error. The exception
IS caught by the outer `try/except` in `process()` and logged as a warning,
so the pipeline continues — but the augmented copy is silently dropped from
the output without the caller knowing.

EVIDENCE:
```python
def _aug_pitch_shift(self, s: AudioSample, cfg: dict) -> AudioSample:
    semitones_range = cfg.get("semitones", [-2, 2])
    n_steps = float(self.rng.uniform(semitones_range[0], semitones_range[1]))
    s.data = librosa.effects.pitch_shift(
        y=s.data, sr=s.sample_rate, n_steps=n_steps  # no empty check
    ).astype(np.float32)
```

REPRODUCTION SCENARIO:
sample.data = np.array([], dtype=np.float32)
node.process([sample])
→ warning logged, augmented copy silently absent from output

IMPACT:
Silent data loss — augmented copies are dropped without clear indication.
The original is still included (correct), but the augmented copies are lost.

FIX DIRECTION:
Add a guard at the top of `process()`:
```python
if s.data is None or len(s.data) == 0:
    log.warning("AugmentationPipelineNode: skipping empty audio sample '%s'", s.path)
    return out  # or skip augmentation copies
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/augmentation_pipeline/nodes.py
FUNCTION:    AugmentationPipelineNode._aug_speed_perturb
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Resample to sr*factor then back to sr (changes duration and pitch).

WHAT IT ACTUALLY DOES:
`target_sr = int(orig_sr * factor)` — if `factor` is very small (e.g., 0.01
from a misconfigured speed_factor range), `target_sr` could be 0 or 1.
`librosa.resample()` with `target_sr=0` raises a `ValueError` inside librosa.
This IS caught by the outer try/except, but the error message is opaque.

More critically: if `factor` is exactly 0.0 (possible if `speed_factor: [0, 1]`
is configured), `target_sr = 0` and librosa raises immediately.

EVIDENCE:
```python
target_sr = int(orig_sr * factor)  # can be 0 if factor is very small
resampled = librosa.resample(y=s.data, orig_sr=orig_sr, target_sr=target_sr)
```

REPRODUCTION SCENARIO:
Config: speed_factor: [0.0, 0.1]
factor = 0.001 → target_sr = 16 (ok) or 0 (crash if orig_sr < 1000)

IMPACT:
Crash caught by outer handler; augmented copy silently dropped.

FIX DIRECTION:
```python
target_sr = max(1, int(orig_sr * factor))
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/augmentation_pipeline/nodes.py
FUNCTION:    AugmentationPipelineNode._aug_gain
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Random gain in gain_db range → 10^(gain/20) * y.

WHAT IT ACTUALLY DOES:
`gain_range = cfg.get("gain_db", [-6, 6])` — if the config provides a scalar
instead of a list (e.g., `"gain_db": 6`), `self.rng.uniform(gain_range[0], gain_range[1])`
will fail with `TypeError: 'int' object is not subscriptable`. This is caught
by the outer try/except and logged as a warning, but the error message is
"'int' object is not subscriptable" — not helpful.

The same pattern applies to `_aug_pitch_shift` (semitones), `_aug_time_stretch`
(rate), `_aug_speed_perturb` (speed_factor), and `_aug_noise_inject` (snr_db).

EVIDENCE:
```python
gain_range = cfg.get("gain_db", [-6, 6])
gain_db = float(self.rng.uniform(gain_range[0], gain_range[1]))
# If gain_range is a scalar int, this crashes
```

REPRODUCTION SCENARIO:
augmentations = [{"type": "gain", "apply_prob": 0.5, "gain_db": 6}]
→ TypeError: 'int' object is not subscriptable (caught, logged as warning)

IMPACT:
Silent augmentation skip; user gets no clear indication that their config is wrong.

FIX DIRECTION:
```python
gain_range = cfg.get("gain_db", [-6, 6])
if not isinstance(gain_range, (list, tuple)) or len(gain_range) < 2:
    raise ValueError(f"AugmentationPipelineNode: 'gain_db' must be [min, max], got: {gain_range}")
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/augmentation_pipeline/nodes.py
FUNCTION:    AugmentationPipelineNode._aug_codec_degrade
CATEGORY:    Silent Failure
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Simulate codec degradation by encoding to MP3/Ogg and decoding back.

WHAT IT ACTUALLY DOES:
The entire soundfile encode/decode block is wrapped in a bare `except Exception`
that falls back to a low-pass filter. This means:
1. Any soundfile error (including OGG encoding failures on some platforms) is
   silently swallowed and replaced with a low-pass filter approximation.
2. The metadata records `{"codec": codec, "bitrate": bitrate}` regardless of
   whether the real codec path or the fallback path was used — the caller
   cannot tell which path was taken.
3. The fallback low-pass filter is a very poor approximation of codec
   degradation and produces qualitatively different results.

EVIDENCE:
```python
try:
    import soundfile as sf
    ...
    s.data = y_decoded.astype(np.float32)
except Exception:
    # Fallback: low-pass filter
    ...
    s.data = scipy.signal.sosfilt(sos, s.data).astype(np.float32)

s.metadata["codec_degrade"] = {"codec": codec, "bitrate": bitrate}
# No indication of which path was taken
```

REPRODUCTION SCENARIO:
soundfile OGG encoding fails on a platform without libvorbis.
→ fallback low-pass filter applied silently; metadata says "codec: mp3"

IMPACT:
Silent wrong result — training data augmented with low-pass filter instead of
codec simulation; metadata is misleading.

FIX DIRECTION:
Add a "method" key to metadata:
```python
s.metadata["codec_degrade"] = {"codec": codec, "bitrate": bitrate, "method": "ogg"}
# or "method": "lowpass_fallback"
```
And log a warning when the fallback is used.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/augmentation_pipeline/nodes.py
FUNCTION:    AugmentationPipelineNode._aug_eq
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Apply parametric EQ via IIR peaking filters.

WHAT IT ACTUALLY DOES:
`w0 = 2 * np.pi * freq / sr` — if `freq >= sr/2` (Nyquist), `w0 >= pi`,
which causes the IIR filter design to produce an unstable or degenerate filter.
`scipy.signal.lfilter` with an unstable filter will produce NaN or Inf values
in the output, which then propagate silently through the pipeline.

EVIDENCE:
```python
w0 = 2 * np.pi * freq / sr
A = 10 ** (gain_db / 40.0)
alpha = np.sin(w0) / (2 * q)
# No check that freq < sr/2
```

REPRODUCTION SCENARIO:
sr=16000, band={"freq": 8000, "gain_db": 6, "q": 1.0}
w0 = pi → sin(pi) = 0 → alpha = 0 → a0 = 1 + 0/A = 1 → degenerate filter

IMPACT:
NaN/Inf values in audio data; silent corruption propagated downstream.

FIX DIRECTION:
```python
if freq >= sr / 2:
    log.warning("AugmentationPipelineNode: EQ band freq %sHz >= Nyquist %sHz — skipping", freq, sr/2)
    continue
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/augmentation_pipeline/nodes.py
FUNCTION:    AugmentationPipelineNode._aug_audiomentations
CATEGORY:    Testability
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Apply an audiomentations transform via config dict.

WHAT IT ACTUALLY DOES:
`transform = transform_cls(**kwargs)` and `transform(samples=s.data, sample_rate=s.sample_rate)`
— the audiomentations API uses `samples=` as the keyword argument in some versions
and positional in others. If the installed version uses a different API, this
will fail with a TypeError that is caught by the outer handler and logged as a
warning, silently dropping the augmentation.

EVIDENCE:
```python
y_aug = transform(samples=s.data, sample_rate=s.sample_rate)
# API varies by audiomentations version
```

REPRODUCTION SCENARIO:
audiomentations >= 0.35 changes call signature.
→ TypeError caught, augmentation silently skipped.

IMPACT:
Silent augmentation skip; version-dependent behavior.

FIX DIRECTION:
Pin audiomentations version in requirements or add version check at import time.

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
| Top Risk | RNG state is shared and advances across `process()` calls, making augmentation sequences irreproducible across pipeline runs even with a fixed seed. |
