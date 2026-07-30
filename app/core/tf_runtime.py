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
                  inside configure_tf_stable_defaults (env-only).
Dependencies:     os, logging
Reason To Change: New TF/XLA GPU autotune failure modes, or sharing policy changes.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_configured = False
_gpu_sharing_configured = False

# TF wheels in this repo do not ship CUDA kernels for Blackwell (CC 12.x);
# PTX JIT / libdevice fails. Prefer CPU for Keras unless explicitly forced.
_MIN_UNSUPPORTED_COMPUTE_MAJOR = 12


def configure_tf_stable_defaults() -> None:
    """Set env defaults before ``import tensorflow``.

    - Disables fragile XLA / Triton GEMM autotune (common crash on consumer GPUs).
    - Enables GPU memory growth so TF does not grab all VRAM (coexists with
      other apps already using the GPU).
    - Does **not** hide GPUs unless ``GRAPHYN_TF_DEVICE=cpu``.

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

    device = os.environ.get("GRAPHYN_TF_DEVICE", "").strip().lower()
    if device == "cpu":
        os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
        log.info("GRAPHYN_TF_DEVICE=cpu — TensorFlow will not see GPUs")
    elif device == "gpu":
        log.info("GRAPHYN_TF_DEVICE=gpu — TensorFlow may use CUDA GPUs (memory growth on)")
    else:
        log.info(
            "TensorFlow GPU allowed by default (memory growth). "
            "Set GRAPHYN_TF_DEVICE=cpu to force CPU."
        )


def configure_tf_gpu_sharing() -> None:
    """Enable per-GPU memory growth after TensorFlow is importable.

    Does not stop or reset other GPU processes. TF allocates only what it needs.
    """
    global _gpu_sharing_configured
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
        for gpu in gpus:
            try:
                tf.config.experimental.set_memory_growth(gpu, True)
            except Exception as exc:
                log.debug("memory_growth unavailable for %s: %s", gpu, exc)
        if gpus:
            log.info(
                "TensorFlow GPU sharing: memory_growth enabled on %d device(s)",
                len(gpus),
            )
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


def select_keras_device(prefer: str = "auto") -> str:
    """Pick ``/GPU:0`` or ``/CPU:0`` for Keras build/fit.

    ``prefer``: ``auto`` | ``cpu`` | ``gpu`` (also honors ``GRAPHYN_TF_DEVICE``).

    GPUs with compute capability >= 12 (e.g. RTX 5070 Ti) are treated as
    unusable for Keras training unless ``GRAPHYN_TF_FORCE_GPU=1`` — current
    TensorFlow wheels lack matching CUDA kernels / libdevice.
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

    force = os.environ.get("GRAPHYN_TF_FORCE_GPU", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
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

    return "/GPU:0"
