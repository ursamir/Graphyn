# app/core/runs/run_outputs.py
"""
Bounded Context:  REST API Layer helpers
Responsibility:   Path-jailed discovery and download of pipeline output files.
Owns:             Jail roots, allow-list, listing run outputs, zip packing.
Public Surface:   list_run_output_files (entries may include node_id),
                  list_run_output_files_detail (items + per-node truncation +
                  inputs_by_node; prioritised, per-node-fair 400 cap),
                  list_run_output_files_for_zip (higher cap for zip packs),
                  list_node_output_files (page one node's files),
                  is_project_metadata_path, resolve_download_path,
                  natural_sort_key (listing order: digit runs compared numerically),
                  pack_outputs_zip (node_id/ subfolders; returns bytes + truncated),
                  OutputPathError, ALLOWED_SUFFIXES.
Must NOT:         Serve files outside project_dir, graphyn_home, or repo examples/,
                  nor config/secret files inside them (webhooks.json, plugin
                  registry, credentials/secrets/audit dirs, *.sqlite, dotfiles);
                  must not attribute ProjectManager-owned project metadata
                  (project.json, spec.md, pipelines/, …) to a run's nodes;
                  must not rediscover domain trees (labels.csv walks, …) —
                  listing uses ArtifactStore + ArtifactTypeHandler.list_files.
Dependencies:     stdlib, app.core.config, app.core.templates.example_templates,
                  app.core.runs.outputs_index, app.core.artifacts.artifact_serializer.
Reason To Change: New output locations, allow-list, or listing sources.
"""
from __future__ import annotations

import io
import json
import os
import re
import zipfile
from pathlib import Path
from typing import Any, Iterable

from app.core.config import artifacts_dir, datasets_output_dir, graphyn_home, project_dir
from app.core.templates.example_templates import examples_dir, repo_root

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
        ".bmp",
        ".json",
        ".jsonl",
        ".keras",
        ".tflite",
        ".zip",
        ".gz",  # deployment_packager edge / docker packages (.tar.gz)
        ".tgz",
        ".h",  # deployment_packager MCU header
        ".h5",
        ".pb",
        ".txt",
        ".npy",
        ".npz",
        ".npzz",
        ".index",
        ".onnx",
        ".ckpt",
        ".pt",
        ".pth",
        ".pkl",
        ".pickle",
        ".csv",
        ".wav",
        ".flac",
        ".mp3",
        ".ogg",
        ".m4a",
        ".aac",
        ".webm",
        ".mp4",
        ".mov",
        ".mkv",
        ".avi",
        ".md",
        ".log",
        ".yaml",
        ".yml",
        ".toml",
        ".html",
        ".htm",
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
# Zip download uses a higher prioritised cap so "Download all" is closer to complete
# than the UI listing (still bounded — huge wav trees are not fully packed).
_MAX_ZIP_FILES = 2000
# Candidates gathered before prioritised selection trims to _MAX_LISTED_FILES.
_MAX_CANDIDATES = 5000
# Share of the cap reserved (at most) for model / metrics / small summary files.
_KEY_FILE_SHARE = 0.5
_KEY_FILE_SUFFIXES = frozenset({".tflite", ".keras", ".onnx", ".h5", ".pt", ".pth", ".zip"})
_SUMMARY_SUFFIXES = frozenset({".json", ".md", ".txt", ".csv", ".png", ".jpg", ".jpeg", ".svg"})
_SUMMARY_MAX_BYTES = 1024 * 1024
# Per-tree audio sample budget during listing walks. Preprocess exporters write
# thousands of wavs; collecting them all for a 400-cap list burned seconds and
# starved other nodes of slots. Full totals still come from a cheap count.
_MAX_AUDIO_SAMPLES_PER_TREE = 16
# Config keys a *source* node (no incoming edges) reads its input from.
_INPUT_PATH_KEYS = ("path", "data_dir")
# Hard cap when counting / paging a single node's files (``?node_id=``).
_MAX_NODE_SCAN = 50_000
# ArtifactStore often serialises whole tensors into data.json (hundreds of MB).
# Path extraction must not json.loads those; listing omits them as downloads.
_MAX_DATA_JSON_PARSE_BYTES = 2 * 1024 * 1024
_MAX_DATA_JSON_LIST_BYTES = 8 * 1024 * 1024

# Files / dirs at the top of datasets/output/<project>/ that belong to the
# ProjectManager (not to any pipeline node). The audio_exporter writes its
# version dir (v1/…) into the same folder, so walks of that folder must skip
# these or a run would "own" the whole project.
_PROJECT_META_NAMES = frozenset(
    {
        "project.json",
        "spec.md",
        "taxonomy.json",
        "contract.json",
        "links.json",
        "environments.json",
        "quality_report.json",
        "curation_decisions.json",
        "lineage.json",
        "pipelines",
        "snapshots",
        "versions",
    }
)
_PROJECT_META_PREFIXES = ("annotations", "curation")
_PROJECT_META_SUFFIXES = (".lock", ".tmp", ".bak", ".partial")


_NATURAL_SPLIT_RE = re.compile(r"(\d+)")


def natural_sort_key(name: str | Path) -> tuple[Any, ...]:
    """Sort key comparing digit runs numerically (``2.wav`` < ``10.wav``).

    Used for every directory walk in this module so per-node truncation keeps
    the *first* N files a human expects (0, 1, 2, …) instead of the
    lexicographic 0, 1, 10, 100, ….
    """
    text = name.name if isinstance(name, Path) else str(name)
    parts = _NATURAL_SPLIT_RE.split(text)
    key: list[Any] = []
    for i, part in enumerate(parts):
        if i % 2:
            key.append((0, int(part), part))
        else:
            key.append((1, part.lower(), part))
    return tuple(key)


