# Group Review Index — 13: Audio Plugins Batch 1

**Files reviewed:** 6  
**Total findings:** 30 (CRITICAL: 1 | HIGH: 16 | MEDIUM: 11 | LOW: 2)  
**Date:** 2026-05-26

---

## File Summaries

| File | Overall Risk | Silent Failures | Top Risk |
|---|---|---|---|
| audio_classifier_nodes.md | HIGH | 2 | TFLite Interpreter shared across concurrent calls causes data corruption or crash |
| audio_conditioner_nodes.md | HIGH | 2 | Silence-trimmed empty array propagates through conditioning pipeline causing IndexError or zero-length AudioSample downstream |
| audio_event_detector_nodes.md | HIGH | 2 | TFLite and PyTorch backends silently return wrong temporal data (all events span full clip duration) despite claiming onset/offset timestamps |
| audio_exporter_nodes.md | CRITICAL | 2 | shutil.rmtree on misconfigured output_dir can irreversibly delete arbitrary filesystem directories |
| audio_generator_nodes.md | HIGH | 2 | Missing conditioning audio file is silently ignored — user expects melody-conditioned generation but receives unconditional output |
| audio_quality_gate_nodes.md | HIGH | 2 | ZeroDivisionError on sample_rate=0 crashes the entire batch in both _check_duration and _compute_quality_metadata |

---

## Priority Findings (CRITICAL and HIGH only)

**[CRITICAL] audio_exporter_nodes.md — AudioExporterNode.process — shutil.rmtree on misconfigured output_dir can irreversibly delete arbitrary filesystem directories**

**[HIGH] audio_classifier_nodes.md — AudioClassifierNode._tflite_classify — TFLite Interpreter is not thread-safe; shared instance across concurrent calls causes data corruption or crash**

**[HIGH] audio_classifier_nodes.md — AudioClassifierNode.process — Unknown input types silently skipped; caller receives shorter list than input with no indication of data loss**

**[HIGH] audio_classifier_nodes.md — AudioClassifierNode.process — No None-guard before iterating inputs; None input crashes with opaque TypeError**

**[HIGH] audio_classifier_nodes.md — AudioClassifierNode._classify_audio — Silent audio (all zeros) produces NaN/inf mel features fed to model, returning garbage probabilities silently**

**[HIGH] audio_conditioner_nodes.md — AudioConditionerNode._condition_one — Silence-trimmed empty array causes IndexError in _apply_preemphasis or ValueError in _peak_normalize**

**[HIGH] audio_conditioner_nodes.md — AudioConditionerNode._apply_preemphasis — IndexError on empty array (zero samples)**

**[HIGH] audio_event_detector_nodes.md — AudioEventDetectorNode._detect_tflite — New TFLite Interpreter allocated per sample; O(n) model loads for a batch of n samples**

**[HIGH] audio_event_detector_nodes.md — AudioEventDetectorNode._detect_pytorch — New PyTorch model loaded per sample; O(n) model loads for a batch of n samples**

**[HIGH] audio_event_detector_nodes.md — AudioEventDetectorNode._detect_tflite — All events assigned start=0.0 and end=full_duration; temporal detection contract violated silently**

**[HIGH] audio_event_detector_nodes.md — AudioEventDetectorNode._detect_pytorch — All events assigned start=0.0 and end=full_duration; temporal detection contract violated silently**

**[HIGH] audio_exporter_nodes.md — AudioExporterNode.process — Disk-full mid-batch leaves partial output with no labels.csv manifest for successfully written files**

**[HIGH] audio_exporter_nodes.md — AudioExporterNode.process — Empty split_ratios dict causes IndexError on first sample requiring split assignment**

**[HIGH] audio_generator_nodes.md — AudioGeneratorNode._generate_musicgen — set_generation_params mutates shared model state without a lock; concurrent calls use wrong parameters**

**[HIGH] audio_generator_nodes.md — AudioGeneratorNode._generate_musicgen — Missing conditioning audio file silently ignored; unconditional generation returned instead of melody-conditioned**

**[HIGH] audio_quality_gate_nodes.md — AudioQualityGateNode._check_duration — ZeroDivisionError on sample_rate=0 crashes entire batch**

---

## Most Dangerous File

**audio_exporter_nodes.md** — The `shutil.rmtree` call on a misconfigured `output_dir` (e.g. `"/"` or `"."`) can irreversibly delete arbitrary filesystem directories, including source files and system directories, with no path validation or safety check.
