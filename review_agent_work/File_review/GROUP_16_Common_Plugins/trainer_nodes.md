# Functional Review — PluginPackage/Common/trainer/nodes.py

**Group:** 16 — Common Plugins  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Common/trainer/nodes.py
FUNCTION:    TrainerNode._train_pytorch
CATEGORY:    Error Handling
SEVERITY:    CRITICAL
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Train a PyTorch nn.Module with Adam, CrossEntropyLoss, and EarlyStopping."

WHAT IT ACTUALLY DOES:
The training loop does not detect NaN loss. If the model produces NaN logits
(e.g., due to exploding gradients, bad initialization, or NaN in input data),
`loss.item()` returns `nan`. The EarlyStopping check compares
`avg_val_loss < best_val_loss` where `best_val_loss = float("inf")`. Since
`nan < inf` is `False` in Python/IEEE 754, `patience_counter` increments on
every epoch. After `patience` epochs of NaN loss, EarlyStopping triggers and
`best_state` is `None` (never updated because `nan < inf` is always False).

Then:
```python
if best_state is not None:
    model.load_state_dict(best_state)
```
`best_state` is None, so the model is saved in its NaN-weight state:
```python
torch.save(model.state_dict(), str(pt_path))
```
A model with NaN weights is saved to disk and returned as a `ModelArtifact`.

THE BUG / RISK:
NaN loss during training causes the model to train for `patience` epochs, then
save a NaN-weight model to disk. The returned `ModelArtifact` points to a
corrupt model file. Downstream nodes (EvaluatorNode, EdgeOptimizerNode) will
load this corrupt model and produce NaN predictions or crash.

EVIDENCE:
```python
best_val_loss = float("inf")
best_state: dict | None = None

for epoch in range(self.config.epochs):
    ...
    avg_val_loss = val_loss / max(val_total, 1)
    # If avg_val_loss is nan:
    if avg_val_loss < best_val_loss:   # nan < inf → False
        best_val_loss = avg_val_loss   # never updated
        best_state = {...}             # never set
    else:
        patience_counter += 1          # increments every epoch
        if patience_counter >= self.config.patience:
            break                      # exits after patience epochs

if best_state is not None:             # False — best_state is None
    model.load_state_dict(best_state)  # skipped

torch.save(model.state_dict(), str(pt_path))  # saves NaN-weight model
```

REPRODUCTION SCENARIO:
Pass a model with a very high learning rate (e.g., 100.0) or NaN in input data.
Loss becomes NaN on epoch 1. After `patience` epochs, a NaN-weight model is
saved.

IMPACT:
Data corruption: NaN-weight model saved to disk. Downstream pipeline stages
produce NaN predictions or crash. This is the most dangerous failure mode in
the trainer.

