# app/core/tf_runtime.py
"""
Bounded Context:  BC6 — Observability & Storage / runtime helpers
Responsibility:   Apply TensorFlow stability defaults before TF is imported by
                  plugins (Trainer / ModelBuilder / EdgeOptimizer), and enable
                  GPU memory growth so Graphyn can share a GPU with other apps.
Owns:             configure_tf_stable_defaults(), configure_tf_gpu_sharing(),
                  select_keras_device()
Public Surface:   configure_tf_stable_defaults, configure_tf_gpu_sharing,
                  select_keras_device
Must NOT:         Kill or reset other GPU processes; must not import tensorflow
                  inside configure_tf_stable_defaults (env-only); must not
                  preallocate all VRAM or hide GPUs unless GRAPHYN_TF_DEVICE=cpu.
Dependencies:     os, logging, subprocess (nvidia-smi, best-effort)
Reason To Change: New TF/XLA GPU autotune failure modes, or sharing policy changes.

Device env (see select_keras_device):
  GRAPHYN_TF_DEVICE=auto|cpu|gpu
      auto (default): use GPU only if visible, compute-capable, and free VRAM
      meets GRAPHYN_TF_GPU_MIN_FREE_MIB. cpu: force CPU and set
      CUDA_VISIBLE_DEVICES=-1. gpu: prefer GPU but still refuse when free VRAM
      is below the minimum (does not evict other apps).
  GRAPHYN_TF_FORCE_GPU=1
      Attempt Keras on compute capability >= 12 (otherwise CPU). Does not
      bypass the free-VRAM gate.
  GRAPHYN_TF_GPU_MIN_FREE_MIB (default 4096)
      Best-effort nvidia-smi free-memory floor. Below this, Keras stays on
      /CPU:0 so other processes (e.g. FaceRecognition) keep their VRAM.
  GRAPHYN_TF_GPU_MAX_MIB (optional)
      Soft cap via set_logical_device_configuration. Skipped when memory
      growth is already enabled (growth wins; never full-card prealloc).
"""
from __future__ import annotations

import logging
import os
import subprocess

log = logging.getLogger(__name__)

_configured = False
_gpu_sharing_configured = False
_memory_growth_enabled = False

# TF wheels in this repo do not ship CUDA kernels for Blackwell (CC 12.x);
# PTX JIT / libdevice fails. Prefer CPU for Keras unless explicitly forced.
_MIN_UNSUPPORTED_COMPUTE_MAJOR = 12
_DEFAULT_MIN_FREE_MIB = 4096
_NVIDIA_SMI_TIMEOUT_S = 2.0


def configure_tf_stable_defaults() -> None:
    """Set env defaults before ``import tensorflow``.

    - Disables fragile XLA / Triton GEMM autotune (common crash on consumer GPUs).
    - Enables GPU memory growth so TF does not grab all VRAM (coexists with
      other apps already using the GPU).
    - Does **not** hide GPUs unless ``GRAPHYN_TF_DEVICE=cpu``.
      Never sets ``CUDA_VISIBLE_DEVICES=-1`` for auto/gpu.

    Safe to call multiple times.
    """
    global _configured
    if _configured:
        return
    _configured = True

    # Avoid Triton GEMM autotuner failures (DEVICE_TYPE_INVALID / no HLO configs).
    os.environ.setdefault("TF_XLA_FLAGS", "--tf_xla_auto_jit=0")
    os.environ.setdefault("XLA_FLAGS", "--xla_gpu_enable_triton_gemm=false")
    # Grow VRAM on demand — do not reserve the whole card (share with other apps).
    os.environ.setdefault("TF_FORCE_GPU_ALLOW_GROWTH", "true")

    device = os.environ.get("GRAPHYN_TF_DEVICE", "auto").strip().lower() or "auto"
    if device == "cpu":
        os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
        log.info("GRAPHYN_TF_DEVICE=cpu — TensorFlow will not see GPUs")
    elif device == "gpu":
        log.info(
            "GRAPHYN_TF_DEVICE=gpu — TensorFlow may use CUDA GPUs "
            "(memory growth on; still gated by GRAPHYN_TF_GPU_MIN_FREE_MIB)"
        )
    else:
        log.info(
            "GRAPHYN_TF_DEVICE=%s — GPU allowed with memory growth when spare "
            "VRAM >= GRAPHYN_TF_GPU_MIN_FREE_MIB (default %d). "
            "Set GRAPHYN_TF_DEVICE=cpu to force CPU.",
            device,
            _DEFAULT_MIN_FREE_MIB,
        )


