# app/core/artifacts/artifact_pack.py
"""
Bounded Context:  BC6 — Artifacts / Mode B transfer
Responsibility:   Pack local files/dirs into content-addressed blobs by role,
                  build/update ArtifactRef manifests, and hydrate blobs back
                  to a stable relative layout under a materialize root.
Owns:             pack helpers, hydrate helpers, host-path scanning,
                  UnreclaimedHostPathError, ROLE_* constants.
Public Surface:   UnreclaimedHostPathError, pack_path_bytes, hydrate_ref_bytes,
                  collect_path_bearing_roles, apply_packed_refs,
                  materialize_refs_onto, strip_host_paths, scan_host_paths,
                  primary_local_path, PATH_METRIC_KEYS.
Must NOT:         Import from app.domain, app.api, or plugin packages.
                  Must not talk HTTP — callers supply put/get callables.
Dependencies:     stdlib, app.models.artifact_ref (type only at runtime).
Reason To Change: New roles, packing formats, or hydrate layout rules.

Used by ``app.core.distributed.transfer`` (Mode B wire) and optionally by
ArtifactSerializerRegistry handlers (on-disk run artifacts). File bytes travel
via manifest/blobs; metadata may still be pickled.
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import re
import shutil
import tarfile
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable

log = logging.getLogger(__name__)

# Metrics / metadata keys that historically smuggled host paths.
PATH_METRIC_KEYS = frozenset(
    {
        "keras_model_path",
        "saved_model_path",
        "labels_path",
        "tflite_path",
        "artifact_path",
        "model_path",
        "checkpoint_path",
        "calibration_path",
        "source_model_path",
        "source",
        "package_path",
        "manifest_path",
    }
)

# Provenance-only keys: stripped on the wire, never packed (do not fail-closed
# when the referenced producer path is missing on this host).
PROVENANCE_PATH_KEYS = frozenset(
    {
        "source_model_path",
        "source",
        "package_path",
    }
)

_ABS_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/)")


class UnreclaimedHostPathError(ValueError):
    """Raised when a producer host path would cross a Mode B node boundary."""


def _safe_basename(name: str) -> str:
    base = Path(str(name or "artifact")).name
    base = base.replace("\\", "/").split("/")[-1]
    if not base or base in {".", ".."} or ".." in base:
        return "artifact"
    return base[:200]


def _safe_relpath(rel: str, *, default: str = "artifact") -> str:
    text = (rel or "").replace("\\", "/").strip().lstrip("/")
    parts = [p for p in text.split("/") if p and p not in {".", ".."}]
    if not parts:
        return default
    return "/".join(parts)[:400]


def is_host_path(value: Any) -> bool:
    """True if *value* looks like an absolute / drive-letter filesystem path."""
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text or text.startswith("artifact://") or text.startswith("file://"):
        # file:// is also host-local; treat as unreclaimed.
        if text.startswith("file://"):
            return True
        return False
    if _ABS_PATH_RE.match(text):
        return True
    # Relative workspace paths are host-local too when they exist on disk as
    # transfer inputs — callers decide; we only flag absolute forms here for
    # fail-closed wire checks. Relative strings without a scheme are allowed
    # on the wire only when empty or clearly non-path metrics.
    return False


def pack_path_bytes(src: Path) -> tuple[bytes, str]:
    """Return ``(blob_bytes, kind)`` for a file (``file``) or directory (``dir``).

    Directories are gzip-compressed tar archives (arcname ``.``). Symlinks and
    non-regular members are skipped.
    """
    src = Path(src)
    if src.is_file():
        data = src.read_bytes()
        if not data:
            raise ValueError(f"Refusing empty file for pack: {src}")
        return data, "file"
    if src.is_dir():
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            tar.add(str(src), arcname=".", recursive=True, filter=_tar_add_filter)
        data = buf.getvalue()
        if not data:
            raise ValueError(f"Refusing empty directory pack: {src}")
        return data, "dir"
    raise ValueError(f"Neither file nor directory: {src}")


def _tar_add_filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
    if tarinfo.issym() or tarinfo.islnk():
        return None
    if not (tarinfo.isfile() or tarinfo.isdir()):
        return None
    return tarinfo


def unpack_directory(data: bytes, dest: Path) -> None:
    """Extract a packed directory tar.gz into *dest* (no ``..`` / absolute)."""
    dest.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO(data)
    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        for member in tar.getmembers():
            name = (member.name or "").replace("\\", "/")
            if name.startswith("/") or name.startswith("..") or "/../" in f"/{name}/":
                raise ValueError(f"Refusing unsafe tar member {member.name!r}")
            if member.issym() or member.islnk():
                continue
            if not (member.isfile() or member.isdir()):
                continue
            tar.extract(member, path=dest, set_attrs=False, filter="data")


def atomic_write_bytes(dest: Path, data: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".{dest.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _guess_media(role: str, path: Path, kind: str) -> str | None:
    if role == "keras_model" or path.suffix.lower() == ".keras":
        return "application/x-keras"
    if role == "labels" or path.name == "labels.txt":
        return "text/plain"
    if role == "tflite" or path.suffix.lower() == ".tflite":
        return "application/x-tflite"
    if role == "pytorch_model" or path.suffix.lower() in {".pt", ".pth"}:
        return "application/x-pytorch"
    if kind == "dir" and role == "saved_model":
        return "application/x-savedmodel"
    return None


def _new_ref(
    *,
    role: str,
    source: Path,
    kind: str,
    relative_path: str,
    media_type: str | None = None,
):
    from app.models.artifact_ref import ArtifactRef

    return ArtifactRef(
        role=role,
        kind=kind,  # type: ignore[arg-type]
        filename=_safe_basename(source.name if kind == "file" else source.name),
        relative_path=_safe_relpath(relative_path, default=_safe_basename(source.name)),
        source_path=str(source),
        media_type=media_type or _guess_media(role, source, kind),
    )


def collect_path_bearing_roles(obj: Any) -> list[Any]:
    """Build / extend ArtifactRef list from declared refs + legacy path fields.

    Existing refs with ``source_path`` or (uri+sha256) are kept. Legacy
    ``model_path`` / metrics path keys are promoted into roles when missing.
    """
    from app.models.artifact_ref import ArtifactRef

    name = type(obj).__name__
    refs: list[Any] = []
    existing = list(getattr(obj, "refs", None) or [])
    for r in existing:
        if isinstance(r, ArtifactRef):
            refs.append(r)
        elif isinstance(r, dict):
            try:
                refs.append(ArtifactRef.model_validate(r))
            except Exception:
                continue

    by_role = {str(r.role): r for r in refs if getattr(r, "role", None)}

    def _ensure(role: str, path_str: str, *, relative: str | None = None, kind_hint: str | None = None) -> None:
        if not path_str or not isinstance(path_str, str):
            return
        path = Path(path_str)
        try:
            exists = path.exists()
        except OSError:
            exists = False
        if not exists:
            # Keep a declared ref that already has uri/sha256 even if local missing.
            return
        if role in by_role:
            cur = by_role[role]
            if not getattr(cur, "source_path", ""):
                cur.source_path = str(path)
            if not getattr(cur, "relative_path", ""):
                cur.relative_path = _safe_relpath(
                    relative or path.name, default=_safe_basename(path.name)
                )
            return
        kind = kind_hint
        if kind is None:
            kind = "dir" if path.is_dir() else "file"
        ref = _new_ref(
            role=role,
            source=path,
            kind=kind,
            relative_path=relative or path.name,
        )
        refs.append(ref)
        by_role[role] = ref

    metrics = getattr(obj, "metrics", None) or {}
    if not isinstance(metrics, dict):
        metrics = {}
    metadata = getattr(obj, "metadata", None) or {}
    if not isinstance(metadata, dict):
        metadata = {}

    if name == "ModelArtifact" or (
        hasattr(obj, "model_path") and hasattr(obj, "labels") and hasattr(obj, "metrics")
    ):
        mp = str(getattr(obj, "model_path", "") or "")
        keras = str(metrics.get("keras_model_path") or "")
        labels_p = str(metrics.get("labels_path") or "")
        if keras:
            _ensure("keras_model", keras, relative="model.keras", kind_hint="file")
        if mp:
            p = Path(mp)
            if p.is_file() and p.suffix.lower() in {".pt", ".pth"}:
                _ensure("pytorch_model", mp, relative=p.name, kind_hint="file")
            elif p.is_file() and p.suffix.lower() == ".keras":
                _ensure("keras_model", mp, relative=p.name, kind_hint="file")
            elif p.is_dir() or (not p.suffix and mp):
                _ensure("saved_model", mp, relative="saved_model", kind_hint="dir")
            else:
                _ensure("other", mp, relative=p.name)
        if labels_p:
            _ensure("labels", labels_p, relative="labels.txt", kind_hint="file")
        # Sibling labels next to keras when not declared.
        if "labels" not in by_role and keras:
            sibling = Path(keras).parent / "labels.txt"
            if sibling.is_file():
                _ensure("labels", str(sibling), relative="labels.txt", kind_hint="file")

    if name == "TFLiteArtifact" or (
        hasattr(obj, "tflite_path") and hasattr(obj, "quantisation")
    ):
        tp = str(getattr(obj, "tflite_path", "") or "")
        if tp:
            _ensure("tflite", tp, relative=Path(tp).name or "model.tflite", kind_hint="file")
        labels_p = str(metrics.get("labels_path") or metadata.get("labels_path") or "")
        if labels_p:
            _ensure("labels", labels_p, relative="labels.txt", kind_hint="file")
        elif tp and "labels" not in by_role:
            sibling = Path(tp).parent / "labels.txt"
            if sibling.is_file():
                _ensure("labels", str(sibling), relative="labels.txt", kind_hint="file")

    if name == "DeploymentArtifact" or (
        hasattr(obj, "artifact_path") and hasattr(obj, "model_format")
    ):
        ap = str(getattr(obj, "artifact_path", "") or "")
        if ap:
            p = Path(ap)
            kind = "dir" if p.is_dir() else "file"
            _ensure(
                "deployment_bundle",
                ap,
                relative=p.name or "bundle",
                kind_hint=kind,
            )
        labels_p = str(metrics.get("labels_path") or metadata.get("labels_path") or "")
        if labels_p:
            _ensure("labels", labels_p, relative="labels.txt", kind_hint="file")
        elif ap and "labels" not in by_role:
            base = Path(ap)
            sibling = (base if base.is_dir() else base.parent) / "labels.txt"
            if sibling.is_file():
                _ensure("labels", str(sibling), relative="labels.txt", kind_hint="file")

    # CsvTableResult
    # CsvTableResult (duck): path + rows — pack the CSV file when present on disk.
    if name == "CsvTableResult" or (
        hasattr(obj, "path") and hasattr(obj, "rows") and hasattr(obj, "row_count")
        and not hasattr(obj, "model_path") and not hasattr(obj, "artifact_path")
    ):
        cp = str(getattr(obj, "path", "") or "")
        if cp:
            _ensure("other", cp, relative=Path(cp).name or "table.csv", kind_hint="file")

    # ObjectRef (duck): local backend uri may be a host file path.
    if name == "ObjectRef" or (
        hasattr(obj, "key") and hasattr(obj, "uri") and hasattr(obj, "backend")
        and not hasattr(obj, "model_path")
    ):
        backend = str(getattr(obj, "backend", "") or "").lower()
        uri = str(getattr(obj, "uri", "") or "")
        if backend in {"", "local", "file"} and uri and not uri.startswith(("s3://", "artifact://", "http://", "https://")):
            _ensure("other", uri, relative=Path(uri).name or "object.bin", kind_hint="file")

    return refs


def apply_packed_refs(
    obj: Any,
    refs: list[Any],
    *,
    put_companion: Callable[[bytes], tuple[str, str]],
    fail_closed: bool = True,
) -> Any:
    """Pack each ref's ``source_path`` into blobs; clear host paths on *obj*.

    Returns an updated object whose ``refs`` carry uri/sha256/logical_id and
    whose path fields / path-metric keys no longer hold unreclaimed host paths.
    """
    from app.models.artifact_ref import ArtifactRef

    packed: list[ArtifactRef] = []
    for ref in refs:
        if not isinstance(ref, ArtifactRef):
            try:
                ref = ArtifactRef.model_validate(ref)
            except Exception:
                continue
        src = str(getattr(ref, "source_path", "") or "").strip()
        if src:
            path = Path(src)
            try:
                exists = path.exists()
            except OSError:
                exists = False
            if not exists:
                if fail_closed:
                    raise UnreclaimedHostPathError(
                        f"ArtifactRef role={ref.role!r} source_path missing: {src!r}"
                    )
                continue
            data, kind = pack_path_bytes(path)
            uri, digest = put_companion(data)
            ref = ref.model_copy(
                update={
                    "kind": kind,
                    "uri": str(uri),
                    "sha256": str(digest),
                    "logical_id": str(digest),
                    "source_path": "",
                    "filename": ref.filename or _safe_basename(path.name),
                    "relative_path": ref.relative_path
                    or _safe_relpath(path.name, default=_safe_basename(path.name)),
                }
            )
        elif not (ref.uri and ref.sha256):
            # Nothing to pack and no wire identity — drop.
            continue
        else:
            # Already packed; ensure source_path cleared.
            if ref.source_path:
                ref = ref.model_copy(update={"source_path": ""})
        packed.append(ref)

    obj = _set_refs(obj, packed)
    obj = strip_host_paths(obj, fail_closed=fail_closed)
    remaining = scan_host_paths(obj)
    if remaining and fail_closed:
        raise UnreclaimedHostPathError(
            "Unreclaimed host path(s) would cross Mode B boundary: "
            + ", ".join(remaining[:8])
        )
    return obj


def _set_refs(obj: Any, refs: list[Any]) -> Any:
    if hasattr(obj, "model_copy"):
        try:
            return obj.model_copy(update={"refs": refs})
        except Exception:
            pass
    if hasattr(obj, "model_dump") and hasattr(type(obj), "model_validate"):
        try:
            payload = obj.model_dump()
            payload["refs"] = refs
            return type(obj).model_validate(payload)
        except Exception:
            pass
    try:
        setattr(obj, "refs", refs)
    except Exception:
        pass
    return obj


def _set_field(obj: Any, field: str, value: Any) -> Any:
    if hasattr(obj, "model_copy"):
        try:
            return obj.model_copy(update={field: value})
        except Exception:
            pass
    if hasattr(obj, "model_dump") and hasattr(type(obj), "model_validate"):
        try:
            payload = obj.model_dump()
            payload[field] = value
            return type(obj).model_validate(payload)
        except Exception:
            pass
    try:
        setattr(obj, field, value)
    except Exception:
        pass
    return obj


def strip_host_paths(obj: Any, *, fail_closed: bool = True) -> Any:
    """Clear absolute host paths from path fields and path-metric keys.

    Relative / empty values are left alone. Path metrics that were host paths
    become empty strings (plugins must use hydrated local paths or refs).
    """
    name = type(obj).__name__
    path_fields: tuple[str, ...] = ()
    if name == "ModelArtifact" or (
        hasattr(obj, "model_path") and hasattr(obj, "labels") and hasattr(obj, "metrics")
    ):
        path_fields = ("model_path",)
    elif name == "TFLiteArtifact" or (
        hasattr(obj, "tflite_path") and hasattr(obj, "quantisation")
    ):
        path_fields = ("tflite_path",)
    elif name == "DeploymentArtifact" or (
        hasattr(obj, "artifact_path") and hasattr(obj, "model_format")
    ):
        path_fields = ("artifact_path",)
    elif name == "DatasetArtifact" or (
        hasattr(obj, "manifest_path") and hasattr(obj, "X_train") and hasattr(obj, "labels")
    ):
        path_fields = ("manifest_path",)
    elif name == "CsvTableResult" or (
        hasattr(obj, "path") and hasattr(obj, "rows") and hasattr(obj, "row_count")
        and not hasattr(obj, "model_path") and not hasattr(obj, "artifact_path")
    ):
        path_fields = ("path",)
    elif name == "ObjectRef" or (
        hasattr(obj, "key") and hasattr(obj, "uri") and hasattr(obj, "backend")
        and not hasattr(obj, "model_path")
    ):
        path_fields = ("uri",)

    for field in path_fields:
        raw = getattr(obj, field, None)
        if not isinstance(raw, str) or not raw.strip():
            continue
        # ObjectRef remote URIs must survive.
        if field == "uri" and raw.startswith(("s3://", "artifact://", "http://", "https://")):
            continue
        if is_host_path(raw) or _looks_local_fs(raw):
            obj = _set_field(obj, field, "")

    for dict_field in ("metrics", "metadata"):
        d = getattr(obj, dict_field, None)
        if not isinstance(d, dict) or not d:
            continue
        changed = False
        new_d = dict(d)
        for key, val in list(new_d.items()):
            if not isinstance(val, str) or not val.strip():
                continue
            if val.startswith(("artifact://", "s3://", "http://", "https://")):
                continue
            key_is_path = key in PATH_METRIC_KEYS or str(key).endswith("_path") or str(key).endswith("_dir")
            if key_is_path and (is_host_path(val) or _looks_local_fs(val)):
                new_d[key] = ""
                changed = True
        if changed:
            obj = _set_field(obj, dict_field, new_d)

    # Clear any residual source_path on refs.
    refs = list(getattr(obj, "refs", None) or [])
    if refs:
        cleaned = []
        for r in refs:
            sp = getattr(r, "source_path", "") or ""
            if sp:
                if hasattr(r, "model_copy"):
                    r = r.model_copy(update={"source_path": ""})
                else:
                    try:
                        r.source_path = ""
                    except Exception:
                        pass
            cleaned.append(r)
        obj = _set_refs(obj, cleaned)
    return obj


def _looks_local_fs(value: str) -> bool:
    """True for absolute paths OR existing relative filesystem paths."""
    text = (value or "").strip()
    if not text or text.startswith("artifact://"):
        return False
    if is_host_path(text):
        return True
    try:
        return Path(text).exists()
    except OSError:
        return False



def declared_unreclaimable_host_paths(obj: Any) -> list[str]:
    """Host paths declared on *obj* that are not packable (missing on disk)."""
    found: list[str] = []
    for field in ("model_path", "tflite_path", "artifact_path"):
        if not hasattr(obj, field):
            continue
        raw = getattr(obj, field, None)
        if not isinstance(raw, str) or not raw.strip():
            continue
        if not (is_host_path(raw) or Path(raw).is_absolute() or _looks_local_fs(raw)):
            # relative non-existing may still be host-intent if absolute-like
            if not Path(raw).is_absolute() and not is_host_path(raw):
                # treat existing-relative only; skip bare relative missing
                if not Path(raw).exists() and ("/" in raw or "\\" in raw or raw.endswith((".keras", ".tflite", ".pt", ".pth"))):
                    # relative path that looks like a file hand-off
                    found.append(f"{type(obj).__name__}.{field}={raw!r} (missing)")
                continue
        try:
            exists = Path(raw).exists()
        except OSError:
            exists = False
        if not exists:
            found.append(f"{type(obj).__name__}.{field}={raw!r} (missing)")
    for dict_field in ("metrics", "metadata"):
        d = getattr(obj, dict_field, None)
        if not isinstance(d, dict):
            continue
        for key, val in d.items():
            if key not in PATH_METRIC_KEYS or not isinstance(val, str) or not val.strip():
                continue
            if key in PROVENANCE_PATH_KEYS:
                # Cleared by strip_host_paths; not a packable companion.
                continue
            if not (is_host_path(val) or Path(val).is_absolute()):
                continue
            try:
                exists = Path(val).exists()
            except OSError:
                exists = False
            if not exists:
                found.append(f"{type(obj).__name__}.{dict_field}[{key}]={val!r} (missing)")
    for r in getattr(obj, "refs", None) or []:
        sp = getattr(r, "source_path", "") or ""
        if not sp.strip():
            continue
        try:
            exists = Path(sp).exists()
        except OSError:
            exists = False
        if not exists and not (getattr(r, "uri", "") and getattr(r, "sha256", "")):
            found.append(
                f"ArtifactRef(role={getattr(r, 'role', '')}).source_path={sp!r} (missing)"
            )
    return found


def scan_host_paths(obj: Any) -> list[str]:
    """Return descriptions of unreclaimed host / source paths still on *obj*."""
    found: list[str] = []
    for field in ("model_path", "tflite_path", "artifact_path", "manifest_path", "path", "uri"):
        if not hasattr(obj, field):
            continue
        raw = getattr(obj, field, None)
        if not isinstance(raw, str) or not raw.strip():
            continue
        if field == "uri" and raw.startswith(("s3://", "artifact://", "http://", "https://")):
            continue
        if is_host_path(raw) or (not raw.startswith("artifact://") and Path(raw).is_absolute()):
            found.append(f"{type(obj).__name__}.{field}={raw!r}")
    for dict_field in ("metrics", "metadata"):
        d = getattr(obj, dict_field, None)
        if isinstance(d, dict):
            for key, val in d.items():
                if not isinstance(val, str) or not val.strip():
                    continue
                if val.startswith(("artifact://", "s3://", "http://", "https://")):
                    continue
                key_is_path = key in PATH_METRIC_KEYS or str(key).endswith("_path") or str(key).endswith("_dir")
                if key_is_path and (is_host_path(val) or Path(val).is_absolute()):
                    found.append(f"{type(obj).__name__}.{dict_field}[{key}]={val!r}")
    for r in getattr(obj, "refs", None) or []:
        sp = getattr(r, "source_path", "") or ""
        if sp.strip():
            found.append(f"ArtifactRef(role={getattr(r, 'role', '')}).source_path={sp!r}")
    return found


def hydrate_ref_bytes(
    ref: Any,
    data: bytes,
    *,
    dest_root: Path,
) -> Path:
    """Write *data* for *ref* under *dest_root* using ``relative_path`` layout."""
    from app.models.artifact_ref import ArtifactRef

    if not isinstance(ref, ArtifactRef):
        ref = ArtifactRef.model_validate(ref)
    digest = (ref.sha256 or hashlib.sha256(data).hexdigest()).lower()
    if ref.sha256 and ref.sha256.lower() != hashlib.sha256(data).hexdigest():
        raise ValueError(
            f"ArtifactRef role={ref.role!r} hash mismatch: "
            f"expected {ref.sha256}, got {hashlib.sha256(data).hexdigest()}"
        )
    rel = _safe_relpath(
        ref.relative_path or ref.filename or ref.role or digest[:12],
        default=_safe_basename(ref.filename or ref.role or "artifact"),
    )
    dest = dest_root / rel
    kind = str(ref.kind or "file")
    if kind == "dir":
        marker = dest_root / f".{rel.replace('/', '__')}.extracted"
        if not marker.is_file():
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            unpack_directory(data, dest)
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(digest, encoding="utf-8")
        return dest
    if not dest.is_file() or dest.stat().st_size != len(data):
        atomic_write_bytes(dest, data)
    return dest


def materialize_refs_onto(
    obj: Any,
    *,
    dest_root: Path,
    get_companion: Callable[..., bytes],
) -> Any:
    """Fetch each ref blob, write under *dest_root*, rewrite local path fields."""
    from app.models.artifact_ref import ArtifactRef

    refs = list(getattr(obj, "refs", None) or [])
    if not refs:
        return obj
    dest_root = Path(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)
    local_by_role: dict[str, Path] = {}
    new_refs: list[Any] = []
    for raw in refs:
        try:
            ref = raw if isinstance(raw, ArtifactRef) else ArtifactRef.model_validate(raw)
        except Exception:
            continue
        uri = str(ref.uri or "")
        if not uri:
            new_refs.append(ref)
            continue
        data = get_companion(uri, expected_sha256=ref.sha256 or None)
        local = hydrate_ref_bytes(ref, data, dest_root=dest_root)
        local_by_role[str(ref.role)] = local
        new_refs.append(ref.model_copy(update={"source_path": ""}))
    obj = _set_refs(obj, new_refs)

    name = type(obj).__name__
    if name == "ModelArtifact" or (
        hasattr(obj, "model_path") and hasattr(obj, "labels") and hasattr(obj, "metrics")
    ):
        primary = (
            local_by_role.get("saved_model")
            or local_by_role.get("keras_model")
            or local_by_role.get("pytorch_model")
            or next(iter(local_by_role.values()), None)
        )
        if primary is not None:
            obj = _set_field(obj, "model_path", str(primary))
        metrics = dict(getattr(obj, "metrics", None) or {})
        if "keras_model" in local_by_role:
            metrics["keras_model_path"] = str(local_by_role["keras_model"])
        if "labels" in local_by_role:
            metrics["labels_path"] = str(local_by_role["labels"])
        if "saved_model" in local_by_role:
            metrics["saved_model_path"] = str(local_by_role["saved_model"])
        if metrics != (getattr(obj, "metrics", None) or {}):
            obj = _set_field(obj, "metrics", metrics)
    elif name == "TFLiteArtifact" or (
        hasattr(obj, "tflite_path") and hasattr(obj, "quantisation")
    ):
        if "tflite" in local_by_role:
            obj = _set_field(obj, "tflite_path", str(local_by_role["tflite"]))
        if "labels" in local_by_role:
            meta = dict(getattr(obj, "metadata", None) or {})
            meta["labels_path"] = str(local_by_role["labels"])
            # TFLiteArtifact has no metadata field historically — use metrics if present.
            if hasattr(obj, "metadata"):
                obj = _set_field(obj, "metadata", meta)
            elif hasattr(obj, "metrics"):
                metrics = dict(getattr(obj, "metrics", None) or {})
                metrics["labels_path"] = str(local_by_role["labels"])
                obj = _set_field(obj, "metrics", metrics)
    elif name == "DeploymentArtifact" or (
        hasattr(obj, "artifact_path") and hasattr(obj, "model_format")
    ):
        primary = (
            local_by_role.get("deployment_bundle")
            or local_by_role.get("tflite")
            or next(iter(local_by_role.values()), None)
        )
        if primary is not None:
            obj = _set_field(obj, "artifact_path", str(primary))
        meta = dict(getattr(obj, "metadata", None) or {})
        if "labels" in local_by_role:
            meta["labels_path"] = str(local_by_role["labels"])
        # Provenance host paths must not revive after hydrate.
        for stale in ("source_model_path", "source", "package_path"):
            if stale in meta and isinstance(meta[stale], str) and (
                is_host_path(meta[stale]) or Path(meta[stale]).is_absolute()
            ):
                meta[stale] = ""
        if meta != (getattr(obj, "metadata", None) or {}):
            obj = _set_field(obj, "metadata", meta)
    elif name == "CsvTableResult" or (
        hasattr(obj, "path") and hasattr(obj, "rows") and hasattr(obj, "row_count")
        and not hasattr(obj, "model_path") and not hasattr(obj, "artifact_path")
    ):
        if "other" in local_by_role:
            obj = _set_field(obj, "path", str(local_by_role["other"]))
    elif name == "ObjectRef" or (
        hasattr(obj, "key") and hasattr(obj, "uri") and hasattr(obj, "backend")
        and not hasattr(obj, "model_path")
    ):
        if "other" in local_by_role:
            obj = _set_field(obj, "uri", str(local_by_role["other"]))
    return obj


def primary_local_path(obj: Any) -> str:
    """Best-effort local path for plugin loading after hydrate."""
    for field in ("model_path", "tflite_path", "artifact_path", "path", "uri"):
        val = getattr(obj, field, None)
        if isinstance(val, str) and val.strip():
            if field == "uri" and val.startswith(("s3://", "artifact://", "http://", "https://")):
                continue
            return val
    metrics = getattr(obj, "metrics", None) or {}
    if isinstance(metrics, dict):
        for key in ("keras_model_path", "saved_model_path", "labels_path"):
            val = metrics.get(key)
            if isinstance(val, str) and val.strip():
                return val
    meta = getattr(obj, "metadata", None) or {}
    if isinstance(meta, dict):
        for key in ("labels_path",):
            val = meta.get(key)
            if isinstance(val, str) and val.strip():
                return val
    return ""


def has_path_bearing_contract(obj: Any) -> bool:
    """True if *obj* is a known path-bearing platform artifact."""
    if obj is None or isinstance(obj, (str, bytes, int, float, bool, complex)):
        return False
    name = type(obj).__name__
    if name in {"ModelArtifact", "TFLiteArtifact", "DeploymentArtifact", "CsvTableResult", "ObjectRef"}:
        return True
    if hasattr(obj, "model_path") and hasattr(obj, "labels") and hasattr(obj, "metrics"):
        return True
    if hasattr(obj, "tflite_path") and hasattr(obj, "quantisation"):
        return True
    if hasattr(obj, "artifact_path") and hasattr(obj, "model_format"):
        return True
    if hasattr(obj, "path") and hasattr(obj, "rows") and hasattr(obj, "row_count") and not hasattr(obj, "model_path"):
        return True
    if hasattr(obj, "key") and hasattr(obj, "uri") and hasattr(obj, "backend") and not hasattr(obj, "model_path"):
        return True
    return False