FIX DIRECTION:
```python
import math
if math.isnan(avg_val_loss) or math.isnan(avg_train_loss):
    log.error(
        "TrainerNode (pytorch): NaN loss detected at epoch %d. "
        "Stopping training. Check learning rate, input data, and model initialization.",
        epoch + 1
    )
    break

# After loop, check if best_state was ever set:
if best_state is None:
    raise RuntimeError(
        "TrainerNode (pytorch): training failed — no valid checkpoint was saved. "
        "Check for NaN loss or data issues."
    )
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/trainer/nodes.py
FUNCTION:    TrainerNode._train_keras
CATEGORY:    Error Handling
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Train a Keras model with EarlyStopping, ModelCheckpoint, ReduceLROnPlateau."

WHAT IT ACTUALLY DOES:
Calls `model.fit(...)` without catching exceptions. If training raises an
exception (e.g., OOM, NaN loss causing Keras to abort, or a custom callback
raising), the exception propagates out of `_train_keras` and out of `process()`.
The output directory `out_path` may have been partially written (e.g., the
checkpoint directory was created but no checkpoint was saved). The
`ModelArtifact` is never returned.

More specifically: Keras does NOT automatically stop on NaN loss unless
`keras.callbacks.TerminateOnNaN()` is included in the callbacks list. The
current callbacks are `EarlyStopping`, `ModelCheckpoint`, and `ReduceLROnPlateau`.
`TerminateOnNaN` is absent. If the model produces NaN loss, Keras continues
training with NaN weights for all remaining epochs, then saves the NaN-weight
model.

THE BUG / RISK:
NaN loss during Keras training is not detected. The model trains for all
`epochs` with NaN weights, then saves a corrupt model. The `ModelArtifact`
points to a NaN-weight SavedModel.

EVIDENCE:
```python
callbacks = [
    keras.callbacks.EarlyStopping(...),
    keras.callbacks.ModelCheckpoint(...),
    keras.callbacks.ReduceLROnPlateau(...),
    # TerminateOnNaN is MISSING
]
history = model.fit(...)
# If loss is NaN, training continues for all epochs
model.save(keras_model_path)  # saves NaN-weight model
```

REPRODUCTION SCENARIO:
Pass a model with a very high learning rate. Loss becomes NaN on epoch 1.
Training continues for all `epochs`. NaN-weight model is saved.

IMPACT:
Data corruption: NaN-weight Keras model saved to disk. Same impact as the
PyTorch NaN case.

FIX DIRECTION:
```python
callbacks = [
    keras.callbacks.EarlyStopping(...),
    keras.callbacks.ModelCheckpoint(...),
    keras.callbacks.ReduceLROnPlateau(...),
    keras.callbacks.TerminateOnNaN(),  # ADD THIS
]
```
And after `model.fit()`, check for NaN in the history:
```python
final_loss = history.history.get("loss", [float("nan")])[-1]
if math.isnan(final_loss):
    raise RuntimeError(
        "TrainerNode (keras): training produced NaN loss. "
        "Check learning rate, input data, and model initialization."
    )
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/trainer/nodes.py
FUNCTION:    TrainerNode._train_pytorch
CATEGORY:    Error Handling
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Train a PyTorch nn.Module with Adam, CrossEntropyLoss, and EarlyStopping."

WHAT IT ACTUALLY DOES:
Does not handle OOM (Out of Memory) errors. If the batch size is too large for
the available GPU/CPU memory, `X_batch.to(device)` or `model(X_batch)` raises
`torch.cuda.OutOfMemoryError` (CUDA OOM) or `MemoryError` (CPU OOM). This
exception propagates out of the training loop without any cleanup. The model
is in an undefined state (mid-backward-pass), and `best_state` may be None or
stale.

THE BUG / RISK:
OOM during training leaves the model in an undefined state. If `best_state` was
set before the OOM, the code after the loop restores it and saves it — this is
correct. But if OOM occurs on the first epoch before any checkpoint, `best_state`
is None and the model is saved in its initial (untrained) state.

EVIDENCE:
```python
for X_batch, y_batch in train_loader:
    X_batch, y_batch = X_batch.to(device), y_batch.to(device)
    # torch.cuda.OutOfMemoryError raised here — no try/except
    logits = model(X_batch)
```

REPRODUCTION SCENARIO:
Set `batch_size=10000` on a GPU with 4 GB VRAM. OOM on first batch.
`best_state` is None. After the exception propagates, no model is saved.

IMPACT:
Pipeline crash with no model artifact. No data corruption (model not saved),
but the pipeline fails without a clear error about OOM.

