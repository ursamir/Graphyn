# Group Review Index — 16: Common Plugins

**Files reviewed:** 11  
**Total findings:** 34 (CRITICAL: 1 | HIGH: 14 | MEDIUM: 14 | LOW: 5)  
**Date:** 2026-05-26

---

## File Summaries

| File | Overall Risk | Silent Failures | Top Risk |
|---|---|---|---|
| dataset_balancer_nodes.md | HIGH | 2 | `_flag_synthetic` discards its own metadata copy — `needs_augmentation` flags silently lost |
| dataset_builder_nodes.md | HIGH | 1 | Mixed-metadata batch triggers misleading ValueError instead of auto-split fallback |
| dataset_versioner_nodes.md | MEDIUM | 1 | Partial output directory left on disk when any write fails mid-process |
| deployment_packager_nodes.md | MEDIUM | 0 | MCU packager builds entire hex representation of model in RAM — OOM risk for models > 5 MB |
| edge_optimizer_nodes.md | HIGH | 2 | INT8 calibration silently uses all-zeros data with wrong shape when X_train_repr.npy is absent |
| embedding_generator_nodes.md | HIGH | 2 | Model cache does not key on model name — wrong model silently reused if config is mutated |
| evaluator_nodes.md | HIGH | 2 | Empty test set produces NaN test_accuracy written to metrics.json without warning |
| experiment_tracker_nodes.md | HIGH | 1 | MLflow backend unavailability causes hard pipeline failure with no fallback to JSON |
| multimodal_fusion_nodes.md | MEDIUM | 2 | Mismatched embedding dimensions crash attention fusion with confusing numpy shape error |
| realtime_inference_nodes.md | HIGH | 1 | `_asr_buffer` accumulates across process() calls when mode changes — unbounded memory growth |
| trainer_nodes.md | CRITICAL | 1 | NaN loss in PyTorch training loop undetected — saves NaN-weight model to disk |

---

## Priority Findings (CRITICAL and HIGH only)

**[CRITICAL] trainer_nodes.md — TrainerNode._train_pytorch — NaN loss undetected; EarlyStopping saves NaN-weight model to disk after `patience` epochs**

**[HIGH] trainer_nodes.md — TrainerNode._train_keras — TerminateOnNaN callback absent; NaN loss trains for all epochs and saves corrupt Keras model**

**[HIGH] trainer_nodes.md — TrainerNode._train_pytorch — OOM during training leaves model in undefined state; no CUDA OOM handling**

**[HIGH] edge_optimizer_nodes.md — EdgeOptimizerNode._export_tflite — INT8 calibration silently uses all-zeros data with hardcoded wrong shape when X_train_repr.npy absent**

**[HIGH] edge_optimizer_nodes.md — EdgeOptimizerNode._export_onnx — PyTorch ONNX export uses hardcoded dummy input shape (1,101,40,1) — wrong for any other model**

**[HIGH] evaluator_nodes.md — EvaluatorNode.process — Empty test set produces NaN test_accuracy in metrics.json without any warning**

**[HIGH] evaluator_nodes.md — EvaluatorNode.process — Model output dimension mismatch with label count produces wrong per-class metrics silently**

**[HIGH] embedding_generator_nodes.md — EmbeddingGeneratorNode.process — Model cache does not key on model name; wrong model silently reused if config mutated between calls**

**[HIGH] embedding_generator_nodes.md — EmbeddingGeneratorNode.process — Empty audio sample produces zero embedding or crash depending on backend**

**[HIGH] experiment_tracker_nodes.md — ExperimentTrackerNode._log_mlflow — MLflow server unavailability causes hard pipeline failure with no fallback to JSON backend**

**[HIGH] dataset_balancer_nodes.md — DatasetBalancerNode._flag_synthetic — Internal metadata copy discarded; needs_augmentation flags silently lost on every synthetic-strategy run**

**[HIGH] dataset_builder_nodes.md — DatasetBuilderNode.process — Mixed-metadata batch (some features with split info, some without) raises misleading ValueError**

**[HIGH] realtime_inference_nodes.md — RealtimeInferenceNode.process — _asr_buffer accumulates across process() calls when mode changes; unbounded memory growth**

**[HIGH] realtime_inference_nodes.md — RealtimeInferenceNode.process — Non-2D feature arrays cause shape mismatch errors in inference backend**

---

## Most Dangerous File

**trainer_nodes.md** — The PyTorch training loop has no NaN loss detection: when loss becomes NaN, EarlyStopping triggers after `patience` epochs and `torch.save` writes a NaN-weight model to disk. The Keras path has the same issue (missing `TerminateOnNaN` callback). Both paths can silently corrupt the model artifact that all downstream nodes depend on.
