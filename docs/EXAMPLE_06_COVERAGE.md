# Example 06 — Speech Commands E2E: coverage report

Templates `speech-commands-e2e-prepare` ("Speech commands E2E · Step 1 · Prepare
dataset") and `ex-06-speech-commands-e2e` ("Speech commands E2E · Step 2 · Train
model"), plus the graphs under `examples/06_speech_commands_e2e/`. Verified
2026-10-01 against the live Docker API (`graphyn-api`, plugins from `./plugins`)
and against the fixed `PluginPackage/` sources (unit tests + a local node-level
E2E run); the two-step template flow was re-verified 2026-10-03 in-process via
the SDK (§2, "Two-step templates").

Which graphs are templates? `app/core/templates/example_templates.py` takes one
canonical graph per example folder — for 06 the first of `pipeline.graph.json`,
`composed.graph.json`, `edge_inference.graph.json`, **`pipeline_train_ml.graph.json`**
— plus every `examples/templates/*.graph.json` starter. So:

| Template id | Source | Title | `metadata.group` / `phase` / `step_title` |
|---|---|---|---|
| `speech-commands-e2e-prepare` | `examples/templates/speech-commands-e2e-prepare.graph.json` | Speech commands E2E · Step 1 · Prepare dataset | `speech-commands-e2e` / 1 / Prepare dataset (`next_template: ex-06-speech-commands-e2e`) |
| `ex-06-speech-commands-e2e` | `examples/06_speech_commands_e2e/pipeline_train_ml.graph.json` | Speech commands E2E · Step 2 · Train model | `speech-commands-e2e` / 2 / Train model (`previous_template: speech-commands-e2e-prepare`) |

Step 1 prepares all six labels in **one** graph: a single recursive
`dataset_ingest` over `workspace/datasets/input/speech-commands` (the seeded
`examples/02_speech_commands/data`, one sub-folder per label → label = folder
name) feeds the same conditioner → segmenter → gates → augmentation → exporter
chain as the per-label shards, and one exporter (`append=false`) writes the
`v1/{train,val,test}/{label}/` tree Step 2 ingests. No merge node is needed:
every node is per-clip, `group_by_source` seeds each source clip's split
independently of batch order, and re-running replaces the dataset instead of
appending duplicates. (Six ingest chains with chained `append=true` exporters
were rejected: parallel branches have no ordering, so the `append=false` reset
could run after another label was written.) The six
`pipeline_preprocess*.graph.json` shards and `pipeline_infer.graph.json` stay
CLI/SDK graphs. Every node in these graphs carries a human `label` (e.g.
"Model builder · DS-CNN (64 filters × 4 blocks)", "Trainer · up to 50 epochs",
"Edge optimizer · TFLite INT8").

## 1. Pipeline

```
Phase 1 — preprocess (template Step 1: one run, recursive ingest of all 6 label folders;
CLI shards: 6 runs, yes [append=false] → no, up, down, go, stop [append=true])
  dataset_ingest_0 (workspace/datasets/input/speech-commands, recursive — or examples/02 data/<label>, flat)
    → audio_conditioner_1 (16 kHz, mono, DC removal, trim 40 dB below peak, peak → -1 dBFS)
    → segmenter_2 (mode=silence, 40 dB below peak; ~1.1 segments per clip)
    → audio_quality_gate_3 (SNR ≥ 5 dB + clipping/silence/bandwidth; duration off)
    → audio_quality_gate_4 (duration 0.2–1.0 s only)
    → augmentation_pipeline_5 (pitch ±2 st + time-stretch 0.9–1.1, 2 copies → 3×)
    → audio_exporter_6 (workspace/artifacts/speech-commands/dataset/speech_commands/v1/{split}/{label}, 70/15/15)

Phase 2 — train (template Step 2)
  dataset_ingest_0 (…/dataset/speech_commands/v1, recursive)
    → feature_frontend_0 (MFCC 40, n_fft 512, hop 160, fmax 8 kHz, per-clip normalise)
    → dataset_builder_0 (fixed_length 101 → X: N×101×40×1; splits from /train|val|test/ path)
        ├→ model_builder_0.input (DS-CNN 64 filters × 4 blocks, dropout 0.25, Adam 1e-3, ≈22.5 K params)
        ├→ trainer_0.dataset      model_builder_0 → trainer_0.model
        └→ evaluator_0.dataset    trainer_0 → evaluator_0.model_artifact
    → edge_optimizer_0 (TFLite, full INT8, uint8 I/O, 100 calibration rows)

Inference
  dataset_ingest_0 → audio_conditioner_0 (16 kHz) → segmenter_0 (silence)
    → feature_frontend_0 (same MFCC, fixed_length 101)
    → realtime_inference_0 (workspace/artifacts/speech-commands/latest/tflite/model.tflite)
```

## 2. Live run results (Docker API, workspace `e06-verify-1`)

All runs were sent the way the console sends them: `POST /api/v1/pipelines/run`
(NDJSON stream) with the graph stamped by the same logic as
`graphyn-ui/src/lib/projectStamp.ts` (so `audio_exporter` wrote to
`workspace/datasets/output/e06-verify-1/v1`). The live container ran the
**pre-fix** plugin code in `./plugins`; nothing was reduced (all epochs ran).

| Phase | Run id | Status | Wall | Per-node durations (s) / counts | Key results |
|---|---|---|---|---|---|
| pre yes | d17267bced574ab0a753bc73dd29ac21 | succeeded | 56 s | ingest 3.3, cond 5.6, seg 4.1 (200→219), gate3 5.1, gate4 5.1 (→206), aug 20.4 (618), export 12.5 | 618 wav: train 429 / val 93 / test 96 |
| pre no | c90f6db1de504b4aaa3d58be8e5b5137 | succeeded | 46 s | seg 231, gate3 →217, gate4 →203, aug 609 | |
| pre up | d3dc7469aa5e46c180149fad9dbf6488 | succeeded | 50 s | seg 237, gate3 →237, gate4 →215, aug 645 | |
| pre down | 2d2089e3996a4a7eb24d910d9ec6d7c2 | succeeded | 47 s | seg 217, gate3 →213, gate4 →202, aug 606 | |
| pre go | cf90dbbe1e2a4021b516f31eac6c686c | succeeded | 49 s | seg 220, gate3 →210, gate4 →198, aug 594 | |
| pre stop | 76633347af5041f18378cfb2203dc200 | succeeded | 51 s | seg 232, gate3 →228, gate4 →211, aug 633 | dataset total 3705 wav (train 2571 / val 556 / test 578), 6 labels 594–645 each |
| train — template as shipped (raw data, `limit: 8`) | f0a5225161b948d1997f2da660302d0c | succeeded | 116 s | ingest 0.9 (48), ff 1.2, builder 6.3, model_builder 0.0 (**cache hit**), trainer 62.5 (21 epochs), evaluator 25.9, edge 18.8 | test n=8, accuracy **0.25**, AUC 0.54 — the old template trained on 8 clips/label |
| train — Phase-1 dataset, template settings (50 epochs, batch 32, patience 15) | 1e4ff50a41f443d49a143fb203abfc98 | succeeded | 2042 s | ingest 73.3 (3705), ff 87.7, builder 123.3, model_builder 10.8, **trainer 1720 (50 epochs, CPU)**, evaluator 14.9, edge 11.5 | X_train 2571×101×40×1; best val_acc 0.856; float test acc **0.867**, macro AUC 0.983; per-class F1 down .87 go .82 no .73 stop .93 up .86 yes .98; INT8 `model.tflite` 48 976 B + labels.txt (6 labels) |
| infer — template as shipped (raw `yes`, `latest` model) | 09731f65dfd44e2c800ce3d501ed3d81 | succeeded | 19 s | realtime_inference 9.8 s (219 segments) | 75.3 % "yes" (165/219) — clips were in the training set |
| infer on test split (per label) | f2ed4865… yes · 18286ed1… no · 5182e881… up · ddd31a8f… down · c63a89bf… go · f4d806a9… stop | all succeeded | 11–12 s each | ~6.4 s inference per label | INT8 accuracy: yes .875, no .312, up .960, down .625, go .553, stop .804 → **0.69 overall** vs 0.867 float |

Why the live numbers are misleading (both fixed in `PluginPackage`, see §4):

* **Train/test leakage** — the live exporter assigned each sample (original +
  2 augmented copies + extra segments) an independent random split: 784 of
  1182 source clips span several splits and **578/578 test files have their
  source clip in train/val**, so 0.867 is optimistic.
* **INT8 calibration bias** — `X_train_repr.npy` held the first 1000 rows of a
  label-sorted `X_train`, i.e. only `down/go/no`. Re-converting the same live
  SavedModel: first-1000 calibration → INT8 test acc 0.683 (= live), evenly
  spaced 1000 rows → 0.763 (100 calibration samples) / 0.853 (500).

### Local run with the fixed plugins (same graph configs, node classes chained in-process)

`examples/06_speech_commands_e2e/verify_local.py` (see §7) — Phase 1 counts identical to live
(e.g. yes 200→219→206→618), then:

| Item | Result |
|---|---|
| Split leakage (sources in >1 split) | **0** (was 784) |
| Split sizes | train 2568 / val 597 / test 540 |
| Trainer | 50 epochs, 1187 s (CPU, contended), LR 1e-3 inherited from model_builder, best val_acc 0.765 |
| Float test accuracy / AUC (honest, held out by source) | **0.791** / 0.958; F1 down .81 go .69 no .69 stop .89 up .81 yes .89 |
| INT8 TFLite (100 spread calibration rows) on test split via `pipeline_infer` preprocessing | 0.672 (direct features 0.670) |
| INT8 with 500 calibration rows | 0.420 — INT8 accuracy is unstable for this model (see Known limitations) |
| float32 TFLite | 0.793 (matches Keras) |

### Two-step templates (SDK, in-process, 2026-10-03)

Template graphs as synced (`rewrite_graph_paths`), run with `Pipeline.from_json(...).run()`
against a scratch `GRAPHYN_PROJECT_DIR` (trainer/evaluator/edge_optimizer/dataset_builder
in their isolated venvs; trainer forced to CPU, epochs reduced):

| Run | Wall | Result |
|---|---|---|
| Step 1 `speech-commands-e2e-prepare` | 46 s | 3705 wav (down 606 · go 594 · no 609 · stop 633 · up 645 · yes 618 — same total as the six live shard runs), train 2556 / val 594 / test 555, **0** of 1182 source clips in more than one split |
| Step 2 `ex-06-speech-commands-e2e`, 3 epochs | 105 s | runs end-to-end; labels.txt (`down…yes`) in trainer/, saved_model/, checkpoints/, evaluation/, tflite/ |
| Step 2, 15 epochs | 265 s | float test acc 0.728, AUC 0.929; INT8 `model.tflite` 48 976 B; run log shows 16 trainer progress events (epoch 0–15 with loss/acc/val_*), evaluator "Test accuracy 72.8 % on 555 held-out samples", edge_optimizer calibrate 10→100 % and "Saved model.tflite (47 KB, int8)" |

## 3. Nodes and config fields

`T` = Graph IR value used by Example 06 (blank = default). Verified-by refers
to tests in `unit_test/plugins/test_example06_audio_nodes.py` (A),
`test_example06_ml_nodes.py` (M), `test_example06_schema.py` (S) and live run
ids above. S checks *every* field for toml ↔ Config parity (name, type,
default, enum, bounds) and that `ui.visible_if` references valid fields/values.

### dataset_ingest
| Field | Type / default / bounds | Ex-06 | Behaviour | Verified by |
|---|---|---|---|---|
| source_type | enum filesystem\|huggingface\|s3\|zip\|tar\|manifest = filesystem | filesystem | loader selection | S, A::TestDatasetIngest |
| path | str "" (required for filesystem) | label dir / v1 dir | resolved via `resolve_ingest_dir`; falls back to bundled `examples/**/data` — **now logged as a warning** | A::test_ingest_warns_when_falling_back, live runs |
| recursive | bool true (visible: filesystem) | false (pre/infer), true (train) | label = parent dir name | A::test_recursive_labels…, test_non_recursive… |
| limit | int 0, ≥0 | (removed from template) | per label when recursive (sorted walk, test/ before train/), total otherwise | A::test_recursive_limit_is_per_label |
| label_override, deduplicate | str "", bool false | — | force label; content-hash dedupe | A::test_label_override, test_deduplicate |
| manifest_path, hf_* (visible by source_type), resume_from, validate_integrity | — | — | not used by Ex-06 | S |
| lazy | bool false | — | **not implemented** (warns) — description now says so | S |

### audio_conditioner
| Field | Default / bounds | Ex-06 | Behaviour | Verified by |
|---|---|---|---|---|
| target_sample_rate | 16000, 1000–384000 | 16000 | librosa resample | A::test_resample_and_mono |
| mono | true | true | `librosa.to_mono` | A::test_resample_and_mono |
| trim_silence / trim_threshold_db | true / 40, (0,120] (visible: trim_silence) | default | top_db below peak; higher = less trimmed (description was inverted) | A::test_trim_silence_toggle_and_threshold |
| normalize / normalize_method | true / peak\|rms\|lufs (visible: normalize) | peak | | A::test_peak…, test_rms…, test_lufs…, test_methods_produce_different_levels, test_normalize_off… |
| target_level_db | −1, [−96, 0] (visible: method ∈ peak,rms) | default | dBFS target; also rms fallback for lufs w/o pyloudnorm | A::test_peak/rms_normalize_hits_target_level |
| target_lufs | −23, [−70, 0] (visible: method = lufs) | — | BS.1770 | A::test_lufs_normalize_hits_target |
| remove_dc_offset | true | default | | A::test_dc_offset_removal |
| preemphasis / preemphasis_coeff | false / 0.97, [0,1] (visible: preemphasis) | — | | A::test_preemphasis_boosts_highs |
| compress / compress_threshold_db / compress_ratio | false / −20 [−96,0] / 4, >0 (visible: compress) | — | | A::test_compression_reduces_peaks |
| limiter / skip_clipped | true / false | default | checked **after** normalisation (description fixed) | A::test_limiter_and_skip_clipped |
| batch_size | 0, ≥0 | — | chunked iteration only | A::test_batch_size_does_not_change_output |

### segmenter
| Field | Default / bounds | Ex-06 | Behaviour | Verified by |
|---|---|---|---|---|
| mode | fixed\|silence\|vad\|event\|speaker_turn = fixed | silence | silence **splits** clips (not just edge trim) | A::TestSegmenter (each mode) |
| window_ms (fixed) / overlap [0,1) | 1000 / 0 | — | | A::test_fixed_windows_and_overlap, test_fixed_short_clip… |
| vad_aggressiveness 0–3 (vad) | 2 | — | falls back to silence w/o webrtcvad | A::test_vad_mode |
| silence_threshold_db (0,120] | 40 | 40 | top_db below peak (description was inverted) | A::test_silence_threshold_higher_keeps_more |
| event_threshold_db ≤0 / event_min_gap_ms ≥1 (event) | −30 / 200 | — | | A::test_event_mode_threshold |
| min_segment_ms / max_segment_ms | 100 / 30000, min<max | default | **max now splits long spans** (was: dropped them, contrary to doc) | A::test_min_segment_drops_short, test_max_segment_splits_long_spans |

### audio_quality_gate (×2)
| Field | Default / bounds | Gate 3 / Gate 4 | Verified by |
|---|---|---|---|
| min_snr_db (visible: check_snr) | 10 | 5 / — | A::test_snr_check |
| max_clipping_ratio [0,1] | 0.01 | default / off | A::test_clipping_check |
| min_duration_s ≥0, max_duration_s ≥0 (0 = no max — **was broken**) | 0.1 / 60 | off / 0.2–1.0 | A::test_duration_bounds, test_max_duration_zero_means_no_max |
| min_lufs/max_lufs ≤0, min ≤ max | −70 / −10 | — | A::test_lufs_check |
| min_bandwidth_hz ≥0 | 1000 | default / off | A::test_bandwidth_check |
| silence_rms_threshold [0,1] | 0.001 | default / off | A::test_silence_check |
| rejection_policy skip\|warn\|raise | skip | skip | A::test_skip_and_warn…, test_raise_policy |
| check_* toggles | snr/clip/silence/duration/bandwidth on, lufs off | gate 3: duration off; gate 4: duration only | S::test_preprocess_quality_gates_are_single_purpose, A::test_ex06_duration_gate_no_longer_applies_hidden_snr |

### augmentation_pipeline
| Field | Default | Ex-06 | Verified by |
|---|---|---|---|
| copies_per_sample ≥0 | 1 | 2 | A::test_copies_per_sample, test_ex06_config_triples_dataset_and_is_seeded |
| augmentations (types gain, pitch_shift, time_stretch, speed_perturb, reverb, noise_inject, codec_degrade, eq, audiomentations; apply_prob ∈ [0,1]; rate/speed_factor > 0 — now validated) | 6-item list (toml default was `[]`, now equal) | pitch_shift ±2 + time_stretch 0.9–1.1, p=1 | A::test_each_augmentation_applies[*], test_reverb_with_ir_dir, test_apply_prob_zero…, test_toml_default_matches_config_default |

### audio_exporter
| Field | Default | Ex-06 | Verified by |
|---|---|---|---|
| output_dir / project | datasets/output/audio_export / "" | artifacts/…/dataset/speech_commands (UI stamps project → datasets/output/<ws>) | A::test_layout_and_split_ratios, test_project_overrides_output_dir, test_refuses_outside_cwd |
| split_ratios (≥0, sum>0, normalised) | 70/15/15 | 70/15/15 | A::test_split_ratio_extremes, test_unnormalised_ratios…, test_preassigned_split_wins |
| **group_by_source** (new) | true | default | A::test_group_by_source_prevents_augmentation_leakage, …_off_scatters, test_group_split_is_stable_across_runs |
| version_tag (pattern `^v\d+(\.\d+)*$`) | v1 | v1 | A::test_version_tag_dir |
| random_seed / append / format(wav) | 42 / false / wav | 42 / false→true | A::test_random_seed…, test_append_accumulates_labels, test_append_false_replaces_version_dir |

### feature_frontend
| Field | Default / bounds | Ex-06 | Verified by |
|---|---|---|---|
| feature_type (8 values) | log_mel | mfcc | A::test_feature_types_shapes[*], test_raw_passthrough |
| sample_rate 1000–384000 | 16000 | default | A::test_resamples_to_sample_rate |
| fixed_length ≥0 | 0 | 101 (infer) | A::test_fixed_length_pads_or_truncates, test_ex06_mfcc_shape_101x40 |
| n_fft ≥16, hop_length ≥1, win_length ≤ n_fft | 512/160/400 | 512/160 | A::test_hop_length_controls_frames, invalid-config tests |
| n_mels ≥1, n_mfcc ≥1 ≤ n_mels | 80/13 | 40 MFCC | A::test_ex06_mfcc_shape_101x40 |
| fmin ≥0, fmax >fmin ≤ Nyquist | 0 / null | fmax 8000 | A::test_mfcc_honours_fmax (**was ignored for MFCC**) |
| log_scale | true | — | A::test_log_scale_toggle_for_log_mel (was ignored for log_mel) |
| normalize / center / delta / delta_delta | true/true/false/false | normalize | A::test_normalize_toggle, test_center_off… (center was ignored for MFCC/chroma), test_deltas |

### dataset_builder
| Field | Default | Ex-06 | Verified by |
|---|---|---|---|
| split_ratios (train/val/test ∈[0,1], sum 1 ±1e-3; toml default was `{}` with stray keys) | 70/15/15 | auto-split only | M::test_auto_split_ratios_stratified, test_train_only_split (crashed before), test_toml_default_split_ratios |
| shuffle / stratify / random_seed | true/true/42 | — | M::test_auto_split_unstratified_and_unshuffled, test_seed_changes_auto_split |
| output_format numpy\|tensorflow\|pytorch | numpy | — | M::test_output_format_tensorflow |
| fixed_length ≥0 | 0 | 101 | M::test_fixed_length_pads_and_truncates, live 1e4ff50a (2571×101×40×1) |
| (new) metadata.test_metadata / split_mode / split_counts | — | — | M::test_test_metadata_feeds_fairness |

### model_builder / trainer
| Field | Default / bounds | Ex-06 | Verified by |
|---|---|---|---|
| architecture ds_cnn\|mobilenet\|simple_cnn | ds_cnn | ds_cnn | M::TestModelBuilder::test_architectures[*] (ds_cnn 4 blocks ≈22.5 K params as README) |
| filters ≥1, num_layers ≥0, dropout [0,1), learning_rate >0 | 64/4/0.25/1e-3 | same | M::test_learning_rate_and_dropout_compiled |
| backend keras\|auto, output_path | auto | keras | live runs |
| trainer.backend keras\|pytorch\|auto | auto | keras | M::test_pytorch_backend_rejects_keras_artifact (clear error now) |
| trainer.device auto\|cpu\|gpu | auto | auto (container forces CPU) | M chain uses cpu; PyTorch path now honours it |
| epochs ≥1, batch_size ≥1 (description said "0 = all at once"), patience ≥0 | 30/32/5 | 50/32/15 | live 1e4ff50a (50 epochs), M::test_trainer_outputs |
| learning_rate >0 or **null = keep model_builder LR** (default was 0.001 and silently overrode model_builder) | null | — | M::test_trainer_outputs (LR 0.01 kept), test_trainer_learning_rate_defaults_to_model |
| reduce_lr_factor (0,1), reduce_lr_patience ≥0, early_stopping_min_delta ≥0, min_val_accuracy [0,1], shuffle, mixed_precision (policy now restored), checkpoint_path | 0.5/3/0/0/true/false/"" | — | M::TestTrainerConfig invalid cases; live LR 1e-3 → 6.25e-5 via ReduceLROnPlateau |

### evaluator
| Field | Default | Verified by |
|---|---|---|
| output_path, plot_confusion_matrix, plot_training_curves, compute_roc (multi-class OvR; description said "binary") | …/true/true/true | M::test_evaluator_metrics, test_evaluator_plot_toggles; live 1e4ff50a |
| compute_fairness / fairness_attribute_key (visible: compute_fairness) | false / speaker_id | M::test_evaluator_metrics (was a no-op: dataset_builder never produced test_metadata) |
| output keeps upstream `*_path` metrics (e.g. keras_model_path) | — | M::test_evaluator_metrics |

### edge_optimizer
| Field | Default | Ex-06 | Verified by |
|---|---|---|---|
| backend tflite\|onnx\|tflm\|executorch\|ultralytics_export\|auto (last 3 = stub) | tflite | tflite | M::test_edge_optimizer_stub_backend |
| quantization float32\|float16\|int8 (TFLite only) | int8 | int8 | M::test_edge_optimizer_quantization[*] (uint8 I/O for int8, shape 1×101×40×1) |
| representative_samples ≥1 | 100 | 100 | live / local INT8 analysis (§2) |
| operator_fusion → "Weight optimization" (float32 + on = dynamic-range; result now reported as `dynamic_range`) | true | — | M::test_edge_optimizer_quantization[float32-True-…] |
| prune | false | — | not implemented (warns) |

| (1.1) `metadata.tensor_details` (input/output shape, dtype, int8 scale/zero_point), `input_shape`/`output_shape`, `source_model_path` | — | — | test_edge_optimizer::test_process_smoke |

### deployment_packager (Ship → package)
| Field | Default | Ship | Verified by |
|---|---|---|---|
| target edge\|docker\|mobile (runnable bundle) \| mcu (C header) \| cmsis_pack/arduino/zephyr/pte_bundle (stub) | mobile | edge | P::test_edge_package_is_runnable_and_traceable[*] |
| include_inference_script (run_inference.py + serve.py) / include_metadata | true / true | true | as above |
| (1.1) source_run_id — training run whose Feature Frontend / Dataset Builder config goes into `preprocessing.json` (empty = the package run's declared `source_run_id`, else a `runs/<id>/` segment of the model path) | "" | set by Ship | P::test_source_run_from_model_path |
| (1.1) selftest strict\|warn\|off, selftest_samples 0–10 | strict / 3 | default | P::test_strict_selftest_fails_on_input_shape_mismatch |

P = `unit_test/plugins/common/test_deployment_packager_bundle.py`.

### realtime_inference
| Field | Default | Ex-06 | Verified by |
|---|---|---|---|
| model_path (now also resolved against the project dir) | "" | latest/tflite/model.tflite | live infer runs, M::test_missing_model_and_labels |
| backend (tflm_host now really uses the TFLite path; ultralytics raises clearly) | auto | auto | M::test_tflm_host_backend_uses_tflite_interpreter |
| mode classification\|wake_word\|streaming_asr (detect/segment behave like classification) | classification | default | M::test_infer_int8_classification_accuracy, test_wake_word_threshold[*], test_streaming_asr_aggregates |
| wake_word_threshold [0,1], streaming_buffer_size ≥1, batch_size ≥1 (informational) | 0.8/10/1 | — | as above |
| adaptive / adaptive_skip_ratio [0,1] (now seeded) | false/0.5 | — | M::test_adaptive_skip[*] |
| (new) int8 + uint8 inputs, time-axis pad/truncate to model input, `confidence`/`true_label` in metadata | — | — | M::test_infer_pads_short_features_to_model_length |

## 4. Fixes made (PluginPackage + examples)

1. audio_exporter: `group_by_source` (default on) — one deterministic split per source clip → no augmentation/segment leakage.
2. trainer: INT8 calibration rows evenly spaced over X_train (was first 1000 of a label-sorted array).
3. trainer: `learning_rate` null = inherit model_builder's compiled LR (Keras 3 safe read); batch_size/epochs ≥1; PyTorch honours `device`, rejects non-`nn.Module`; GPU-retry keeps `shuffle`; mixed-precision policy restored.
4. audio_quality_gate: `max_duration_s = 0` means no max (was: reject everything); range validators.
5. segmenter: `max_segment_ms` splits long spans as documented.
6. feature_frontend: MFCC honours fmin/fmax/center, chroma honours center, log_mel honours log_scale; `normalized` metadata is a Python bool (numpy bool broke artifact/cache JSON in live run 1e4ff50a); validators (win_length ≤ n_fft, n_mfcc ≤ n_mels, fmax ≤ Nyquist).
7. dataset_builder: toml default/stray keys fixed; val/test = 0 no longer crashes; `test_metadata` for fairness.
8. evaluator: keeps upstream `*_path` metrics; descriptions.
9. edge_optimizer: honest `dynamic_range` label; descriptions for stub backends / prune / operator_fusion.
10. realtime_inference: tflm_host dispatch, int8 inputs, shape adaptation, model path resolution, seeded skipping, confidence metadata.
11. augmentation_pipeline: toml default equals Config default; spec validation.
12. dataset_ingest: fallback directory is logged.
13. Bounds (`minimum/maximum/exclusive*`, `pattern`) and `ui.visible_if` on all Example 06 plugins, mirrored by Pydantic `Field(ge/le/gt/lt/pattern)` / validators.
14. Graphs: train template reads the Phase-1 dataset (`workspace/artifacts/speech-commands/dataset/speech_commands/v1`, no `limit: 8`); quality gate 4 no longer re-applies SNR ≥ 10 dB (default) and gate 3 no longer applies duration; README corrected (thresholds, append chain, paths, epochs).

15. **Two-step templates (UX overhaul):** new Step 1 template `speech-commands-e2e-prepare` (all six labels, one graph); Step 2 (`pipeline_train_ml`) gets `title`, `group`/`phase`/`step_title`, a user-facing description ("run Step 1 first"; no CLI file names, no stale raw-clip fallback claim) and human node labels; the preprocess shards and the infer graph get node labels too. Tests: `unit_test/plugins/test_ux_plugins_templates.py`.
16. **Live progress:** trainer (per epoch: loss/accuracy/val_loss/val_accuracy/pct; early-stopping notice), evaluator (`evaluate` 0→100 with `test_accuracy`), edge_optimizer (`convert`, int8 `calibrate`), feature_frontend / dataset_builder / augmentation_pipeline / audio_exporter (pct over items) call `emit_node_progress` (defensive import). Isolated nodes reach the run log through the worker stderr marker. Tests: `test_ux_plugins_progress.py`.
17. **labels.txt everywhere:** trainer writes it beside `model.keras`, inside `saved_model/` and `checkpoints/`; evaluator beside the model and `metrics.json`; edge_optimizer beside `model.tflite`/`model.onnx` (falls back to the source folder's `labels.txt` when the artifact has none). Always the model's class-index order (`down, go, no, stop, up, yes`) — the console Ship default `yes, no, up, down, go, stop` does **not** match and must be replaced by this file / `labels` metadata. Outputs carry `labels`, `labels_path` and a `display_name` (`DS-CNN (30 epochs)`, `DS-CNN (21 of 50 epochs)`, `… · TFLite INT8`) in `ModelArtifact.metrics` / `DeploymentArtifact.metadata`; `metrics.json` stays numeric. Tests: `test_ux_plugins_labels.py`.
18. **Inspector text:** plugin.toml / Config descriptions no longer show env-var names, internal file names or library calls; those moved to `ui.help_advanced`. Output locations (`output_path`, `output_dir`, `checkpoint_path`, `resume_from`) are in the Advanced group (`realtime_inference.model_path` stays visible because it is required). Tests: `test_ux_plugins_schema_ux.py`.

19. **Reproducible training (same graph + seed → same model).** Live runs of the Step 2 graph with the same graph hash and seed 42 gave 71.1 % vs 75.6 % test accuracy. Causes and fixes:
    * `model_builder` never seeded TF, so every run started from different initial weights (main cause). It now calls `seed_everything(self.seed)` (trainer plugin `nodes.py`) before building: `random`, NumPy and TF via `keras.utils.set_random_seed`, plus `tf.config.experimental.enable_op_determinism()` (guarded; skipped when unavailable).
    * `trainer` seeds the same way before `load_model`/`clone_model` and again before `fit` (shuffle order, dropout); op determinism makes cuDNN conv/reduction kernels and the tf.data shuffle deterministic on GPU. A GPU op with no deterministic kernel falls into the existing GPU→CPU retry. PyTorch path: `torch.manual_seed`, `use_deterministic_algorithms(warn_only=True)`, seeded `DataLoader` generator.
    * Platform (isolated workers, `app/core/plugins/isolated_executor.py` / `worker.py`): the worker subprocess gets `PYTHONHASHSEED=<node seed>`, `TF_DETERMINISTIC_OPS=1`, `TF_CUDNN_DETERMINISTIC=1`, `GRAPHYN_NODE_SEED`, and `random` / `np.random` are seeded before `process()`. Opt out with `GRAPHYN_ISOLATED_DETERMINISTIC=0`.
    * `dataset_builder`: split inference from the path used to iterate a `set` (`PYTHONHASHSEED`-dependent when a path contains more than one of `train/val/test`) — now the segment nearest the file wins. Auto-split sorts features by `source_path` before the seeded `train_test_split`, so upstream delivery order no longer matters. (Metadata-split mode was already sorted.) `dataset_ingest` already walks directories and files in sorted order; `augmentation_pipeline` already uses `np.random.default_rng(node seed)`.
    * Node seeds are `derive_node_seed(graph seed, node_type, index, logical config)` (stable hash) — unchanged.
    * Tests: `unit_test/plugins/test_example06_determinism.py`, `unit_test/core/plugins/test_isolated_determinism_env.py`.
20. **Stale installed plugins at the same version.** The container ran an old `plugins/…/trainer/nodes.py` (no progress code) because startup only reinstalled bundled plugins on a *version* change. Startup now compares a content hash of `PluginPackage/<pack>/<plugin>` with the installed copy and recopies the code when it differs (venv kept unless requirements changed) — see `PLUGIN_GUIDE.md` → Bundled auto-install. Tests: `unit_test/core/plugins/test_bundled_code_drift.py`.
21. **Version bumps for fixes 19–20 code changes.** `trainer` plugin 1.0.0 → 1.1.0 (node `trainer` 1.0.0 → 1.1.0, node `model_builder` 1.1.0 → 1.2.0) and `dataset-builder` plugin 1.0.0 → 1.1.0 (node `dataset_builder` 1.0.0 → 1.1.0). Seeded weights and order-stable splits change results, so the node version (part of the pipeline-cache key) is bumped to invalidate outputs cached by the old code.

22. **Runnable, traceable Ship packages (`deployment-packager` 1.0.0 → 1.1.0, `edge-optimizer` 1.0.0 → 1.1.0).** The old edge TAR had `model.tflite`, `labels.txt`, a `metadata.json` without any feature settings and a `run_inference.py` that fed `np.zeros((1,101,40,1))` — a user could not run the model on real audio (train/serve skew), int8 input scaling was not handled, nothing tied the package to its training run, and fastapi/uvicorn were listed but unused. Package contents now (edge = files at the TAR root; docker = `<name>/…` + `Dockerfile` running `serve.py`; mobile = ZIP + `inference_android.java`):

    | File | Content |
    |---|---|
    | `model.tflite`, `labels.txt` | model + class order (`down, go, no, stop, up, yes`) |
    | `preprocessing.json` | source run id; decode (`librosa.load(sr=None, mono=True)` like dataset_ingest) + resample; the **full Feature Frontend config of the source run** (from `runs/<source>/graph.json`, omitted keys filled from the node's defaults): feature_type, sample_rate, n_fft, hop/win length, n_mels, n_mfcc, fmin/fmax, log_scale, normalize (per-clip z-score), center, deltas, fixed_length; Dataset Builder `frames.fixed_length` (pad zeros at the end / keep the first frames; taken from the model input when training used 0); model input/output tensor shape, dtype and int8 `scale`/`zero_point`; labels; librosa/numpy versions of the training host |
    | `run_inference.py` | WAV → exactly the training tensor → model → top-k (`--top-k`, `--json`, `--describe`, `--features x.npy`); quantizes for uint8/int8 inputs and dequantizes outputs; runtime `ai_edge_litert` → `tflite_runtime` → `tensorflow.lite` |
    | `serve.py` + `requirements-serve.txt` | optional `POST /predict` (raw audio body); fastapi/uvicorn only here |
    | `requirements.txt` | numpy, **librosa pinned to the training run's version**, soundfile, tflite-runtime / ai-edge-litert (tensorflow fallback noted) |
    | `README.md` | what the model does, labels, source-run test accuracy, how to run, input requirements (16 kHz mono, 101 frames ≈ 1 s), provenance summary, `sha256sum -c SHA256SUMS` |
    | `selftest.json` | see below |
    | `provenance.json` | source run (id, graph hash, record hash, status, test accuracy), registered model (name / stage / version from the run's `lineage_request` + registry; `matches_source_run`), model sha256 / format / quantization / source path, dataset external inputs (path, content hash, file count) from the source `prove.json`, graphyn + packager version, build time, package run id, sha256 + size of every file |
    | `SHA256SUMS`, `metadata.json` | `sha256sum -c` list; legacy metadata (+ input/output tensors) |

    **Parity by construction + test.** `run_inference.py` is a line-for-line mirror of `feature_frontend` (same librosa calls and arguments, same resampler, same z-score, same (F,T)→(T,F) transpose and fixed_length handling) and `dataset_builder._pad_or_truncate`; all parameters come from the source run's own graph snapshot, and librosa is pinned to the training version. **Self-test** (in the packager, `selftest=strict` by default): picks up to `selftest_samples` real clips from the source run's dataset_ingest folder (prefers `test/`, one per label), runs the *shipped* script's preprocessing on them and compares with the platform's own Feature Frontend node on the same waveform (`preprocessing_parity`, max |diff| ≤ 1e-4), checks the feature shape against the model input tensor (`input_shape`), then runs the shipped `run_inference.py --features … --describe --json` with a TFLite-capable Python (host, else the edge-optimizer venv; `GRAPHYN_PACKAGER_SELFTEST_PYTHON` overrides) and records predictions vs the folder label (`model_runs`, informational — the evaluator keeps no per-sample predictions). Strict mode fails the package run on a parity/shape/model failure; missing data/runtime → `skipped`/`partial`, never a silent pass. On the live model (`787747eeb2…`, 6 test clips) parity diff is 0.0 and 4/6 clips are predicted correctly.
    **Console sidecar** `<package>.manifest.json` (next to the archive): package sha256 + size, contents with roles/sizes/sha256, self-test summary, input summary, labels, metrics, how-to-run commands — shown in Ship step 4 and on the package run's Overview.
    **Ship wizard** passes `source_run_id` into the packager config. `/outputs/file` now allows `.gz` / `.tgz` / `.h`, so edge / docker packages and MCU headers download from the console (previously 415). Explicit downloads are audited (`model.download` / `run.output_download` / `run.outputs_zip` / `ship.download`, with path, size, sha256, actor — see `TRUST_MODEL.md`). Tests: P (12), `test_edge_optimizer.py`, `unit_test/api/test_download_audit.py`, `graphyn-ui/src/features/edge/shipManifest.test.ts`.

## 5. Known limitations

* A container started before fix 20 may still run older plugin copies; after an image rebuild/restart, startup now recopies any bundled plugin whose code differs from `PluginPackage/` (look for `source code changed at the same version` in the API log). Manual fallback: `graphyn plugin install --upgrade` / Plugins UI.
* INT8 accuracy is unstable for this DS-CNN (float 0.79 → INT8 0.42–0.67 depending on calibration rows; 0.76–0.85 for the live model). Use `quantization=float16`/`float32` when accuracy matters, or add quantization-aware training.
* The SNR estimator (mean power vs 5th-percentile magnitude) rates stationary white noise at ≈ 24 dB, so `min_snr_db=5` rarely rejects hiss (A::test_snr_check documents this).
* `segmenter mode=silence` can split one keyword into several labelled segments (≈ 10 % extra samples); inference emits one prediction per segment.
* Template training on CPU takes ≈ 29 min (50 epochs × ~34 s); all 1200 bundled clips are used by Phase 1, so there is no truly unseen hold-out beyond the grouped test split.
* `fairness_attribute_key=speaker_id` needs upstream metadata; dataset_ingest does not parse Speech Commands speaker ids from filenames.
* **Reproducibility limits.** Bit-identical results need the same device and software stack: `trainer`/`model_builder` `device=auto` picks GPU only when free VRAM ≥ `GRAPHYN_TF_GPU_MIN_FREE_MIB`, so one run may train on GPU and the next on CPU (different float rounding → different model); a GPU failure mid-run retries on CPU. Set `device: cpu` (or keep the GPU free) for run-to-run equality. Different TF/CUDA/cuDNN versions, CPU instruction sets (oneDNN kernels) or `mixed_precision=true` also change results. Op determinism slows some GPU kernels; `GRAPHYN_ISOLATED_DETERMINISTIC=0` trades it back for speed. The INT8 TFLite converter is deterministic for a given SavedModel + calibration rows. In-process nodes (audio prep) are not given a `PYTHONHASHSEED`; none of them iterate hash-ordered sets for results.
* `lazy`, `prune`, `detect`/`segment` modes, `batch_size` of realtime_inference are declared but not implemented (now documented as such).
* Ship packages: `run_inference.py` classifies the first `fixed_length` frames (≈ 1 s) of a file, like training; long recordings must be trimmed to the keyword (no sliding window). The README's accuracy is the source run's Keras test accuracy, not the quantized export's. The self-test needs librosa on the API host and the source dataset on disk; otherwise it records `skipped` with the reason. ONNX exports get preprocessing/provenance/README but `run_inference.py` is TFLite-only.

## 6. App / UI bugs (fixed)

| # | Bug | Fix | Tests |
|---|---|---|---|
| 1 | Pipeline-cache keys use the logical config, so a hit returned another run's run-scoped paths (`model_builder` → `runs/e5a81a2e…/models/compiled_….keras`); isolated stubs lost `cacheable=False` and stale entries kept hitting. | `app/core/execution/cache_rescope.py`: on a hit, paths under `artifacts/<slug>/runs/<other>/` are rewritten to the current run and the files copied there; the hit is discarded (node re-runs) when that is impossible. `cacheable` is checked **before** `cache.load` in sequential, parallel and distributed execution (isolated stubs take `cacheable` from the plugin's `NodeMetadata`). | `unit_test/core/test_example06_app_fixes.py` (cache tests) |
| 2 | `publish_latest` moved `latest` to empty preprocess run dirs, breaking `latest/tflite/model.tflite` for the infer graph. | Run dirs are no longer pre-created; `_finalize_run_artifacts` calls `publish_latest_if_produced` — `latest` moves only when `artifacts/<slug>/runs/<id>/` holds a file; an empty run tree is pruned. | `test_latest_not_moved_by_run_without_artifacts`, `test_publish_latest_if_produced_prunes_empty_tree` |
| 3 | `GET /runs/{id}/outputs?with_meta=1` cap (400) was filled by `dataset_ingest` input WAVs (396 of 3708), hiding `model.tflite` / `metrics.json`. | Source-node input files (pre-existing files under `path`/`data_dir`) are not outputs (`inputs_by_node` counts them); the cap is filled run-level → key files (models, metrics, small summaries) → bulk files, round-robin per node. On the live train run the listing is now 18 files incl. `tflite/model.tflite`, `metrics.json`. | `test_outputs_prioritise_key_files_and_skip_ingest_inputs`, `test_outputs_keep_files_ingest_wrote_during_run` |
| 4 | Console project stamp rewrote `audio_exporter.output_dir` (and set `project`, which overrides it) to `workspace/datasets/output/<ws>`, so Phase 2 ingested nothing from `workspace/artifacts/speech-commands/dataset/speech_commands/v1` and silently fell back to raw clips via a hard-coded `speech-command` rule. | `projectStamp.ts` only retargets empty/default/Library `output_dir`s; explicit artifact paths are kept (backend `graph_prepare` already never rewrote node paths). The hard-coded fallback is gone: a missing pipeline-produced dataset raises "has not been produced yet" unless `GRAPHYN_INGEST_EXAMPLE_FALLBACK=1`; template sync no longer flags such paths as missing. | `graphyn-ui/src/lib/projectStamp.test.ts`, `unit_test/core/test_workspace_paths.py::TestResolveIngestDir`, `test_prepare_graph_project_does_not_rewrite_handoff_paths`, `unit_test/plugins/test_example06_audio_nodes.py::test_ingest_warns_when_falling_back` |
| 5 | `audio_quality_gate` `node_end.output_count` summed `output` + `rejected` (219 shown where 206 passed). | `output_count` is the `output` port count (sum only for nodes without an `output` port); the event adds `output_counts` per port and `rejected_count`. | `test_logger_output_count_uses_primary_port`, `test_node_end_event_counts_output_port_only` |

Live `plugin_ui` dropping `exclusive*`/`pattern`/`ui.visible_if` was already fixed in the working tree. The running container still has the old code until it is rebuilt.

## 7. Reproduce

```bash
# unit tests (TF chain is marked heavy)
GRAPHYN_SKIP_PLUGIN_LOAD=1 venv/bin/pytest -q unit_test/plugins/test_example06_schema.py \
    unit_test/plugins/test_example06_audio_nodes.py
GRAPHYN_RUN_HEAVY=1 GRAPHYN_TF_DEVICE=cpu CUDA_VISIBLE_DEVICES=-1 GRAPHYN_SKIP_PLUGIN_LOAD=1 \
    venv/bin/pytest -q unit_test/plugins/test_example06_ml_nodes.py

# UX overhaul tests (progress, labels, templates, inspector text)
GRAPHYN_RUN_HEAVY=1 GRAPHYN_TF_DEVICE=cpu CUDA_VISIBLE_DEVICES=-1 GRAPHYN_SKIP_PLUGIN_LOAD=1 \
    venv/bin/pytest -q unit_test/plugins/test_ux_plugins_*.py

# Step 1 → Step 2 templates in-process via the SDK (scratch workspace; seed the input first:
#   mkdir -p $W/datasets/input && ln -s $PWD/examples/02_speech_commands/data $W/datasets/input/speech-commands)
#   load each template with rewrite_graph_paths(graph, slug=<template id>), then
#   initialize_registry(); Pipeline.from_json(path).run()   with GRAPHYN_PROJECT_DIR=$W, cwd=$(dirname $W)

# in-process E2E with the PluginPackage sources (≈ 25 min on CPU)
GRAPHYN_SKIP_PLUGIN_LOAD=1 GRAPHYN_TF_DEVICE=cpu CUDA_VISIBLE_DEVICES=-1 \
    venv/bin/python examples/06_speech_commands_e2e/verify_local.py /tmp/e06 50

# CLI end-to-end
bash examples/06_speech_commands_e2e/run_preprocess.sh
bash examples/06_speech_commands_e2e/run_train_ml.sh

# Live API (as the console does): POST each pipeline_preprocess*.graph.json, then the
# template graph from GET /api/v1/pipelines/templates/ex-06-speech-commands-e2e, to
# POST /api/v1/pipelines/run (NDJSON) with Authorization: Bearer $GRAPHYN_API_TOKEN;
# then GET /api/v1/runs/{id}/status, /outputs?with_meta=1, /artifacts.
```
