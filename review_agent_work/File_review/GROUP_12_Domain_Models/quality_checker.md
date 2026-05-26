# Functional Review — app/domain/quality_checker.py

**Group:** 12 — Domain & Models  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/domain/quality_checker.py
FUNCTION:    QualityChecker._check_snr
CATEGORY:    Silent Failure Risk
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Estimate SNR using the first `noise_profile_ms` ms as the noise estimate; flag samples below `snr_threshold_db`.

WHAT IT ACTUALLY DOES:
Uses `audio_data[:noise_samples]` as the noise estimate and `audio_data` (the entire file) as the signal. The SNR formula is `10 * log10(signal_power / noise_power)`. Since `signal_power` is computed over the entire file (which includes the noise region), and `noise_power` is computed over only the first N samples, the ratio `signal_power / noise_power` is always ≥ 1 for any file where the noise region is not louder than the rest of the file. This means the SNR estimate is systematically biased upward — a file that is pure noise will report SNR ≈ 0 dB (correct), but a file where the first 100ms is louder than the rest (e.g., a click or pop at the start) will report a negative SNR even for clean audio.

More critically: for silence-only audio (`audio_data` is all zeros), `noise_power = 0.0`, the function returns `[]` (no finding) via the `if noise_power <= 0: return []` guard. This is correct. But for near-silence audio where `noise_power > 0` but `signal_power` is also near zero (e.g., a file with a tiny click at the start followed by silence), `snr_db` will be very negative and the file will be flagged as low-SNR even though it is essentially silent — which may or may not be the desired behavior.

THE BUG / RISK:
The docstring acknowledges the limitation ("assumes the first noise_profile_ms milliseconds contain only background noise") but the implementation uses `np.mean(audio_data ** 2)` as `signal_power` — this is the mean power of the entire file, not the non-noise portion. For a file that starts with speech (common in many datasets), the "noise" estimate is actually signal power, making `noise_power ≈ signal_power` and SNR ≈ 0 dB, causing false positives.

EVIDENCE:
Lines ~230–260:
```python
noise_frames = audio_data[:noise_samples]
noise_power = float(np.mean(noise_frames ** 2))
if noise_power <= 0:
    return []
signal_power = float(np.mean(audio_data ** 2))
snr_db = 10.0 * math.log10(signal_power / noise_power)
```
`signal_power` includes the noise region.

REPRODUCTION SCENARIO:
Audio file: first 100ms is speech at -20 dBFS, rest is silence. `noise_power` = power of speech = high. `signal_power` = mean power of entire file = lower (mostly silence). `snr_db` = negative → false low-SNR warning.

IMPACT:
Silent wrong result — false positive SNR warnings for files that start with speech. False negatives for files that start with silence followed by noise. Quality reports are unreliable for datasets where audio does not start with silence.

FIX DIRECTION:
Exclude the noise region from the signal power calculation:
```python
signal_frames = audio_data[noise_samples:]
if len(signal_frames) == 0:
    return []
signal_power = float(np.mean(signal_frames ** 2))
```

--------------------------------------------------------------------
FILE:        app/domain/quality_checker.py
FUNCTION:    QualityChecker.run
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Run all quality checks on the given project/version; never raises — all errors are recorded as findings.

WHAT IT ACTUALLY DOES:
The docstring says "Never raises — all errors are recorded as findings." However, `version_dir.rglob("*.wav")` is only guarded by `if version_dir.exists()`. If `version_dir` exists but is not a directory (e.g., it is a file), `rglob` raises `NotADirectoryError`. Additionally, `self._persist(project_dir, findings)` is called at the end, but if `project_dir` does not exist (e.g., the project was deleted between the start of the run and the persist call), `project_dir.mkdir(parents=True, exist_ok=True)` will succeed (it creates the directory), but this silently recreates a deleted project directory.

