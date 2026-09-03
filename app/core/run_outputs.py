# app/core/run_outputs.py
"""
Bounded Context:  REST API Layer helpers
Responsibility:   Path-jailed discovery and download of pipeline output files.
Owns:             Jail roots, allow-list, listing run outputs, zip packing.
Public Surface:   list_run_output_files, resolve_download_path, pack_outputs_zip,
                  OutputPathError, ALLOWED_SUFFIXES.
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
    if not suffix and parent in {"saved_model", "variables"}:
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


def file_entry(path: Path, *, kind: str | None = None) -> dict[str, Any]:
    resolved = path.resolve()
    is_dir = resolved.is_dir()
    size = 0
    if not is_dir:
        try:
            size = resolved.stat().st_size
        except OSError:
            size = 0
    return {
        "name": resolved.name,
        "path": _display_path(resolved),
        "size": size,
        "kind": kind or ("dir" if is_dir else "file"),
    }


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


def _paths_from_artifact_record(record: Any) -> list[Path]:
    paths: list[Path] = []
    data_path = getattr(record, "data_path", None)
    if isinstance(data_path, str) and data_path.strip():
        paths.append(Path(data_path))
        paths.append(project_dir() / data_path)
        paths.append(artifacts_dir() / data_path)
    metadata = getattr(record, "metadata", None) or {}
    if isinstance(metadata, dict):
        for key in ("path", "model_path", "output_path", "file_path", "saved_path"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                paths.append(Path(value))
    dump = record.model_dump() if hasattr(record, "model_dump") else {}
    if isinstance(dump, dict):
        for key in ("path", "data_path"):
            value = dump.get(key)
            if isinstance(value, str) and value.strip():
                paths.append(Path(value))
    return paths


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
      (c) ArtifactRecord paths for this run_id
      (d) latest/ only when the pointer/symlink targets this run_id
      (e) the stable workspace/artifacts/<slug>/dataset/ tree
    Does not walk sibling run folders or the whole artifacts tree.
    """
    from app.core.workspace_paths import ARTIFACTS_PREFIX, artifact_fs_path, artifact_layout, latest_run_id

    collected: list[Path] = []
    collected.extend(_collect_listed_paths(run_dir, limit=_MAX_LISTED_FILES, this_run_id=run_id))

    graph = _load_run_graph(run_dir)
    slug = _run_slug(run_id, run_dir, graph)
    if slug:
        layout = artifact_layout(slug, run_id)
        remaining = _MAX_LISTED_FILES - len(collected)
        if remaining > 0:
            collected.extend(
                _collect_listed_paths(
                    artifact_fs_path(layout["run_dir"]),
                    limit=remaining,
                    this_run_id=run_id,
                )
            )
        if latest_run_id(slug) == run_id:
            remaining = _MAX_LISTED_FILES - len(collected)
            if remaining > 0:
                collected.extend(
                    _collect_listed_paths(
                        artifact_fs_path(layout["latest_dir"]),
                        limit=remaining,
                        this_run_id=run_id,
                    )
                )
        remaining = _MAX_LISTED_FILES - len(collected)
        if remaining > 0:
            collected.extend(
                _collect_listed_paths(
                    artifact_fs_path(f"{ARTIFACTS_PREFIX}/{slug}/dataset"),
                    limit=remaining,
                    this_run_id=run_id,
                )
            )

    try:
        from app.core.artifact_store import ArtifactStore

        for record in ArtifactStore().list(run_id=run_id):
            for raw in _paths_from_artifact_record(record):
                remaining = _MAX_LISTED_FILES - len(collected)
                if remaining <= 0:
                    break
                collected.extend(_collect_listed_paths(raw, limit=remaining, this_run_id=run_id))
    except Exception:
        pass

    for raw in _output_paths_from_graph(graph):
        bases: list[Path] = []
        if raw.is_absolute():
            bases.append(raw)
        else:
            parts = raw.parts
            if parts and parts[0] == "workspace":
                bases.append(project_dir() / Path(*parts[1:]))
            bases.extend((Path.cwd() / raw, project_dir() / raw, repo_root() / raw))
        for candidate in bases:
            remaining = _MAX_LISTED_FILES - len(collected)
            if remaining <= 0:
                break
            collected.extend(_collect_listed_paths(candidate, limit=remaining, this_run_id=run_id))

    files = _dedupe_files(collected)
    return [file_entry(p) for p in files]


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
