# app/core/plugins/wave1_runtime.py
"""
Bounded Context:  BC3 — Wave-1 deep runtime helpers (YOLO / TFLM / RAG)
Responsibility:   Resolve capability-shared Wave-1 venvs, install hints, and
                  optional-dep probes so Proposed pack nodes can leave stub
                  mode when heavy deps are present.
Owns:             resolve_wave1_venv, wave1_python, probe_import, install_hint
Public Surface:   same + WAVE1_CAPABILITIES
Must NOT:         Import from app.domain or app.api.
Dependencies:     stdlib
Reason To Change: New Wave-1 capability packs or env-var layout.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

# Capability → env var for an explicit venv root (contains bin/python).
WAVE1_CAPABILITIES: dict[str, str] = {
    "vision": "GRAPHYN_WAVE1_VENV_VISION",
    "tinyml": "GRAPHYN_WAVE1_VENV_TINYML",
    "rag": "GRAPHYN_WAVE1_VENV_RAG",
}

# Plugin slug → capability (used by install script + docs).
WAVE1_PLUGIN_CAPABILITY: dict[str, str] = {
    "yolo-train": "vision",
    "yolo-predict": "vision",
    "yolo-val": "vision",
    "yolo-export": "vision",
    "yolo-track": "vision",
    "yolo-resume-train": "vision",
    "yolo-hyperparam-search": "vision",
    "yolo-task-detect": "vision",
    "yolo-task-segment": "vision",
    "yolo-task-pose": "vision",
    "yolo-task-obb-classify": "vision",
    "tflm-quantize": "tinyml",
    "tflm-convert": "tinyml",
    "tflm-host-sim": "tinyml",
    "tflm-op-support-check": "tinyml",
    "tinyml-ptq-calib-builder": "tinyml",
    "vector-store-write": "rag",
    "vector-store-query": "rag",
    "text-embed": "rag",
    "chunk-semantic": "rag",
    "multimodal-caption-embed": "rag",
}

_INSTALL_SCRIPT = "scripts/install_wave1_plugin_venvs.sh"


def wave1_venvs_root() -> Path:
    """Root for capability venvs (wave1-vision, wave1-tinyml, wave1-rag)."""
    override = os.environ.get("GRAPHYN_WAVE1_VENVS_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    override = os.environ.get("GRAPHYN_PLUGIN_VENVS_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    try:
        from app.core.config import plugin_venvs_dir

        return plugin_venvs_dir()
    except Exception:
        home = os.environ.get("GRAPHYN_HOME", "").strip()
        if home:
            return Path(home).expanduser().resolve() / "plugins" / "venvs"
        return Path.cwd() / ".graphyn" / "plugins" / "venvs"


def resolve_wave1_venv(capability: str) -> Path | None:
    """Return the venv root for *capability* when it has a usable Python."""
    cap = (capability or "").strip().lower()
    env_key = WAVE1_CAPABILITIES.get(cap)
    if env_key:
        raw = os.environ.get(env_key, "").strip()
        if raw:
            root = Path(raw).expanduser().resolve()
            if _python_bin(root).is_file():
                return root
    root = wave1_venvs_root() / f"wave1-{cap}"
    if _python_bin(root).is_file():
        return root
    return None


def _python_bin(venv_root: Path) -> Path:
    if os.name == "nt":
        return venv_root / "Scripts" / "python.exe"
    return venv_root / "bin" / "python"


def wave1_python(capability: str) -> Path | None:
    root = resolve_wave1_venv(capability)
    return _python_bin(root) if root is not None else None


def probe_import(*module_names: str) -> bool:
    """True when every named module can be found by the current interpreter."""
    for name in module_names:
        if importlib.util.find_spec(name) is None:
            return False
    return True


def install_hint(capability: str, packages: list[str] | None = None) -> str:
    pkgs = ", ".join(packages or [])
    env_key = WAVE1_CAPABILITIES.get(capability, f"GRAPHYN_WAVE1_VENV_{capability.upper()}")
    extra = f" Required packages: {pkgs}." if pkgs else ""
    return (
        f"Wave-1 {capability} runtime missing.{extra} "
        f"Run {_INSTALL_SCRIPT} (creates wave1-{capability} venv), "
        f"or set {env_key} to a venv with those packages, "
        f"then set config.stub=False. "
        f"Alternatively: Plugins → Install optional (venv) for the plugin."
    )


def want_real_backend(stub_flag: bool, *module_names: str) -> tuple[bool, str | None]:
    """Decide stub vs real.

    Returns ``(use_real, error_or_None)``.
    - stub_flag True → always stub (use_real=False).
    - stub_flag False + imports ok → use_real=True.
    - stub_flag False + imports missing → use_real=False with install hint error.
    """
    if stub_flag:
        return False, None
    if probe_import(*module_names):
        return True, None
    return False, "missing"


def force_cpu_torch_env() -> None:
    """Prefer CPU when FaceRecognition (or other jobs) own the GPU."""
    contested = os.environ.get("GRAPHYN_WAVE1_FORCE_CPU", "1").strip().lower()
    if contested in ("0", "false", "no"):
        return
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
    os.environ.setdefault("ULTRALYTICS_OFFLINE", "1")