def is_project_metadata_path(path: Path) -> bool:
    """True when ``path`` is ProjectManager-owned metadata (or the project dir).

    Only applies under ``datasets/output/<project>/`` when that folder holds a
    ``project.json``; everything else returns False.
    """
    try:
        resolved = path.resolve()
        base = datasets_output_dir().resolve()
        if not resolved.is_relative_to(base):
            return False
        parts = resolved.relative_to(base).parts
    except (OSError, ValueError):
        return False
    if not parts:
        return True
    if not (base / parts[0] / "project.json").is_file():
        return False
    if len(parts) == 1:
        return True  # the project folder itself — not a node output
    top = parts[1].lower()
    if top in _PROJECT_META_NAMES or top.startswith("."):
        return True
    if top.startswith(_PROJECT_META_PREFIXES):
        return True
    if any(".tmp" in part.lower() or part.startswith(".") for part in parts[1:]):
        return True
    return resolved.name.lower().endswith(_PROJECT_META_SUFFIXES)
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


_JAIL_ROOTS_CACHE: tuple[tuple[str, str, str], tuple[Path, ...]] | None = None


def jail_roots() -> list[Path]:
    """Jail roots for download / listing checks.

    Cached for the current ``GRAPHYN_PROJECT_DIR`` / ``GRAPHYN_HOME`` /
    examples root — a preprocess outputs listing previously called this
    ~16k times (resolve × 3 each).
    """
    global _JAIL_ROOTS_CACHE
    key = (
        os.environ.get("GRAPHYN_PROJECT_DIR", ""),
        os.environ.get("GRAPHYN_HOME", ""),
        os.environ.get("GRAPHYN_EXAMPLES_DIR", ""),
    )
    cached = _JAIL_ROOTS_CACHE
    if cached is not None and cached[0] == key:
        return list(cached[1])
    roots: list[Path] = []
    for candidate in (project_dir(), graphyn_home(), examples_dir()):
        try:
            roots.append(candidate.resolve())
        except OSError:
            continue
    seen: set[str] = set()
    unique: list[Path] = []
    for root in roots:
        s = str(root)
        if s not in seen:
            seen.add(s)
            unique.append(root)
    _JAIL_ROOTS_CACHE = (key, tuple(unique))
    return list(unique)


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
    # Internal run-cache files are not console downloadables.
    if path.name.lower() in {"outputs_index.json"}:
        return False
    suffix = path.suffix.lower()
    # ArtifactStore data.json often holds dumped tensors (hundreds of MB). Those
    # are not console downloadables — listing them invited 20 s UI stalls when
    # path-scanning tried to parse the whole file.
    if path.name.lower() == "data.json":
        try:
            if path.stat().st_size > _MAX_DATA_JSON_LIST_BYTES:
                return False
        except OSError:
            return False
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


# Config / secret material that lives inside the jail roots but must never be
# served by GET /outputs/file (webhook URL = secret, plugin registry sources,
# credential DB, audit log, worker/distributed state, dotenv files).
_DENIED_DOWNLOAD_DIR_NAMES = frozenset(
    {"credentials", "secrets", "audit", "plugins", "distributed", ".git", ".ssh", ".graphyn"}
)
_DENIED_DOWNLOAD_FILE_NAMES = frozenset(
    {
        "webhooks.json",
        "registry.json",
        "schedules.json",
        "notifications.jsonl",
        "store.sqlite",
        "master.key",
        "credentials.json",
        "secrets.json",
    }
)
_DENIED_DOWNLOAD_SUFFIXES = frozenset(
    {".sqlite", ".sqlite3", ".db", ".key", ".pem", ".lock", ".jsonl", ".env", ".token"}
)


def _is_denied_download(resolved: Path) -> bool:
    """True for config / secret files under a jail root (fail closed)."""
    name = resolved.name.lower()
    if name in _DENIED_DOWNLOAD_FILE_NAMES:
        return True
    if name == ".env" or name.startswith(".env.") or name.startswith("."):
        return True
    if resolved.suffix.lower() in _DENIED_DOWNLOAD_SUFFIXES:
        return True
    for root in jail_roots():
        try:
            if not resolved.is_relative_to(root):
                continue
            rel_parts = resolved.relative_to(root).parts[:-1]
        except (ValueError, OSError):
            continue
        if any(part.lower() in _DENIED_DOWNLOAD_DIR_NAMES or part.startswith(".") for part in rel_parts):
            return True
    return False


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
        if _is_denied_download(chosen):
            raise OutputPathError(403, "Config / secret files are not downloadable")
        if not _allowed_file(chosen):
            raise OutputPathError(415, "File type is not allowed for download")
        return chosen
    if jailed_missing:
        raise OutputPathError(404, "File not found")
    raise OutputPathError(403, "Path is outside allowed directories")


