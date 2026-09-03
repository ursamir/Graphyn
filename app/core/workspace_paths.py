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
import re
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
