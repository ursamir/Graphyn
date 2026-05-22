# Implementation Plan: Enhanced Node System

← [Back to design.md](design.md) | ← [Back to requirements.md](requirements.md)

---

## Overview

This plan migrates the current hand-written `NODE_REGISTRY` dict and minimal `Node` base class to a fully typed, auto-discovering, Pydantic-v2-native node infrastructure. Tasks are ordered so that each layer depends only on previously completed layers:

1. **Foundation** — errors, ports, config, `Node` base class, `CompatibilityChecker`
2. **Registration** — `NodeMetadata`, `TypeCatalogue`, `NodeRegistry`, `AutoDiscovery`, `__init__.py`
3. **Runtime** — `NodeObserver`, `NodeExecutor`, lifecycle + retry + streaming
4. **Migration** — `AudioSample`, all audio nodes, delete old `registry.py`, update `registry_runtime.py`, update `validation.py`
5. **Pipeline** — DAG data structures, `PipelineGraph`, rewritten `run_pipeline`, serialisation, schema export
6. **Property Tests** — all 8 Hypothesis property tests

Tasks marked `*` are optional (test sub-tasks) and can be skipped for a faster MVP.

---

## Sub-Documents

| File | Tasks | Topics |
|---|---|---|
| [tasks-01-foundation.md](tasks-01-foundation.md) | 1–9 | `hypothesis` install · errors · ports · config · `Node` base · `CompatibilityChecker` |
| [tasks-02-registration.md](tasks-02-registration.md) | 10–16 | `NodeMetadata` · `TypeCatalogue` · `NodeRegistry` · `AutoDiscovery` · `__init__.py` |
| [tasks-03-runtime.md](tasks-03-runtime.md) | 17–20 | `NodeObserver` · `NodeExecutor` · lifecycle · retry · streaming |
| [tasks-04-migration.md](tasks-04-migration.md) | 21–31 | `AudioSample` · all audio nodes · delete old registry · `registry_runtime.py` · `validation.py` |
| [tasks-05-pipeline.md](tasks-05-pipeline.md) | 32–37 | DAG data structures · `PipelineGraph` · `run_pipeline` · serialisation · schema export |
| [tasks-06-tests.md](tasks-06-tests.md) | 38–46 | 8 Hypothesis property tests |

---

## Tasks (Summary)

### Foundation (tasks-01-foundation.md)

- [ ] 1. Add `hypothesis` and `pydantic` to `requirements.txt`
- [ ] 2. Create `app/core/nodes/errors.py` — custom exception hierarchy
- [ ] 3. Create `app/core/nodes/ports.py` — `PortDataType`, `InputPort`, `OutputPort`
- [ ] 4. Create `app/core/nodes/config.py` — `NodeConfig` base class
- [ ] 5. Create `app/core/nodes/retry.py` — `RetryPolicy`
- [ ] 6. Create `app/core/nodes/compat.py` — `CompatibilityChecker` and `_type_to_schema`
- [ ] 7. Rewrite `app/core/nodes/base.py` — `Node` base class
- [ ]* 8. Write unit tests for foundation layer (`tests/test_foundation.py`)
- [ ] 9. Checkpoint — foundation layer

### Registration (tasks-02-registration.md)

- [ ] 10. Create `app/core/nodes/metadata.py` — `NodeMetadata`
- [ ] 11. Create `app/core/nodes/catalogue.py` — `TypeCatalogue`
- [ ] 12. Rewrite `app/core/nodes/registry.py` — `NodeRegistry` singleton class
- [ ] 13. Create `app/core/nodes/discovery.py` — `AutoDiscovery`
- [ ] 14. Rewrite `app/core/nodes/__init__.py` — singleton wiring
- [ ]* 15. Write unit tests for registration layer (`tests/test_registration.py`)
- [ ] 16. Checkpoint — registration layer

### Runtime (tasks-03-runtime.md)

- [ ] 17. Create `app/core/nodes/observers.py` — `NodeObserver`, `LoggingObserver`, `CompositeObserver`
- [ ] 18. Implement `NodeExecutor` in `app/core/pipeline.py` (runtime section)
- [ ]* 19. Write unit tests for runtime layer (`tests/test_runtime.py`)
- [ ] 20. Checkpoint — runtime layer

### Migration (tasks-04-migration.md)

- [ ] 21. Migrate `app/models/audio_sample.py` — `AudioSample` to `PortDataType`
- [ ] 22. Migrate input/source nodes: `InputNode`, `MicInputNode`
- [ ] 23. Migrate preprocessing nodes: `CleanNode`, `TrimNode`, `ResampleNode`, `FormatConvertNode`, `NormalizeNode`, `GainNode`
- [ ] 24. Migrate augmentation nodes: `AugmentNode`, `PitchShiftNode`, `TimeStretchNode`, `SpeedPerturbNode`, `ReverbNode`, `NoiseMixNode`
- [ ] 25. Migrate processing/composition nodes: `FilterNode`, `FadeNode`, `DenoiseNode`, `ConcatenateNode`, `TagNode`, `DuplicateNode`, `SegmentNode`, `SpectrogramNode`
- [ ] 26. Migrate compression/VAD nodes: `CompressionNode`, `VADNode`, `PaddingNode`, `SilenceDetectorNode`
- [ ] 27. Migrate split/export nodes: `SplitNode`, `StratifiedSplitNode`, `ExportNode`, `HFExportNode`, `TFRecordExportNode`
- [ ] 28. Delete old `app/core/nodes/registry.py` hand-written format and update `registry_runtime.py`
- [ ] 29. Update `app/core/validation.py` to use `CompatibilityChecker`
- [ ]* 30. Write migration regression tests (`tests/test_migration.py`)
- [ ] 31. Checkpoint — migration complete

### Pipeline DAG (tasks-05-pipeline.md)

- [ ] 32. Add DAG data structures to `app/core/pipeline.py`: `NodeSpec`, `EdgeSpec`, `PipelineConfig`
- [ ] 33. Implement `PipelineGraph` in `app/core/pipeline.py`
- [ ] 34. Rewrite `run_pipeline` in `app/core/pipeline.py` as DAG executor
- [ ]* 35. Write unit tests for pipeline DAG (`tests/test_pipeline_dag.py`)
- [ ]* 36. Write integration tests for full pipeline execution (`tests/test_pipeline_integration.py`)
- [ ] 37. Checkpoint — pipeline DAG executor complete

### Property-Based Tests (tasks-06-tests.md)

- [ ] 38. Write Property 1 — `are_compatible` is reflexive for non-`None` types
- [ ] 39. Write Property 2 — `are_compatible` respects `issubclass` for plain classes
- [ ] 40. Write Property 3 — `TypeCatalogue` round-trip: `resolve(fqn(T)) is T`
- [ ] 41. Write Property 4 — Registry completeness: every registered node is retrievable
- [ ] 42. Write Property 5 — SISO wrapper equivalence
- [ ] 43. Write Property 6 — Retry backoff formula
- [ ] 44. Write Property 7 — `NodeMetadata` serialisation round-trip
- [ ] 45. Write Property 8 — Config schema idempotence
- [ ] 46. Checkpoint — all property tests pass

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Each task references specific requirements and the design file/section it implements
- Checkpoints (tasks 9, 16, 20, 31, 37, 46) ensure incremental validation at each layer boundary
- Property tests (tasks 38–45) validate universal correctness properties using Hypothesis
- The old `NODE_REGISTRY` dict is deleted in task 28 — do not attempt tasks 28+ before tasks 12–14 are complete
- `hypothesis` must be installed (task 1) before any property tests can run
