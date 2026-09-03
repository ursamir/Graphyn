# app/core/workspace_paths.py
"""
Bounded Context:  Graph Language / Workspace
Responsibility:   Rewrite pipeline output paths into workspace/artifacts/<slug>/.
Owns:             artifact_slug, rewire_graph_outputs, apply_output_rewire.
Public Surface:   artifact_slug, rewire_graph_outputs, apply_output_rewire,
                  ARTIFACTS_PREFIX.
Must NOT:         Execute pipelines or write files.
Dependencies:     copy, re, pathlib; GraphIR loader imported lazily.
Reason To Change: Artifact layout or relocatable-output heuristics change.

Slug policy
-----------
``artifact_slug(raw)`` lowercases, maps ``_`` to ``-``, keeps ``[a-z0-9-]``,
strips a leading ``ex-`` template prefix and a leading numeric example-folder
prefix (``01-wake-word`` → ``wake-word``). Example 6 names that contain
``speech-commands-e2e`` collapse to ``speech-commands`` so train + preprocess
share ``workspace/artifacts/speech-commands``.

Template sync uses the template id (``ex-01-wake-word`` → ``wake-word``).
Saved Builder templates use the template name. Run/validate uses
``metadata.name``.
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

ARTIFACTS_PREFIX = "workspace/artifacts"
_MERITECH_PREFIXES = (
    "/home/meritech/Desktop/newAudio3/",
    "/home/meritech/Desktop/newAudio3",
)
_OUTPUT_KEYS = frozenset({"output_dir", "output_path", "model_path", "root"})
_PATH_KEYS = frozenset({"output_dir", "output_path", "model_path", "path", "file_path", "root"})
_GENERIC_TAILS = frozenset({"output", "outputs", "out"})
_SAFE_SLUG_RE = re.compile(r"[^a-z0-9-]+")
_EXAMPLES_OUTPUT_RE = re.compile(r"(?:^|/)examples/[^/]+/output(?:/(.*))?$", re.I)
_EXAMPLES_DATA_RE = re.compile(r"(?:^|/)examples/[^/]+/data(?:/|$)", re.I)
_DATASETS_OUTPUT_RE = re.compile(r"(?:^|/)workspace/datasets/output(?:/(.*))?$", re.I)
_OUTPUT_FILE_SUFFIXES = frozenset(
    {
        ".csv",
        ".json",
        ".png",
        ".jpg",
        ".jpeg",
        ".keras",
        ".tflite",
        ".onnx",
        ".h5",
        ".wav",
        ".md",
        ".srt",
        ".vtt",
    }
)


def _posix(value: str) -> str:
    return value.replace("\\", "/").strip()


def artifact_slug(raw: str) -> str:
    """Sanitize ``raw`` to a workspace artifact folder name ``[a-z0-9-]``."""
    text = (raw or "").strip().lower().replace("_", "-")
    text = _SAFE_SLUG_RE.sub("-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    if text.startswith("ex-"):
        text = text[3:]
    text = re.sub(r"^\d+-+", "", text).strip("-")
    if "speech-commands-e2e" in text:
        return "speech-commands"
    return text or "pipeline"


def strip_legacy_absolute_prefix(value: str) -> str:
    """Turn ``/home/meritech/Desktop/newAudio3/...`` into a repo-relative path."""
    text = _posix(value)
    for prefix in _MERITECH_PREFIXES:
        if text.startswith(prefix):
            rest = text[len(prefix) :].lstrip("/")
            return rest or text
    return text


def _is_artifacts_path(posix: str) -> bool:
    padded = f"/{posix}"
    return (
        posix == ARTIFACTS_PREFIX
        or posix.startswith(f"{ARTIFACTS_PREFIX}/")
        or "/workspace/artifacts/" in padded
        or padded.endswith("/workspace/artifacts")
    )


def _normalize_artifacts(posix: str) -> str:
    idx = posix.find(ARTIFACTS_PREFIX)
    if idx >= 0:
        return posix[idx:]
    return posix


def _is_sample_data_path(posix: str) -> bool:
    if _EXAMPLES_OUTPUT_RE.search(posix):
        return False
    if _EXAMPLES_DATA_RE.search(posix):
        return True
    if "/data/" in f"/{posix}/" and "/output/" not in posix:
        return True
    return False


def _relocatable_tail(posix: str) -> str | None:
    """Tail to preserve under ``workspace/artifacts/<slug>/``, or None."""
    match = _EXAMPLES_OUTPUT_RE.search(posix)
    if match:
        return (match.group(1) or "").strip("/")
    match = _DATASETS_OUTPUT_RE.search(posix)
    if match:
        return (match.group(1) or "").strip("/")
    if posix == "output" or posix.startswith("output/"):
        return posix[len("output") :].lstrip("/")
    return None


def _join_artifacts(slug: str, tail: str) -> str:
    parts = [p for p in tail.split("/") if p]
    if not parts:
        return f"{ARTIFACTS_PREFIX}/{slug}"
    if len(parts) == 1 and parts[0].lower() in _GENERIC_TAILS:
        return f"{ARTIFACTS_PREFIX}/{slug}"
    return f"{ARTIFACTS_PREFIX}/{slug}/{'/'.join(parts)}"


def _should_rewire_key(key: str, posix: str) -> bool:
    if _is_artifacts_path(posix):
        return False
    if _is_sample_data_path(posix):
        return False
    tail = _relocatable_tail(posix)
    if tail is None:
        return False
    if key in _OUTPUT_KEYS:
        return True
    if key == "path":
        suffix = Path(posix).suffix.lower()
        if suffix in _OUTPUT_FILE_SUFFIXES:
            return True
        # Directories (and files without a listed suffix) under examples/**/output.
        return True
    return False


def _rewrite_string(key: str, value: str, slug: str) -> str:
    stripped = strip_legacy_absolute_prefix(value)
    posix = _posix(stripped)
    if _is_artifacts_path(posix):
        return _normalize_artifacts(posix)
    if _should_rewire_key(key, posix):
        tail = _relocatable_tail(posix) or ""
        return _join_artifacts(slug, tail)
    return posix if posix != _posix(value) else value


def _rewrite_value(key: str, value: Any, slug: str) -> Any:
    if isinstance(value, str):
        if key in _PATH_KEYS or value.startswith("/home/meritech/"):
            use_key = key if key in _PATH_KEYS else "path"
            return _rewrite_string(use_key, value, slug)
        return value
    if isinstance(value, dict):
        return {k: _rewrite_value(k, v, slug) for k, v in value.items()}
    if isinstance(value, list):
        return [_rewrite_value(key, item, slug) for item in value]
    return value


def rewire_graph_outputs(graph: dict[str, Any], *, slug: str) -> dict[str, Any]:
    """Return a copy of ``graph`` with output paths under workspace/artifacts/<slug>.

    Input dataset paths under ``examples/**/data`` are left in place (after
    stripping a legacy meritech absolute prefix). Paths already under
    ``workspace/artifacts/`` are normalized, not moved. Custom output locations
    outside ``examples/**/output`` (and the legacy ``output/`` /
    ``workspace/datasets/output`` roots) are not rewritten.
    """
    if not isinstance(graph, dict):
        return graph
    slug = artifact_slug(slug)
    return _rewrite_value("", copy.deepcopy(graph), slug)


def apply_output_rewire(graph: Any) -> Any:
    """Rewire a loaded GraphIR using ``metadata.name`` as the slug."""
    from app.core.ir.loader import dump_ir, load_ir

    data = dump_ir(graph)
    name = "pipeline"
    meta = data.get("metadata") if isinstance(data, dict) else None
    if isinstance(meta, dict) and meta.get("name"):
        name = str(meta["name"])
    return load_ir(rewire_graph_outputs(data, slug=name))

def _graph_name(graph: dict[str, Any] | Any) -> str:
    if isinstance(graph, dict):
        meta = graph.get("metadata")
        if isinstance(meta, dict) and meta.get("name"):
            return str(meta["name"])
        return "pipeline"
    meta = getattr(graph, "metadata", None)
    name = getattr(meta, "name", None) if meta is not None else None
    return str(name) if name else "pipeline"


def artifact_layout(slug: str, run_id: str) -> dict[str, str]:
    """Return posix paths for this run's artifact folder and the latest alias."""
    slug = artifact_slug(slug)
    rid = str(run_id).strip()
    return {
        "run_dir": f"{ARTIFACTS_PREFIX}/{slug}/runs/{rid}",
        "latest_dir": f"{ARTIFACTS_PREFIX}/{slug}/latest",
    }