def _walk_allowed_files(
    root: Path,
    *,
    limit: int,
    this_run_id: str | None = None,
    stats: dict[str, int] | None = None,
    audio_cap: int | None = _MAX_AUDIO_SAMPLES_PER_TREE,
) -> list[Path]:
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
    _ = jail_roots()
    audio_kept = 0
    audio_seen = 0
    for dirpath, dirnames, filenames in os.walk(resolved_root):
        dirnames[:] = sorted(
            (
                d
                for d in dirnames
                if d not in _SKIP_DIR_NAMES
                and d not in _SKIP_HEAVY_DIR_NAMES
                and not d.startswith(".")
            ),
            key=natural_sort_key,
        )
        if this_run_id:
            base = Path(dirpath)
            if base.name == "runs":
                dirnames[:] = [d for d in dirnames if d == this_run_id]
        for name in sorted(filenames, key=natural_sort_key):
            if name.startswith("."):
                continue
            suffix = Path(name).suffix.lower()
            is_audio = suffix in _DATASET_AUDIO_SUFFIXES
            if is_audio:
                audio_seen += 1
                if audio_cap is not None and audio_kept >= audio_cap:
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
                if is_audio:
                    audio_kept += 1
                if len(found) >= limit:
                    if stats is not None and audio_seen:
                        stats["audio_seen"] = stats.get("audio_seen", 0) + audio_seen
                    return found
    if stats is not None and audio_seen:
        stats["audio_seen"] = stats.get("audio_seen", 0) + audio_seen
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
            (d for d in dirnames if d not in _SKIP_DIR_NAMES and not d.startswith(".")),
            key=natural_sort_key,
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
        for name in sorted(filenames, key=natural_sort_key):
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
    root: Path,
    *,
    limit: int,
    this_run_id: str | None = None,
    stats: dict[str, int] | None = None,
) -> list[Path]:
    if limit <= 0:
        return []
    if _path_has_dataset_segment(root):
        return _summarize_dataset_tree(root, limit=limit)
    return _walk_allowed_files(
        root, limit=limit, this_run_id=this_run_id, stats=stats
    )


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
    """Read path refs from an ArtifactStore data dir (role manifest, manifest.json or data.json).

    Model / deployment / TFLite artifacts write ``*_artifact_manifest.json``
    with their files copied under ``files/`` — those copies are returned.

    Prefers the small ``manifest.json`` written by typed serializers
    (``audio_samples``, ``dataset_artifact``). Legacy tensor dumps in
    ``data.json`` larger than ``_MAX_DATA_JSON_PARSE_BYTES`` are skipped — those
    belong in ``.npy`` via DatasetArtifactHandler, not JSON.
    """
    candidates: list[Path] = []
    try:
        resolved = data_root.resolve()
    except OSError:
        return []
    if resolved.is_file() and resolved.name in {"data.json", "manifest.json"}:
        candidates.append(resolved)
    elif resolved.is_dir():
        # Typed handlers write manifest.json; generic fallback still uses data.json.
        candidates.append(resolved / "manifest.json")
        candidates.append(resolved / "data.json")
    if resolved.is_dir():
        from app.core.artifacts.artifact_pack import role_manifest_file_paths

        role_files = role_manifest_file_paths(resolved)
        if role_files is not None:
            return role_files
    skip = _artifact_skip_path_keys(node_id)
    for path in candidates:
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > _MAX_DATA_JSON_PARSE_BYTES:
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        found = _path_strings_from_json(raw, skip_keys=skip)
        if found:
            return found
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
    root: Path,
    *,
    limit: int,
    this_run_id: str | None = None,
    stats: dict[str, int] | None = None,
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
        for child in sorted(resolved.iterdir(), key=natural_sort_key):
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
    if stats is not None:
        stats["total"] = stats.get("total", 0) + len(audio_files) + len(other)
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


def _node_output_roots(graph: dict[str, Any]) -> dict[str, list[str]]:
    """Map node_id → normalized output_path/output_dir prefixes from the run graph."""
    from app.core.paths.write_paths import _resolve_under_project

    out: dict[str, list[str]] = {}
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        nid = str(node.get("id") or "").strip()
        if not nid:
            continue
        cfg = node.get("config") if isinstance(node.get("config"), dict) else {}
        roots: list[str] = []
        for key in ("output_path", "output_dir"):
            raw = cfg.get(key)
            if not isinstance(raw, str) or not raw.strip():
                continue
            posix = raw.replace("\\", "/").rstrip("/")
            roots.append(posix)
            if posix.startswith("workspace/"):
                roots.append(posix[len("workspace/") :])
            try:
                resolved = _resolve_under_project(posix)
            except Exception:
                resolved = None
            if resolved is None:
                try:
                    text = posix
                    if text.startswith("workspace/"):
                        text = text[len("workspace/") :]
                    resolved = (project_dir() / text).resolve()
                except Exception:
                    resolved = None
            if resolved is not None:
                try:
                    roots.append(str(resolved.resolve()).replace("\\", "/"))
                except OSError:
                    roots.append(str(resolved).replace("\\", "/"))
            elif posix.startswith("/"):
                roots.append(posix)
        if roots:
            out[nid] = list(dict.fromkeys(roots))
    return out


def _hint_node_for_path(
    path: Path,
    nodes: list[str],
    *,
    graph: dict[str, Any] | None = None,
) -> str | None:
    """Attribute shared-run-dir files to a node via basename/dirname conventions.

    When several nodes match a hint (two evaluators), prefer the one whose
    configured ``output_path`` is a parent of ``path``.
    """
    if not nodes:
        return None
    lower_name = path.name.lower()
    posix = str(path).replace("\\", "/")
    roots = _node_output_roots(graph) if graph else {}

    def _disambiguate(hits: list[str]) -> str | None:
        if not hits:
            return None
        if len(hits) == 1:
            return hits[0]
        scored: list[tuple[int, str]] = []
        for nid in hits:
            best = -1
            for root in roots.get(nid, []):
                if not root:
                    continue
                if posix == root or posix.startswith(root.rstrip("/") + "/"):
                    best = max(best, len(root))
            if best >= 0:
                scored.append((best, nid))
        if scored:
            scored.sort(reverse=True)
            return scored[0][1]
        return None

    for names, hints in _NODE_BASENAME_HINTS:
        if lower_name in names:
            hits = [n for n in nodes if n and any(h in n.lower() for h in hints)]
            hit = _disambiguate(hits)
            if hit:
                return hit
            hit = _match_node_hint(lower_name, nodes, hints)
            if hit:
                return hit
    # compiled_<uuid>.keras hand-off from ModelBuilder (exact name not fixed).
    if lower_name.startswith("compiled_") and lower_name.endswith(".keras"):
        hits = [n for n in nodes if n and "model_builder" in n.lower()]
        hit = _disambiguate(hits) or _match_node_hint(lower_name, nodes, ("model_builder",))
        if hit:
            return hit
    for part in path.parts:
        low = part.lower()
        for names, hints in _NODE_DIRNAME_HINTS:
            if low in names:
                hits = [n for n in nodes if n and any(h in n.lower() for h in hints)]
                hit = _disambiguate(hits)
                if hit:
                    return hit
                hit = _match_node_hint(low, nodes, hints)
                if hit:
                    return hit
    return None


