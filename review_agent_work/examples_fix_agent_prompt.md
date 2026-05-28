# Examples Fix Agent — Self-Iterating

Senior Engineer mode. One example per session. Self-advancing via checkpoint.
**Only output: the SESSION COMPLETE block.**

---

## S1 — CHECKPOINT

Read `examples/fix_agent_checkpoint.md`. Take the first `pending` row.
- All rows done/skipped/failed → print `All examples complete.` and stop.
- File missing → create from APPENDIX A, then continue.

---

## S2 — READ EXAMPLE

Read all files in the example dir: `.py`, `.graph.json`, `README.md`, `.sh`.
Read `examples/README.md` for expected behaviour.

---

## S3 — STATIC ANALYSIS

Check these categories. For each issue assign: `BUG` | `STALE` | `FALSE-POSITIVE` | `SKIP`.

**A. Broken imports** — only these are actually broken (all others are OK or shim-backed):
- `from app.core.pipeline import run_pipeline` → deprecated, still works, mark STALE
- Any import from a path that doesn't exist → BUG

**B. Node config fields** — verify every `PipelineNode`/`IRNode` config against the actual
`Config(NodeConfig)` class in `PluginPackage/`. Use APPENDIX B as a quick-check reference.
Always read the source to confirm. Top known renames: `sample_rate`→`target_sample_rate` on `audio_conditioner`.

**C. SDK API**
- `Pipeline.run()` valid kwargs: `use_cache`, `checkpoint`, `streaming`, `parallel`, `max_workers`, `resume_run_id`, `include_nodes`, `exclude_nodes`, `input_overrides`, `event_driven`, `logger`, `observer`
- `Pipeline.run()` → `ArtifactCollection` (not dict; `__getitem__` still works for backward compat)
- `Pipeline.run_with_manager()` → `(ArtifactCollection, RunManager)` tuple

**D. Graph JSON** — every `.graph.json`:
- `schema_version` must be `"1.1"`
- `node_type` values must exist in `PluginPackage/`
- Edge `src_id`/`dst_id` must reference existing node `id`s
- Edge port names must match node `input_ports`/`output_ports` ClassVars
- Config fields must match node `Config` class

**E. Paths**
- Plugin install paths need trailing slash: `"PluginPackage/Audio/foo/"` not `"PluginPackage/Audio/foo"`
- Shell scripts must use `venv/bin/python`, not `python` or `python3`
- `OUTPUT_DIR` must be inside the example's own `output/` dir

**F. Post-review behavioral rules**
- `edge_optimizer` INT8 requires `X_train_repr.npy` in SavedModel dir — if trainer not in same pipeline, use `"float16"`
- `dataset_balancer` `target_count` must be `>= 0`
- `realtime_inference` `model_path` must point to an existing file
- `run_with_manager()` returns a tuple — must unpack as `result, run_mgr = ...`

---

## S4 — RUN

```bash
cd /home/meritech/Desktop/newAudio3
venv/bin/python examples/<N>_<name>/<script>.py 2>&1 | tail -60
```

Pre-run checks:
- **Data missing**: if `DATA_PATH` absent → example prints "run prepare_real_data.py" and exits 1 → `data-missing`, not a bug
- **Ex 08, 21**: need API server → use `--sdk-only` or skip REST section
- **Ex 06, 07**: need TF/Keras → graceful ImportError = OK; crash = BUG
- **Ex 07**: starts MCP subprocess → check for subprocess errors

Output interpretation:
- Exit 0 + expected output → PASS
- Exit 1 + "prepare_real_data" message → data-missing
- Exit 1 + traceback → BUG
- Exit 0 + wrong output → BUG

---

## S5 — FIX

Fix all `BUG` verdicts, severity order. Read source before editing. No refactoring beyond fix scope.

Standard fixes:
- Wrong config field → read `Config` class, use correct name
- `schema_version "1.0"` → `"1.1"`
- Unknown `node_type` → read `NodeMetadata(node_type=...)` in `PluginPackage/`
- Wrong port name → read `input_ports`/`output_ports` ClassVars
- Missing trailing slash on plugin install path → add it
- `python` in shell script → `venv/bin/python`
- INT8 without repr data → change to `"float16"`
- `run_with_manager()` not unpacked → `result, run_mgr = pipeline.run_with_manager(...)`

---

## S6 — RE-RUN