def artifact_fs_path(posix: str) -> Path:
    """Map ``workspace/artifacts/...`` to ``{project_dir}/artifacts/...``."""
    from app.core.config import project_dir

    text = _normalize_artifacts(_posix(posix))
    if text.startswith("workspace/"):
        return project_dir() / Path(*text.split("/")[1:])
    if text.startswith("artifacts/"):
        return project_dir() / text
    return project_dir() / text


def slug_from_artifacts_posix(posix: str) -> str | None:
    text = _normalize_artifacts(_posix(posix))
    marker = f"{ARTIFACTS_PREFIX}/"
    if text.startswith(marker):
        slug = text[len(marker) :].split("/", 1)[0]
        return slug or None
    if text.startswith("artifacts/"):
        slug = text.split("/", 2)[1] if text.count("/") >= 1 else ""
        return slug or None
    return None


def _scope_artifact_string(posix: str, run_id: str) -> str:
    text = _normalize_artifacts(_posix(posix))
    marker = ARTIFACTS_PREFIX + "/"
    if not text.startswith(marker):
        return posix if posix == text else text
    rest = text[len(marker):]
    if not rest:
        return text
    parts = [p for p in rest.split("/") if p]
    slug = parts[0]
    tail = parts[1:]
    if tail and tail[0] in {"runs", "latest"}:
        return text
    if tail:
        return f"{ARTIFACTS_PREFIX}/{slug}/runs/{run_id}/{"/".join(tail)}"
    return f"{ARTIFACTS_PREFIX}/{slug}/runs/{run_id}"