def _resolve_attributed_node(
    path: Path,
    attributed: str | None,
    nodes: list[str],
    graph: dict[str, Any],
) -> str | None:
    """Prefer basename/dir producer hints over shared-folder path stamps.

    Shared ``output_path`` between trainer+evaluator used to stamp eval plots
    onto the trainer (trainers win ``_attr_priority``). Basename hints correct
    that when the file is clearly an evaluator / edge / trainer product.
    """
    hinted = _hint_node_for_path(path, nodes, graph=graph)
    if hinted:
        return hinted
    return attributed or None


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


_VERSION_TAG_RE = re.compile(r"^v\d+(\.\d+)*$")


def _node_config_output_paths(config: dict[str, Any]) -> list[str]:
    """Output path strings a node config points at.

    Version-stamping exporters (``version_tag`` + ``output_dir``/``project``)
    write only ``<output_dir>/<version_tag>/``; the parent is the
    ProjectManager project folder, so report the version dir instead.
    """
    version_tag = str(config.get("version_tag") or "").strip()
    if version_tag and _VERSION_TAG_RE.match(version_tag):
        project = str(config.get("project") or "").strip()
        if project:
            return [f"workspace/datasets/output/{project}/{version_tag}"]
        out_dir = config.get("output_dir")
        if isinstance(out_dir, str) and out_dir.strip():
            return [f"{out_dir.rstrip('/')}/{version_tag}"]
    found: list[str] = []
    for key in ("output_path", "model_path", "output_dir", "path", "root"):
        value = config.get(key)
        if isinstance(value, str) and value.strip() and _looks_like_output_path(key, value):
            found.append(value)
    return found


def _output_paths_from_graph(graph: dict[str, Any], *, skip: Any = None) -> list[Path]:
    found: list[Path] = []
    nodes = graph.get("nodes") or []
    if not isinstance(nodes, list):
        return found
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        config = node.get("config") or {}
        if not isinstance(config, dict):
            continue
        node_id = str(node.get("id") or f"{node.get('type', 'node')}_{i}").strip()
        found.extend(
            Path(v)
            for v in _node_config_output_paths(config)
            if skip is None or not skip(node_id, v)
        )
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
        from app.core.paths.workspace_paths import artifact_slug

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


def _iter_configured_write_roots(graph: dict[str, Any]) -> list[tuple[str, Path]]:
    """Node id + resolved write roots from IR config (WRITE_CONFIG_KEYS).

    This is not scavenger rediscovery: only paths the graph declared as write
    destinations for a named node. Bridges runs that finished before
    ``publish_files`` / isolated envelope (plots, tflite, …).
    """
    from app.core.paths.write_paths import WRITE_CONFIG_KEYS, _resolve_under_project

    out: list[tuple[str, Path]] = []
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        nid = str(node.get("id") or "").strip()
        if not nid:
            continue
        cfg = node.get("config")
        if not isinstance(cfg, dict):
            continue
        for key in WRITE_CONFIG_KEYS:
            raw = cfg.get(key)
            if not isinstance(raw, str) or not raw.strip():
                continue
            try:
                root = _resolve_under_project(raw.strip())
            except Exception:
                root = None
            if root is None:
                try:
                    text = raw.strip().replace("\\", "/")
                    if text.startswith("workspace/"):
                        text = text[len("workspace/") :]
                    root = (project_dir() / text).resolve()
                except Exception:
                    continue
            if root.is_dir() and is_under_jail(root):
                out.append((nid, root))
    return out


def _collect_configured_write_files(
    graph: dict[str, Any],
    *,
    seen_keys: set[str],
    collected: list[Path],
    attribution: dict[str, str],
    node_ids: list[str],
    per_root_cap: int = 64,
    ctx: "_ListingContext | None" = None,
    input_filter: "_InputFilter | None" = None,
) -> None:
    """Merge allowed files from graph-declared write dirs into the listing.

    When *ctx* is given, the node's full file total under the declared root is
    recorded in ``ctx.summarized_totals`` so truncation metadata is honest.
    """
    for nid, root in _iter_configured_write_roots(graph):
        if nid not in node_ids:
            node_ids.append(nid)
        if ctx is not None:
            ctx.add_root(nid, root)
            total = _count_allowed_files_fast([root], this_run_id=None, cap=_MAX_NODE_SCAN)
            if total:
                ctx.summarized_totals[nid] = max(ctx.summarized_totals.get(nid, 0), total)
                if total > per_root_cap:
                    ctx.capped = True
        count = 0
        try:
            children = sorted(root.rglob("*"), key=natural_sort_key)
        except OSError:
            continue
        for child in children:
            if count >= per_root_cap:
                break
            try:
                if not child.is_file():
                    continue
                resolved = child.resolve()
            except OSError:
                continue
            if is_project_metadata_path(resolved):
                continue
            if not is_under_jail(resolved) or not _allowed_file(resolved):
                continue
            if input_filter is not None and input_filter.input_owner(resolved):
                continue
            key = str(resolved)
            if key in seen_keys:
                attribution.setdefault(key, nid)
                continue
            seen_keys.add(key)
            collected.append(resolved)
            attribution[key] = nid
            count += 1


