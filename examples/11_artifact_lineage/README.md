# Example 11 — Artifact Lineage Tracking

Demonstrates Phase 4 provenance — artifact tracking, lineage trees, and the `ArtifactCollection` returned by `Pipeline.run()`.

---

## What This Demonstrates

- `result.artifacts` — list of `ArtifactRecord` objects from `Pipeline.run()`
- `result.run_id` — run ID from `ArtifactCollection`
- `result.get_by_type(artifact_type)` — filter artifacts by type
- `result.lineage(artifact_id)` — full upstream provenance tree
- `ArtifactStore.list(run_id=...)` — query artifacts by run, node, or type
- `ProvenanceStore.get_lineage(artifact_id)` — recursive lineage tree
- `audiobuilder artifacts list --run <run_id>` — CLI query
- `audiobuilder artifacts lineage <artifact_id>` — CLI lineage
- `GET /api/v1/artifacts/{id}/lineage` — REST API lineage

---

## How to Run

```bash
# Prepare data (if not already done)
venv/bin/python examples/prepare_real_data.py

venv/bin/python examples/11_artifact_lineage/lineage_demo.py
```

---

## What Lineage Looks Like

After running a pipeline, the provenance system records which node produced each artifact and what inputs it consumed. The lineage tree walks backwards from any artifact to its origins:

```
◉ DatasetVersionerNode (dataset_versioner_6)  artifact: f586ad2a...
  └─ DatasetBuilderNode (dataset_builder_5)   artifact: c3e3e3c3...
    └─ FeatureFrontendNode (feature_frontend_4)  artifact: 20034839...
      └─ SegmenterNode (segmenter_2)          artifact: 651e6c04...
        └─ AudioConditionerNode (audio_conditioner_1)  artifact: d27678d3...
          └─ DatasetIngestNode (dataset_ingest_0)  artifact: 26686a01...
      └─ AudioQualityGateNode (audio_quality_gate_3)  artifact: 42ae2819...
```

This answers: *"Where did this artifact come from, and what data was it derived from?"*

---

## SDK Usage

```python
from app.core.sdk import Pipeline, PipelineNode

pipeline = Pipeline([...])
result = pipeline.run()

# Access artifacts
print(result.run_id)
print(result.artifacts)           # list[ArtifactRecord]

# Filter by type
audio = result.get_by_type("audio_samples")
models = result.get_by_type("model_artifact")

# Walk lineage tree
if result.artifacts:
    tree = result.lineage(result.artifacts[0].artifact_id)
    print(tree)

# Query the store directly
from app.core.artifact_store import ArtifactStore
store = ArtifactStore()
records = store.list(run_id=result.run_id)
records = store.list(artifact_type="audio_samples")
```

---

## CLI Usage

```bash
# List artifacts for a run
audiobuilder artifacts list --run <run_id>

# Get a specific artifact
audiobuilder artifacts get <artifact_id>

# Walk the lineage tree
audiobuilder artifacts lineage <artifact_id>

# Replay the run that produced an artifact
audiobuilder artifacts replay <run_id>
```
