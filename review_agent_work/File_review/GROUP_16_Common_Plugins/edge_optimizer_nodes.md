# Functional Review — PluginPackage/Common/edge_optimizer/nodes.py

**Group:** 16 — Common Plugins  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Common/edge_optimizer/nodes.py
FUNCTION:    EdgeOptimizerNode._export_tflite (INT8 branch)
CATEGORY:    Silent Failure
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Full integer quantization using representative dataset."

WHAT IT ACTUALLY DOES:
When `X_train_repr.npy` is not found, the code attempts to infer the input shape
by running a dummy float32 conversion, then creating a zero-filled array. The
fallback chain is:
1. Try to infer shape from a temporary converter run.
2. If that fails, use hardcoded shape `(100, 101, 40, 1)`.

The hardcoded fallback shape `(100, 101, 40, 1)` is specific to one audio
feature configuration (101 frames, 40 mel bins). For any other model (different
frame count, different feature size, or non-audio models), the representative
dataset has the wrong shape, causing the INT8 calibration to silently use
incorrect data. The converter may succeed (TFLite does not validate calibration
data shape strictly in all versions), producing a quantized model calibrated on
zeros — which is the worst possible calibration data.

THE BUG / RISK:
INT8 model calibrated on all-zeros data produces a model with incorrect
quantization parameters. The model will run without error but produce wrong
predictions. This is a silent wrong result.

EVIDENCE:
```python
log.warning(
    "EdgeOptimizerNode: could not infer input shape for INT8 calibration. "
    "Using generic shape (100, 101, 40, 1). ..."
)
X_repr = np.zeros((100, 101, 40, 1), dtype=np.float32)
```

REPRODUCTION SCENARIO:
Use a model with input shape `(1, 64, 128, 1)` (64 frames, 128 mel bins).
`X_train_repr.npy` is absent. The shape inference fails. The fallback uses
`(100, 101, 40, 1)`. TFLite converter may accept this or raise a shape mismatch
error — if it accepts it, the INT8 model is calibrated on wrong-shape zeros.

IMPACT:
Silent wrong result: INT8 model with incorrect quantization parameters deployed
to edge devices. Accuracy degradation with no error.

FIX DIRECTION:
Raise an error instead of silently using wrong-shape zeros:
```python
raise ValueError(
    "EdgeOptimizerNode: INT8 quantization requires X_train_repr.npy in the "
    f"SavedModel directory ({repr_path}). "
    "TrainerNode saves this file automatically. "
    "Cannot proceed with INT8 calibration without representative data."
)
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/edge_optimizer/nodes.py
FUNCTION:    EdgeOptimizerNode._export_onnx (PyTorch branch)
CATEGORY:    Silent Failure
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Convert SavedModel or PyTorch model to ONNX."

WHAT IT ACTUALLY DOES:
For PyTorch models, uses a hardcoded dummy input shape `(1, 101, 40, 1)`:
```python
dummy_input = torch.zeros(1, 101, 40, 1)
torch.onnx.export(model, dummy_input, onnx_path, ...)
```
This shape is hardcoded and specific to one audio feature configuration.
For any PyTorch model with a different input shape, `torch.onnx.export` will
either raise a shape mismatch error (if the model validates input shape) or
silently export an ONNX model with incorrect input shape metadata.

THE BUG / RISK:
ONNX model exported with wrong input shape. Downstream inference will fail or
produce wrong results when the actual input has a different shape.

EVIDENCE:
```python
dummy_input = torch.zeros(1, 101, 40, 1)   # hardcoded — wrong for other models
torch.onnx.export(model, dummy_input, onnx_path, opset_version=17, ...)
```

REPRODUCTION SCENARIO:
Pass a PyTorch model expecting input shape `(1, 64, 128, 1)`. The export
succeeds with wrong shape metadata, or raises a confusing shape error.

IMPACT:
Silent wrong result or confusing crash. ONNX model may be unusable.

FIX DIRECTION:
Require the caller to provide the input shape via config, or read it from
`artifact.input_shape` if available:
```python
input_shape = getattr(artifact, "input_shape", None) or (1, 101, 40, 1)
dummy_input = torch.zeros(*input_shape)
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/edge_optimizer/nodes.py
FUNCTION:    EdgeOptimizerNode.process
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Optimize a SavedModel for edge deployment."

WHAT IT ACTUALLY DOES:
Does not validate that `artifact.model_path` exists before calling
`_export_tflite` or `_export_onnx`. Both methods access `artifact.model_path`
directly. `_export_tflite` passes it to `tf.lite.TFLiteConverter.from_saved_model()`
which raises a TensorFlow-specific error if the path doesn't exist. The error
message from TF is not user-friendly.

THE BUG / RISK:
Missing model path produces a confusing TensorFlow or OS error instead of a
clear `FileNotFoundError` with the path.

EVIDENCE:
```python
def process(self, artifact) -> DeploymentArtifact:
    # No check that artifact.model_path exists
    if backend == "tflite":
        return self._export_tflite(artifact, out_path)
```

REPRODUCTION SCENARIO:
Pass a `ModelArtifact` with `model_path="/nonexistent/path"`. TF raises
`InvalidArgumentError` or similar.

IMPACT:
Confusing error message. No data loss.

FIX DIRECTION:
```python
if not artifact.model_path or not Path(artifact.model_path).exists():
    raise FileNotFoundError(
        f"EdgeOptimizerNode: model not found at '{artifact.model_path}'"
    )
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/edge_optimizer/nodes.py
FUNCTION:    EdgeOptimizerNode._export_tflite (INT8 branch)
CATEGORY:    Resource Leak
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Infer input shape by running a temporary converter.

WHAT IT ACTUALLY DOES:
Creates a temporary TFLite interpreter `_interp` to infer input shape, but
never calls `del _interp` or releases it. TFLite interpreters hold native
memory. In a long-running pipeline, this leaks a TFLite interpreter object
per INT8 conversion where `X_train_repr.npy` is absent.

EVIDENCE:
```python
_dummy_tflite = converter_tmp.convert()
_interp = tf.lite.Interpreter(model_content=_dummy_tflite)
_interp.allocate_tensors()
_inp_shape = _interp.get_input_details()[0]["shape"]
# _interp never deleted
```

REPRODUCTION SCENARIO:
Run INT8 conversion without `X_train_repr.npy` in a loop. Each iteration leaks
a TFLite interpreter.

IMPACT:
Memory leak in repeated-conversion scenarios.

FIX DIRECTION:
```python
try:
    _interp = tf.lite.Interpreter(model_content=_dummy_tflite)
    _interp.allocate_tensors()
    _inp_shape = _interp.get_input_details()[0]["shape"]
finally:
    del _interp
```
--------------------------------------------------------------------

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 2 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | UNSAFE |
| Test Hostile | NO |
| Top Risk | INT8 calibration silently uses all-zeros data with wrong shape when X_train_repr.npy is absent — produces a deployed model with incorrect quantization parameters |
