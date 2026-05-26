# Functional Review — PluginPackage/Common/deployment_packager/nodes.py

**Group:** 16 — Common Plugins  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Common/deployment_packager/nodes.py
FUNCTION:    DeploymentPackagerNode._package_mcu
CATEGORY:    Performance
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Format model as C byte array" for MCU deployment.

WHAT IT ACTUALLY DOES:
Builds the hex string with:
```python
hex_vals = ", ".join(f"0x{b:02x}" for b in model_bytes)
```
This is O(N) string concatenation via `join`, which is fine. However, for a
typical TFLite model (1–10 MB), this produces a C header with 1–10 million
comma-separated hex values in a single line. Writing this to a `.h` file with
`header_path.write_text(header)` builds the entire string in memory first.
For a 10 MB model, the hex string alone is ~50 MB in memory.

THE BUG / RISK:
OOM risk for large models. The entire hex representation is built in RAM before
writing. On constrained CI/CD environments or edge build machines, this can
cause the process to be killed.

EVIDENCE:
```python
hex_vals = ", ".join(f"0x{b:02x}" for b in model_bytes)  # ~5 bytes per byte → 50MB for 10MB model
header = f"...\nstatic const uint8_t g_model_data[] = {{{hex_vals}}};\n..."
header_path.write_text(header)  # entire string in memory
```

REPRODUCTION SCENARIO:
Pass a 10 MB TFLite model to `_package_mcu`. Memory usage spikes ~50 MB for
the hex string alone, plus the full header string.

IMPACT:
OOM on memory-constrained systems. No data loss, but process may be killed.

FIX DIRECTION:
Write the header incrementally using a file handle:
```python
with open(header_path, "w") as f:
    f.write("/* Auto-generated MCU deployment header */\n#pragma once\n...")
    f.write(f"static const uint8_t g_model_data[] = {{")
    for i, b in enumerate(model_bytes):
        f.write(f"0x{b:02x}")
        if i < len(model_bytes) - 1:
            f.write(", ")
    f.write("};\n")
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/deployment_packager/nodes.py
FUNCTION:    DeploymentPackagerNode.process
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Bundle optimized models into deployment-ready packages."

WHAT IT ACTUALLY DOES:
Does not validate `target` before dispatching. The `else: raise ValueError`
branch is correct, but `artifact.artifact_path` is used as `Path(artifact.artifact_path)`
without checking if it is None or an empty string. If `artifact.artifact_path` is
None (e.g., a freshly constructed DeploymentArtifact with no model yet), then
`model_path = Path(None)` raises `TypeError: argument should be str, bytes or
os.PathLike, not NoneType`.

THE BUG / RISK:
`Path(None)` raises `TypeError` before reaching the target-specific packager.
The error message does not indicate that `artifact_path` is missing.

EVIDENCE:
```python
model_path = Path(artifact.artifact_path) if artifact.artifact_path else None
```
Wait — this IS guarded with `if artifact.artifact_path else None`. So `model_path`
will be `None` when `artifact_path` is falsy. The packagers then check
`if model_path and model_path.exists()` before using it. This is actually safe.

However, `artifact.labels` is accessed as `artifact.labels or []`. If `labels`
is not an attribute of the artifact (e.g., a custom object), this raises
`AttributeError`. The port type is `DeploymentArtifact` but the runtime type
check is not enforced.

THE BUG / RISK (revised):
If a non-DeploymentArtifact object is passed (port type is not enforced at
runtime), `artifact.labels` raises `AttributeError`.

EVIDENCE:
```python
labels = artifact.labels or []   # AttributeError if artifact has no .labels
```

REPRODUCTION SCENARIO:
Pass a `ModelArtifact` (which has `.labels`) — this works. Pass a plain dict —
`AttributeError: 'dict' object has no attribute 'labels'`.

IMPACT:
Crash with confusing error if wrong artifact type is passed.

FIX DIRECTION:
```python
labels = getattr(artifact, "labels", None) or []
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/deployment_packager/nodes.py
FUNCTION:    DeploymentPackagerNode._package_docker
CATEGORY:    Resource Leak
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Create TAR of the docker context" and clean up the staging directory.

WHAT IT ACTUALLY DOES:
Uses a `try/finally` block to clean up `pkg_dir`. However, if `tarfile.open`
itself raises (e.g., disk full before the TAR is created), the `finally` block
still runs `shutil.rmtree(pkg_dir, ignore_errors=True)`, which is correct.
But the TAR file at `tar_path` may be partially written and left on disk.

THE BUG / RISK:
A partially-written TAR file is left at `tar_path` if the TAR creation fails
mid-write. Subsequent calls with the same `name` will overwrite it, but if the
caller checks for the file's existence before calling, it may find a corrupt file.

EVIDENCE:
```python
tar_path = out_dir / f"{name}_docker.tar.gz"
with tarfile.open(tar_path, "w:gz") as tf:
    tf.add(pkg_dir, arcname=name)   # may fail mid-write
# finally: shutil.rmtree(pkg_dir) — staging dir cleaned, but tar_path may be partial
```

REPRODUCTION SCENARIO:
Fill disk mid-TAR write. `tar_path` exists but is corrupt.

IMPACT:
Corrupt output file left on disk. Low severity as it would be overwritten on retry.

FIX DIRECTION:
Write to a temp path and rename atomically on success:
```python
import tempfile, os
tmp = tar_path.with_suffix(".tmp.tar.gz")
try:
    with tarfile.open(tmp, "w:gz") as tf:
        tf.add(pkg_dir, arcname=name)
    os.replace(tmp, tar_path)
finally:
    tmp.unlink(missing_ok=True)
    shutil.rmtree(pkg_dir, ignore_errors=True)
```
--------------------------------------------------------------------

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 0 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | UNSAFE |
| Test Hostile | NO |
| Top Risk | MCU packager builds entire hex representation of model in RAM — OOM risk for models > 5 MB |