def _min_free_vram_mib() -> int:
    raw = os.environ.get("GRAPHYN_TF_GPU_MIN_FREE_MIB", "").strip()
    if not raw:
        return _DEFAULT_MIN_FREE_MIB
    try:
        return max(0, int(raw))
    except ValueError:
        log.warning(
            "Invalid GRAPHYN_TF_GPU_MIN_FREE_MIB=%r; using %d",
            raw,
            _DEFAULT_MIN_FREE_MIB,
        )
        return _DEFAULT_MIN_FREE_MIB


def _free_vram_mib() -> int | None:
    """Best-effort free VRAM (MiB) of GPU 0 via nvidia-smi. None if unavailable."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=_NVIDIA_SMI_TIMEOUT_S,
            check=False,
        )
    except Exception as exc:
        log.debug("nvidia-smi free-memory query failed: %s", exc)
        return None
    if result.returncode != 0:
        log.debug(
            "nvidia-smi exited %s: %s",
            result.returncode,
            (result.stderr or result.stdout or "").strip()[:200],
        )
        return None
    lines = [ln.strip() for ln in (result.stdout or "").splitlines() if ln.strip()]
    if not lines:
        return None
    try:
        return int(float(lines[0]))
    except ValueError:
        log.debug("nvidia-smi unparsable free memory: %r", lines[0])
        return None


def _maybe_cap_gpu_memory(tf, gpus) -> None:
    """Optional GRAPHYN_TF_GPU_MAX_MIB logical-device cap.

    TensorFlow cannot combine this with memory_growth on the same device.
    If growth is already locking the GPU, skip the cap (prefer growth).
    """
    raw = os.environ.get("GRAPHYN_TF_GPU_MAX_MIB", "").strip()
    if not raw:
        return
    try:
        limit = int(raw)
    except ValueError:
        log.warning("Invalid GRAPHYN_TF_GPU_MAX_MIB=%r; ignoring", raw)
        return
    if limit <= 0:
        return
    if _memory_growth_enabled:
        log.info(
            "GRAPHYN_TF_GPU_MAX_MIB=%s ignored: memory_growth already enabled "
            "(prefer growth over a hard cap that can conflict / prealloc)",
            limit,
        )
        return
    try:
        tf.config.set_logical_device_configuration(
            gpus[0],
            [tf.config.LogicalDeviceConfiguration(memory_limit=limit)],
        )
        log.info("TensorFlow GPU logical memory cap: %d MiB", limit)
    except Exception as exc:
        log.info(
            "GRAPHYN_TF_GPU_MAX_MIB not applied (prefer memory_growth / CPU fallback): %s",
            exc,
        )


def configure_tf_gpu_sharing() -> None:
    """Enable per-GPU memory growth after TensorFlow is importable.

    Does not stop or reset other GPU processes. TF allocates only what it needs.
    Never sets allow_growth=false or full VRAM preallocation.
    """
    global _gpu_sharing_configured, _memory_growth_enabled
    if _gpu_sharing_configured:
        return

    configure_tf_stable_defaults()
    if os.environ.get("CUDA_VISIBLE_DEVICES", "").strip() == "-1":
        _gpu_sharing_configured = True
        return

    try:
        import tensorflow as tf  # type: ignore
    except ImportError:
        return

    try:
        gpus = tf.config.list_physical_devices("GPU")
        growth_ok = False
        for gpu in gpus:
            try:
                tf.config.experimental.set_memory_growth(gpu, True)
                growth_ok = True
            except Exception as exc:
                log.debug("memory_growth unavailable for %s: %s", gpu, exc)
        _memory_growth_enabled = growth_ok
        if gpus:
            log.info(
                "TensorFlow GPU sharing: memory_growth enabled on %d device(s)",
                len(gpus),
            )
            _maybe_cap_gpu_memory(tf, gpus)
        _gpu_sharing_configured = True
    except Exception as exc:
        log.warning("configure_tf_gpu_sharing failed: %s", exc)


def _gpu_compute_capability(tf, gpu) -> tuple[int, int] | None:
    try:
        details = tf.config.experimental.get_device_details(gpu) or {}
        cc = details.get("compute_capability")
        if isinstance(cc, (list, tuple)) and len(cc) >= 2:
            return int(cc[0]), int(cc[1])
    except Exception:
        return None
    return None


def _force_gpu() -> bool:
    return os.environ.get("GRAPHYN_TF_FORCE_GPU", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def select_keras_device(prefer: str = "auto") -> str:
    """Pick ``/GPU:0`` or ``/CPU:0`` for Keras build/fit.

    ``prefer``: ``auto`` | ``cpu`` | ``gpu`` (also honors ``GRAPHYN_TF_DEVICE``).

    GPUs with compute capability >= 12 (e.g. RTX 5070 Ti) are treated as
    unusable for Keras training unless ``GRAPHYN_TF_FORCE_GPU=1`` — current
    TensorFlow wheels lack matching CUDA kernels / libdevice.

    After listing GPUs, free VRAM is queried (nvidia-smi, 2s timeout). If
    free MiB is below ``GRAPHYN_TF_GPU_MIN_FREE_MIB`` (default 4096), returns
    ``/CPU:0`` without hiding the device or touching other processes.
    """
    configure_tf_stable_defaults()
    configure_tf_gpu_sharing()

    want = (prefer or "auto").strip().lower()
    env_dev = os.environ.get("GRAPHYN_TF_DEVICE", "").strip().lower()
    if want == "auto" and env_dev in ("cpu", "gpu"):
        want = env_dev
    if want == "auto" and os.environ.get("CUDA_VISIBLE_DEVICES", "").strip() == "-1":
        want = "cpu"
    if want == "cpu":
        return "/CPU:0"

    try:
        import tensorflow as tf  # type: ignore
    except ImportError:
        return "/CPU:0"

    gpus = tf.config.list_physical_devices("GPU")
    if not gpus:
        if want == "gpu":
            log.warning("select_keras_device: device=gpu but no GPU visible; using CPU")
        return "/CPU:0"

    force = _force_gpu()
    cc = _gpu_compute_capability(tf, gpus[0])
    if cc and cc[0] >= _MIN_UNSUPPORTED_COMPUTE_MAJOR and not force:
        log.warning(
            "select_keras_device: GPU %s compute capability %s.%s is not supported "
            "by this TensorFlow build (Keras training would fail). Using CPU. "
            "Set GRAPHYN_TF_FORCE_GPU=1 to attempt GPU anyway.",
            getattr(gpus[0], "name", gpus[0]),
            cc[0],
            cc[1],
        )
        return "/CPU:0"

    min_free = _min_free_vram_mib()
    free = _free_vram_mib()
    if free is not None and free < min_free:
        log.info(
            "select_keras_device: GPU free VRAM %s MiB < GRAPHYN_TF_GPU_MIN_FREE_MIB=%s; "
            "using /CPU:0 so other apps keep their allocation",
            free,
            min_free,
        )
        return "/CPU:0"

    return "/GPU:0"
