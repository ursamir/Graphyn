# Group Review Index — 12: Domain & Models

**Files reviewed:** 11  
**Total findings:** 27 (CRITICAL: 0 | HIGH: 12 | MEDIUM: 11 | LOW: 4)  
**Date:** 2026-05-26

---

## File Summaries

| File | Overall Risk | Silent Failures | Top Risk |
|---|---|---|---|
| ingestion.md | HIGH | 2 | `stream_job` hangs or returns partial events for cross-worker Redis jobs — frozen snapshot never refreshed |
| project_manager.md | HIGH | 2 | `validate_annotations` silently returns wrong counts when annotation keys use a different path format than rglob paths |
| quality_checker.md | HIGH | 2 | `_check_snr` uses entire-file mean power as signal_power (including noise region), producing wrong SNR for audio that doesn't start with silence |
| audio_sample.md | MEDIUM | 0 | Mutable class-level `metadata: dict = {}` — latent shared-state bug with `model_construct()` |
| audio_artifact_serializer.md | HIGH | 1 | `deserialize` returns `None` on any single corrupt WAV, discarding all valid samples and forcing full re-execution |
| feature_array.md | LOW | 0 | Mutable class-level `metadata: dict = {}` and dead-code `model_post_init` |
| model_artifact.md | HIGH | 1 | All three mutable fields (`labels`, `history`, `metrics`) use class-level defaults — shared across `model_construct()` instances |
| prediction_result.md | HIGH | 1 | `probabilities` and `metadata` use class-level mutable defaults — silent result corruption in batch inference |
| tensor_batch.md | MEDIUM | 1 | `batch_size` returns N for a 1-D array of shape (N,), silently treating a flat vector as a batch of N scalars |
| tflite_artifact.md | MEDIUM | 1 | `labels: list = []` mutable class-level default; `quantisation` vs `quantization` spelling inconsistency |
| deployment_artifact.md | LOW | 0 | None — clean file |

---

## Priority Findings (CRITICAL and HIGH only)

**[HIGH] ingestion.md — IngestionService.stream_job — Frozen Redis snapshot causes infinite loop or premature exit in cross-worker SSE streaming**

**[HIGH] ingestion.md — IngestionService._run_url_job — File handle closed inside `with` block before `unlink()`, leaving partial oversized files on disk (Windows: PermissionError)**

**[HIGH] project_manager.md — ProjectManager.validate_annotations — Silent wrong result: annotated_count=0 when annotation sample_path keys use different path format than rglob-discovered paths**

**[HIGH] project_manager.md — ProjectManager._estimate_snr — Returns -120 dB for files shorter than 100ms (noise profile window), producing false low-SNR outliers in get_stats**

**[HIGH] quality_checker.md — QualityChecker._check_snr — signal_power computed over entire file including noise region; produces systematically wrong SNR for audio not starting with silence**

**[HIGH] quality_checker.md — QualityChecker.run — "Never raises" contract violated: NotADirectoryError propagates when version_dir is a file; _check_outliers has no try/except**

**[HIGH] audio_artifact_serializer.md — AudioSampleHandler.deserialize — Returns None (cache miss) on any single corrupt WAV, discarding all valid samples and forcing full upstream re-execution**

**[HIGH] audio_artifact_serializer.md — AudioSampleHandler.serialize — No cleanup on partial write failure; orphaned WAV files accumulate on disk**

**[HIGH] model_artifact.md — ModelArtifact — labels/history/metrics use class-level mutable defaults; shared across model_construct() instances causing silent training history corruption**

**[HIGH] prediction_result.md — PredictionResult — probabilities/metadata use class-level mutable defaults; shared across model_construct() instances causing silent batch inference result corruption**

**[HIGH] ingestion.md — IngestionService._run_hf_job — Samples with undecodable audio counted as successful ingestion (duration=0.0 silently accepted)**

**[HIGH] tflite_artifact.md — TFLiteArtifact — labels uses class-level mutable default; shared across model_construct() instances**

---

## Most Dangerous File

**audio_artifact_serializer.md** — `deserialize` returns `None` (complete cache miss) when any single WAV file in a checkpoint or cache directory is corrupt, silently discarding all valid samples and forcing full re-execution of potentially expensive upstream ML nodes. Combined with the `serialize` resource leak (no cleanup on partial write), a disk-full event during serialization leaves orphaned files that can trigger this failure on every subsequent run.
