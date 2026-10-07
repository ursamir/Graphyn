# app/core/mlops/dataset_inputs.py
"""
Bounded Context:  BC6 — Data / datasets
Responsibility:   Input-dataset (``datasets/input/<label>``) operations shared by
                  the REST API, CLI and MCP: generic file listing, stats,
                  capped multi-file / archive uploads with per-file sha256,
                  immutable snapshots (``datasets/output/_inputs/<label>/vN``)
                  and streamed zip downloads.
Owns:             AUDIO_EXTENSIONS, UPLOAD_ALLOWED_EXTENSIONS, UploadLimits,
                  UploadSession, UploadError, file_kind, iter_files,
                  label_file_rows, label_counts, label_stats,
                  snapshot_input_label, list_input_snapshots, list_artifact_datasets,
                  publish_artifact_dataset, iter_zip_stream,
                  sha256_file, audit_file_meta, INPUT_SNAPSHOT_PROJECT,
                  LABEL_INVENTORY_DIR, LABEL_INVENTORY_NAME,
                  invalidate_label_inventory.
Public Surface:   Same.
Must NOT:         Import app.api or app.domain; record audit events (callers
                  audit with their own actor).
Dependencies:     stdlib (hashlib, os, shutil, tarfile, zipfile, tempfile),
                  app.core.config, app.core.mlops.dataset_versions,
                  soundfile (optional, audio stats only).
Reason To Change: Upload caps / allowlist, snapshot layout or zip format change.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tarfile
import time
import uuid
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any, Iterable, Iterator

from app.core.mlops.dataset_versions import (
    aggregate_content_hash,
    next_free_version,
    write_manifest,
)

AUDIO_EXTENSIONS: tuple[str, ...] = (".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac")
UPLOAD_ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    AUDIO_EXTENSIONS
    + (
        ".csv", ".tsv", ".json", ".jsonl", ".txt", ".md",
        ".pdf", ".png", ".jpg", ".jpeg", ".parquet",
    )
)
ARCHIVE_SUFFIXES: tuple[str, ...] = (".zip", ".tar", ".tar.gz", ".tgz")
# Snapshots of input labels live under this pseudo-project in datasets/output.
INPUT_SNAPSHOT_PROJECT = "_inputs"
# Cached file/audio counts for large input trees (sibling dir, not inside the label).
LABEL_INVENTORY_DIR = ".graphyn_inventories"
LABEL_INVENTORY_NAME = ".graphyn_label_inventory.json"  # legacy in-label name (ignored in walks)
_LABEL_RE = re.compile(r"^[\w\-]{1,64}$")
_UNSAFE_CHARS_RE = re.compile(r"[^\w.\-]")
_SKIP_NAMES = frozenset({"__MACOSX", "Thumbs.db", "desktop.ini", LABEL_INVENTORY_NAME, LABEL_INVENTORY_DIR})
_CHUNK = 1024 * 1024


def _env_int(name: str, default: int) -> int:
    try:
        val = int(str(os.environ.get(name, "")).strip() or default)
        return val if val > 0 else default
    except ValueError:
        return default


@dataclass(frozen=True)
class UploadLimits:
    """Per-request caps (env-configurable, read at call time)."""

    max_request_bytes: int
    max_files: int
    max_extract_bytes: int
    max_archive_files: int

    @classmethod
    def from_env(cls) -> "UploadLimits":
        return cls(
            max_request_bytes=_env_int("GRAPHYN_UPLOAD_MAX_BYTES", 100 * 1024 * 1024),
            max_files=_env_int("GRAPHYN_UPLOAD_MAX_FILES", 1000),
            max_extract_bytes=_env_int("GRAPHYN_UPLOAD_MAX_EXTRACT_BYTES", 2 * 1024 ** 3),
            max_archive_files=_env_int("GRAPHYN_UPLOAD_MAX_ARCHIVE_FILES", 20000),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_request_bytes": self.max_request_bytes,
            "max_files": self.max_files,
            "max_extract_bytes": self.max_extract_bytes,
            "max_archive_files": self.max_archive_files,
            "allowed_extensions": sorted(UPLOAD_ALLOWED_EXTENSIONS),
            "archive_extensions": list(ARCHIVE_SUFFIXES),
        }


class UploadError(Exception):
    """Upload rejected; ``status`` is the HTTP status the API should return."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ── naming helpers ───────────────────────────────────────────────────────────


def is_valid_label(label: str) -> bool:
    return bool(_LABEL_RE.fullmatch(label or ""))


def sanitize_label(label: str) -> str:
    """Directory-safe label (``[\\w-]``, ≤ 64 chars); ``default`` when empty."""
    out = re.sub(r"[^\w\-]", "_", (label or "").strip())[:64].strip("_")
    return out or "default"