def _should_scope_key(key: str, posix: str) -> bool:
    if not _is_artifacts_path(_posix(posix)):
        return False
    if key in _OUTPUT_KEYS:
        return True
    if key == "path":
        suffix = Path(posix).suffix.lower()
        if suffix in _OUTPUT_FILE_SUFFIXES:
            return True
        padded = f"/{_posix(posix)}/"
        return "/output/" in padded
    return False


def _scope_value(key: str, value: Any, run_id: str) -> Any:
    if isinstance(value, str):
        if key in _PATH_KEYS and _should_scope_key(key, value):
            return _scope_artifact_string(value, run_id)
        return value
    if isinstance(value, dict):
        return {k: _scope_value(k, v, run_id) for k, v in value.items()}
    if isinstance(value, list):
        return [_scope_value(key, item, run_id) for item in value]
    return value


def scope_outputs_to_run(graph: Any, run_id: str) -> Any:
    """Insert ``/runs/<run_id>/`` after the artifact slug on output paths.

    Leaves ``latest/`` (inputs from a promoted run), paths already under
    ``/runs/``, and ``examples/**/data`` ingest paths unchanged.
    """
    rid = str(run_id).strip()
    if not rid:
        return graph

    is_dict = isinstance(graph, dict)
    if is_dict:
        data = copy.deepcopy(graph)
    else:
        from app.core.ir.loader import dump_ir, load_ir

        data = dump_ir(graph)

    rewritten = _scope_value("", data, rid)
    if is_dict:
        return rewritten
    from app.core.ir.loader import load_ir

    return load_ir(rewritten)


def read_metrics_json(directory: Path | str | None) -> dict[str, Any] | None:
    """Load ``metrics.json`` from a directory; return None if missing/invalid."""
    if directory is None:
        return None
    path = Path(directory) / "metrics.json"
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def read_run_metrics(slug: str, run_id: str) -> dict[str, Any] | None:
    layout = artifact_layout(slug, run_id)
    return read_metrics_json(artifact_fs_path(layout["run_dir"]))


def latest_run_id(slug: str) -> str | None:
    """Return the run_id currently aliased as latest, if any."""
    slug = artifact_slug(slug)
    layout = artifact_layout(slug, "_")
    latest = artifact_fs_path(layout["latest_dir"])
    slug_dir = latest.parent
    try:
        if latest.is_symlink():
            target = os.readlink(latest)
            posix = _posix(target)
            parts = [p for p in posix.replace("\\", "/").split("/") if p]
            if "runs" in parts:
                idx = parts.index("runs")
                if idx + 1 < len(parts):
                    return parts[idx + 1]
    except OSError:
        pass
    for candidate in (slug_dir / "latest.json", latest / "latest.json"):
        try:
            if candidate.is_file():
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("run_id"):
                    return str(data["run_id"])
        except Exception:
            continue
    return None


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _copy_key_files(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        return
    for child in src.rglob("*"):
        if not child.is_file():
            continue
        rel = child.relative_to(src)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            try:
                target.unlink()
            except OSError:
                pass
        try:
            os.symlink(child, target)
        except OSError:
            shutil.copy2(child, target)


def publish_latest(slug: str, run_id: str) -> str:
    """Point ``workspace/artifacts/<slug>/latest`` at ``runs/<run_id>``.

    Prefers a POSIX symlink replaced atomically. If the symlink cannot be
    created (Windows, permissions), write ``latest.json`` and copy/symlink
    key files into the ``latest/`` directory.
    """
    layout = artifact_layout(slug, run_id)
    latest_rel = layout["latest_dir"]
    run_rel = layout["run_dir"]
    latest = artifact_fs_path(latest_rel)
    run_path = artifact_fs_path(run_rel)
    slug_dir = latest.parent
    slug_dir.mkdir(parents=True, exist_ok=True)
    run_path.mkdir(parents=True, exist_ok=True)

    pointer = {"run_id": str(run_id), "path": run_rel}
    tmp = slug_dir / f".latest-{run_id}.tmp"
    try:
        if tmp.exists() or tmp.is_symlink():
            tmp.unlink()
        os.symlink(f"runs/{run_id}", tmp, target_is_directory=True)
        if latest.is_dir() and not latest.is_symlink():
            bak = slug_dir / f".latest-old-{run_id}"
            if bak.exists() or bak.is_symlink():
                if bak.is_dir() and not bak.is_symlink():
                    shutil.rmtree(bak)
                else:
                    bak.unlink()
            os.rename(latest, bak)
            try:
                os.replace(tmp, latest)
            finally:
                shutil.rmtree(bak, ignore_errors=True)
        else:
            os.replace(tmp, latest)
        leftover = slug_dir / "latest.json"
        if leftover.is_file():
            leftover.unlink()
        return latest_rel
    except OSError:
        if tmp.exists() or tmp.is_symlink():
            try:
                tmp.unlink()
            except OSError:
                pass

    _atomic_write_json(slug_dir / "latest.json", pointer)
    if latest.is_symlink():
        latest.unlink()
    _copy_key_files(run_path, latest)
    _atomic_write_json(latest / "latest.json", pointer)
    return latest_rel