def _dedupe_files(paths: Iterable[Path], *, limit: int | None = None) -> list[Path]:
    if limit is None:
        limit = _MAX_LISTED_FILES
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
    """Record node_id for ``root`` (files under it are attributed in ``_add_paths``).

    Previously walked up to ``limit`` files under every output root; on Example 06
    preprocess that re-scanned thousands of wavs for no listing benefit.
    """
    if not node_id:
        return
    try:
        resolved = root.resolve()
    except OSError:
        return
    attribution.setdefault(str(resolved), node_id)
    # ``limit`` kept for call-site compatibility; walking is intentionally skipped.
    _ = limit


def _name_looks_allowed(name: str) -> bool:
    """Suffix-only allow check for fast counting (no stat / resolve)."""
    if name.startswith("."):
        return False
    lower = name.lower()
    if lower == "data.json":
        return True
    suffix = Path(name).suffix.lower()
    if suffix in ALLOWED_SUFFIXES:
        return True
    return lower.startswith("variables.")


def _count_allowed_files_fast(
    roots: Iterable[Path],
    *,
    this_run_id: str | None,
    cap: int,
) -> int:
    """Count downloadable files under ``roots`` without per-file resolve/jail.

    Roots are already jail-checked when recorded on the listing context. Used
    for ``truncated_by_node.total`` so with_meta does not re-materialise every
    wav path (preprocess exporters: ~3.7k files).
    """
    count = 0
    seen: set[str] = set()
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            continue
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        if resolved.is_file():
            if _name_looks_allowed(resolved.name) and not is_project_metadata_path(resolved):
                count += 1
                if count >= cap:
                    return count
            continue
        if not resolved.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(resolved, followlinks=False):
            dirnames[:] = [
                d
                for d in dirnames
                if d not in _SKIP_DIR_NAMES and not d.startswith(".")
            ]
            base_name = os.path.basename(dirpath)
            if base_name in _PROJECT_META_NAMES:
                dirnames[:] = []
                continue
            if this_run_id and base_name == "runs":
                dirnames[:] = [d for d in dirnames if d == this_run_id]
            for name in filenames:
                if not _name_looks_allowed(name):
                    continue
                count += 1
                if count >= cap:
                    return count
    return count


def _graph_node_output_paths(
    graph: dict[str, Any], *, skip: Any = None
) -> list[tuple[str, Path]]:
    """(node_id, output path) pairs from graph config for attribution.

    ``skip(node_id, value)`` drops config values that are a node's *input*.
    """
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
        for value in _node_config_output_paths(config):
            if skip is not None and skip(node_id, value):
                continue
            for candidate in _candidate_fs_paths(value):
                found.append((node_id, candidate))
    return found


def _run_slug(run_id: str, run_dir: Path, graph: dict[str, Any]) -> str | None:
    from app.core.paths.workspace_paths import artifact_slug, slug_from_artifacts_posix

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


class _ListingContext:
    """Side information gathered while listing a run's outputs."""

    def __init__(self) -> None:
        # node_id -> roots (files / dirs) that node produced
        self.node_roots: dict[str, list[Path]] = {}
        # node_id -> known file totals for summarized artifact data dirs
        self.summarized_totals: dict[str, int] = {}
        # node_id -> number of pre-existing *input* files that were skipped
        self.input_counts: dict[str, int] = {}
        self.capped = False

    def add_root(self, node_id: str | None, root: Path) -> None:
        if not node_id:
            return
        roots = self.node_roots.setdefault(node_id, [])
        if root not in roots:
            roots.append(root)



