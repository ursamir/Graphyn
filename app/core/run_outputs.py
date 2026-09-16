# app/core/run_outputs.py
"""
Bounded Context:  REST API Layer helpers
Responsibility:   Path-jailed discovery and download of pipeline output files.
Owns:             Jail roots, allow-list, listing run outputs, zip packing.
Public Surface:   list_run_output_files (entries may include node_id), resolve_download_path,
                  pack_outputs_zip, OutputPathError, ALLOWED_SUFFIXES.
Must NOT:         Serve files outside project_dir, graphyn_home, or repo examples/.
Dependencies:     stdlib, app.core.config, app.core.example_templates.
Reason To Change: New output locations, allow-list, or listing sources.
"""
from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path
from typing import Any, Iterable

from app.core.config import artifacts_dir, graphyn_home, project_dir
from app.core.example_templates import examples_dir, repo_root

LEGACY_EXAMPLE_OUTPUT = "examples/06_speech_commands_e2e/output"

# Console-downloadable artifacts (plots, metrics, Keras, TFLite, zip).
# Extra suffixes cover SavedModel / labels / calibration dumps next to those.
ALLOWED_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".svg",
        ".json",
        ".keras",
        ".tflite",
        ".zip",
        ".h5",
        ".pb",
        ".txt",
        ".npy",
        ".npz",
        ".index",
        ".onnx",
        ".ckpt",
        ".csv",
        ".wav",
        ".flac",
        ".mp3",
        ".webm",
        ".md",
    }
)

_SKIP_DIR_NAMES = frozenset(
    {".git", "__pycache__", "node_modules", "data", ".venv"}
)
# Generic os.walk skips this name so a 10k-wav tree cannot fill the 400-file cap.
_SKIP_HEAVY_DIR_NAMES = frozenset({"dataset"})

_DATASET_META_NAMES = frozenset(
    {"labels.csv", "metadata.json", "dataset.json", "manifest.csv", "readme.md"}
)
_DATASET_AUDIO_SUFFIXES = frozenset({".wav", ".flac", ".mp3", ".ogg", ".webm"})
_MAX_DATASET_DIRS = 12
_MAX_DATASET_WAVS = 3
_MAX_DATASET_DEPTH = 3  # dataset / <name> / v1 / train|val|test

_MAX_LISTED_FILES = 400
_MAX_ZIP_BYTES = 512 * 1024 * 1024