More critically: for silence-only audio (all zeros), `_check_clipping` calls `np.abs(audio_data).max()` which returns `0.0` — no finding, correct. `_check_dc_offset` calls `np.mean(audio_data)` which returns `0.0` — no finding, correct. `_check_snr` returns `[]` because `noise_power <= 0` — correct. `_check_duplicate` computes SHA-256 of all-zero bytes — this will correctly detect duplicate silence files. So silence-only audio is handled correctly for most checks.

For clipped audio (all samples at ±1.0): `_check_clipping` correctly flags it. `_check_snr`: `noise_power = 1.0`, `signal_power = 1.0`, `snr_db = 0.0` — flagged as low-SNR (below 10 dB threshold). This is a false positive for clipped audio — the SNR check fires for a different reason than intended.

For mono vs stereo: `_load_audio` uses `librosa.load(..., mono=True)` which always returns mono. `soundfile` fallback uses `data.mean(axis=1)` for multi-channel. So stereo is handled correctly.

THE BUG / RISK:
The "never raises" contract is violated for `NotADirectoryError` when `version_dir` is a file, and for any unhandled exception in `_check_outliers` or `_check_class_imbalance` (these have no try/except).

EVIDENCE:
Lines ~75–80:
```python
wav_files = sorted(version_dir.rglob("*.wav")) if version_dir.exists() else []
```
No check that `version_dir.is_dir()`.

Lines ~155–165 (`_check_outliers` call): no try/except around the call.

REPRODUCTION SCENARIO:
`version_dir` is a file (filesystem corruption or naming collision). `version_dir.rglob("*.wav")` raises `NotADirectoryError`, which propagates out of `run()`, violating the "never raises" contract.

IMPACT:
Unhandled exception propagates to the API layer, returning a 500 error instead of an empty findings list.

FIX DIRECTION:
Change the guard to `if version_dir.exists() and version_dir.is_dir()`. Wrap the entire `run()` body in a try/except as the docstring promises.

--------------------------------------------------------------------
FILE:        app/domain/quality_checker.py
FUNCTION:    QualityChecker._check_duplicate
CATEGORY:    Performance
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Compute SHA-256 of raw float32 PCM bytes after resampling to 16 kHz mono; flag pairs with identical fingerprints.

WHAT IT ACTUALLY DOES:
For each file, calls `librosa.resample(mono, orig_sr=sr, target_sr=16000)` if `sr != 16000`. For large datasets, this is O(N) resampling operations, each of which is CPU-intensive. The resampled array is then converted to float32 bytes and SHA-256 hashed. For a 10-second audio file at 44100 Hz, the resampled array is ~160,000 float32 values = 640 KB. SHA-256 of 640 KB is fast, but the resampling itself is expensive.

More importantly: the `fingerprints` dict is passed by reference and mutated across all files. If `_check_duplicate` raises an exception for one file (caught by the outer try/except), the `fingerprints` dict may be in an inconsistent state — but since the exception is caught and the fingerprint is not added, this is actually safe.

THE BUG / RISK:
For very large audio files (e.g., 10-minute recordings), `mono.astype(np.float32).tobytes()` before resampling creates a large in-memory buffer. After resampling to 16 kHz, the buffer is smaller, but the intermediate full-resolution buffer is held in memory during the hash computation. For a 10-minute 44100 Hz file: 26.5M samples × 4 bytes = 106 MB per file, held in memory simultaneously with the resampled version.

EVIDENCE:
Lines ~290–315:
```python
mono = _to_mono(audio_data)
if sr != target_sr:
    mono = librosa.resample(mono, orig_sr=sr, target_sr=target_sr)
pcm_bytes = mono.astype(np.float32).tobytes()
fingerprint = hashlib.sha256(pcm_bytes).hexdigest()
```

REPRODUCTION SCENARIO:
Dataset with 1000 × 10-minute 44100 Hz WAV files. Each duplicate check loads the full audio (already done by `_load_audio`), resamples it, and hashes it. Peak memory per file: ~106 MB for the original + ~38 MB for the resampled = ~144 MB per file (though the original is already in `audio_data`).

