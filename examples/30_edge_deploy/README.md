# 30 — Edge deploy (optimize → package)

Graphyn-native Edge Impulse-like path: **model path → edge_optimizer → deployment_packager → download**.

No Edge Impulse cloud — uses Common plugins only.

## Required inputs

| Input | Where | Notes |
|---|---|---|
| Trained model | `model_ref` python_code → `model_path` | Keras **SavedModel directory** or `.keras` file under `workspace/artifacts/…` (typically from `trainer` / Example 06). |
| Labels | same node → `labels` | Class names; written into the package as `labels.txt`. |
| Optional INT8 calib | beside the model | `X_train_repr.npy` next to the SavedModel (needed only for `quantization=int8`). |

Template defaults use **TFLite float32** (lighter than int8) and package **target=edge** (TAR under `workspace/artifacts/edge-deploy/packages/`).

## Graph

```
model_ref (python_code) → edge_optimizer → deployment_packager
```

Starter copy also lives at `examples/templates/edge-deploy.graph.json` (Builder Templates → **edge-deploy**).

## UI wizard

Library → **Edge** (`#/edge`): choose template → configure model path / target → run → download package.

## CLI smoke (when a model exists)

```bash
# After training (e.g. examples/06) copy/symlink SavedModel to the configured path, then:
graphyn run --graph examples/30_edge_deploy/pipeline.graph.json
# or open Library → Edge and Run
```

Outputs:

- Optimized model: `workspace/artifacts/edge-deploy/optimized/`
- Package: `workspace/artifacts/edge-deploy/packages/edge_model_edge.tar` (or `.zip` / `.h` depending on target)