def _safe_part(part: str) -> str:
    out = _UNSAFE_CHARS_RE.sub("_", part).lstrip(".")[:200]
    return out or "file"


def archive_suffix(name: str) -> str | None:
    low = (name or "").lower()
    for suf in ARCHIVE_SUFFIXES:
        if low.endswith(suf):
            return suf
    return None


def file_kind(name: str) -> str:
    """Coarse kind used by listings/stats: audio | table | json | text | image | pdf | archive | other."""
    low = (name or "").lower()
    ext = os.path.splitext(low)[1]
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    if ext in (".csv", ".tsv", ".parquet"):
        return "table"
    if ext in (".json", ".jsonl"):
        return "json"
    if ext in (".txt", ".md"):
        return "text"
    if ext in (".png", ".jpg", ".jpeg"):
        return "image"
    if ext == ".pdf":
        return "pdf"
    if archive_suffix(low):
        return "archive"
    return "other"


def _split_rel(rel: str) -> list[str] | None:
    """Split an uploaded relative path; None when unsafe or hidden."""
    raw = (rel or "").replace("\\", "/")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        return None
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    if any(p.startswith(".") or p in _SKIP_NAMES for p in parts):
        return None
    return parts


# ── listing / stats ──────────────────────────────────────────────────────────


def iter_files(root: Path, *, jail: Path | None = None) -> Iterator[tuple[Path, str]]:
    """Yield ``(abs_path, rel_posix)`` for regular files under *root*, sorted.

    Hidden files/dirs (``.``-prefixed) are skipped. Directory symlinks are
    followed (labels may be symlinked trees) but each directory is visited
    once; when *jail* is given, files resolving outside it are skipped.
    """
    root = Path(root)
    jail_r = jail.resolve() if jail is not None else None
    seen: set[str] = set()
    out: list[tuple[str, Path]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        real = os.path.realpath(dirpath)
        if real in seen:
            dirnames[:] = []
            continue
        seen.add(real)
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in _SKIP_NAMES)
        for fn in filenames:
            if fn.startswith(".") or fn in _SKIP_NAMES:
                continue
            abs_path = Path(dirpath) / fn
            if jail_r is not None:
                try:
                    if not abs_path.resolve().is_relative_to(jail_r):
                        continue
                except OSError:
                    continue
            if not abs_path.is_file():
                continue
            rel = abs_path.relative_to(root).as_posix()
            out.append((rel, abs_path))
    out.sort(key=lambda e: tuple(e[0].split("/")))
    for rel, abs_path in out:
        yield abs_path, rel


def count_files_budgeted(
    root: Path,
    *,
    max_files: int = 50_000,
) -> dict[str, Any]:
    """Walk *root* counting files, stopping after *max_files*.

    Returns ``{file_count, audio_count, truncated}``. Prefer this over unbounded
    ``rglob`` (MCP / large trees). Hidden / skip-name entries are ignored.
    """
    total = audio = 0
    truncated = False
    root = Path(root)
    if not root.is_dir():
        return {"file_count": 0, "audio_count": 0, "truncated": False}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in _SKIP_NAMES]
        for fn in filenames:
            if fn.startswith(".") or fn in _SKIP_NAMES:
                continue
            if total >= max_files:
                # One more visible file than the budget → the count is a floor.
                truncated = True
                return {"file_count": total, "audio_count": audio, "truncated": truncated}
            total += 1
            if fn.lower().endswith(AUDIO_EXTENSIONS):
                audio += 1
    return {"file_count": total, "audio_count": audio, "truncated": truncated}


def _inventory_ttl_s() -> float:
    try:
        return max(0.0, float(os.environ.get("GRAPHYN_INPUT_INVENTORY_TTL_S", "300") or "300"))
    except ValueError:
        return 300.0


def _dir_mtime_signature(root: Path) -> str:
    """Shallow fingerprint: the label dir + its immediate sub-folders' mtimes.

    Input labels are ``<label>/<class>/files`` (or flat), so adding / removing a
    file bumps one of these mtimes. This touches only two directory levels —
    never every file — which is what makes the cache cheaper than recounting.
    Edits deeper than ``<label>/<class>/`` are picked up by the TTL
    (``GRAPHYN_INPUT_INVENTORY_TTL_S``, default 300 s); API writers also call
    :func:`invalidate_label_inventory`.
    """
    root = Path(root)
    if not root.is_dir():
        return ""

    def _mt(p: Path) -> int:
        try:
            st = p.stat()
            return getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
        except OSError:
            return 0

    parts = [f".:{_mt(root)}"]
    try:
        with os.scandir(root) as it:
            for entry in it:
                name = entry.name
                if name.startswith(".") or name in _SKIP_NAMES:
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=True)
                except OSError:
                    continue
                if is_dir:
                    parts.append(f"{name}:{_mt(Path(entry.path))}")
    except OSError:
        return ""
    parts.sort()
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:32]