IMPACT:
High memory usage for large audio files; potential OOM for very large datasets. Not a correctness bug.

FIX DIRECTION:
Hash only the first N seconds (e.g., 30s) for a fast pre-filter, then do full comparison only for candidates. Or use a streaming SHA-256 over the resampled data without materializing the full byte string.

--------------------------------------------------------------------
FILE:        app/domain/quality_checker.py
FUNCTION:    QualityChecker._check_outliers
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Flag samples outside mean ± 3σ for duration, peak amplitude, and spectral centroid.

WHAT IT ACTUALLY DOES:
Uses population standard deviation (`/ n`) via `_mean_std`. For a dataset with exactly 2 samples, the population std is non-zero only if the values differ. If both values are identical, `std = 0` and the check is skipped (correct). If they differ, both samples are flagged as outliers (since each is 1σ away from the mean with n=2, and 1σ < 3σ — actually neither would be flagged). Wait: with n=2, `mean = (a+b)/2`, `std = |a-b|/2`. For sample `a`: `|a - mean| = |a-b|/2 = std`. So `a` is exactly 1σ from the mean — not flagged (< 3σ). This is correct.

The real issue: `_spectral_centroid` returns `0.0` on failure (librosa unavailable or exception). If librosa fails for all files, `centroids` is a list of all zeros, `std = 0`, and the centroid outlier check is silently skipped. This is safe but means the centroid check provides no signal when librosa is unavailable, with no warning to the caller.

EVIDENCE:
Lines ~320–340:
```python
for metric_name, values in metrics:
    mean, std = _mean_std(values)
    if std == 0:
        continue
```
Silent skip when all centroids are 0.0 (librosa failure).

REPRODUCTION SCENARIO:
librosa is not installed. All `_spectral_centroid` calls return 0.0. The centroid outlier check is silently skipped. The quality report contains no centroid findings even for genuinely anomalous files.

IMPACT:
Silent degradation of quality check coverage when librosa is unavailable. No warning in the report.

FIX DIRECTION:
Track whether centroid computation succeeded for any file. If all centroids are 0.0 due to failure, add a finding or log a warning that the centroid check was skipped.

--------------------------------------------------------------------
FILE:        app/domain/quality_checker.py
FUNCTION:    QualityChecker.run
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Handle edge case: silence-only audio, clipped audio, mono vs stereo.

WHAT IT ACTUALLY DOES:
For a WAV file with zero samples (0 frames), `_wav_info` returns `duration_ms = 0.0`. `_check_duration_range` will flag it if `min_duration_ms > 0`. `_load_audio` via librosa will return an empty array (shape `(0,)`). `_check_clipping` calls `np.abs(audio_data).max()` on an empty array — this raises `ValueError: zero-size array to reduction operation fmax which has no identity`. This exception is caught by the `except Exception` in `_check_clipping`, so it returns `[]` silently. The zero-length file is not flagged for clipping (correct) but the exception is silently swallowed.

EVIDENCE:
`_check_clipping` lines ~195–210:
```python
try:
    peak = float(np.abs(audio_data).max())
    ...
except Exception as exc:
    logger.debug("clipping check failed for %s: %s", rel_path, exc)
return []
```
`np.abs(np.array([])).max()` raises `ValueError`.

REPRODUCTION SCENARIO:
WAV file with 0 frames (valid WAV header, no audio data). `audio_data` is `np.array([], dtype=float32)`. `np.abs(audio_data).max()` raises `ValueError`.

IMPACT:
Low — exception is caught and logged at DEBUG level. The clipping check silently returns no finding for zero-length files, which is the correct behavior. But the debug log may confuse developers.

FIX DIRECTION:
Add an explicit guard: `if len(audio_data) == 0: return []` at the top of `_check_clipping`, `_check_dc_offset`, and `_check_snr`.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 2 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | `_check_snr` uses the entire file's mean power as `signal_power` (including the noise region), producing systematically wrong SNR estimates for audio that does not start with silence — the most common case in speech datasets. |
