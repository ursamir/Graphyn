# Group Review Index — 14: Audio Plugins Batch 2

**Files reviewed:** 5 (of 7 listed; 2 files do not exist on disk — see input_output_nodes_NOT_FOUND.md)
**Total findings:** 22 (CRITICAL: 0 | HIGH: 9 | MEDIUM: 10 | LOW: 3)
**Date:** 2026-05-26

---

## File Summaries

| File | Overall Risk | Silent Failures | Top Risk |
|---|---|---|---|
| alignment_node_nodes.md | HIGH | 3 | `_parse_textgrid` never resets `in_tier`, silently mixing intervals from multiple TextGrid tiers into word-level output |
| audio_annotator_nodes.md | MEDIUM | 2 | `_rule_matches` silently ignores misconfigured rules (missing "field" key) with no warning |
| augmentation_pipeline_nodes.md | HIGH | 2 | RNG state advances across `process()` calls — augmentation sequences are irreproducible across pipeline runs even with a fixed seed |
| dataset_ingest_nodes.md | HIGH | 1 | ZIP and TAR ingestion produce AudioSample objects with dangling path references pointing to deleted temp directories |
| feature_frontend_nodes.md | HIGH | 2 | `_append_deltas` computes delta-delta as `librosa.feature.delta(features, order=2)` instead of `delta(delta(features))`, silently producing non-standard features |
| input_output_nodes_NOT_FOUND.md | N/A | N/A | Files listed in checkpoint do not exist on disk |

---

## Priority Findings (CRITICAL and HIGH only)

**[HIGH] alignment_node_nodes.md — AlignmentNode.setup — Silent pass on ImportError means node appears healthy at startup even when ctc-forced-aligner is missing; crash deferred to mid-pipeline execution**

**[HIGH] alignment_node_nodes.md — AlignmentNode._align_ctc — Model loaded inside _align_ctc when setup() not called; every process() call reloads model from disk; no teardown() to release GPU memory**

**[HIGH] alignment_node_nodes.md — AlignmentNode._align_ctc — No empty-audio guard before torch.from_numpy(); zero-length audio crashes with opaque PyTorch tensor shape error**

**[HIGH] augmentation_pipeline_nodes.md — AugmentationPipelineNode.__init__ — self.rng is shared mutable state that advances across process() calls; seed only guarantees reproducibility for the first call**

**[HIGH] augmentation_pipeline_nodes.md — AugmentationPipelineNode._aug_pitch_shift — No empty-audio guard; zero-length audio crashes inside librosa; exception caught by outer handler and augmented copy silently dropped**

**[HIGH] dataset_ingest_nodes.md — DatasetIngestNode._load_zip — TemporaryDirectory deleted after _load_filesystem() returns; all AudioSample.path values are dangling references to deleted temp files**

**[HIGH] dataset_ingest_nodes.md — DatasetIngestNode._load_tar — Same dangling-path issue as _load_zip; temp dir deleted before samples are returned**

**[HIGH] dataset_ingest_nodes.md — DatasetIngestNode._load_filesystem — Per-file checkpoint append opens/closes file once per sample; O(N) file operations on large datasets causes severe performance degradation**

**[HIGH] feature_frontend_nodes.md — FeatureFrontendNode.process — sample.data=None crashes with AttributeError; empty array crashes inside librosa; entire batch fails on a single bad sample**

**[HIGH] feature_frontend_nodes.md — FeatureFrontendNode.process — sample.sample_rate=0 or None causes ZeroDivisionError inside librosa.resample with no domain-level error message**

**[HIGH] feature_frontend_nodes.md — FeatureFrontendNode._append_deltas — delta-delta computed as librosa.feature.delta(features, order=2) instead of delta(delta(features)); silently produces non-standard features that degrade model accuracy**

---

## Most Dangerous File

**dataset_ingest_nodes.md** — ZIP and TAR ingestion silently produce AudioSample objects with dangling path references (temp dir deleted after extraction), AND the per-file checkpoint append pattern causes O(N) file I/O on large datasets, AND a single S3 download failure aborts the entire ingestion run losing all previously loaded samples. Three independent HIGH-severity issues in a single source node that is the entry point for all dataset loading.