class OutputPathError(Exception):
    """Raised when a download path is missing, disallowed, or outside the jail."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _has_dotdot(raw: str) -> bool:
    normalized = raw.replace("\\", "/")
    return any(part == ".." for part in Path(normalized).parts) or "/../" in f"/{normalized}/"


def jail_roots() -> list[Path]:
    roots: list[Path] = []
    for candidate in (project_dir(), graphyn_home(), examples_dir()):
        try:
            roots.append(candidate.resolve())
        except OSError:
            continue
    seen: set[str] = set()
    unique: list[Path] = []
    for root in roots:
        key = str(root)
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def is_under_jail(resolved: Path) -> bool:
    for root in jail_roots():
        try:
            if resolved == root or resolved.is_relative_to(root):
                return True
        except (ValueError, OSError):
            continue
    return False


def _allowed_file(path: Path) -> bool:
    if not path.is_file():
        return False
    suffix = path.suffix.lower()
    if suffix in ALLOWED_SUFFIXES:
        return True
    parent = path.parent.name.lower()
    # TF SavedModel shards: variables.data-00000-of-00001 (suffix is not empty).
    if parent in {"saved_model", "variables"} and (
        not suffix or path.name.startswith("variables.")
    ):
        return True
    return False


def _display_path(path: Path) -> str:
    """Prefer a jail-relative path so the file endpoint can re-resolve it."""
    resolved = path.resolve()
    try:
        examples = examples_dir().resolve()
        if resolved == examples or resolved.is_relative_to(examples):
            rel = resolved.relative_to(examples)
            return f"examples/{rel.as_posix()}" if str(rel) != "." else "examples"
    except (ValueError, OSError):
        pass
    for root in jail_roots():
        try:
            if resolved == root or resolved.is_relative_to(root):
                rel = resolved.relative_to(root)
                return rel.as_posix() if str(rel) != "." else str(resolved)
        except (ValueError, OSError):
            continue
    return str(resolved)


def file_entry(
    path: Path, *, kind: str | None = None, node_id: str | None = None
) -> dict[str, Any]:
    resolved = path.resolve()
    is_dir = resolved.is_dir()
    size = 0
    if not is_dir:
        try:
            size = resolved.stat().st_size
        except OSError:
            size = 0
    entry: dict[str, Any] = {
        "name": resolved.name,
        "path": _display_path(resolved),
        "size": size,
        "kind": kind or ("dir" if is_dir else "file"),
    }
    if node_id:
        entry["node_id"] = node_id
    return entry


def resolve_download_path(raw: str) -> Path:
    """Resolve ``raw`` into a jailed file path.

    Rejects ``..``. Absolute paths must already sit under a jail root.
    Relative paths are tried against cwd, project_dir, and repo root.
    """
    if raw is None or not str(raw).strip():
        raise OutputPathError(400, "Missing path")
    text = str(raw).strip()
    if _has_dotdot(text):
        raise OutputPathError(400, "Path traversal not allowed")

    path = Path(text)
    candidates: list[Path] = []
    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.append(Path.cwd() / path)
        candidates.append(project_dir() / path)
        candidates.append(repo_root() / path)
        parts = path.parts
        if parts and parts[0] == "workspace":
            candidates.append(project_dir() / Path(*parts[1:]))
        if parts and parts[0] == "examples":
            candidates.append(examples_dir() / Path(*parts[1:]))

    jailed_existing: list[Path] = []
    jailed_missing = False
    outside = False
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if not is_under_jail(resolved):
            outside = True
            continue
        if resolved.exists():
            jailed_existing.append(resolved)
        else:
            jailed_missing = True

    if jailed_existing:
        chosen = jailed_existing[0]
        if chosen.is_dir():
            raise OutputPathError(400, "Path is a directory — use the zip endpoint")
        if not _allowed_file(chosen):
            raise OutputPathError(415, "File type is not allowed for download")
        return chosen
    if jailed_missing:
        raise OutputPathError(404, "File not found")
    raise OutputPathError(403, "Path is outside allowed directories")


def _walk_allowed_files(root: Path, *, limit: int, this_run_id: str | None = None) -> list[Path]:
    found: list[Path] = []
    if not root.exists() or limit <= 0:
        return found
    if root.is_file():
        try:
            resolved = root.resolve()
        except OSError:
            return found
        if _allowed_file(resolved) and is_under_jail(resolved):
            found.append(resolved)
        return found
    if not root.is_dir():
        return found
    try:
        resolved_root = root.resolve()
    except OSError:
        return found
    if not is_under_jail(resolved_root):
        return found
    for dirpath, dirnames, filenames in os.walk(resolved_root):
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in _SKIP_DIR_NAMES
            and d not in _SKIP_HEAVY_DIR_NAMES
            and not d.startswith(".")
        )
        if this_run_id:
            base = Path(dirpath)
            if base.name == "runs":
                dirnames[:] = [d for d in dirnames if d == this_run_id]
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            child = Path(dirpath) / name
            try:
                resolved = child.resolve()
            except OSError:
                continue
            if not is_under_jail(resolved):
                continue
            if _allowed_file(resolved):
                found.append(resolved)
                if len(found) >= limit:
                    return found
    return found



def _path_has_dataset_segment(path: Path) -> bool:
    return any(part.lower() == "dataset" for part in path.parts)


def _dataset_depth(path: Path) -> int | None:
    parts = [part.lower() for part in path.parts]
    if "dataset" not in parts:
        return None
    return len(parts) - parts.index("dataset") - 1


def _summarize_dataset_tree(root: Path, *, limit: int) -> list[Path]:
    """List a dataset tree without enumerating every wav.

    Includes the dataset folders (up to split level), labels/metadata, and a
    handful of sample audio files so the 400-entry cap still has room for plots.
    """
    found: list[Path] = []
    if not root.exists() or limit <= 0:
        return found
    try:
        resolved_root = root.resolve()
    except OSError:
        return found
    if not is_under_jail(resolved_root):
        return found

    seen: set[str] = set()

    def add(path: Path) -> bool:
        if len(found) >= limit:
            return False
        try:
            resolved = path.resolve()
        except OSError:
            return True
        if not is_under_jail(resolved):
            return True
        key = str(resolved)
        if key in seen:
            return True
        seen.add(key)
        found.append(resolved)
        return len(found) < limit

    if resolved_root.is_file():
        add(resolved_root)
        return found
    if resolved_root.is_dir():
        add(resolved_root)

    dir_count = 1 if resolved_root.is_dir() else 0
    wav_count = 0
    for dirpath, dirnames, filenames in os.walk(resolved_root):
        dirnames[:] = sorted(
            d for d in dirnames if d not in _SKIP_DIR_NAMES and not d.startswith(".")
        )
        base = Path(dirpath)
        depth = _dataset_depth(base)
        if depth is not None and depth >= _MAX_DATASET_DEPTH:
            dirnames[:] = []
        elif dir_count < _MAX_DATASET_DIRS:
            for name in list(dirnames):
                child = base / name
                child_depth = _dataset_depth(child)
                if child_depth is None or child_depth > _MAX_DATASET_DEPTH:
                    continue
                if dir_count >= _MAX_DATASET_DIRS:
                    break
                if add(child):
                    dir_count += 1
                else:
                    return found
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            child = base / name
            lower = name.lower()
            suffix = child.suffix.lower()
            if lower in _DATASET_META_NAMES or suffix in {".csv", ".json", ".md"}:
                if not add(child):
                    return found
            elif suffix in _DATASET_AUDIO_SUFFIXES and wav_count < _MAX_DATASET_WAVS:
                if not add(child):
                    return found
                wav_count += 1
    return found


def _collect_listed_paths(
    root: Path, *, limit: int, this_run_id: str | None = None
) -> list[Path]:
    if limit <= 0:
        return []
    if _path_has_dataset_segment(root):
        return _summarize_dataset_tree(root, limit=limit)
    return _walk_allowed_files(root, limit=limit, this_run_id=this_run_id)


# Basename / dirname → node_id substrings (shared run dirs lack per-node folders).
_NODE_BASENAME_HINTS: tuple[tuple[frozenset[str], tuple[str, ...]], ...] = (
    (
        frozenset(
            {
                "confusion_matrix.png",
                "roc_curves.png",
                "training_curves.png",
                "metrics.json",
            }
        ),
        ("evaluator", "evaluation"),
    ),
    (
        frozenset({"model.keras", "best.keras", "model.pt", "model.pth"}),
        ("trainer", "train"),
    ),
    (
        frozenset({"model.tflite", "labels.txt", "model.onnx"}),
        ("edge", "optim", "tflite"),
    ),
)
_NODE_DIRNAME_HINTS: tuple[tuple[frozenset[str], tuple[str, ...]], ...] = (
    (frozenset({"saved_model", "checkpoints"}), ("trainer", "train")),
    (frozenset({"tflite"}), ("edge", "optim", "tflite")),
)

_PATH_VALUE_KEYS = frozenset(
    {
        "path",
        "model_path",
        "output_path",
        "output_dir",
        "file_path",
        "saved_path",
        "artifact_path",
        "keras_model_path",
        "manifest_path",
        "root",
    }
)


def _candidate_fs_paths(raw: str | Path) -> list[Path]:
    """Expand a stored path string into plausible on-disk locations."""
    text = str(raw).strip()
    if not text:
        return []
    path = Path(text)
    out: list[Path] = []
    if path.is_absolute():
        out.append(path)
        return out
    parts = path.parts
    if parts and parts[0] == "workspace":
        out.append(project_dir() / Path(*parts[1:]))
    if parts and parts[0] == "artifacts":
        out.append(project_dir() / path)
        try:
            out.append(artifacts_dir() / Path(*parts[1:]))
        except Exception:
            pass
    out.extend((Path.cwd() / path, project_dir() / path, repo_root() / path))
    return out


def _looks_like_path_string(value: str) -> bool:
    text = value.replace("\\", "/").strip()
    if not text or len(text) > 512 or "\n" in text:
        return False
    if text.startswith(("/", "./", "../", "workspace/", "artifacts/", "examples/")):
        return True
    if "/" not in text:
        return False
    suffix = Path(text).suffix.lower()
    return suffix in ALLOWED_SUFFIXES or text.rstrip("/").endswith(
        ("saved_model", "checkpoints", "tflite", "output", "data")
    )


def _path_strings_from_json(
    obj: Any, *, key: str | None = None, skip_keys: frozenset[str] | None = None
) -> list[str]:
    """Collect filesystem-looking strings from serialized node data.json."""
    found: list[str] = []
    if isinstance(obj, str):
        if skip_keys and key in skip_keys:
            return found
        if key in _PATH_VALUE_KEYS or _looks_like_path_string(obj):
            if _looks_like_path_string(obj):
                found.append(obj)
        return found
    if isinstance(obj, dict):
        for k, v in obj.items():
            found.extend(_path_strings_from_json(v, key=str(k), skip_keys=skip_keys))
        return found
    if isinstance(obj, list):
        # Skip huge tensor dumps; only scan short lists of path-like values.
        if len(obj) > 64:
            return found
        for item in obj:
            found.extend(_path_strings_from_json(item, key=key, skip_keys=skip_keys))
    return found


def _artifact_skip_path_keys(node_id: str) -> frozenset[str]:
    """Evaluator data.json often re-points at the trainer's model — don't steal it."""
    low = (node_id or "").lower()
    if "evaluator" in low or "evaluation" in low:
        return frozenset({"model_path", "path"})
    return frozenset()


def _load_data_json_paths(data_root: Path, *, node_id: str = "") -> list[str]:
    """Read path refs from an ArtifactStore data dir (or data.json file)."""
    candidates: list[Path] = []
    try:
        resolved = data_root.resolve()
    except OSError:
        return []
    if resolved.is_file() and resolved.name == "data.json":
        candidates.append(resolved)
    elif resolved.is_dir():
        candidates.append(resolved / "data.json")
    skip = _artifact_skip_path_keys(node_id)
    for path in candidates:
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        return _path_strings_from_json(raw, skip_keys=skip)
    return []


def _paths_from_artifact_record(record: Any) -> list[Path]:
    paths: list[Path] = []
    nid = str(getattr(record, "node_id", "") or "").strip()
    data_path = getattr(record, "data_path", None)
    data_roots: list[Path] = []
    if isinstance(data_path, str) and data_path.strip():
        for candidate in _candidate_fs_paths(data_path):
            paths.append(candidate)
            data_roots.append(candidate)
    metadata = getattr(record, "metadata", None) or {}
    if isinstance(metadata, dict):
        for key in (
            "path",
            "model_path",
            "output_path",
            "file_path",
            "saved_path",
            "artifact_path",
        ):
            if key in _artifact_skip_path_keys(nid):
                continue
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                paths.extend(_candidate_fs_paths(value))
    dump = record.model_dump() if hasattr(record, "model_dump") else {}
    if isinstance(dump, dict):
        for key in ("path", "data_path"):
            value = dump.get(key)
            if isinstance(value, str) and value.strip():
                paths.extend(_candidate_fs_paths(value))
    for root in data_roots:
        for ref in _load_data_json_paths(root, node_id=nid):
            paths.extend(_candidate_fs_paths(ref))
    # Unique existing paths (prefer resolved) so duplicate candidates cannot
    # inflate the listing cap before later nodes are visited.
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        try:
            key = str(path.resolve()) if path.exists() else str(path)
        except OSError:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


_MAX_AUDIO_SAMPLES_LISTED = 8


def _collect_artifact_data_dir(
    root: Path, *, limit: int, this_run_id: str | None = None
) -> list[Path]:
    """List an ArtifactStore data/ dir; summarize large audio-sample dumps."""
    if limit <= 0:
        return []
    try:
        resolved = root.resolve()
    except OSError:
        return []
    if not resolved.is_dir():
        return _collect_listed_paths(root, limit=limit, this_run_id=this_run_id)
    audio_files: list[Path] = []
    other: list[Path] = []
    try:
        for child in sorted(resolved.iterdir()):
            if not child.is_file() or child.name.startswith("."):
                continue
            if child.suffix.lower() in _DATASET_AUDIO_SUFFIXES:
                audio_files.append(child)
            elif _allowed_file(child):
                other.append(child)
    except OSError:
        return _collect_listed_paths(root, limit=limit, this_run_id=this_run_id)
    if len(audio_files) <= _MAX_AUDIO_SAMPLES_LISTED:
        return _collect_listed_paths(root, limit=limit, this_run_id=this_run_id)
    # Prefer manifest/meta + a few sample clips so the run cap stays usable.
    preferred = [
        p
        for p in other
        if p.name.lower() in {"manifest.json", "data.json", "metadata.json", "labels.csv"}
    ]
    rest_other = [p for p in other if p not in preferred]
    picked = preferred + rest_other + audio_files[:_MAX_AUDIO_SAMPLES_LISTED]
    out: list[Path] = []
    for path in picked:
        if len(out) >= limit:
            break
        try:
            resolved_file = path.resolve()
        except OSError:
            continue
        if is_under_jail(resolved_file):
            out.append(resolved_file)
    return out


def _attr_priority(node_id: str) -> int:
    """Lower stamps first so producers win shared folders over consumers."""
    low = (node_id or "").lower()
    if any(h in low for h in ("trainer", "train", "model_builder", "edge", "optim")):
        return 0
    if any(h in low for h in ("evaluator", "evaluation")):
        return 2
    return 1


def _match_node_hint(name: str, nodes: list[str], hints: tuple[str, ...]) -> str | None:
    lower_nodes = [(n, n.lower()) for n in nodes if n]
    for hint in hints:
        hits = [n for n, low in lower_nodes if hint in low]
        if len(hits) == 1:
            return hits[0]
    return None


def _hint_node_for_path(path: Path, nodes: list[str]) -> str | None:
    """Attribute shared-run-dir files to a node via basename/dirname conventions."""
    if not nodes:
        return None
    lower_name = path.name.lower()
    for names, hints in _NODE_BASENAME_HINTS:
        if lower_name in names:
            hit = _match_node_hint(lower_name, nodes, hints)
            if hit:
                return hit
    for part in path.parts:
        low = part.lower()
        for names, hints in _NODE_DIRNAME_HINTS:
            if low in names:
                hit = _match_node_hint(low, nodes, hints)
                if hit:
                    return hit
    return None


def _looks_like_output_path(key: str, value: str) -> bool:
    posix = value.replace("\\", "/").strip()
    if not posix:
        return False
    if key in ("output_path", "model_path", "output_dir", "root"):
        return True
    if key != "path":
        return False
    lowered = posix.lower()
    if "/data/" in f"/{lowered}/" and "/output/" not in lowered:
        return False
    if "workspace/artifacts" in lowered or "/output/" in f"/{lowered}/" or lowered.endswith("/output"):
        return True
    suffix = Path(posix).suffix.lower()
    return suffix in ALLOWED_SUFFIXES


def _output_paths_from_graph(graph: dict[str, Any]) -> list[Path]:
    found: list[Path] = []
    nodes = graph.get("nodes") or []
    if not isinstance(nodes, list):
        return found
    for node in nodes:
        if not isinstance(node, dict):
            continue
        config = node.get("config") or {}
        if not isinstance(config, dict):
            continue
        for key in ("output_path", "model_path", "output_dir", "path", "root"):
            value = config.get(key)
            if isinstance(value, str) and value.strip() and _looks_like_output_path(key, value):
                found.append(Path(value))
    return found


def _artifact_dirs_from_graph(graph: dict[str, Any]) -> list[Path]:
    """Folders under project artifacts/ referenced by the graph (plus slug)."""
    roots: list[Path] = []
    try:
        art = artifacts_dir()
    except Exception:
        return roots
    roots.append(art)
    slugs: set[str] = set()
    meta = graph.get("metadata") if isinstance(graph, dict) else None
    if isinstance(meta, dict) and meta.get("name"):
        from app.core.workspace_paths import artifact_slug

        slugs.add(artifact_slug(str(meta["name"])))
    for raw in _output_paths_from_graph(graph):
        posix = str(raw).replace("\\", "/")
        marker = "workspace/artifacts/"
        if marker in posix:
            rest = posix.split(marker, 1)[1]
            slug = rest.split("/", 1)[0]
            if slug:
                slugs.add(slug)
        elif posix.startswith("artifacts/"):
            slug = posix.split("/", 2)[1] if posix.count("/") >= 1 else ""
            if slug:
                slugs.add(slug)
    for slug in slugs:
        roots.append(art / slug)
    return roots


def _load_run_graph(run_dir: Path) -> dict[str, Any]:
    graph_path = run_dir / "graph.json"
    if not graph_path.is_file():
        return {}
    try:
        data = json.loads(graph_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _dedupe_files(paths: Iterable[Path], *, limit: int = _MAX_LISTED_FILES) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for path in paths:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        out.append(resolved)
        if len(out) >= limit:
            break
    return out


def _stamp_path_tree(
    attribution: dict[str, str],
    root: Path,
    node_id: str,
    *,
    limit: int = 200,
) -> None:
    """Record node_id for root and allowed files under it (no overwrite)."""
    if not node_id:
        return
    try:
        resolved = root.resolve()
    except OSError:
        return
    key = str(resolved)
    attribution.setdefault(key, node_id)
    if resolved.is_file():
        return
    if not resolved.is_dir():
        return
    n = 0
    for child in _walk_allowed_files(resolved, limit=limit):
        attribution.setdefault(str(child.resolve()), node_id)
        n += 1
        if n >= limit:
            break


def _graph_node_output_paths(graph: dict[str, Any]) -> list[tuple[str, Path]]:
    """(node_id, output path) pairs from graph config for attribution."""
    found: list[tuple[str, Path]] = []
    nodes = graph.get("nodes") or []
    if not isinstance(nodes, list):
        return found
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or f"{node.get('type', 'node')}_{i}").strip()
        config = node.get("config") or {}
        if not isinstance(config, dict):
            continue
        for key in ("output_path", "model_path", "output_dir", "path", "root"):
            value = config.get(key)
            if isinstance(value, str) and value.strip() and _looks_like_output_path(key, value):
                for candidate in _candidate_fs_paths(value):
                    found.append((node_id, candidate))
    return found


def _run_slug(run_id: str, run_dir: Path, graph: dict[str, Any]) -> str | None:
    from app.core.workspace_paths import artifact_slug, slug_from_artifacts_posix

    meta_path = run_dir / "meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        if isinstance(meta, dict):
            artifacts = meta.get("artifacts_dir")
            if isinstance(artifacts, str) and artifacts.strip():
                slug = slug_from_artifacts_posix(artifacts)
                if slug:
                    return slug
            name = meta.get("graph_name")
            if isinstance(name, str) and name.strip():
                return artifact_slug(name)
    meta = graph.get("metadata") if isinstance(graph, dict) else None
    if isinstance(meta, dict) and meta.get("name"):
        return artifact_slug(str(meta["name"]))
    for raw in _output_paths_from_graph(graph):
        slug = slug_from_artifacts_posix(str(raw))
        if slug:
            return slug
    return None


def list_run_output_files(run_id: str, run_dir: Path) -> list[dict[str, Any]]:
    """Collect downloadable files for a run.

    Sources:
      (a) journal files under workspace/runs/<run_id>/
      (b) workspace/artifacts/<slug>/runs/<run_id>/
      (c) ArtifactRecord paths for this run_id (data dir + path refs inside data.json)
      (d) latest/ only when the pointer/symlink targets this run_id
      (e) the stable workspace/artifacts/<slug>/dataset/ tree
    Does not walk sibling run folders or the whole artifacts tree.

    Each entry may include ``node_id`` when the file is tied to a node via the
    artifact store, data.json path refs, graph output_path, or basename hints.
    """
    from app.core.workspace_paths import ARTIFACTS_PREFIX, artifact_fs_path, artifact_layout, latest_run_id

    collected: list[Path] = []
    seen_keys: set[str] = set()
    attribution: dict[str, str] = {}
    node_ids: list[str] = []

    def _add_paths(paths: Iterable[Path], *, node_id: str | None = None) -> None:
        for path in paths:
            if len(collected) >= _MAX_LISTED_FILES:
                return
            try:
                resolved = path.resolve()
            except OSError:
                continue
            key = str(resolved)
            if key in seen_keys:
                if node_id:
                    attribution.setdefault(key, node_id)
                continue
            seen_keys.add(key)
            collected.append(resolved)
            if node_id:
                attribution.setdefault(key, node_id)

    _add_paths(_collect_listed_paths(run_dir, limit=_MAX_LISTED_FILES, this_run_id=run_id))

    graph = _load_run_graph(run_dir)
    for node_id, raw in _graph_node_output_paths(graph):
        if node_id and node_id not in node_ids:
            node_ids.append(node_id)
        remaining = _MAX_LISTED_FILES - len(collected)
        if remaining <= 0:
            break
        batch = _collect_listed_paths(raw, limit=remaining, this_run_id=run_id)
        stamp_id: str | None = None
        try:
            resolved = raw.resolve()
            name = resolved.name.lower()
            if name != run_id.lower() and (
                resolved.is_file() or name not in {run_id.lower(), "runs"}
            ):
                stamp_id = node_id
        except OSError:
            stamp_id = None
        _add_paths(batch, node_id=stamp_id)
        if stamp_id:
            _stamp_path_tree(attribution, raw, stamp_id)

    slug = _run_slug(run_id, run_dir, graph)
    if slug:
        layout = artifact_layout(slug, run_id)
        remaining = _MAX_LISTED_FILES - len(collected)
        if remaining > 0:
            _add_paths(
                _collect_listed_paths(
                    artifact_fs_path(layout["run_dir"]),
                    limit=remaining,
                    this_run_id=run_id,
                )
            )
        if latest_run_id(slug) == run_id:
            remaining = _MAX_LISTED_FILES - len(collected)
            if remaining > 0:
                _add_paths(
                    _collect_listed_paths(
                        artifact_fs_path(layout["latest_dir"]),
                        limit=remaining,
                        this_run_id=run_id,
                    )
                )
        remaining = _MAX_LISTED_FILES - len(collected)
        if remaining > 0:
            _add_paths(
                _collect_listed_paths(
                    artifact_fs_path(f"{ARTIFACTS_PREFIX}/{slug}/dataset"),
                    limit=remaining,
                    this_run_id=run_id,
                )
            )

    try:
        from app.core.artifact_store import ArtifactStore

        records = list(ArtifactStore().list(run_id=run_id))
        records.sort(
            key=lambda r: (
                _attr_priority(str(getattr(r, "node_id", "") or "")),
                str(getattr(r, "node_id", "") or ""),
            )
        )
        for record in records:
            nid = str(getattr(record, "node_id", "") or "").strip()
            if nid and nid not in node_ids:
                node_ids.append(nid)
            for raw in _paths_from_artifact_record(record):
                remaining = _MAX_LISTED_FILES - len(collected)
                if remaining <= 0:
                    break
                try:
                    resolved = raw.resolve()
                    use_audio_cap = (
                        resolved.is_dir() and resolved.name.lower() == "data"
                    )
                except OSError:
                    use_audio_cap = False
                if use_audio_cap:
                    batch = _collect_artifact_data_dir(
                        raw, limit=remaining, this_run_id=run_id
                    )
                else:
                    batch = _collect_listed_paths(
                        raw, limit=remaining, this_run_id=run_id
                    )
                _add_paths(batch, node_id=nid or None)
                if nid:
                    _stamp_path_tree(attribution, raw, nid)
    except Exception:
        pass

    for raw in _output_paths_from_graph(graph):
        bases: list[Path] = []
        if raw.is_absolute():
            bases.append(raw)
        else:
            bases.extend(_candidate_fs_paths(raw))
        for candidate in bases:
            remaining = _MAX_LISTED_FILES - len(collected)
            if remaining <= 0:
                break
            _add_paths(
                _collect_listed_paths(candidate, limit=remaining, this_run_id=run_id)
            )

    entries: list[dict[str, Any]] = []
    for path in collected:
        key = str(path.resolve())
        node_id = attribution.get(key)
        if not node_id:
            node_id = _hint_node_for_path(path, node_ids)
        entries.append(file_entry(path, node_id=node_id))
    return entries


def pack_outputs_zip(entries: list[dict[str, Any]]) -> bytes:
    """Zip listed files; names are uniqued by parent folder when needed."""
    buf = io.BytesIO()
    used_names: set[str] = set()
    total = 0
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for entry in entries:
            if entry.get("kind") == "dir":
                continue
            raw = str(entry.get("path") or "")
            try:
                path = resolve_download_path(raw)
            except OutputPathError:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            total += size
            if total > _MAX_ZIP_BYTES:
                break
            arc = path.name
            if arc in used_names:
                arc = f"{path.parent.name}_{path.name}"
            used_names.add(arc)
            zf.write(path, arcname=arc)
    return buf.getvalue()