Re-run after fixes. Same command as S4.
- Passes → S7
- Regression from your fix → fix it
- data-missing / deps-missing → mark and proceed

---

## S7 — VALIDATE GRAPHS

```bash
venv/bin/python -m app.cli.main validate --graph examples/<N>_<name>/<file>.graph.json 2>&1
```

Run for every `.graph.json`. Exit 1 → fix it (same fixes as S5 graph section).
If validation needs plugins installed first, run the example script's install block first.

---

## S8 — UPDATE CHECKPOINT

Edit `examples/fix_agent_checkpoint.md`.

Row status values: `done` | `fixed` | `data-missing` | `deps-missing` | `partial` | `skipped`

Status block updates:
- `current_example` → next pending row path (or `complete`)
- `last_completed_example` → this example
- `examples_done` +1, `session_count` +1

---

## S9 — REPORT

Print exactly:
```
---
SESSION COMPLETE
Example:          examples/<N>_<name>/
Scripts tested:   <.py files>
Graphs validated: <.graph.json files>
Issues: BUG:<n> STALE:<n> FP:<n> SKIP:<n>
Fixes applied:    <n>
Run result:       PASS | data-missing | deps-missing | fixed | deferred
Notes:            <one line>
Next:             <next pending example>
---
```
Stop. Do not begin the next example.

---

## PRINCIPLES

1. Run the code — static analysis alone is not enough.
2. Data/deps missing ≠ bug — graceful exit is correct behaviour.
3. Fix root cause — if a field name is wrong in both `.py` and `.graph.json`, fix both.
4. One example per session.
5. No new features, no unrelated refactoring.
6. Files in `app/` modified → must have 7-field contract docstring as first statement (see `file-header-contracts.md`). Files in `examples/` are exempt.

---

## APPENDIX A — CHECKPOINT TEMPLATE

Create `examples/fix_agent_checkpoint.md`:

```markdown
# Examples Fix Agent Checkpoint

## Status

current_example: examples/01_wake_word/
current_example_status: pending
last_completed_example: (none)
examples_done: 0
session_count: 0

---

## File Queue

| # | Status | Example Dir | Primary Script | Notes |
|---|---|---|---|---|
| 1 | pending | `examples/01_wake_word/` | `run_sdk.py` | |
| 2 | pending | `examples/02_speech_commands/` | `run_sdk.py` | |
| 3 | pending | `examples/03_environmental_sounds/` | `run_sdk.py` | |
| 4 | pending | `examples/04_speaker_verification/` | `run_sdk.py` | |
| 5 | pending | `examples/05_speech_enhancement/` | `run_sdk.py` | |
| 6 | pending | `examples/06_speech_commands_e2e/` | `run_train.py` | |
| 7 | pending | `examples/07_mcp_agent_pipeline/` | `agent.py` | |
| 8 | pending | `examples/08_rest_api_streaming/` | `stream_client.py` | |
| 9 | pending | `examples/09_parallel_execution/` | `parallel_pipeline.py` | |
| 10 | pending | `examples/10_resumable_pipeline/` | `resumable_pipeline.py` | |
| 11 | pending | `examples/11_artifact_lineage/` | `lineage_demo.py` | |
| 12 | pending | `examples/12_conditional_branching/` | `conditional_pipeline.py` | |
| 13 | pending | `examples/13_csv_data_processing/` | `csv_pipeline.py` | |
| 14 | pending | `examples/14_plugin_manifest/` | `manifest_demo.py` | |
| 15 | pending | `examples/15_event_driven_pipeline/` | `event_driven_demo.py` | |
| 16 | pending | `examples/16_deterministic_replay/` | `replay_demo.py` | |
| 17 | pending | `examples/17_partial_execution/` | `partial_demo.py` | |
| 18 | pending | `examples/18_pipeline_composition/` | `composition_demo.py` | |
| 19 | pending | `examples/19_capability_scheduling/` | `capability_demo.py` | |
| 20 | pending | `examples/20_retry_fault_tolerance/` | `retry_demo.py` | |
| 21 | pending | `examples/21_runtime_control_api/` | `runtime_control_demo.py` | |
```

---

## APPENDIX B — NODE CONFIG QUICK REFERENCE

Verify against actual source before trusting this table.

