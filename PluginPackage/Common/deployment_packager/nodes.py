"""DeploymentPackagerNode — bundle optimized models into deployment-ready packages.

Targets:
    edge    — TAR.GZ: model + labels + preprocessing.json + run_inference.py
              (real WAV → features → model) + README + provenance + self-test
    docker  — TAR.GZ docker context: the edge bundle + Dockerfile (serve.py)
    mobile  — ZIP: the edge bundle + Android snippet
    mcu     — C header file with model as byte array + labels array

Every bundle (edge / docker / mobile) is *runnable on real audio*:

* ``preprocessing.json`` — the exact Feature Frontend + Dataset Builder
  configuration of the **source training run** (resolved from its graph
  snapshot ``runs/<source>/graph.json``), the model's input/output tensor
  shape / dtype / quantization and the label order.
* ``run_inference.py`` — loads audio like dataset_ingest, extracts features
  with the same librosa calls as feature_frontend, pads/crops like
  dataset_builder, quantizes for integer models, prints top-k (``--json``).
* ``provenance.json`` — source run + record hash, registered model, model and
  dataset hashes, graphyn version, build time, package run id and the sha256
  of every file; ``SHA256SUMS`` for ``sha256sum -c``.
* ``selftest.json`` — the packager runs the shipped script on real clips of
  the source dataset and checks feature parity against the platform's own
  Feature Frontend and the model input shape.

A sidecar ``<package>.manifest.json`` next to the archive lists contents,
checksums, the self-test summary and "how to run" commands for the console.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.deployment_artifact import DeploymentArtifact

log = logging.getLogger(__name__)

PACKAGER_VERSION = "1.1.1"
_BUNDLE_DIR = Path(__file__).resolve().parent / "bundle"
_RUN_ID_IN_PATH = re.compile(r"(?:^|/)runs/([0-9a-f]{32})(?:/|$)")
_AUDIO_SUFFIXES = (".wav", ".flac", ".ogg", ".mp3", ".m4a", ".aiff", ".aif")
_PARITY_TOL = 1e-4

# Feature Frontend defaults (used only when the snapshot omits a key and the
# feature_frontend node class is not registered to fill them in).
_FEATURE_DEFAULTS: dict[str, Any] = {
    "feature_type": "log_mel",
    "sample_rate": 16000,
    "fixed_length": 0,
    "n_fft": 512,
    "hop_length": 160,
    "win_length": 400,
    "n_mels": 80,
    "n_mfcc": 13,
    "fmin": 0.0,
    "fmax": None,
    "log_scale": True,
    "normalize": True,
    "center": True,
    "delta": False,
    "delta_delta": False,
}

# ── inference snippet templates ───────────────────────────────────────────────

_ANDROID_SNIPPET = """\
// Android TFLite inference snippet
// Features: compute exactly as described in preprocessing.json (same as
// run_inference.py: MFCC/log-mel params, per-utterance z-score, pad/crop to
// frames.fixed_length), then quantize with input.quantization when the model
// input is uint8/int8.
import org.tensorflow.lite.Interpreter;
import java.nio.ByteBuffer;

Interpreter tflite = new Interpreter(loadModelFile(context, "model.tflite"));
float[][] output = new float[1][NUM_CLASSES];
tflite.run(inputBuffer, output);
"""

_DOCKERFILE = """\
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 \\
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-serve.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-serve.txt
COPY . .
EXPOSE 8080
# Containers must bind 0.0.0.0 so published ports work; local serve.py docs use 127.0.0.1.
CMD ["uvicorn", "serve:app", "--host", "0.0.0.0", "--port", "8080"]
"""

_REQUIREMENTS_SERVE = """\
# Optional HTTP endpoint (serve.py) — not needed for run_inference.py
fastapi>=0.100
uvicorn>=0.23
"""

# File roles shown in the console / manifest (in display order).
_ROLES: dict[str, str] = {
    "model.tflite": "model",
    "model.onnx": "model",
    "labels.txt": "labels",
    "preprocessing.json": "preprocessing",
    "run_inference.py": "inference script",
    "serve.py": "http endpoint (optional)",
    "requirements.txt": "requirements",
    "requirements-serve.txt": "requirements (serve)",
    "README.md": "readme",
    "metadata.json": "metadata",
    "selftest.json": "self-test",
    "provenance.json": "provenance",
    "SHA256SUMS": "checksums",
    "Dockerfile": "dockerfile",
    "inference_android.java": "android snippet",
}


# ── small helpers ─────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=False, default=str) + "\n", encoding="utf-8")


def _source_model_metrics(source_run_id: str | None, src_meta: dict[str, Any], artifact: Any) -> dict[str, Any]:
    """Metrics of the source-run path that trained the shipped model.

    ``meta.metrics`` is the FIRST path's metrics.json (Path A); a multi-path run
    must report the path whose trainer produced ``source_model_path``
    (``…/<trainer_node>/model.keras``). Falls back to the best path, then to
    ``meta.metrics``.
    """
    fallback = src_meta.get("metrics") if isinstance(src_meta.get("metrics"), dict) else {}
    root = _runs_root()
    if not source_run_id or root is None:
        return dict(fallback)
    try:
        from app.core.runs.run_summary import headline_metrics, run_summary_fields

        summary = run_summary_fields(source_run_id, root / source_run_id, src_meta,
                                     include_regression=False).get("summary") or {}
    except Exception:
        return dict(fallback)
    meta = getattr(artifact, "metadata", None) or {}
    src_path = str(meta.get("source_model_path") or meta.get("source") or "")
    segments = set(Path(src_path).parts) if src_path else set()
    for p in summary.get("paths") or []:
        if isinstance(p, dict) and p.get("metrics") and segments & set(p.get("node_ids") or []):
            return dict(p["metrics"])
    head = headline_metrics(summary)
    if head and isinstance(head.get("metrics"), dict):
        return dict(head["metrics"])
    return dict(fallback)


def _runs_root() -> Path | None:
    try:
        from app.core.config import runs_dir

        return Path(runs_dir())
    except Exception:
        return None


def _workspace_path(raw: Any) -> Path | None:
    """``workspace/...`` / relative / absolute string → filesystem Path."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        from app.core.runs.run_summary import resolve_workspace_path

        p = resolve_workspace_path(raw)
        if p is not None and p.exists():
            return p
    except Exception:
        pass
    p = Path(raw)
    return p if p.exists() else None


def _lib_version(name: str) -> str | None:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:
        return None


def _graphyn_version() -> str | None:
    v = _lib_version("graphyn-sdk")
    if v:
        return v
    try:
        import app

        return str(getattr(app, "__version__", "") or "") or None
    except Exception:
        return None