def _run_started_at(run_dir: Path) -> float | None:
    """Run start (epoch seconds) from meta.json ``created_at``; None if unknown."""
    from datetime import datetime

    try:
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    raw = meta.get("created_at") if isinstance(meta, dict) else None
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.fromisoformat(raw.strip().replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class _InputFilter:
    """Pre-existing files under a source node's input ``path`` are inputs, not outputs.

    A node with no incoming edges that reads ``path`` / ``data_dir`` (e.g. a
    dataset ingest) passes its input files downstream; their paths show up in
    its artifact record and under its config path. Only files written during
    this run (mtime >= run start) are attributed to it as outputs.
    """

    def __init__(self, graph: dict[str, Any], run_dir: Path) -> None:
        self.roots: list[tuple[str, Path]] = []
        self.values: set[tuple[str, str]] = set()
        self.started_at = _run_started_at(run_dir)
        nodes = graph.get("nodes") if isinstance(graph, dict) else None
        edges = graph.get("edges") if isinstance(graph, dict) else None
        if not isinstance(nodes, list):
            return
        targets = {
            str(e.get("dst_id") or e.get("target") or "")
            for e in (edges if isinstance(edges, list) else [])
            if isinstance(e, dict)
        }
        for i, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            nid = str(node.get("id") or f"{node.get('type', 'node')}_{i}").strip()
            if nid in targets:
                continue
            config = node.get("config") or {}
            if not isinstance(config, dict):
                continue
            for key in _INPUT_PATH_KEYS:
                value = config.get(key)
                if not isinstance(value, str) or not value.strip():
                    continue
                self.values.add((nid, value))
                for candidate in _candidate_fs_paths(value):
                    try:
                        resolved = candidate.resolve()
                    except OSError:
                        continue
                    if resolved.exists() and (nid, resolved) not in self.roots:
                        self.roots.append((nid, resolved))

    def reads_from(self, tree: Path) -> bool:
        """True when some input root lies inside (or is) ``tree``."""
        try:
            base = tree.resolve()
        except OSError:
            return False
        return any(root == base or base in root.parents for _nid, root in self.roots)

    def is_input_value(self, node_id: str, value: str) -> bool:
        return (node_id, value) in self.values

    def input_owner(self, resolved: Path) -> str | None:
        """node_id whose input tree holds this pre-existing file, else None."""
        if not self.roots:
            return None
        owner = None
        for nid, root in self.roots:
            if resolved == root or root in resolved.parents:
                owner = nid
                break
        if owner is None:
            return None
        if self.started_at is not None:
            try:
                if resolved.stat().st_mtime >= self.started_at:
                    return None  # written by this run
            except OSError:
                return None
        return owner


def _is_key_file(path: Path) -> bool:
    """Models, metrics and other small summary files (listed before bulk outputs)."""
    suffix = path.suffix.lower()
    if suffix in _KEY_FILE_SUFFIXES:
        return True
    if suffix not in _SUMMARY_SUFFIXES:
        return False
    try:
        return path.is_file() and path.stat().st_size <= _SUMMARY_MAX_BYTES
    except OSError:
        return False


def _round_robin(groups: list[list[Path]], budget: int) -> list[list[Path]]:
    """Take one item per group in turn until ``budget`` is spent (fair share)."""
    picked: list[list[Path]] = [[] for _ in groups]
    idx = [0] * len(groups)
    while budget > 0:
        progressed = False
        for g, items in enumerate(groups):
            if budget <= 0:
                break
            if idx[g] < len(items):
                picked[g].append(items[idx[g]])
                idx[g] += 1
                budget -= 1
                progressed = True
        if not progressed:
            break
    return picked


def _select_listing(
    collected: list[Path],
    node_of: dict[str, str | None],
    node_order: list[str],
    run_dir: Path,
    cap: int,
) -> list[Path]:
    """Prioritised, per-node-fair subset of ``collected`` (at most ``cap``).

    Order: run journal files, then model / metrics / small summary files, then
    bulk files — key and bulk files are each shared round-robin across nodes
    (graph order, unattributed last), so one node cannot fill the cap.
    """
    if len(collected) <= cap:
        return list(collected)
    try:
        run_root = run_dir.resolve()
    except OSError:
        run_root = run_dir
    run_level: list[Path] = []
    rest: list[Path] = []
    for path in collected:
        (run_level if run_root == path or run_root in path.parents else rest).append(path)
    selected = run_level[:cap]
    budget = cap - len(selected)
    if budget <= 0:
        return selected
    order = list(node_order)
    for path in rest:
        nid = node_of.get(str(path))
        if nid and nid not in order:
            order.append(nid)
    keys: list[str | None] = [*order, None]
    key_groups: dict[str | None, list[Path]] = {k: [] for k in keys}
    bulk_groups: dict[str | None, list[Path]] = {k: [] for k in keys}
    for path in rest:
        nid = node_of.get(str(path))
        bucket = key_groups if _is_key_file(path) else bulk_groups
        bucket.setdefault(nid, []).append(path)
    key_budget = min(budget, max(1, int(cap * _KEY_FILE_SHARE)))
    key_pick = _round_robin([key_groups[k] for k in keys], key_budget)
    for group in key_pick:
        selected.extend(group)
    budget = cap - len(selected)
    # Key files that did not fit their share compete with bulk files.
    leftovers: list[list[Path]] = []
    for i, k in enumerate(keys):
        taken = set(key_pick[i])
        leftovers.append([p for p in key_groups[k] if p not in taken] + bulk_groups[k])
    for group in _round_robin(leftovers, budget):
        selected.extend(group)
    return selected


def _resolve_artifact_data_dir(raw: str) -> Path | None:
    """Resolve an ArtifactRecord.data_path under the project jail."""
    text = str(raw or "").replace("\\", "/").strip()
    if not text:
        return None
    path = Path(text)
    try:
        if path.is_absolute():
            resolved = path.resolve()
        else:
            rel = text.lstrip("./")
            if rel.startswith("workspace/"):
                rel = rel[len("workspace/") :]
            resolved = (project_dir() / rel).resolve()
        if not is_under_jail(resolved):
            return None
        return resolved
    except OSError:
        return None


def _shallow_data_dir_files(data_dir: Path, *, limit: int = 64) -> list[Path]:
    """Generic fallback: files directly in data_dir (no deep walk)."""
    found: list[Path] = []
    if not data_dir.is_dir():
        if data_dir.is_file() and _allowed_file(data_dir):
            return [data_dir]
        return found
    try:
        children = sorted(data_dir.iterdir(), key=lambda p: natural_sort_key(p.name))
    except OSError:
        return found
    for child in children:
        if child.name.startswith("."):
            continue
        try:
            resolved = child.resolve()
        except OSError:
            continue
        if not resolved.is_file():
            continue
        if not is_under_jail(resolved) or not _allowed_file(resolved):
            continue
        found.append(resolved)
        if len(found) >= limit:
            break
    return found


def _expand_artifact_entry(
    entry: dict[str, Any],
    *,
    sample_cap: int | None = 32,
) -> tuple[list[Path], int, str | None]:
    """Expand one ArtifactStore index entry via handler.list_files (or shallow)."""
    node_id = str(entry.get("node_id") or "") or None
    data_dir = _resolve_artifact_data_dir(str(entry.get("data_path") or ""))
    if data_dir is None:
        return [], 0, node_id

    artifact_type = str(entry.get("artifact_type") or "")
    try:
        from app.core.artifacts.artifact_serializer import get_serializer_registry

        handler = get_serializer_registry().get(artifact_type) if artifact_type else None
    except Exception:
        handler = None

    if handler is not None:
        try:
            listing = handler.list_files(data_dir)
        except Exception:
            listing = None
        if listing is not None:
            paths = [e.path for e in listing.entries]
            if sample_cap is not None:
                paths = paths[:sample_cap]
            return paths, int(listing.total), node_id

    # Fail-open: shallow generic listing of the artifact data dir only.
    files = _shallow_data_dir_files(
        data_dir, limit=50_000 if sample_cap is None else max(sample_cap, 16)
    )
    return files, len(files), node_id


def _list_run_outputs(
    run_id: str,
    run_dir: Path,
    *,
    max_files: int | None = None,
    sample_cap: int | None = 32,
) -> tuple[list[dict[str, Any]], _ListingContext]:
    """Build the downloadable listing from ArtifactStore inventories.

    Preferred path: ``outputs_index.json`` (ArtifactRecord refs) expanded via
    ``ArtifactTypeHandler.list_files``. Does not walk domain trees.
    ``max_files`` caps the prioritised selection (UI listing vs zip).
    ``sample_cap`` limits how many files each ArtifactStore entry contributes
    before selection (UI keeps 32 so huge wav dumps do not starve the list;
    zip passes ``None`` so the higher zip budget can include more clips).
    """
    from app.core.runs.outputs_index import (
        artifacts_from_index,
        ensure_outputs_index,
    )

    ctx = _ListingContext()
    collected: list[Path] = []
    seen_keys: set[str] = set()
    attribution: dict[str, str] = {}
    node_ids: list[str] = []

    # Run journal files first (graph / meta / logs).
    for path in _collect_listed_paths(run_dir, limit=50, this_run_id=run_id):
        try:
            resolved = path.resolve()
        except OSError:
            continue
        key = str(resolved)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        collected.append(resolved)

    graph = _load_run_graph(run_dir)
    in_filter = _InputFilter(graph, run_dir)
    index = ensure_outputs_index(run_id, run_dir)
    for entry in artifacts_from_index(index):
        paths, total, node_id = _expand_artifact_entry(entry, sample_cap=sample_cap)
        if node_id and in_filter.roots:
            # Pre-existing input files a source node passed through are not outputs.
            kept: list[Path] = []
            skipped = 0
            for pth in paths:
                try:
                    res = pth.resolve()
                except OSError:
                    continue
                if in_filter.input_owner(res):
                    skipped += 1
                    continue
                kept.append(pth)
            if skipped:
                ctx.input_counts[node_id] = ctx.input_counts.get(node_id, 0) + skipped
                total = max(0, total - skipped) if len(kept) < len(paths) else total
                paths = kept
        if node_id and total:
            ctx.summarized_totals[node_id] = max(
                ctx.summarized_totals.get(node_id, 0), total
            )
            if node_id not in node_ids:
                node_ids.append(node_id)
            raw = entry.get("data_path")
            if isinstance(raw, str):
                data_dir = _resolve_artifact_data_dir(raw)
                if data_dir is not None:
                    ctx.add_root(node_id, data_dir)

        for path in paths:
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if is_project_metadata_path(resolved):
                continue
            key = str(resolved)
            if key in seen_keys:
                if node_id:
                    attribution.setdefault(key, node_id)
                continue
            if not is_under_jail(resolved):
                continue
            if resolved.is_file() and not _allowed_file(resolved):
                continue
            # Skip missing inventory refs (handler may list not-yet-copied paths).
            if not resolved.exists():
                continue
            seen_keys.add(key)
            collected.append(resolved)
            if node_id:
                attribution.setdefault(key, node_id)

        if sample_cap is not None and total > sample_cap:
            ctx.capped = True

    _collect_configured_write_files(
        graph,
        seen_keys=seen_keys,
        collected=collected,
        attribution=attribution,
        node_ids=node_ids,
        ctx=ctx,
        input_filter=in_filter,
    )

    order = [
        str(n["id"])
        for n in (graph.get("nodes") or [])
        if isinstance(n, dict) and n.get("id")
    ]
    order.extend(n for n in node_ids if n not in order)
    all_nodes = list(dict.fromkeys([*order, *node_ids]))
    node_of: dict[str, str | None] = {}
    for path in collected:
        key = str(path)
        node_of[key] = _resolve_attributed_node(
            path, attribution.get(key), all_nodes, graph
        )
    # F19 (F-12): resolve the cap at call time (a default bound at import time
    # ignored runtime overrides of _MAX_LISTED_FILES).
    cap = max(1, int(_MAX_LISTED_FILES if max_files is None else max_files))
    selected = _select_listing(collected, node_of, order, run_dir, cap)
    if len(selected) < len(collected):
        ctx.capped = True
    entries = [file_entry(path, node_id=node_of.get(str(path))) for path in selected]
    return entries, ctx


def list_run_output_files(run_id: str, run_dir: Path) -> list[dict[str, Any]]:
    """Collect downloadable files for a run.

    Sources:
      (a) journal files under workspace/runs/<run_id>/
      (b) ArtifactStore records for this run_id, expanded via
          ``ArtifactTypeHandler.list_files`` (or a shallow data_dir fallback)
      (c) graph-declared write dirs (``WRITE_CONFIG_KEYS``) — config bridge for
          plots/models written before ``publish_files`` adoption
    Does not walk sibling run folders or ProjectManager metadata
    (see :func:`is_project_metadata_path`).

    Each entry may include ``node_id`` from the ArtifactRecord. The list is
    capped (400 entries) — use :func:`list_run_output_files_detail` for
    truncation metadata.
    """
    entries, _ctx = _list_run_outputs(run_id, run_dir)
    return entries


def list_run_output_files_detail(run_id: str, run_dir: Path) -> dict[str, Any]:
    """Same listing as :func:`list_run_output_files`, plus truncation metadata.

    Returns ``{"items": [...], "truncated": bool, "max_items": int,
    "truncated_by_node": {node_id: {"shown": n, "total": m}},
    "inputs_by_node": {node_id: {"total": k}}}``.

    ``total`` comes from handler inventories (``FileListing.total``), not from
    re-walking trees. Page a node's full list with :func:`list_node_output_files`.
    """
    entries, ctx = _list_run_outputs(run_id, run_dir)
    shown: dict[str, int] = {}
    for entry in entries:
        nid = entry.get("node_id")
        if nid and entry.get("kind") != "dir":
            shown[nid] = shown.get(nid, 0) + 1
    truncated_by_node: dict[str, dict[str, int]] = {}
    for nid, total in ctx.summarized_totals.items():
        n_shown = shown.get(nid, 0)
        if total > n_shown:
            truncated_by_node[nid] = {"shown": n_shown, "total": total}
    return {
        "items": entries,
        "truncated": bool(ctx.capped or truncated_by_node),
        "max_items": _MAX_LISTED_FILES,
        "truncated_by_node": truncated_by_node,
        "inputs_by_node": {nid: {"total": n} for nid, n in ctx.input_counts.items()},
    }


def list_run_outputs_truncated_hint(run_id: str, run_dir: Path) -> tuple[list[dict[str, Any]], bool]:
    """Cheap listing + whether anything was capped or summarized (no full scan)."""
    entries, ctx = _list_run_outputs(run_id, run_dir)
    return entries, bool(ctx.capped or ctx.summarized_totals)


def list_node_output_files(
    run_id: str,
    run_dir: Path,
    node_id: str,
    *,
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    """Page every downloadable file one node produced in this run.

    Reads ArtifactStore inventories via ``handler.list_files`` — does not
    re-walk domain trees.
    """
    from app.core.runs.outputs_index import artifacts_from_index, ensure_outputs_index

    index = ensure_outputs_index(run_id, run_dir)
    graph = _load_run_graph(run_dir)
    in_filter = _InputFilter(graph, run_dir)
    files: list[Path] = []
    seen: set[str] = set()
    sources: list[list[Path]] = []
    for entry in artifacts_from_index(index):
        if str(entry.get("node_id") or "") != node_id:
            continue
        paths, _total, _nid = _expand_artifact_entry(entry, sample_cap=None)
        sources.append(list(paths))
    # F19 (F-12): same graph-declared write roots the run listing uses.
    for nid, root in _iter_configured_write_roots(graph):
        if nid != node_id:
            continue
        found: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES and not d.startswith(".")]
            for name in filenames:
                found.append(Path(dirpath) / name)
                if len(found) >= _MAX_NODE_SCAN:
                    break
            if len(found) >= _MAX_NODE_SCAN:
                break
        sources.append(found)
    for paths in sources:
        for path in paths:
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if not resolved.exists():
                continue
            if is_project_metadata_path(resolved):
                continue
            if not is_under_jail(resolved):
                continue
            if resolved.is_file() and not _allowed_file(resolved):
                continue
            if in_filter.input_owner(resolved):
                continue
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            files.append(resolved)
            if len(files) >= _MAX_NODE_SCAN:
                break
        if len(files) >= _MAX_NODE_SCAN:
            break

    files = sorted(files, key=lambda p: (*natural_sort_key(p), str(p)))
    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))
    page = files[offset : offset + limit]
    return {
        "node_id": node_id,
        "items": [file_entry(p, node_id=node_id) for p in page],
        "total": len(files),
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(page) < len(files),
    }