def invalidate_label_inventory(label_path: Path) -> None:
    """Drop the cached inventory so the next :func:`label_counts` rescans."""
    label_path = Path(label_path)
    for path in (
        label_path.parent / LABEL_INVENTORY_DIR / f"{label_path.name}.json",
        label_path / LABEL_INVENTORY_NAME,
    ):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _inventory_path(label_path: Path) -> Path:
    return Path(label_path).parent / LABEL_INVENTORY_DIR / f"{Path(label_path).name}.json"


def _read_label_inventory(label_path: Path) -> dict[str, Any] | None:
    path = _inventory_path(label_path)
    if not path.is_file():
        # Migrate / ignore legacy in-label file
        legacy = Path(label_path) / LABEL_INVENTORY_NAME
        if legacy.is_file():
            try:
                legacy.unlink(missing_ok=True)
            except OSError:
                pass
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_label_inventory(label_path: Path, payload: dict[str, Any]) -> None:
    path = _inventory_path(label_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def label_counts(label_path: Path, *, max_files: int = 50_000) -> dict[str, Any]:
    """Cheap per-label counts: ``{file_count, audio_count, truncated}``.

    Caps the walk at *max_files* so huge trees cannot hang list endpoints;
    ``truncated: true`` means the counts are a floor, not exact.
    Caches results under ``datasets/input/.graphyn_inventories/<label>.json``
    keyed by a shallow mtime signature (see :func:`_dir_mtime_signature`) plus
    a TTL, so large trees are not re-walked on every ``GET /data/inputs``.
    """
    label_path = Path(label_path)
    sig = _dir_mtime_signature(label_path)
    cached = _read_label_inventory(label_path)
    fresh = False
    if cached:
        try:
            age = time.time() - float(cached.get("counted_at_epoch") or 0)
            fresh = 0 <= age <= _inventory_ttl_s()
        except (TypeError, ValueError):
            fresh = False
    if (
        cached
        and fresh
        and cached.get("signature") == sig
        and cached.get("max_files") == max_files
        and isinstance(cached.get("file_count"), int)
        and isinstance(cached.get("audio_count"), int)
    ):
        return {
            "file_count": int(cached["file_count"]),
            "audio_count": int(cached["audio_count"]),
            "truncated": bool(cached.get("truncated")),
        }

    counted = count_files_budgeted(label_path, max_files=max_files)
    out = {
        "file_count": int(counted["file_count"]),
        "audio_count": int(counted["audio_count"]),
        "truncated": bool(counted.get("truncated")),
    }
    _write_label_inventory(
        label_path,
        {
            **out,
            "counted_at_epoch": time.time(),
            "max_files": max_files,
            "signature": sig,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return out


def label_file_rows(input_root: Path, label_path: Path, label: str) -> list[dict[str, Any]]:
    """Every file in a label: ``{path (rel to input root), label, kind, ext, size_bytes, modified_at}``."""
    rows: list[dict[str, Any]] = []
    for abs_path, _rel in iter_files(label_path):
        try:
            rel_path = os.path.relpath(abs_path, input_root).replace("\\", "/")
        except ValueError:
            continue
        entry: dict[str, Any] = {
            "path": rel_path,
            "label": label,
            "kind": file_kind(abs_path.name),
            "ext": abs_path.suffix.lower(),
        }
        try:
            st = abs_path.stat()
            entry["size_bytes"] = st.st_size
            entry["modified_at"] = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
        except OSError:
            pass
        rows.append(entry)
    return rows


def label_stats(
    label_path: Path,
    label: str,
    *,
    max_audio_probe: int = 400,
    probe_seconds: float = 5.0,
) -> dict[str, Any]:
    """File counts by kind/extension, bytes, per-class (first subfolder) counts
    and an audio duration / sample-rate summary over an evenly spaced sample of
    at most *max_audio_probe* files (header reads only, time-capped)."""
    by_kind: Counter[str] = Counter()
    by_ext: Counter[str] = Counter()
    classes: dict[str, dict[str, int]] = {}
    total_bytes = 0
    audio_files: list[Path] = []
    file_count = 0
    for abs_path, rel in iter_files(label_path):
        file_count += 1
        kind = file_kind(abs_path.name)
        by_kind[kind] += 1
        by_ext[abs_path.suffix.lower() or "(none)"] += 1
        try:
            size = abs_path.stat().st_size
        except OSError:
            size = 0
        total_bytes += size
        parts = rel.split("/")
        cls = parts[0] if len(parts) > 1 else "(root)"
        row = classes.setdefault(cls, {"file_count": 0, "audio_count": 0, "bytes": 0})
        row["file_count"] += 1
        row["bytes"] += size
        if kind == "audio":
            row["audio_count"] += 1
            audio_files.append(abs_path)

    audio: dict[str, Any] = {"count": len(audio_files), "probed": 0}
    if audio_files:
        step = max(1, len(audio_files) // max_audio_probe)
        sample = audio_files[::step][:max_audio_probe]
        durations: list[float] = []
        rates: Counter[str] = Counter()
        channels: Counter[str] = Counter()
        unreadable = 0
        deadline = time.monotonic() + probe_seconds
        try:
            import soundfile as sf  # type: ignore
        except Exception:  # pragma: no cover - soundfile is a core dep
            sf = None
        for p in sample:
            if sf is None or time.monotonic() > deadline:
                break
            try:
                info = sf.info(str(p))
            except Exception:
                unreadable += 1
                continue
            durations.append(float(info.duration))
            rates[str(int(info.samplerate))] += 1
            channels[str(int(info.channels))] += 1
        audio["probed"] = len(durations) + unreadable
        audio["unreadable"] = unreadable
        audio["sample_rates"] = dict(rates)
        audio["channels"] = dict(channels)
        if durations:
            mean = sum(durations) / len(durations)
            audio["duration_s"] = {
                "min": round(min(durations), 3),
                "max": round(max(durations), 3),
                "mean": round(mean, 3),
            }
            audio["estimated_total_duration_s"] = round(mean * len(audio_files), 1)
        audio["sampled"] = audio["probed"] < len(audio_files)

    return {
        "label": label,
        "file_count": file_count,
        "total_bytes": total_bytes,
        "by_kind": dict(by_kind),
        "by_extension": dict(by_ext),
        "classes": [
            {"name": name, **vals} for name, vals in sorted(classes.items(), key=lambda kv: kv[0])
        ],
        "audio": audio,
    }


# ── uploads ──────────────────────────────────────────────────────────────────


def _sha256_stream(src: IO[bytes], dest: Path, *, budget: int | None) -> tuple[str, int]:
    """Copy *src* → *dest* with sha256; raise UploadError(413) past *budget*."""
    h = hashlib.sha256()
    total = 0
    with dest.open("wb") as out:
        while True:
            chunk = src.read(_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if budget is not None and total > budget:
                raise UploadError(413, "Upload exceeds the configured size limit")
            h.update(chunk)
            out.write(chunk)
    return h.hexdigest(), total


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def strip_common_root(names: list[list[str]], *, min_depth: int) -> list[list[str]]:
    """Drop a single shared top-level folder (the picked folder / archive wrapper).

    ``min_depth=2`` (keep-folders mode): strip when every path is in a folder.
    ``min_depth=3`` (folders-as-labels): strip when at least one path is two
    folders deep (``root/yes/a.wav``); ``yes/a.wav`` alone keeps ``yes`` as label.
    """
    if not names or any(len(p) < 2 for p in names):
        return names
    if len({p[0] for p in names}) != 1:
        return names
    if min_depth >= 3 and not any(len(p) >= 3 for p in names):
        return names
    return [p[1:] for p in names]


@dataclass
class UploadSession:
    """One upload request: plain files and/or archives into input labels.

    ``folders_as_labels``: the first folder of each (common-root-stripped)
    relative path names the label; files without a folder go to
    ``target_label``. False keeps sub-paths under ``target_label`` — the
    normal case: ``yes/a.wav`` becomes ``<target>/yes/a.wav`` (one dataset with
    class sub-folders, which Dataset Ingest labels by parent folder). None
    (auto) means False for plain files and archive members alike.
    ``strip_root=False`` keeps plain-file paths as sent (clients that already
    removed the picked folder and upload in several batches).
    On any error :meth:`rollback` removes every file this session created.
    """

    input_root: Path
    target_label: str
    folders_as_labels: bool | None = None
    strip_root: bool = True
    limits: UploadLimits = field(default_factory=UploadLimits.from_env)
    written: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    archives: list[str] = field(default_factory=list)
    _created: list[Path] = field(default_factory=list)
    _plain_bytes: int = 0
    _extract_bytes: int = 0
    _archive_files: int = 0

    def __post_init__(self) -> None:
        if not is_valid_label(self.target_label):
            raise UploadError(422, f"Invalid label {self.target_label!r} (letters, digits, _ and - only, max 64)")
        self.input_root = Path(self.input_root)

    # destination ----------------------------------------------------------

    def plan(self, parts: list[str], folders_as_labels: bool) -> tuple[str, list[str]]:
        if folders_as_labels and len(parts) >= 2:
            return sanitize_label(parts[0]), [_safe_part(p) for p in parts[1:]]
        return self.target_label, [_safe_part(p) for p in parts]

    def _dest(self, label: str, sub: list[str]) -> Path:
        root = self.input_root.resolve()
        dest = root.joinpath(label, *sub)
        if not dest.resolve().is_relative_to(root):
            linked = root.joinpath(label)
            if linked.is_symlink():
                raise UploadError(
                    400,
                    f"Dataset '{label}' is a linked (read-only) folder outside the workspace — "
                    "upload into a different dataset name",
                )
            raise UploadError(400, "Path is outside workspace")
        return dest

    def _commit(self, tmp: Path, dest: Path, digest: str, size: int, label: str, original: str) -> None:
        """Move tmp into place; identical existing file → skipped duplicate; else rename."""
        final = dest
        if final.exists():
            try:
                if final.is_file() and final.stat().st_size == size and sha256_file(final) == digest:
                    tmp.unlink(missing_ok=True)
                    self.skipped.append({"name": original, "reason": "identical file already in label"})
                    return
            except OSError:
                pass
            stem, ext = os.path.splitext(dest.name)
            n = 1
            while final.exists():
                final = dest.with_name(f"{stem}_{n}{ext}")
                n += 1
        os.replace(tmp, final)
        self._created.append(final)
        rel = final.relative_to(self.input_root.resolve()).as_posix()
        row: dict[str, Any] = {"path": rel, "label": label, "size": size, "sha256": digest}
        if original and Path(original).name != final.name:
            row["original_name"] = original
        self.written.append(row)
        invalidate_label_inventory(self.input_root / label)

    def _write_member(self, src: IO[bytes], parts: list[str], folders_as_labels: bool, original: str, *, budget: int | None) -> int:
        label, sub = self.plan(parts, folders_as_labels)
        dest = self._dest(label, sub)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.parent / f".upload-{uuid.uuid4().hex}.part"
        try:
            digest, size = _sha256_stream(src, tmp, budget=budget)
            self._commit(tmp, dest, digest, size, label, original)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        return size

    # plain files ----------------------------------------------------------

    def add_files(self, items: list[tuple[str, IO[bytes]]]) -> None:
        """Add uploaded ``(relative_name, fileobj)``; archives are extracted."""
        if len(items) > self.limits.max_files:
            raise UploadError(413, f"Too many files in one upload (max {self.limits.max_files})")
        plain: list[tuple[list[str], str, IO[bytes]]] = []
        for name, fh in items:
            if archive_suffix(name):
                self.add_archive(name, fh)
                continue
            parts = _split_rel(name)
            if parts is None:
                self.skipped.append({"name": name, "reason": "unsafe or hidden path"})
                continue
            ext = os.path.splitext(parts[-1])[1].lower()
            if ext not in UPLOAD_ALLOWED_EXTENSIONS:
                self.skipped.append({"name": name, "reason": f"file type {ext or '(none)'} not allowed"})
                continue
            plain.append((parts, name, fh))
        fal = bool(self.folders_as_labels)
        names = [p for p, _, _ in plain]
        stripped = strip_common_root(names, min_depth=3 if fal else 2) if self.strip_root else names
        for (parts, name, fh), sp in zip(plain, stripped):
            budget = self.limits.max_request_bytes - self._plain_bytes
            size = self._write_member(fh, sp, fal, name, budget=budget)
            self._plain_bytes += size

    # archives -------------------------------------------------------------

    def add_archive(self, name: str, fh: IO[bytes]) -> None:
        """Extract a zip / tar(.gz) archive with member filtering and caps.

        Archives default to ``folders_as_labels=True`` (``yes/a.wav`` → label
        ``yes``). Symlinks, hard links, devices, absolute / ``..`` / hidden
        members and non-allowlisted types are skipped; exceeding the file or
        byte cap aborts the request (caller rolls back).
        """
        fal = bool(self.folders_as_labels)
        suffix = archive_suffix(name)
        if not suffix:
            raise UploadError(400, f"{name}: not a supported archive")
        self.archives.append(name)
        tmp_dir = self.input_root / ".upload-tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        spool = tmp_dir / f"{uuid.uuid4().hex}{suffix}"
        try:
            budget = self.limits.max_request_bytes - self._plain_bytes
            _digest, size = _sha256_stream(fh, spool, budget=budget)
            self._plain_bytes += size
            if suffix == ".zip":
                self._extract_zip(spool, fal, name)
            else:
                self._extract_tar(spool, fal, name)
        finally:
            spool.unlink(missing_ok=True)
            try:
                tmp_dir.rmdir()
            except OSError:
                pass

    def _member_ok(self, member_name: str, archive: str) -> list[str] | None:
        parts = _split_rel(member_name)
        if parts is None:
            segs = [seg for seg in member_name.replace("\\", "/").split("/") if seg]
            unsafe = member_name.startswith(("/", "\\")) or ".." in segs or bool(re.match(r"^[A-Za-z]:", member_name))
            if unsafe:
                self.skipped.append({"name": f"{archive}:{member_name}", "reason": "unsafe path"})
            return None
        ext = os.path.splitext(parts[-1])[1].lower()
        if ext not in UPLOAD_ALLOWED_EXTENSIONS:
            self.skipped.append({"name": f"{archive}:{member_name}", "reason": f"file type {ext or '(none)'} not allowed"})
            return None
        return parts

    def _count_member(self, declared: int) -> None:
        self._archive_files += 1
        if self._archive_files > self.limits.max_archive_files:
            raise UploadError(413, f"Archive has too many files (max {self.limits.max_archive_files})")
        if declared and self._extract_bytes + declared > self.limits.max_extract_bytes:
            raise UploadError(413, "Archive expands past the configured size limit")

    def _extract_zip(self, path: Path, fal: bool, archive: str) -> None:
        try:
            zf = zipfile.ZipFile(path)
        except zipfile.BadZipFile as exc:
            raise UploadError(400, f"{archive}: not a valid zip ({exc})") from exc
        with zf:
            members: list[tuple[zipfile.ZipInfo, list[str]]] = []
            for info in zf.infolist():
                if info.is_dir():
                    continue
                mode = (info.external_attr >> 16) & 0o170000
                if mode and mode != 0o100000:  # symlink / device / other
                    self.skipped.append({"name": f"{archive}:{info.filename}", "reason": "not a regular file"})
                    continue
                parts = self._member_ok(info.filename, archive)
                if parts is not None:
                    members.append((info, parts))
            stripped = strip_common_root([p for _, p in members], min_depth=3)  # archives: strip only a wrapper above class folders
            for (info, _), sp in zip(members, stripped):
                self._count_member(info.file_size)
                with zf.open(info) as src:
                    budget = self.limits.max_extract_bytes - self._extract_bytes
                    self._extract_bytes += self._write_member(src, sp, fal, f"{archive}:{info.filename}", budget=budget)

    def _extract_tar(self, path: Path, fal: bool, archive: str) -> None:
        try:
            tf = tarfile.open(path, "r:*")
        except tarfile.TarError as exc:
            raise UploadError(400, f"{archive}: not a valid tar archive ({exc})") from exc
        with tf:
            members: list[tuple[tarfile.TarInfo, list[str]]] = []
            for m in tf:
                if m.isdir():
                    continue
                if not m.isreg():
                    self.skipped.append({"name": f"{archive}:{m.name}", "reason": "not a regular file"})
                    continue
                parts = self._member_ok(m.name, archive)
                if parts is not None:
                    members.append((m, parts))
                if len(members) > self.limits.max_archive_files:
                    raise UploadError(413, f"Archive has too many files (max {self.limits.max_archive_files})")
            stripped = strip_common_root([p for _, p in members], min_depth=3)  # archives: strip only a wrapper above class folders
            for (m, _), sp in zip(members, stripped):
                self._count_member(m.size)
                src = tf.extractfile(m)
                if src is None:
                    continue
                with src:
                    budget = self.limits.max_extract_bytes - self._extract_bytes
                    self._extract_bytes += self._write_member(src, sp, fal, f"{archive}:{m.name}", budget=budget)

    # results --------------------------------------------------------------

    def rollback(self) -> None:
        for p in reversed(self._created):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        self._created.clear()
        self.written.clear()

    def summary(self) -> dict[str, Any]:
        labels = sorted({w["label"] for w in self.written})
        total = sum(int(w["size"]) for w in self.written)
        return {
            "label": self.target_label,
            "labels": labels,
            "files": list(self.written),
            "count": len(self.written),
            "total_bytes": total,
            "content_hash": aggregate_content_hash([(w["path"], w["sha256"]) for w in self.written]),
            "skipped": list(self.skipped),
            "archives": list(self.archives),
        }


def audit_file_meta(files: list[dict[str, Any]], cap: int = 500) -> dict[str, Any]:
    """Audit-friendly per-file rows (path, size, sha256), capped."""
    rows = [{"path": f.get("path"), "size": f.get("size"), "sha256": f.get("sha256")} for f in files[:cap]]
    return {"files": rows, "files_truncated": len(files) > cap}


# ── snapshots ────────────────────────────────────────────────────────────────


def _newest_snapshot(parent: Path) -> Path | None:
    import re as _re

    rx = _re.compile(r"^v\d+(?:\.\d+)*$")
    vers = [c for c in parent.iterdir() if c.is_dir() and rx.match(c.name)] if parent.is_dir() else []
    if not vers:
        return None
    return max(vers, key=lambda c: tuple(int(x) for x in c.name[1:].split(".")))


def _read_manifest_quiet(version_dir: Path) -> dict[str, Any] | None:
    try:
        import json as _json

        return _json.loads((version_dir / "manifest.json").read_text(encoding="utf-8"))
    except Exception:
        return None


def snapshot_input_label(
    label: str,
    *,
    input_root: Path,
    output_root: Path,
    jail_external: bool = True,
) -> dict[str, Any]:
    """Freeze ``input_root/<label>`` into ``output_root/_inputs/<label>/vN``.

    Copies every (non-hidden) file, writes ``manifest.json`` (per-file sha256
    + content_hash + ``source``) and moves the finished tree into place in one
    rename so a half-written snapshot never shows up as a version.
    """
    src = Path(input_root) / label
    if not src.is_dir():
        raise FileNotFoundError(f"Input label '{label}' not found")
    parent = Path(output_root) / INPUT_SNAPSHOT_PROJECT / label
    parent.mkdir(parents=True, exist_ok=True)
    staging = parent / f".staging-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        count = 0
        total = 0
        jail = Path(input_root) if jail_external else None
        for abs_path, rel in iter_files(src, jail=jail):
            dst = staging / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(abs_path, dst)
            count += 1
            total += dst.stat().st_size
        from app.core.mlops.dataset_versions import compute_manifest

        man = compute_manifest(staging)
        created = datetime.now(timezone.utc).isoformat()
        man["source"] = {"kind": "input_label", "label": label}
        man["created_at"] = created
        write_manifest(staging, man)
        # Unchanged since the newest snapshot → reuse it (no duplicate copy).
        newest = _newest_snapshot(parent)
        if newest is not None:
            prev_man = _read_manifest_quiet(newest)
            if prev_man and prev_man.get("content_hash") == man.get("content_hash"):
                shutil.rmtree(staging, ignore_errors=True)
                return {
                    "project": f"{INPUT_SNAPSHOT_PROJECT}/{label}",
                    "label": label,
                    "version": newest.name,
                    "path": str(newest),
                    "file_count": count,
                    "total_bytes": total,
                    "content_hash": man.get("content_hash"),
                    "created_at": prev_man.get("created_at"),
                    "reused": True,
                }
        for _ in range(50):
            version = next_free_version(parent)
            target = parent / version
            try:
                os.rename(staging, target)
                break
            except OSError:
                if target.exists():
                    continue
                raise
        else:  # pragma: no cover - pathological race
            raise RuntimeError("Could not allocate a snapshot version")
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "project": f"{INPUT_SNAPSHOT_PROJECT}/{label}",
        "label": label,
        "version": version,
        "path": str(target),
        "file_count": count,
        "total_bytes": total,
        "content_hash": man.get("content_hash"),
        "created_at": created,
    }


def list_input_snapshots(output_root: Path) -> list[dict[str, Any]]:
    """``[{project: "_inputs/<label>", label, versions, kind}]`` for Outputs listings."""
    from app.core.mlops.dataset_versions import VERSION_RE

    base = Path(output_root) / INPUT_SNAPSHOT_PROJECT
    out: list[dict[str, Any]] = []
    if not base.is_dir():
        return out
    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        versions = sorted(
            v.name for v in child.iterdir() if v.is_dir() and VERSION_RE.match(v.name)
        )
        out.append(
            {
                "project": f"{INPUT_SNAPSHOT_PROJECT}/{child.name}",
                "label": child.name,
                "versions": versions,
                "kind": "input_snapshot",
            }
        )
    return out


def list_artifact_datasets(artifacts_root: Path) -> list[dict[str, Any]]:
    """Legacy template hand-off trees under ``artifacts/<slug>/dataset/<name>/vN``.

    Returned as soft-listed Outputs rows (``kind: artifact_dataset``) so the
    console can show them and offer Publish into ``datasets/output/<workspace>``.
    """
    from app.core.mlops.dataset_versions import VERSION_RE

    root = Path(artifacts_root)
    out: list[dict[str, Any]] = []

    def _children(p: Path) -> list[Path]:
        # One unreadable folder must not turn the whole Outputs listing into a 500.
        try:
            return sorted(p.iterdir())
        except OSError:
            return []

    def _non_empty(p: Path) -> bool:
        try:
            return any(p.iterdir())
        except OSError:
            return False

    if not root.is_dir():
        return out
    for slug in _children(root):
        if not slug.is_dir() or slug.name.startswith("."):
            continue
        ds_root = slug / "dataset"
        if not ds_root.is_dir():
            continue
        for name in _children(ds_root):
            if not name.is_dir() or name.name.startswith("."):
                continue
            versions = sorted(
                v.name
                for v in _children(name)
                if v.is_dir() and VERSION_RE.match(v.name) and _non_empty(v)
            )
            if not versions:
                continue
            fs_path = f"workspace/artifacts/{slug.name}/dataset/{name.name}"
            out.append(
                {
                    "project": f"_artifacts/{slug.name}/{name.name}",
                    "label": f"{slug.name}/{name.name}",
                    "versions": versions,
                    "kind": "artifact_dataset",
                    "fs_path": fs_path,
                }
            )
    return out


def publish_artifact_dataset(
    *,
    source_dir: Path,
    target_project_dir: Path,
    version: str | None = None,
    source_label: str | None = None,
) -> dict[str, Any]:
    """Copy an artifact dataset version tree into ``datasets/output/<project>/vN``.

    Symlinks are dropped (never followed — a link inside the tree must not pull
    in files from outside it). An explicit *version* that already exists raises
    ``FileExistsError`` (versions are immutable); with no version the next free
    one is used.
    """
    from app.core.mlops.dataset_versions import (
        VERSION_RE,
        compute_manifest,
        next_free_version,
        write_manifest,
    )

    src = Path(source_dir)
    if not src.is_dir():
        raise FileNotFoundError(f"Source dataset version not found: {src}")
    target_project_dir = Path(target_project_dir)
    target_project_dir.mkdir(parents=True, exist_ok=True)
    ver = (version or "").strip()
    if ver and not VERSION_RE.match(ver):
        raise ValueError(f"Invalid version {ver!r}")
    if not ver:
        ver = next_free_version(target_project_dir)
    dest = target_project_dir / ver
    if dest.exists():
        if version:
            raise FileExistsError(f"Version {ver} already exists")
        ver = next_free_version(target_project_dir)
        dest = target_project_dir / ver

    def _skip_links(dirpath: str, names: list[str]) -> list[str]:
        return [n for n in names if os.path.islink(os.path.join(dirpath, n))]

    staging = target_project_dir / f".publish-{uuid.uuid4().hex}"
    try:
        shutil.copytree(src, staging, symlinks=False, ignore=_skip_links, dirs_exist_ok=False)
        man = compute_manifest(staging)
        man["source"] = {
            "kind": "artifact_publish",
            "from": (source_label or src.name).replace("\\", "/"),
        }
        man["created_at"] = datetime.now(timezone.utc).isoformat()
        write_manifest(staging, man)
        os.rename(staging, dest)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "project": target_project_dir.name,
        "version": ver,
        "path": str(dest),
        "file_count": man.get("file_count"),
        "content_hash": man.get("content_hash"),
        "source": man.get("source"),
    }


# ── streamed zip ─────────────────────────────────────────────────────────────


class _ZipSink:
    """Write-only, non-seekable sink; ``drain()`` hands out what was written."""

    def __init__(self) -> None:
        self._buf: list[bytes] = []
        self._pos = 0

    def write(self, data: bytes) -> int:
        if data:
            self._buf.append(bytes(data))
            self._pos += len(data)
        return len(data)

    def tell(self) -> int:
        return self._pos

    def flush(self) -> None:
        return None

    def drain(self) -> bytes:
        out = b"".join(self._buf)
        self._buf.clear()
        return out


def iter_zip_stream(
    files: Iterable[tuple[Path, str]],
    *,
    prefix: str = "",
    extra: Iterable[tuple[str, bytes]] = (),
    manifest_name: str | None = None,
    manifest_extra: dict[str, Any] | None = None,
) -> Iterator[bytes]:
    """Stream a zip of ``(abs_path, rel)`` entries without holding it in memory.

    Entries are stored as ``<prefix><rel>``; memory stays at about one chunk.
    With *manifest_name*, a manifest (``files[{path: rel, sha256, size}]`` +
    ``content_hash``, computed while streaming — equal to the hash a snapshot
    of the same tree records) is appended as ``<prefix><manifest_name>``.
    """
    sink = _ZipSink()
    zf = zipfile.ZipFile(sink, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True)
    rows: list[dict[str, Any]] = []
    try:
        for abs_path, rel in files:
            arcname = f"{prefix}{rel}"
            try:
                info = zipfile.ZipInfo.from_file(str(abs_path), arcname)
            except OSError:
                continue
            info.compress_type = zipfile.ZIP_DEFLATED
            h = hashlib.sha256()
            size = 0
            with open(abs_path, "rb") as src, zf.open(info, mode="w", force_zip64=True) as dst:
                while True:
                    chunk = src.read(_CHUNK)
                    if not chunk:
                        break
                    h.update(chunk)
                    size += len(chunk)
                    dst.write(chunk)
                    out = sink.drain()
                    if out:
                        yield out
            rows.append({"path": rel, "sha256": h.hexdigest(), "size": size})
            out = sink.drain()
            if out:
                yield out
        for rel, data in extra:
            zf.writestr(f"{prefix}{rel}", data)
            yield sink.drain()
        if manifest_name:
            man = {
                "schema_version": "1.0",
                "files": rows,
                "file_count": len(rows),
                "content_hash": aggregate_content_hash([(r["path"], r["sha256"]) for r in rows]),
                **(manifest_extra or {}),
            }
            man["sha256"] = man["content_hash"]
            zf.writestr(f"{prefix}{manifest_name}", json.dumps(man, indent=2, sort_keys=True) + "\n")
    finally:
        zf.close()
    tail = sink.drain()
    if tail:
        yield tail