# ── source run resolution ─────────────────────────────────────────────────────

def resolve_source_context(
    *,
    artifact: DeploymentArtifact | None,
    own_run_id: str = "",
    explicit_source_run_id: str = "",
    runs_root: Path | None = None,
) -> dict[str, Any]:
    """Find the training run whose model is being packaged + its records.

    Order: explicit config ``source_run_id`` → the package run's declared
    ``source_run_id`` (meta.json, set by the Ship wizard) → a ``runs/<id>/``
    segment in the optimizer's source model path / the model path itself.
    """
    root = runs_root or _runs_root()
    own_meta = _read_json(root / own_run_id / "meta.json") if (root and own_run_id) else {}
    src = (explicit_source_run_id or "").strip()
    how = "config" if src else ""
    if not src and isinstance(own_meta.get("source_run_id"), str):
        src = own_meta["source_run_id"].strip()
        how = "package_run_meta" if src else ""
    if not src and artifact is not None:
        meta = artifact.metadata or {}
        for cand in (meta.get("source_model_path"), meta.get("source"), artifact.artifact_path):
            m = _RUN_ID_IN_PATH.search(str(cand or "").replace("\\", "/"))
            if m:
                src, how = m.group(1), "model_path"
                break
    src_dir = (root / src) if (root and src) else None
    graph = _read_json(src_dir / "graph.json") if src_dir else {}
    prove = _read_json(src_dir / "prove.json") if src_dir else {}
    src_meta = _read_json(src_dir / "meta.json") if src_dir else {}
    lineage_req = own_meta.get("lineage_request") if isinstance(own_meta.get("lineage_request"), dict) else {}
    return {
        "package_run_id": own_run_id or None,
        "package_run_meta": own_meta,
        "source_run_id": src or None,
        "resolved_from": how or None,
        "graph": graph,
        "prove": prove,
        "source_meta": src_meta,
        "lineage_request": lineage_req,
    }


def _upstream(graph: dict[str, Any], node_id: str) -> list[str]:
    """All ancestors of ``node_id`` (BFS over edges, nearest first)."""
    edges = graph.get("edges") or []
    seen: list[str] = []
    frontier = [node_id]
    while frontier:
        nxt = []
        for nid in frontier:
            for e in edges:
                if isinstance(e, dict) and e.get("dst_id") == nid:
                    s = e.get("src_id")
                    if s and s not in seen:
                        seen.append(s)
                        nxt.append(s)
        frontier = nxt
    return seen


def _full_feature_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Fill omitted Feature Frontend keys with the node's own defaults."""
    try:
        from app.core.nodes import registry

        cls = registry.get_class("feature_frontend")
        model = cls.Config.model_validate({k: v for k, v in cfg.items() if k in cls.Config.model_fields})
        full = model.model_dump()
        return {k: full.get(k) for k in _FEATURE_DEFAULTS} | {
            k: v for k, v in full.items() if k not in _FEATURE_DEFAULTS and k in cfg
        }
    except Exception:
        out = dict(_FEATURE_DEFAULTS)
        out.update({k: v for k, v in cfg.items() if k in _FEATURE_DEFAULTS})
        return out


def preprocessing_from_graph(graph: dict[str, Any]) -> dict[str, Any] | None:
    """Feature Frontend + Dataset Builder config of a training graph snapshot."""
    nodes = [n for n in (graph.get("nodes") or []) if isinstance(n, dict)]
    by_id = {n.get("id"): n for n in nodes}
    builder = next((n for n in nodes if n.get("node_type") == "dataset_builder"), None)
    frontend = None
    if builder is not None:
        for nid in _upstream(graph, str(builder.get("id"))):
            n = by_id.get(nid)
            if n and n.get("node_type") == "feature_frontend":
                frontend = n
                break
    if frontend is None:
        frontend = next((n for n in nodes if n.get("node_type") == "feature_frontend"), None)
    if frontend is None:
        return None
    ingest = None
    for nid in _upstream(graph, str(frontend.get("id"))):
        n = by_id.get(nid)
        if n and n.get("node_type") == "dataset_ingest":
            ingest = n
            break
    fcfg = _full_feature_config(dict(frontend.get("config") or {}))
    bcfg = dict((builder or {}).get("config") or {})
    fixed = int(bcfg.get("fixed_length") or 0)
    return {
        "feature_node_id": frontend.get("id"),
        "builder_node_id": (builder or {}).get("id"),
        "ingest_node_id": (ingest or {}).get("id"),
        "ingest_config": dict((ingest or {}).get("config") or {}),
        "features": fcfg,
        "frames": {
            "fixed_length": fixed,
            "fixed_length_source": "dataset_builder" if fixed else None,
            "pad": "zeros at the end of the time axis",
            "truncate": "keep the first fixed_length frames",
            "layout": "(T, F) time-major; model input adds batch + channel axes",
        },
    }


# ── tensor details ────────────────────────────────────────────────────────────

def _tflite_details_inprocess(model_path: Path) -> dict[str, Any] | None:
    """Model tensor details via an in-process TFLite runtime (when installed)."""
    for mod in ("ai_edge_litert.interpreter", "tflite_runtime.interpreter"):
        if importlib.util.find_spec(mod.split(".")[0]) is None:
            continue
        try:
            m = __import__(mod, fromlist=["Interpreter"])
            return _describe_interp(m.Interpreter(model_path=str(model_path)))
        except Exception:
            continue
    if importlib.util.find_spec("tensorflow") is None:
        return None
    try:
        import tensorflow as tf  # type: ignore

        return _describe_interp(tf.lite.Interpreter(model_path=str(model_path)))
    except Exception:
        return None


def _describe_interp(interp: Any) -> dict[str, Any]:
    import numpy as np

    interp.allocate_tensors()

    def one(d: dict[str, Any]) -> dict[str, Any]:
        scale, zero = d.get("quantization") or (0.0, 0)
        return {
            "name": d.get("name"),
            "shape": [int(x) for x in d.get("shape", [])],
            "dtype": np.dtype(d.get("dtype")).name,
            "quantization": {"scale": float(scale), "zero_point": int(zero)} if scale else None,
        }

    return {
        "inputs": [one(d) for d in interp.get_input_details()],
        "outputs": [one(d) for d in interp.get_output_details()],
    }


def _model_details(artifact: DeploymentArtifact, model_path: Path | None) -> dict[str, Any] | None:
    meta = artifact.metadata or {}
    td = meta.get("tensor_details")
    if isinstance(td, dict) and td.get("inputs"):
        return td
    if model_path and model_path.suffix.lower() == ".tflite" and model_path.is_file():
        return _tflite_details_inprocess(model_path)
    return None