def _safe_zip_component(name: str) -> str:
    """Filesystem-safe single path segment for zip member folders."""
    text = re.sub(r"[^\w.\-]+", "_", str(name or "").strip(), flags=re.UNICODE)
    text = text.strip("._")[:80]
    return text or "run"


def pack_outputs_zip(entries: list[dict[str, Any]]) -> tuple[bytes, bool, int]:
    """Zip listed files under ``<node_id>/<filename>`` (``run/`` when unattributed).

    Returns ``(zip_bytes, truncated, file_count)`` — ``truncated`` is True when the
    byte budget stopped packing before every entry.
    """
    buf = io.BytesIO()
    used_names: set[str] = set()
    total = 0
    packed = 0
    truncated = False
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
                truncated = True
                break
            folder = _safe_zip_component(str(entry.get("node_id") or "run"))
            arc = f"{folder}/{path.name}"
            if arc in used_names:
                stem = path.stem
                suffix = path.suffix
                n = 2
                while True:
                    candidate = f"{folder}/{stem}_{n}{suffix}"
                    if candidate not in used_names:
                        arc = candidate
                        break
                    n += 1
            used_names.add(arc)
            zf.write(path, arcname=arc)
            packed += 1
    return buf.getvalue(), truncated, packed


def list_run_output_files_for_zip(
    run_id: str, run_dir: Path
) -> tuple[list[dict[str, Any]], bool]:
    """Prioritised listing for zip download (higher cap than the UI list).

    Expands each ArtifactStore inventory without the UI sample_cap=32 so
    Dataset Ingest (and similar) can contribute more than a preview handful.
    Still prioritised + capped at ``_MAX_ZIP_FILES`` / byte budget.
    """
    entries, ctx = _list_run_outputs(
        run_id, run_dir, max_files=_MAX_ZIP_FILES, sample_cap=None
    )
    # Truncated when selection or known inventory totals exceed what we packed.
    listing_short = bool(ctx.capped)
    if not listing_short:
        shown: dict[str, int] = {}
        for entry in entries:
            nid = entry.get("node_id")
            if nid and entry.get("kind") != "dir":
                shown[nid] = shown.get(nid, 0) + 1
        for nid, total in ctx.summarized_totals.items():
            if total > shown.get(nid, 0):
                listing_short = True
                break
    return entries, listing_short

# Public names. A leading underscore stays private to this module.
load_run_graph = _load_run_graph