| node_type | Key config fields |
|---|---|
| `dataset_ingest` | `path`, `source_type`(filesystem\|s3\|huggingface\|archive\|manifest), `recursive`, `label`, `limit` |
| `audio_conditioner` | `target_sample_rate`, `mono`, `normalize`, `normalize_method`(peak\|rms\|lufs), `target_lufs`, `compress`, `compress_ratio`, `trim_silence` |
| `audio_quality_gate` | `min_snr_db`, `min_duration_s`, `max_duration_s`, `max_clipping_pct`, `rejection_policy`(skip\|raise\|flag) |
| `audio_annotator` | `mode`(manual\|rule\|auto\|weak), `label`, `rules`, `taxonomy` |
| `alignment_node` | `backend`(ctc\|mfa\|auto), `language`, `transcript_key` |
| `segmenter` | `mode`(silence\|vad\|fixed\|event), `silence_threshold_db`, `min_segment_s`, `max_segment_s`, `window_s`, `hop_s` |
| `augmentation_pipeline` | `augmentations`(list[{type,...}]), `copies_per_sample`, `random_seed` |
| `speech_enhancer` | `backend`(rnnoise\|deepfilter\|auto), `mode`(denoise\|dereverberate\|isolate\|telephony) |
| `speaker_separator` | `backend`(pyannote\|speechbrain\|auto), `num_speakers` |
| `environment_simulator` | `preset`(room\|car\|office\|outdoor), `room_dimensions`, `rt60` |
| `feature_frontend` | `feature_type`(mfcc\|log_mel\|spectrogram\|chroma\|raw), `n_mfcc`, `n_fft`, `hop_length`, `fmax`, `fixed_length`, `normalize` |
| `stream_processor` | `window_s`, `hop_s`, `buffer_size` |
| `audio_event_detector` | `backend`(yamnet\|pytorch\|auto), `threshold`, `merge_tolerance_ms` |
| `audio_classifier` | `backend`(tflite\|pytorch\|auto), `model_path`, `top_k` |
| `speech_synthesizer` | `backend`(coqui\|espeak\|auto), `language`, `voice` |
| `voice_converter` | `backend`(speechbrain\|knnvc\|auto), `target_speaker` |
| `audio_generator` | `backend`(musicgen\|audiogen\|auto), `model_size`(small\|medium\|large), `duration_s`, `prompt` |
| `audio_exporter` | `output_dir`, `split_ratios`, `version_tag`, `random_seed`, `append`(bool) |
| `stream_ingest` | `source`(mic\|websocket\|rtp\|rtsp), `sample_rate`, `duration_s` |
| `dataset_builder` | `split_ratios`, `shuffle`, `stratify`, `output_format`(numpy\|tensorflow\|pytorch), `fixed_length`, `random_seed` |
| `dataset_balancer` | `strategy`(oversample\|undersample\|weighted\|synthetic), `target_count`(int≥0), `balance_by`, `jitter_std`, `random_seed` |
| `dataset_versioner` | `output_dir`, `version_tag`, `include_metadata`, `create_snapshot` |
| `trainer` | `backend`(keras\|pytorch\|auto), `epochs`, `batch_size`, `output_path`, `patience`, `mixed_precision`, `min_val_accuracy` |
| `model_builder` | `architecture`(ds_cnn\|mobilenet\|simple_cnn), `filters`, `num_layers`, `dropout_rate`, `learning_rate`, `backend`(keras\|auto) |
| `evaluator` | `output_path`, `plot_confusion_matrix`, `plot_training_curves`, `compute_roc`, `compute_fairness` |
| `experiment_tracker` | `backend`(json\|mlflow), `experiment_name`, `tracking_uri`, `log_artifacts`, `output_dir` |
| `edge_optimizer` | `backend`(tflite\|onnx\|auto), `quantization`(float32\|float16\|int8), `output_path`, `representative_samples` |
| `deployment_packager` | `target`(mobile\|mcu\|docker\|edge), `output_path`, `include_inference_script`, `package_name` |
| `realtime_inference` | `model_path`(required), `backend`(tflite\|pytorch\|onnx\|auto), `mode`(classification\|wake_word\|streaming_asr), `wake_word_threshold` |
| `embedding_generator` | `model`(wav2vec2\|hubert\|clap\|yamnet\|xvector\|openl3), `pooling`(mean\|cls\|last\|none), `normalize` |
| `multimodal_fusion` | `fusion_type`(concat\|attention\|late\|cross_attention), `audio_dim`, `output_dim`, `normalize` |