# ── self-test ─────────────────────────────────────────────────────────────────

def _pick_sample_files(dataset_dir: Path, n: int) -> list[tuple[Path, str]]:
    """Up to ``n`` audio files with distinct parent-folder labels (prefer test/)."""
    if n <= 0 or not dataset_dir.is_dir():
        return []
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(dataset_dir):
        dirnames.sort()
        for fn in sorted(filenames):
            if fn.lower().endswith(_AUDIO_SUFFIXES):
                found.append(Path(dirpath) / fn)
        if len(found) >= 5000:
            break
    if not found:
        return []
    test = [p for p in found if "test" in {part.lower() for part in p.relative_to(dataset_dir).parts[:-1]}]
    pool = test or found
    picked: list[tuple[Path, str]] = []
    labels_seen: set[str] = set()
    for p in pool:
        lbl = p.parent.name
        if lbl in labels_seen:
            continue
        labels_seen.add(lbl)
        picked.append((p, lbl))
        if len(picked) >= n:
            break
    for p in pool:  # fewer labels than n → fill with more files
        if len(picked) >= n:
            break
        if all(p != q for q, _ in picked):
            picked.append((p, p.parent.name))
    return picked


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _reference_features(y, sr: int, label: str, path: Path, feature_cfg: dict[str, Any], fixed: int):
    """Features from the platform's own Feature Frontend node (+ builder pad)."""
    import numpy as np

    from app.core.nodes import registry
    from app.models.audio_sample import AudioSample

    cls = registry.get_class("feature_frontend")
    if getattr(cls, "_graphyn_isolated", False):
        raise RuntimeError("feature_frontend runs isolated — no in-process reference")
    node = cls(config=dict(feature_cfg), seed=0)
    out = node.process({"input": [AudioSample(path=str(path), sample_rate=int(sr), data=y, label=label, metadata={})]})
    arrs = out["output"] if isinstance(out, dict) else out
    arr = np.asarray(arrs[0].data, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr[:, np.newaxis]
    elif arr.ndim > 2:
        arr = arr.reshape(arr.shape[0], -1)
    if fixed > 0:
        t, f = arr.shape
        if t > fixed:
            arr = arr[:fixed, :]
        elif t < fixed:
            arr = np.concatenate([arr, np.zeros((fixed - t, f), dtype=np.float32)], axis=0)
    return arr


def _tflite_python() -> tuple[str | None, str]:
    """Python interpreter able to run TFLite (for the model step of the self-test)."""
    env = os.environ.get("GRAPHYN_PACKAGER_SELFTEST_PYTHON", "").strip()
    if env and Path(env).exists():
        return env, "GRAPHYN_PACKAGER_SELFTEST_PYTHON"
    for mod in ("ai_edge_litert", "tflite_runtime", "tensorflow"):
        if importlib.util.find_spec(mod) is not None:
            return sys.executable, "host python"
    try:
        from app.core.plugins.runtime_registry import get_runtime_registry

        spec = get_runtime_registry().get_for_node("edge_optimizer")
        if spec and spec.venv_python and Path(spec.venv_python).exists():
            return spec.venv_python, "edge_optimizer venv"
    except Exception:
        pass
    return None, "no TFLite runtime on this host"


def run_selftest(
    stage: Path,
    preprocessing: dict[str, Any],
    *,
    dataset_dir: Path | None,
    n_samples: int,
    model_file: str | None,
) -> dict[str, Any]:
    """Run the shipped ``run_inference.py`` on real clips; check parity + shape.

    Checks: ``preprocessing_parity`` (shipped feature code vs the platform's
    Feature Frontend on the same waveform, max |diff| ≤ 1e-4),
    ``input_shape`` (features vs the model's input tensor) and ``model_runs``
    (the shipped script runs the model on the features; predictions vs the
    clip's folder label are recorded, informational only).
    """
    import numpy as np

    result: dict[str, Any] = {"status": "skipped", "ran_at": _now(), "checks": [], "samples": [], "notes": []}

    def check(name: str, status: str, detail: str, **extra: Any) -> None:
        result["checks"].append({"name": name, "status": status, "detail": detail, **extra})

    if n_samples <= 0:
        result["notes"].append("self-test disabled (selftest_samples=0)")
        return result
    if not preprocessing.get("features"):
        result["notes"].append("source run feature configuration not found — nothing to verify")
        return result
    script = stage / "run_inference.py"
    if not script.is_file():
        result["notes"].append("run_inference.py not in the package")
        return result
    try:
        import librosa  # noqa: F401
    except Exception:
        result["notes"].append("librosa not installed on the packaging host — self-test skipped")
        return result
    samples = _pick_sample_files(dataset_dir, n_samples) if dataset_dir else []
    if not samples:
        result["notes"].append(
            "no source dataset audio reachable from this host"
            + (f" ({dataset_dir})" if dataset_dir else "")
            + " — checked shapes only"
        )

    mod = _load_module(script, f"_graphyn_pkg_run_inference_{os.getpid()}_{id(stage)}")
    fixed = int((preprocessing.get("frames") or {}).get("fixed_length") or 0)
    feats_by_file: list[tuple[Path, str, Any]] = []
    diffs: list[float] = []
    ref_error = None
    for path, label in samples:
        try:
            y, sr = mod.load_audio(path)
            feats = mod.extract_features(y, sr, preprocessing)
        except Exception as exc:
            check("preprocessing_parity", "failed", f"{path.name}: shipped preprocessing raised {exc!r}")
            continue
        feats_by_file.append((path, label, feats))
        row: dict[str, Any] = {
            "file": str(path.relative_to(dataset_dir)) if dataset_dir else path.name,
            "label": label,
            "feature_shape": list(feats.shape),
        }
        try:
            import librosa as _lr

            y_ref, sr_ref = _lr.load(str(path), sr=None, mono=True)
            ref = _reference_features(y_ref, int(sr_ref), label, path, preprocessing["features"], fixed)
            if ref.shape != feats.shape:
                row["max_abs_diff"] = None
                row["reference_shape"] = list(ref.shape)
                diffs.append(float("inf"))
            else:
                d = float(np.max(np.abs(ref - feats))) if feats.size else 0.0
                row["max_abs_diff"] = d
                diffs.append(d)
        except Exception as exc:
            ref_error = f"{type(exc).__name__}: {exc}"
        result["samples"].append(row)

    if diffs:
        worst = max(diffs)
        ok = worst <= _PARITY_TOL
        check(
            "preprocessing_parity",
            "passed" if ok else "failed",
            (f"shipped run_inference.py features match the platform Feature Frontend on {len(diffs)} clip(s) "
             f"(max |diff| {worst:.2e} ≤ {_PARITY_TOL:g})") if ok else
            f"shipped features differ from the platform Feature Frontend (max |diff| {worst:.3g} > {_PARITY_TOL:g})",
            max_abs_diff=None if worst == float("inf") else worst,
        )
    elif samples and ref_error:
        check("preprocessing_parity", "skipped", f"platform Feature Frontend unavailable ({ref_error})")

    # Model input shape (from tensor details) vs features.
    inp = (preprocessing.get("input") or {})
    shape = inp.get("shape") if isinstance(inp, dict) else None
    if feats_by_file and shape:
        fshape = list(feats_by_file[0][2].shape)
        expect = [int(x) for x in shape]
        core = [d for d in expect[1:] if d != 1] if len(expect) > 2 else expect
        ok = [d for d in fshape if d != 1] == core or int(np.prod(fshape)) == int(np.prod(expect[1:] or [1]))
        check("input_shape", "passed" if ok else "failed",
              f"features {fshape} → model input {expect}" if ok else
              f"features {fshape} do not fit model input {expect}")

    # Model step: the shipped script on the computed features.
    if model_file and model_file.endswith(".tflite") and (feats_by_file or not shape):
        py, py_src = _tflite_python()
        if py is None:
            check("model_runs", "skipped", py_src)
        else:
            with tempfile.TemporaryDirectory(prefix="pkg_selftest_") as td:
                npys = []
                for i, (_p, _l, feats) in enumerate(feats_by_file):
                    f = Path(td) / f"sample_{i}.npy"
                    np.save(f, feats)
                    npys.append(str(f))
                cmd = [py, str(script), "--describe", "--json", "--top-k", "3"]
                if npys:
                    cmd += ["--features", *npys]
                try:
                    proc = subprocess.run(
                        cmd, cwd=str(stage), capture_output=True, text=True, timeout=600,
                        env={**os.environ, "TF_CPP_MIN_LOG_LEVEL": "3", "PYTHONDONTWRITEBYTECODE": "1"},
                    )
                    out = proc.stdout
                    rep = json.loads(out[out.index("{"):]) if "{" in out else {}
                except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
                    rep = {}
                    proc = None
                    check("model_runs", "failed", f"run_inference.py did not complete: {exc!r}")
                if rep:
                    result["model"] = rep.get("model")
                    result["runtime"] = f"{rep.get('runtime')} ({py_src})"
                    errs = [r for r in rep.get("results", []) if "error" in r]
                    for row, r in zip(result["samples"], rep.get("results", [])):
                        if "top" in r:
                            row["predicted"] = r["top"][0]["label"]
                            row["probability"] = round(float(r["top"][0]["probability"]), 4)
                            row["top"] = r["top"]
                        else:
                            row["error"] = r.get("error")
                    if errs:
                        check("model_runs", "failed", f"run_inference.py failed on {len(errs)} clip(s): {errs[0].get('error')}")
                    elif npys:
                        agree = sum(1 for row in result["samples"] if row.get("predicted") == row.get("label"))
                        check("model_runs", "passed",
                              f"run_inference.py ran the model on {len(npys)} clip(s) with {result['runtime']}; "
                              f"{agree}/{len(npys)} top-1 match the folder label (informational)")
                    else:
                        check("model_runs", "passed", f"model loads with {result['runtime']}")
                elif proc is not None and not any(c["name"] == "model_runs" for c in result["checks"]):
                    tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
                    check("model_runs", "failed", "run_inference.py exited "
                          f"{proc.returncode}: {' / '.join(tail)[:400]}")

    statuses = [c["status"] for c in result["checks"]]
    if "failed" in statuses:
        result["status"] = "failed"
    elif "passed" in statuses:
        result["status"] = "passed" if "skipped" not in statuses else "partial"
    return result


# ── README ────────────────────────────────────────────────────────────────────

def _fmt_pct(v: Any) -> str:
    try:
        return f"{100.0 * float(v):.1f} %"
    except (TypeError, ValueError):
        return "—"


def render_readme(
    *,
    package_file: str,
    labels: list[str],
    preprocessing: dict[str, Any],
    provenance: dict[str, Any],
    selftest: dict[str, Any],
    metrics: dict[str, Any],
    target: str,
) -> str:
    fc = preprocessing.get("features") or {}
    frames = preprocessing.get("frames") or {}
    inp = preprocessing.get("input") or {}
    sr = int(fc.get("sample_rate") or 16000)
    fixed = int(frames.get("fixed_length") or 0)
    hop = int(fc.get("hop_length") or 160)
    dur = (fixed - 1) * hop / sr if fixed > 1 else None
    src = provenance.get("source_run") or {}
    reg = provenance.get("registered_model") or {}
    model = provenance.get("model") or {}
    ds = provenance.get("dataset") or []
    title = (reg.get("name") and f"{reg.get('name')}" + (f" ({reg.get('stage')})" if reg.get("stage") else "")) \
        or model.get("display_name") or (provenance.get("package") or {}).get("name") or "Model package"
    lines = [
        f"# {title}",
        "",
        f"Audio classifier exported by Graphyn ({model.get('format') or 'tflite'}, "
        f"{model.get('quantization') or 'float32'}). It maps a short audio clip to one of "
        f"{len(labels)} classes.",
        "",
        "## Labels (model output order)",
        "",
        "| index | label |",
        "|---|---|",
        *[f"| {i} | {lbl} |" for i, lbl in enumerate(labels)],
        "",
    ]
    if metrics:
        lines += ["## Metrics (source run evaluation)", ""]
        if "test_accuracy" in metrics:
            lines.append(f"- Test accuracy: **{_fmt_pct(metrics['test_accuracy'])}**")
        if "roc_auc" in metrics:
            lines.append(f"- ROC AUC: {float(metrics['roc_auc']):.3f}")
        lines += [
            "- Measured on the source run's held-out test split with the trained (pre-export) model; "
            "quantized exports can differ slightly.",
            "",
        ]
    lines += [
        "## How to run",
        "",
        "```bash",
        f"mkdir model && tar -xzf {package_file} -C model && cd model" if package_file.endswith(".tar.gz")
        else f"mkdir model && unzip {package_file} -d model && cd model",
        "sha256sum -c SHA256SUMS            # verify every file",
        "python -m venv .venv && . .venv/bin/activate",
        "pip install -r requirements.txt     # or: pip install numpy librosa tensorflow",
        "python run_inference.py clip.wav    # top-3 labels",
        "python run_inference.py a.wav b.wav --top-k 5 --json",
        "```",
        "",
        "Optional HTTP endpoint: `pip install -r requirements-serve.txt && uvicorn serve:app --port 8080`, "
        "then `curl --data-binary @clip.wav -H 'Content-Type: audio/wav' localhost:8080/predict`.",
        "",
        "## Input requirements",
        "",
        f"- Any WAV/FLAC/OGG file; it is mixed down to **mono** and resampled to **{sr} Hz** "
        "(librosa, same as training).",
    ]
    if fixed:
        lines.append(
            f"- The model sees **{fixed} frames** (hop {hop} samples ≈ {dur:.2f} s of audio); shorter clips are "
            "zero-padded at the end, longer ones are cut after the first frames — trim long recordings to the "
            "spoken word first."
        )
    lines += [
        f"- Features: `{fc.get('feature_type')}` — see `preprocessing.json` for every parameter "
        "(n_fft, hop/win length, mel bins, fmin/fmax, log scale, per-clip z-score normalisation).",
    ]
    if inp.get("shape"):
        q = inp.get("quantization") or {}
        lines.append(
            f"- Model input tensor `{inp.get('shape')}` `{inp.get('dtype')}`"
            + (f" (quantized: scale {q.get('scale')}, zero point {q.get('zero_point')} — "
               "run_inference.py applies it)" if q else "")
            + "."
        )
    lines += [
        "",
        "## Provenance",
        "",
        f"- Source training run: `{src.get('run_id') or 'unknown'}`"
        + (f" (record hash `{str(src.get('record_hash'))[:16]}…`)" if src.get("record_hash") else ""),
    ]
    if reg.get("name"):
        lines.append(
            f"- Registered model: `{reg.get('name')}`"
            + (f" · stage `{reg.get('stage')}`" if reg.get("stage") else "")
            + (f" · version `{reg.get('version')}`" if reg.get("version") else "")
        )
    if model.get("sha256"):
        lines.append(f"- Model sha256: `{model.get('sha256')}`")
    for d in ds:
        if d.get("content_hash"):
            lines.append(
                f"- Dataset `{d.get('path')}`: {d.get('file_count') or '?'} files, `{d.get('content_hash')}`"
            )
    pkg = provenance.get("package") or {}
    lines += [
        f"- Built {pkg.get('built_at')} by package run `{pkg.get('package_run_id') or '—'}` "
        f"(graphyn {pkg.get('graphyn_version') or '?'}, deployment_packager {pkg.get('packager_version')}).",
        "- Full details: `provenance.json` (sha256 of every file), `metadata.json`.",
        "",
        "## Self-test",
        "",
        f"Status: **{selftest.get('status')}** (see `selftest.json`).",
        "",
        *[f"- {c['name']}: {c['status']} — {c['detail']}" for c in selftest.get("checks", [])],
        *[f"- note: {n}" for n in selftest.get("notes", [])],
        "",
    ]
    if target == "docker":
        lines += ["## Docker", "", "```bash", "docker build -t audio-model . && docker run -p 8080:8080 audio-model",
                  "```", ""]
    return "\n".join(lines)


# ── node ──────────────────────────────────────────────────────────────────────

class DeploymentPackagerNode(Node):
    """Bundle optimized models into deployment-ready packages.

    Config:
        target (str): "mobile" | "mcu" | "docker" | "edge"
        output_path (str): directory for output packages
        include_inference_script (bool): include run_inference.py / serve.py
        include_metadata (bool): include metadata.json
        package_name (str): base name for the output file (auto-derived if empty)
        source_run_id (str): training run whose preprocessing to ship (empty = the
            package run's declared source run, else a runs/<id>/ path segment)
        selftest (str): "strict" (fail on parity/shape mismatch) | "warn" | "off"
        selftest_samples (int): real clips from the source dataset to verify on
    """

    node_type: ClassVar[str] = "deployment_packager"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="deployment_packager",
        label="Deployment Packager",
        description=(
            "Bundle optimized models into runnable deployment packages: model, "
            "preprocessing.json from the source training run, a real WAV inference "
            "script, README, provenance and a self-test."
        ),
        category="ML",
        version=PACKAGER_VERSION,
        tags=["ml", "deployment", "packaging", "tflite", "docker", "edge", "mcu"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=False,
        cacheable=False,
        streaming_support=False,
        realtime_support=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=DeploymentArtifact,
            cardinality="single",
            required=True,
            description="DeploymentArtifact from edge_optimizer",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=DeploymentArtifact,
            description="DeploymentArtifact with artifact_path pointing to the package",
        )
    }

    class Config(NodeConfig):
        target: Literal["mobile", "mcu", "docker", "edge", "cmsis_pack", "arduino", "zephyr", "pte_bundle"] = Field(default='mobile', title="Target", description="Deployment target. One of: mobile, mcu, docker, edge, cmsis_pack, arduino, zephyr, pte_bundle.")
        output_path: str = Field(default='workspace/artifacts/packages', title="Output path", description="Folder for the deployment package.")
        include_inference_script: bool = Field(default=True, title="Include inference script", description="Bundle run_inference.py (real audio → prediction) and the optional serve.py endpoint (On/Off).")
        include_metadata: bool = Field(default=True, title="Include metadata", description="Bundle model metadata / labels JSON with the package (On/Off).")
        package_name: str = Field(default='', title="Package name", description="Name of the deployment package artifact (empty = derive from model).")
        source_run_id: str = Field(default='', title="Source training run", description="Run whose Feature Frontend / Dataset Builder settings go into preprocessing.json (empty = the run declared by Ship, else read from the model path).")
        selftest: Literal["strict", "warn", "off"] = Field(default='strict', title="Self-test", description="strict = fail the run when the shipped preprocessing or input shape does not match training; warn = record only; off = skip.")
        selftest_samples: int = Field(default=3, ge=0, le=10, title="Self-test clips", description="Real clips from the source dataset the shipped script is verified on (0 = shape checks only).")

    # ── SISO process ──────────────────────────────────────────────────────────

    def process(self, artifact: DeploymentArtifact) -> DeploymentArtifact:
        target = self.config.target
        out_dir = Path(self.config.output_path)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

        model_path = Path(artifact.artifact_path) if artifact.artifact_path else None
        labels = list(getattr(artifact, "labels", None) or [])
        pkg_name = self.config.package_name or f"model_{target}"
        bundle_info: dict[str, Any] | None = None

        if target in ("mobile", "docker", "edge"):
            pkg_path, bundle_info = self._package_bundle(model_path, labels, artifact, out_dir, pkg_name, target)
        elif target == "mcu":
            pkg_path = self._package_mcu(model_path, labels, out_dir, pkg_name)
        elif target in ("cmsis_pack", "arduino", "zephyr", "pte_bundle"):
            pkg_path = self._package_additive_target(model_path, labels, artifact, out_dir, pkg_name, target)
        else:
            raise ValueError(
                f"DeploymentPackagerNode: unknown target '{target}'. "
                "Choose from: mobile, mcu, docker, edge, cmsis_pack, arduino, zephyr, pte_bundle"
            )

        new_meta = dict(artifact.metadata)
        packager_meta: dict[str, Any] = {
            "target": target,
            "package_path": str(pkg_path),
            "include_inference_script": self.config.include_inference_script,
            "version": PACKAGER_VERSION,
        }
        if bundle_info:
            packager_meta.update(bundle_info)
        new_meta["packager"] = packager_meta
        update: dict[str, Any] = {"artifact_path": str(pkg_path), "metadata": new_meta}
        if bundle_info and bundle_info.get("input_shape"):
            update["input_shape"] = bundle_info["input_shape"]
        try:
            result = artifact.model_copy(update=update)
        except Exception:
            result = copy.deepcopy(artifact)
            for k, v in update.items():
                setattr(result, k, v)
        log.info("DeploymentPackagerNode: packaged → %s", pkg_path)
        return result

    # ── runnable bundle (edge / docker / mobile) ──────────────────────────────

    def _own_run_id(self) -> str:
        return str(getattr(self, "_run_id", "") or getattr(self, "_current_run_id", "") or "").strip()

    def _stage_bundle(
        self,
        stage: Path,
        model_path: Path | None,
        labels: list[str],
        artifact: DeploymentArtifact,
        target: str,
        archive_name: str,
    ) -> dict[str, Any]:
        """Write every package file into ``stage``; return the bundle summary."""
        ctx = resolve_source_context(
            artifact=artifact,
            own_run_id=self._own_run_id(),
            explicit_source_run_id=self.config.source_run_id,
        )
        graph = ctx["graph"] or {}
        prove = ctx["prove"] or {}
        src_meta = ctx["source_meta"] or {}
        pre_src = preprocessing_from_graph(graph) if graph else None

        model_file = None
        if model_path and model_path.is_file():
            model_file = "model.tflite" if model_path.suffix.lower() == ".tflite" else model_path.name
            shutil.copy2(model_path, stage / model_file)
        (stage / "labels.txt").write_text("\n".join(labels), encoding="utf-8")

        details = _model_details(artifact, model_path)
        env_libs = ((prove.get("environment") or {}).get("libraries") or {}) if isinstance(prove.get("environment"), dict) else {}
        librosa_ver = env_libs.get("librosa") or _lib_version("librosa")

        preprocessing: dict[str, Any] = {
            "schema": "graphyn.preprocessing/1",
            "source": {
                "run_id": ctx["source_run_id"],
                "resolved_from": ctx["resolved_from"],
                "graph_name": (graph.get("metadata") or {}).get("name") if graph else None,
                "feature_node_id": (pre_src or {}).get("feature_node_id"),
                "builder_node_id": (pre_src or {}).get("builder_node_id"),
                "config_source": "runs/<source>/graph.json" if pre_src else None,
            },
            "audio": {
                "decode": "librosa.load(path, sr=None, mono=True) — as dataset_ingest",
                "resample": "librosa.resample (default resampler) when the rate differs",
                "sample_rate": (pre_src or {}).get("features", {}).get("sample_rate"),
                "channels": 1,
            },
            "features": (pre_src or {}).get("features"),
            "normalization": (
                {"kind": "per-clip z-score over the whole feature matrix", "eps": 1e-8}
                if (pre_src or {}).get("features", {}).get("normalize") else None
            ),
            "frames": (pre_src or {}).get("frames"),
            "input": None,
            "output": None,
            "labels": labels,
            "libraries": {"librosa": librosa_ver, "numpy": env_libs.get("numpy") or _lib_version("numpy")},
        }
        if details:
            ins, outs = details.get("inputs") or [], details.get("outputs") or []
            preprocessing["input"] = ins[0] if ins else None
            preprocessing["output"] = outs[0] if outs else None
        self._fill_frames_from_input(preprocessing)
        if not pre_src:
            preprocessing["warning"] = (
                "Source training run feature settings not found"
                + (f" (run {ctx['source_run_id']})" if ctx["source_run_id"] else "")
                + " — run_inference.py cannot reproduce training preprocessing; set "
                "deployment_packager.source_run_id."
            )
        _write_json(stage / "preprocessing.json", preprocessing)

        if self.config.include_inference_script:
            shutil.copy2(_BUNDLE_DIR / "run_inference.py", stage / "run_inference.py")
            shutil.copy2(_BUNDLE_DIR / "serve.py", stage / "serve.py")
            (stage / "requirements-serve.txt").write_text(_REQUIREMENTS_SERVE, encoding="utf-8")
        (stage / "requirements.txt").write_text(self._requirements(librosa_ver), encoding="utf-8")
        if target == "docker":
            (stage / "Dockerfile").write_text(_DOCKERFILE, encoding="utf-8")
        if target == "mobile" and self.config.include_inference_script:
            (stage / "inference_android.java").write_text(_ANDROID_SNIPPET, encoding="utf-8")

        if self.config.include_metadata:
            _write_json(stage / "metadata.json", {
                "model_format": artifact.model_format,
                "target_hardware": artifact.target_hardware,
                "quantization": artifact.quantization,
                "n_classes": len(labels),
                "labels": labels,
                "model_file": model_file,
                "input": preprocessing.get("input"),
                "output": preprocessing.get("output"),
                "preprocessing": "preprocessing.json",
                "provenance": "provenance.json",
                "display_name": (artifact.metadata or {}).get("display_name"),
            })

        # Self-test (may fill model tensor details we could not read in-process).
        selftest: dict[str, Any]
        if self.config.selftest == "off":
            selftest = {"status": "skipped", "ran_at": _now(), "checks": [], "samples": [], "notes": ["self-test off"]}
        else:
            ingest_cfg = (pre_src or {}).get("ingest_config") or {}
            dataset_dir = _workspace_path(ingest_cfg.get("path")) if ingest_cfg.get("source_type", "filesystem") == "filesystem" else None
            try:
                selftest = run_selftest(
                    stage, preprocessing, dataset_dir=dataset_dir,
                    n_samples=int(self.config.selftest_samples), model_file=model_file,
                )
            except Exception as exc:  # never let a broken self-test hide the package
                log.warning("DeploymentPackagerNode: self-test crashed: %s", exc, exc_info=True)
                selftest = {"status": "failed", "ran_at": _now(), "checks": [
                    {"name": "selftest", "status": "failed", "detail": f"self-test crashed: {exc!r}"}],
                    "samples": [], "notes": []}
            if not preprocessing.get("input") and isinstance(selftest.get("model"), dict):
                ins = selftest["model"].get("inputs") or []
                outs = selftest["model"].get("outputs") or []
                preprocessing["input"] = ins[0] if ins else None
                preprocessing["output"] = outs[0] if outs else None
                self._fill_frames_from_input(preprocessing)
                _write_json(stage / "preprocessing.json", preprocessing)
                if self.config.include_metadata:
                    meta_doc = _read_json(stage / "metadata.json")
                    meta_doc.update({"input": preprocessing["input"], "output": preprocessing["output"]})
                    _write_json(stage / "metadata.json", meta_doc)
        selftest["mode"] = self.config.selftest
        _write_json(stage / "selftest.json", selftest)

        # Provenance.
        lineage_model = (ctx["lineage_request"] or {}).get("model") or {}
        registered = self._registered_model(lineage_model, ctx["source_run_id"])
        ext_inputs = prove.get("external_inputs") or src_meta.get("external_inputs") or []
        dataset = [
            {k: d.get(k) for k in ("node_id", "node_type", "path", "kind", "content_hash", "hash_mode",
                                   "file_count", "total_bytes")}
            for d in ext_inputs if isinstance(d, dict)
        ]
        metrics = _source_model_metrics(ctx["source_run_id"], src_meta, artifact)
        provenance: dict[str, Any] = {
            "schema": "graphyn.package-provenance/1",
            "package": {
                "name": archive_name,
                "target": target,
                "built_at": _now(),
                "package_run_id": ctx["package_run_id"],
                "graphyn_version": _graphyn_version(),
                "packager_version": PACKAGER_VERSION,
            },
            "source_run": {
                "run_id": ctx["source_run_id"],
                "resolved_from": ctx["resolved_from"],
                "project": src_meta.get("project") or prove.get("project"),
                "graph_name": src_meta.get("graph_name") or prove.get("graph_name"),
                "graph_hash": prove.get("graph_hash") or src_meta.get("graph_hash"),
                "record_hash": prove.get("record_hash"),
                "status": src_meta.get("status") or prove.get("status"),
                "test_accuracy": metrics.get("test_accuracy") if metrics else None,
            },
            "registered_model": registered,
            "model": {
                "file": model_file,
                "sha256": _sha256_file(stage / model_file) if model_file else None,
                "size_bytes": (stage / model_file).stat().st_size if model_file else None,
                "format": artifact.model_format,
                "quantization": artifact.quantization,
                "display_name": (artifact.metadata or {}).get("display_name"),
                "source_model_path": (artifact.metadata or {}).get("source_model_path")
                or (artifact.metadata or {}).get("source"),
            },
            "dataset": dataset,
            "selftest": {"status": selftest.get("status"), "mode": selftest.get("mode")},
        }
        readme = render_readme(
            package_file=archive_name, labels=labels, preprocessing=preprocessing,
            provenance=provenance, selftest=selftest, metrics=metrics or {}, target=target,
        )
        (stage / "README.md").write_text(readme, encoding="utf-8")
        files = {
            p.name: {"sha256": _sha256_file(p), "size": p.stat().st_size}
            for p in sorted(stage.iterdir()) if p.is_file()
        }
        provenance["files"] = files
        _write_json(stage / "provenance.json", provenance)
        files["provenance.json"] = {
            "sha256": _sha256_file(stage / "provenance.json"),
            "size": (stage / "provenance.json").stat().st_size,
        }
        (stage / "SHA256SUMS").write_text(
            "".join(f"{v['sha256']}  {k}\n" for k, v in sorted(files.items())), encoding="utf-8"
        )

        if self.config.selftest == "strict" and selftest.get("status") == "failed":
            bad = [c for c in selftest.get("checks", []) if c.get("status") == "failed"]
            raise RuntimeError(
                "DeploymentPackagerNode: package self-test failed — "
                + "; ".join(f"{c['name']}: {c['detail']}" for c in bad)
                + " (set selftest='warn' to package anyway)"
            )

        return {
            "source_run_id": ctx["source_run_id"],
            "registered_model": registered,
            "preprocessing": preprocessing,
            "selftest": selftest,
            "provenance": provenance,
            "metrics": metrics or {},
            "input_shape": list((preprocessing.get("input") or {}).get("shape") or []),
        }

    @staticmethod
    def _fill_frames_from_input(pre: dict[str, Any]) -> None:
        """fixed_length=0 in training → take the frame count from the model input."""
        frames = pre.get("frames")
        inp = pre.get("input") or {}
        shape = inp.get("shape") if isinstance(inp, dict) else None
        if isinstance(frames, dict) and not frames.get("fixed_length") and shape and len(shape) >= 3:
            frames["fixed_length"] = int(shape[1])
            frames["fixed_length_source"] = "model input shape (training padded to the longest clip)"
        audio = pre.get("audio") or {}
        fc = pre.get("features") or {}
        if isinstance(frames, dict) and frames.get("fixed_length") and fc.get("hop_length") and fc.get("sample_rate"):
            audio["expected_duration_s"] = round(
                (int(frames["fixed_length"]) - 1) * int(fc["hop_length"]) / int(fc["sample_rate"]), 3
            )

    @staticmethod
    def _requirements(librosa_ver: str | None) -> str:
        lib = f"librosa=={librosa_ver}" if librosa_ver else "librosa>=0.10,<0.11"
        return (
            "# Runtime for run_inference.py\n"
            "numpy>=1.24\n"
            f"{lib}  # same version as the training run's Feature Frontend (preprocessing parity)\n"
            "soundfile>=0.12\n"
            "# TFLite runtime (any one works; tensorflow is the universal fallback)\n"
            'tflite-runtime>=2.14 ; python_version < "3.12" and platform_system == "Linux"\n'
            'ai-edge-litert>=1.2 ; python_version >= "3.12" and platform_system != "Windows"\n'
            '# tensorflow>=2.13  # uncomment on Windows / when no wheel above exists\n'
        )

    @staticmethod
    def _registered_model(lineage_model: dict[str, Any], source_run_id: str | None) -> dict[str, Any] | None:
        name = str(lineage_model.get("name") or "").strip()
        if not name:
            return None
        out: dict[str, Any] = {
            "name": name,
            "stage": lineage_model.get("stage"),
            "version": lineage_model.get("version"),
        }
        try:
            from app.core.mlops.model_registry import get_model

            rec = get_model(name)
            stage = (rec.get("stages") or {}).get(str(out.get("stage") or "")) or {}
            if isinstance(stage, dict) and stage:
                out["version"] = out.get("version") or stage.get("version")
                out["registry_run_id"] = stage.get("run_id")
                out["registered_at"] = stage.get("updated_at")
                if source_run_id and stage.get("run_id"):
                    out["matches_source_run"] = stage.get("run_id") == source_run_id
        except Exception:
            pass
        return out

    def _package_bundle(self, model_path, labels, artifact, out_dir: Path, name: str, target: str):
        if target == "mobile":
            archive = out_dir / f"{name}.zip"
        elif target == "docker":
            archive = out_dir / f"{name}_docker.tar.gz"
        else:
            archive = out_dir / f"{name}_edge.tar.gz"
        stage = Path(tempfile.mkdtemp(prefix=f".{name}_stage_", dir=str(out_dir)))
        try:
            info = self._stage_bundle(stage, model_path, labels, artifact, target, archive.name)
            tmp = archive.with_name(archive.name + ".tmp")
            members = sorted(p for p in stage.iterdir() if p.is_file())
            if target == "mobile":
                with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
                    for p in members:
                        zf.write(p, p.name)
            else:
                prefix = f"{name}/" if target == "docker" else ""
                with tarfile.open(tmp, "w:gz") as tf:
                    for p in members:
                        ti = tf.gettarinfo(str(p), arcname=prefix + p.name)
                        ti.uid = ti.gid = 0
                        ti.uname = ti.gname = ""
                        ti.mode = 0o755 if p.suffix == ".py" else 0o644
                        with open(p, "rb") as fh:
                            tf.addfile(ti, fh)
            os.replace(tmp, archive)
            files = (info.get("provenance") or {}).get("files") or {}
        finally:
            shutil.rmtree(stage, ignore_errors=True)

        order = list(_ROLES)
        contents = [
            {"path": k, "role": _ROLES.get(k, "file"), "size": v.get("size"), "sha256": v.get("sha256")}
            for k, v in sorted(files.items(), key=lambda kv: (order.index(kv[0]) if kv[0] in order else 99, kv[0]))
        ]
        pkg_sha = _sha256_file(archive)
        extract = (f"mkdir model && unzip {archive.name} -d model && cd model" if target == "mobile"
                   else f"mkdir model && tar -xzf {archive.name} -C model && cd model"
                   + (f"/{name}" if target == "docker" else ""))
        how = [
            f"sha256sum {archive.name}   # expect {pkg_sha}",
            extract,
            "sha256sum -c SHA256SUMS",
            "pip install -r requirements.txt",
            "python run_inference.py clip.wav --top-k 3",
        ]
        if target == "docker":
            how += ["docker build -t audio-model . && docker run -p 8080:8080 audio-model"]
        selftest = info.get("selftest") or {}
        provenance = info.get("provenance") or {}
        pre = info.get("preprocessing") or {}
        manifest = {
            "schema": "graphyn.package-manifest/1",
            "package": archive.name,
            "package_path": str(archive),
            "sha256": pkg_sha,
            "size_bytes": archive.stat().st_size,
            "target": target,
            "built_at": (provenance.get("package") or {}).get("built_at"),
            "package_run_id": (provenance.get("package") or {}).get("package_run_id"),
            "source_run_id": info.get("source_run_id"),
            "registered_model": info.get("registered_model"),
            "labels": labels,
            "metrics": {k: info["metrics"][k] for k in ("test_accuracy", "roc_auc") if k in (info.get("metrics") or {})},
            "input": {
                "sample_rate": (pre.get("features") or {}).get("sample_rate"),
                "channels": 1,
                "fixed_length": (pre.get("frames") or {}).get("fixed_length"),
                "expected_duration_s": (pre.get("audio") or {}).get("expected_duration_s"),
                "feature_type": (pre.get("features") or {}).get("feature_type"),
                "tensor": pre.get("input"),
            },
            "contents": contents,
            "selftest": {
                "status": selftest.get("status"),
                "mode": selftest.get("mode"),
                "checks": selftest.get("checks", []),
                "samples": [
                    {k: s.get(k) for k in ("file", "label", "predicted", "probability", "max_abs_diff")}
                    for s in selftest.get("samples", [])
                ],
                "notes": selftest.get("notes", []),
            },
            "how_to_run": how,
            "warning": pre.get("warning"),
        }
        manifest_path = archive.with_name(archive.name + ".manifest.json")
        _write_json(manifest_path, manifest)
        return archive, {
            "manifest_path": str(manifest_path),
            "sha256": pkg_sha,
            "source_run_id": info.get("source_run_id"),
            "registered_model": info.get("registered_model"),
            "selftest_status": selftest.get("status"),
            "contents": [c["path"] for c in contents],
            "input_shape": info.get("input_shape"),
        }

    # ── other targets ─────────────────────────────────────────────────────────

    def _package_additive_target(self, model_path, labels, artifact, out_dir, pkg_name, target: str):
        """Stub packagers for cmsis_pack/arduino/zephyr/pte_bundle (prefer TinyML nodes)."""
        dest = Path(out_dir) / f"{pkg_name}_{target}"
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "PACKAGE_STUB.txt").write_text(
            f"target={target}\nsource={model_path}\nprefer=cmsis_pack_exporter|executorch_export\n",
            encoding="utf-8",
        )
        return dest

    def _package_mcu(self, model_path, labels, out_dir, name) -> Path:
        header_path = out_dir / f"{name}.h"
        model_bytes = b""
        if model_path and model_path.exists():
            model_bytes = model_path.read_bytes()

        label_strs = ", ".join(f'"{lbl}"' for lbl in labels)
        model_name = model_path.name if model_path else "model"

        # Write header incrementally to avoid building a ~50 MB string in RAM
        # for large models (5–10 MB TFLite files → ~50 MB hex representation).
        with open(header_path, "w") as fh:
            fh.write(
                f"/* Auto-generated MCU deployment header */\n"
                f"#pragma once\n"
                f"#include <stdint.h>\n\n"
                f"/* Model: {model_name} */\n"
                f"/* Size: {len(model_bytes)} bytes */\n"
                f"static const uint8_t g_model_data[] = {{"
            )
            for i, b in enumerate(model_bytes):
                fh.write(f"0x{b:02x}")
                if i < len(model_bytes) - 1:
                    fh.write(", ")
            fh.write(
                f"}};\n"
                f"static const int g_model_data_len = {len(model_bytes)};\n\n"
                f"/* Labels */\n"
                f"static const char* g_labels[] = {{{label_strs}}};\n"
                f"static const int g_num_labels = {len(labels)};\n"
            )
        return header_path


__all__ = [
    "DeploymentPackagerNode",
    "preprocessing_from_graph",
    "render_readme",
    "resolve_source_context",
    "run_selftest",
]