FIX DIRECTION:
```python
except torch.cuda.OutOfMemoryError as e:
    log.error(
        "TrainerNode (pytorch): CUDA OOM at epoch %d. "
        "Reduce batch_size (current: %d). Error: %s",
        epoch + 1, self.config.batch_size, e
    )
    torch.cuda.empty_cache()
    break
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/trainer/nodes.py
FUNCTION:    TrainerNode._train_keras
CATEGORY:    Resource Leak
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Save X_train representative data for INT8 TFLite calibration."

WHAT IT ACTUALLY DOES:
Saves the ENTIRE `dataset.X_train` array to `X_train_repr.npy`:
```python
np.save(repr_path, dataset.X_train)
```
For a large training set (e.g., 100,000 samples × 101 frames × 40 bins × 1 channel
× 4 bytes = ~1.6 GB), this writes 1.6 GB to disk. The `EdgeOptimizerNode` only
uses `min(representative_samples, len(X_repr))` samples (default 100) for
calibration. Saving the full training set is wasteful.

THE BUG / RISK:
Disk space exhaustion for large datasets. A 100K-sample training set produces
a ~1.6 GB calibration file when only 100 samples are needed.

EVIDENCE:
```python
repr_path = str(out_path / "saved_model" / "X_train_repr.npy")
np.save(repr_path, dataset.X_train)  # saves ALL training samples
```

REPRODUCTION SCENARIO:
Train on a 100K-sample dataset. `X_train_repr.npy` is ~1.6 GB.
`EdgeOptimizerNode` uses only 100 samples from it.

IMPACT:
Disk space waste. No data loss, but can cause disk full errors on constrained
systems.

FIX DIRECTION:
Save only the first N samples:
```python
n_repr = min(1000, len(dataset.X_train))
np.save(repr_path, dataset.X_train[:n_repr])
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/trainer/nodes.py
FUNCTION:    ModelBuilderNode.process
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Build a model from the dataset's input_shape and n_classes."

WHAT IT ACTUALLY DOES:
Accesses `dataset.input_shape` and `dataset.n_classes` directly without
checking if they are valid. If `dataset` is None (e.g., the pipeline sends
None to the input port), `dataset.input_shape` raises `AttributeError`. If
`dataset.n_classes == 0` (empty dataset), `keras.layers.Dense(0, ...)` raises
a Keras error about invalid units.

THE BUG / RISK:
None dataset or zero-class dataset causes a confusing crash in Keras model
construction.

EVIDENCE:
```python
dataset = inputs.get("input")
# No None check
model = self._build_keras_model(dataset.input_shape, dataset.n_classes)
# AttributeError if dataset is None
# Keras error if n_classes == 0
```

REPRODUCTION SCENARIO:
```python
node.process({"input": None})  # AttributeError: 'NoneType' object has no attribute 'input_shape'
```

IMPACT:
Crash with confusing error.

FIX DIRECTION:
```python
dataset = inputs.get("input")
if dataset is None:
    raise ValueError("ModelBuilderNode: 'input' port received None — expected DatasetArtifact")
if dataset.n_classes == 0:
    raise ValueError("ModelBuilderNode: dataset has 0 classes — cannot build model")
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/trainer/nodes.py
FUNCTION:    TrainerNode._train_pytorch
CATEGORY:    Performance
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Deep-copy state dict to CPU for safe storage."

WHAT IT ACTUALLY DOES:
```python
best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
```
This is called every time `avg_val_loss < best_val_loss`, which can be every
epoch in the early stages of training. For a large model (e.g., 100M parameters),
this copies ~400 MB of tensors on every improvement. For 30 epochs with
improvements on 20 of them, this is 8 GB of tensor copies.

THE BUG / RISK:
Excessive memory allocation for large models. Each checkpoint copy allocates
the full model size in CPU memory. For large models, this can cause OOM.

EVIDENCE:
```python
if avg_val_loss < best_val_loss:
    best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
    # Full model copy on every improvement
```

REPRODUCTION SCENARIO:
Train a 100M-parameter model for 30 epochs with steady improvement. Each epoch
copies ~400 MB. Peak memory usage: current model (400 MB) + best_state (400 MB)
= 800 MB extra.

IMPACT:
Memory pressure for large models. Not a crash for typical audio models (which
are small), but a risk for larger architectures.

FIX DIRECTION:
Save to a temp file instead of keeping in memory:
```python
import tempfile
best_ckpt_path = out_path / "best_checkpoint.pt"
torch.save(model.state_dict(), str(best_ckpt_path))
# At end: model.load_state_dict(torch.load(best_ckpt_path))
```
--------------------------------------------------------------------

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | CRITICAL |
| Silent Failures | 1 |
| Error Handling | MISSING |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | UNSAFE |
| Test Hostile | NO |
| Top Risk | NaN loss in PyTorch training loop is undetected — EarlyStopping triggers after `patience` epochs and saves a NaN-weight model to disk, corrupting the entire downstream pipeline |
