# app/core/mlops/ship_packages.py
"""
Bounded Context:  BC6 — Observability & Storage / Ship packages
Responsibility:   File-backed ship package store + lifecycle (§19 / §9.2.14).
Owns:             create/list/get/download/promote/transition helpers;
                  model payload + labels.txt embedding and label-order
                  validation (LabelsMismatch → ``labels_mismatch``).
                  If-Match check + manifest write run under a per-package
                  lock (project_pipelines.resource_lock) — no lost updates.
Public Surface:   Same helpers for API / MCP; InvalidPackageTransition,
                  LabelsMismatch.
Must NOT:         Import app.api or app.domain.
Dependencies:     stdlib; model_registry (lazy); run_summary (lazy); project_pipelines
                  (resource_lock, lazy); audit (lazy).
Reason To Change: Manifest schema or lifecycle matrix changes.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

log = logging.getLogger(__name__)

MANIFEST_SCHEMA_VERSION = "1.0"
PACKAGE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

# Canonical lifecycle states (SRS §19.2)
LIFECYCLE_STATES = frozenset(
    {
        "draft",
        "validated",
        "built",
        "signed",
        "published",
        "deployed",
        "failed",
        "superseded",
    }
)
TERMINAL_STATES = frozenset({"failed", "superseded"})

# Read aliases (SHIP-007)
_READ_ALIASES = {
    "creating": "draft",
    "ready": "built",
}

# Action → next status matrix (None = illegal)
_MATRIX: dict[str, dict[str, Optional[str]]] = {
    "draft": {
        "validate": "validated",
        "fail": "failed",
    },
    "validated": {
        "build": "built",
        "fail": "failed",
    },
    "built": {
        "sign": "signed",
        "fail": "failed",
        # Dev shortcut: allow publish without sign when unsigned_allowed
        "publish": "published",
    },
    "signed": {
        "publish": "published",
        "fail": "failed",
    },
    "published": {
        "deploy": "deployed",
        "supersede": "superseded",
        "fail": "failed",
    },
    "deployed": {
        "supersede": "superseded",
        "fail": "failed",
    },
    "failed": {},
    "superseded": {},
}


class InvalidPackageTransition(ValueError):
    """Illegal package lifecycle transition → HTTP 409 invalid_transition."""

    def __init__(self, current: str, action: str) -> None:
        self.current = current
        self.action = action
        super().__init__(f"invalid_transition: cannot {action} from status={current}")


def normalize_status(status: Optional[str]) -> str:
    if not status or not isinstance(status, str):
        return "unknown"
    s = status.strip().lower()
    if s in _READ_ALIASES:
        return _READ_ALIASES[s]
    return s


def wire_status(status: str) -> str:
    """Optional create-response aliases (creating/ready) for POST create."""
    cur = normalize_status(status)
    if cur == "draft":
        return "creating"
    if cur in ("built", "signed"):
        return "ready"
    return cur


def can_transition(current: str, action: str) -> bool:
    cur = normalize_status(current)
    row = _MATRIX.get(cur)
    if row is None:
        return False
    return row.get(action) is not None


def next_status(current: str, action: str) -> str:
    cur = normalize_status(current)
    row = _MATRIX.get(cur)
    if row is None:
        raise InvalidPackageTransition(cur, action)
    nxt = row.get(action)
    if nxt is None:
        raise InvalidPackageTransition(cur, action)
    return nxt


def packages_root(project_dir: Path) -> Path:
    return Path(project_dir) / "ship" / "packages"


def package_dir(project_dir: Path, package_id: str) -> Path:
    safe = (package_id or "").strip()
    if not PACKAGE_ID_RE.match(safe):
        raise ValueError(f"Invalid package_id {package_id!r}")
    root = packages_root(project_dir).resolve()
    path = (root / safe).resolve()
    if not str(path).startswith(str(root) + "/") and path != root:
        raise ValueError("Invalid package path")
    return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".pkg-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with open(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
            fh.flush()
            try:
                import os

                os.fsync(fh.fileno())
            except OSError:
                pass
        tmp.replace(path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_manifest(pkg_dir: Path) -> dict[str, Any]:
    path = pkg_dir / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"Package not found at {pkg_dir.name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Corrupt package manifest")
    if "status" in data:
        data["status"] = normalize_status(str(data["status"]))
    return data


def _save_manifest(pkg_dir: Path, manifest: dict[str, Any]) -> None:
    _atomic_write_json(pkg_dir / "manifest.json", manifest)


def _resolve_model_ref(
    model_name: str,
    model_stage_or_version: str,
) -> dict[str, Any]:
    from app.core.mlops.model_registry import get_model

    try:
        rec = get_model(model_name)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Model '{model_name}' not found") from exc
    stages = rec.get("stages") if isinstance(rec.get("stages"), dict) else {}
    stage_key = (model_stage_or_version or "").strip().lower()
    stage_rec = None
    if stage_key in stages and isinstance(stages[stage_key], dict):
        stage_rec = stages[stage_key]
    elif stage_key and stage_key not in ("latest", "staging", "prod"):
        # Treat as explicit run_id match across stages
        for _name, srec in stages.items():
            if isinstance(srec, dict) and str(srec.get("run_id") or "") == model_stage_or_version:
                stage_rec = srec
                stage_key = _name
                break
    if stage_rec is None:
        # Prefer requested stage, else latest, else staging
        for candidate in (stage_key, "latest", "staging", "prod"):
            if candidate in stages and isinstance(stages[candidate], dict):
                stage_rec = stages[candidate]
                stage_key = candidate
                break
    if not isinstance(stage_rec, dict) or not stage_rec.get("run_id"):
        raise ValueError(
            f"Model '{model_name}' has no usable stage/version '{model_stage_or_version}'"
        )
    return {
        "name": model_name,
        "stage_or_version": stage_key or model_stage_or_version,
        "run_id": str(stage_rec.get("run_id") or ""),
        "artifact_id": str(stage_rec.get("slug") or rec.get("slug") or ""),
        "slug": str(stage_rec.get("slug") or rec.get("slug") or ""),
    }


class LabelsMismatch(ValueError):
    """Requested label order differs from the model's labels.txt → 422 ``labels_mismatch``."""

    def __init__(self, expected: list[str], got: list[str], source: str | None = None) -> None:
        self.expected = list(expected)
        self.got = list(got)
        self.source = source
        super().__init__(
            "labels do not match the model's class order "
            f"(expected {self.expected}, got {self.got})"
        )


# Max bytes of model payload copied into package.zip (bigger → pointer only).
MAX_EMBED_MODEL_BYTES = 256 * 1024 * 1024


def _resolve_model_file(
    *,
    model_path: str | None,
    run_id: str | None,
    stage_artifact: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return ``{path, fs_path, format, kind, node_id, labels, labels_source}`` or None."""
    from app.core.runs.run_summary import (
        model_row_for_path,
        read_labels_txt,
        resolve_workspace_path,
        to_workspace_rel,
        MODEL_FILE_FORMATS,
    )

    raw = model_path or (stage_artifact or {}).get("artifact_path")
    if not raw:
        return None
    fs = resolve_workspace_path(str(raw))
    if fs is None or not fs.exists():
        raise FileNotFoundError(f"Model file not found: {raw}")
    try:
        from app.core.config import project_dir

        root = project_dir().resolve()
        if not fs.resolve().is_relative_to(root):
            raise ValueError(f"model_path must be inside the workspace: {raw}")
    except OSError:
        pass
    row: dict[str, Any] | None = None
    rid = run_id or (stage_artifact or {}).get("source_run_id") or (stage_artifact or {}).get("run_id")
    if rid:
        try:
            from app.core.config import runs_dir

            rp = runs_dir() / str(rid)
            if rp.is_dir():
                row = model_row_for_path(str(rid), rp, str(raw))
        except Exception:
            row = None
    if fs.is_dir():
        fmt = "saved_model" if (fs / "saved_model.pb").is_file() else "directory"
    else:
        fmt = MODEL_FILE_FORMATS.get(fs.suffix.lower(), fs.suffix.lstrip(".").lower() or "file")
    txt = read_labels_txt(fs)
    labels = txt or list((row or {}).get("labels") or (stage_artifact or {}).get("labels") or [])
    return {
        "path": to_workspace_rel(fs),
        "fs_path": fs,
        "format": (row or {}).get("format") or fmt,
        "kind": (row or {}).get("kind") or (stage_artifact or {}).get("artifact_kind"),
        "node_id": (row or {}).get("node_id") or (stage_artifact or {}).get("node_id"),
        "run_id": rid,
        "labels": labels,
        "labels_source": "labels.txt" if txt else ((row or {}).get("labels_source") or ("registry" if labels else None)),
    }


def _embed_model(zf: zipfile.ZipFile, fs: Path) -> list[tuple[str, bytes | Path]]:
    """Return [(arcname, path)] of model payload files (size-capped)."""
    items: list[tuple[str, Path]] = []
    if fs.is_file():
        items.append((f"model/{fs.name}", fs))
    elif fs.is_dir():
        for p in sorted(fs.rglob("*")):
            if p.is_file():
                items.append((f"model/{fs.name}/{p.relative_to(fs).as_posix()}", p))
    total = 0
    for _arc, p in items:
        try:
            total += p.stat().st_size
        except OSError:
            pass
    if total > MAX_EMBED_MODEL_BYTES:
        return []
    return items  # type: ignore[return-value]


def _summary(manifest: dict[str, Any]) -> dict[str, Any]:
    checksums = manifest.get("checksums") if isinstance(manifest.get("checksums"), dict) else {}
    return {
        "package_id": manifest.get("package_id"),
        "status": normalize_status(str(manifest.get("status") or "")),
        "env": manifest.get("env") or "draft",
        "model_ref": manifest.get("model_ref"),
        "created_at": manifest.get("created_at"),
        "checksum": checksums.get("sha256"),
    }


def list_packages(
    project_dir: Path,
    *,
    limit: int = 100,
    env: str | None = None,
) -> dict[str, Any]:
    root = packages_root(project_dir)
    if not root.is_dir():
        return {"items": [], "total": 0}
    items: list[dict[str, Any]] = []
    for child in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime if p.is_dir() else 0, reverse=True):
        if not child.is_dir():
            continue
        try:
            man = _load_manifest(child)
        except Exception:
            continue
        if env and str(man.get("env") or "").lower() != env.strip().lower():
            continue
        items.append(_summary(man))
    total = len(items)
    limit = max(1, min(int(limit or 100), 500))
    return {"items": items[:limit], "total": total}


def get_package(project_dir: Path, package_id: str) -> dict[str, Any]:
    pkg = package_dir(project_dir, package_id)
    if not pkg.is_dir():
        raise FileNotFoundError(f"Package '{package_id}' not found")
    man = _load_manifest(pkg)
    return {
        "package_id": man.get("package_id"),
        "status": normalize_status(str(man.get("status") or "")),
        "env": man.get("env") or "draft",
        "manifest": man,
        "checksums": man.get("checksums") or {},
        "created_at": man.get("created_at"),
        "resource_version": man.get("resource_version") or 1,
    }


def create_package(
    project_dir: Path,
    *,
    project_name: str,
    model_name: str | None,
    model_stage_or_version: str | None,
    target: dict[str, Any],
    env: str = "draft",
    actor: str = "api",
    notes: str | None = None,
    unsigned_allowed: bool = True,
    package_id: str | None = None,
    model_path: str | None = None,
    run_id: str | None = None,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Create package, write archive+manifest, advance to ``built`` (SHIP-001).

    Model source: a registered ``model_name``@``model_stage_or_version``
    (its stage's real artifact), and/or ``model_path`` (+ ``run_id``) from
    GET /runs/{id}/models. The model file (≤ 256 MB) and ``labels.txt`` are
    embedded in the archive. ``labels`` must match the model's labels.txt
    order exactly, else :class:`LabelsMismatch` (``labels_mismatch``).
    """
    if not isinstance(target, dict) or not target:
        raise ValueError("target object required (runtime/arch)")
    runtime = str(target.get("runtime") or "").strip()
    if not runtime:
        raise ValueError("target.runtime is required")
    env_s = (env or "draft").strip().lower()
    if env_s not in ("draft", "staging", "prod"):
        raise ValueError("env must be draft, staging, or prod")

    warnings: list[dict[str, Any]] = []
    stage_artifact: dict[str, Any] | None = None
    if model_name:
        model_ref = _resolve_model_ref(model_name, model_stage_or_version or "staging")
        try:
            from app.core.mlops.model_registry import describe_model

            described = describe_model(model_name)
            st = (described.get("stages") or {}).get(model_ref.get("stage_or_version"))
            if isinstance(st, dict):
                stage_artifact = st
        except Exception:
            stage_artifact = None
    elif model_path:
        model_ref = {
            "name": None,
            "stage_or_version": "run",
            "run_id": str(run_id or ""),
            "artifact_id": "",
            "slug": "",
        }
    else:
        raise ValueError("model_name or model_path is required")
    model_file = _resolve_model_file(
        model_path=model_path,
        run_id=run_id or (model_ref.get("run_id") or None),
        stage_artifact=stage_artifact,
    )
    if model_file is not None:
        expected = list(model_file.get("labels") or [])
        if labels is not None:
            got = [str(x) for x in labels]
            if expected and got != expected:
                raise LabelsMismatch(expected, got, model_file.get("labels_source"))
            if not expected and got:
                warnings.append(
                    {"code": "labels_unverified", "message": "model has no labels.txt to verify against"}
                )
                model_file["labels"] = got
        if model_file.get("kind") == "compiled_untrained":
            warnings.append(
                {
                    "code": "compiled_untrained",
                    "message": "model is a compiled-but-untrained model_builder output",
                }
            )
        model_ref.update(
            {
                "model_path": model_file["path"],
                "format": model_file.get("format"),
                "node_id": model_file.get("node_id"),
                "labels": model_file.get("labels") or [],
            }
        )
        if not model_ref.get("run_id") and model_file.get("run_id"):
            model_ref["run_id"] = str(model_file["run_id"])
    pid = (package_id or f"pkg-{uuid4().hex[:12]}").strip()
    if not PACKAGE_ID_RE.match(pid):
        raise ValueError(f"Invalid package_id {pid!r}")

    pkg = package_dir(project_dir, pid)
    if pkg.exists():
        raise ValueError(f"Package '{pid}' already exists")
    pkg.mkdir(parents=True, exist_ok=False)

    created_at = _now()
    files_meta: list[dict[str, Any]] = []
    archive_bytes = io.BytesIO()

    # Build a minimal archive: manifest stub + model pointer payload
    model_payload = {
        "model_name": model_name,
        "model_ref": model_ref,
        "target": target,
        "created_at": created_at,
    }
    model_json = (json.dumps(model_payload, indent=2) + "\n").encode("utf-8")
    model_sha = _sha256_bytes(model_json)
    files_meta.append(
        {
            "path": "model/ref.json",
            "sha256": model_sha,
            "size": len(model_json),
            "role": "model_ref",
        }
    )
    readme = (
        f"Graphyn ship package {pid}\n"
        f"model={model_name or model_ref.get('model_path')}@{model_ref.get('stage_or_version')}\n"
        f"runtime={runtime}\n"
    ).encode("utf-8")
    files_meta.append(
        {
            "path": "README.txt",
            "sha256": _sha256_bytes(readme),
            "size": len(readme),
            "role": "docs",
        }
    )

    with zipfile.ZipFile(archive_bytes, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("model/ref.json", model_json)
        zf.writestr("README.txt", readme)
        if model_file is not None:
            embedded = _embed_model(zf, model_file["fs_path"])
            if not embedded:
                warnings.append(
                    {"code": "model_not_embedded", "message": "model too large; package holds a pointer only"}
                )
            for arc, src in embedded:
                data = Path(src).read_bytes()
                zf.writestr(arc, data)
                files_meta.append(
                    {"path": arc, "sha256": _sha256_bytes(data), "size": len(data), "role": "model"}
                )
            lbls = model_file.get("labels") or []
            if lbls:
                ltxt = ("\n".join(lbls) + "\n").encode("utf-8")
                zf.writestr("model/labels.txt", ltxt)
                files_meta.append(
                    {"path": "model/labels.txt", "sha256": _sha256_bytes(ltxt), "size": len(ltxt), "role": "labels"}
                )
    archive_data = archive_bytes.getvalue()
    archive_sha = _sha256_bytes(archive_data)
    archive_path = pkg / "package.zip"
    archive_path.write_bytes(archive_data)

    compatibility = {
        "min_runtime_version": str(target.get("min_runtime_version") or "0.0.0"),
        "opset": target.get("opset"),
        "features": list(target.get("features") or []),
    }
    if not isinstance(compatibility["features"], list):
        compatibility["features"] = []

    manifest: dict[str, Any] = {
        "package_id": pid,
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "created_at": created_at,
        "actor": actor,
        "project": project_name,
        "target": {
            "runtime": runtime,
            "arch": target.get("arch") or target.get("architecture") or "any",
            "os": target.get("os"),
            "device_class": target.get("device_class"),
        },
        "runtime": runtime,
        "model_ref": model_ref,
        "preprocessing_deps": list(target.get("preprocessing_deps") or []),
        "graph_hash": target.get("graph_hash"),
        "files": files_meta,
        "checksums": {"sha256": archive_sha},
        "signatures": [],
        "compatibility": compatibility,
        "env": env_s if env_s != "prod" else "staging",  # create never lands on prod channel
        "status": "draft",
        "lineage": {
            "run_id": model_ref.get("run_id"),
            "model_name": model_name,
            "dataset_versions": list(target.get("dataset_versions") or []),
        },
        "notes": notes or "",
        "warnings": warnings,
        "labels": list((model_file or {}).get("labels") or []),
        "unsigned_allowed": bool(unsigned_allowed),
        "deployment_status": "not_deployed",
        "resource_version": 1,
        "updated_at": created_at,
    }
    # Advance draft → validated → built (and optionally signed when unsigned_allowed)
    manifest["status"] = "validated"
    manifest["status"] = "built"
    if unsigned_allowed:
        manifest["signatures"] = [
            {"alg": "unsigned", "value": "", "key_id": "dev-unsigned"}
        ]
        manifest["status"] = "signed"
    _save_manifest(pkg, manifest)

    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor=actor,
            action="ship.create",
            resource_type="ship_package",
            resource_id=pid,
            meta={
                "model_name": model_name,
                "stage": model_ref.get("stage_or_version"),
                "status": manifest["status"],
                "checksum": archive_sha,
            },
        )
    except Exception:
        pass

    return {
        "package_id": pid,
        "status": wire_status(str(manifest["status"])),
        "manifest": manifest,
        "warnings": warnings,
    }



def _package_lock(pkg_dir: Path):
    from app.core.pipelines.project_pipelines import resource_lock

    return resource_lock(pkg_dir / ".manifest.lock")


def _check_resource_version(man: dict, expected: str | None, *, via_if_match: bool) -> None:
    if expected is None:
        return
    current = str(man.get("resource_version") or 1)
    if str(expected) != current:
        from app.core.errors import VersionConflict
        raise VersionConflict(via_if_match=via_if_match, current=current)


def transition_package(
    project_dir: Path,
    package_id: str,
    action: str,
    *,
    actor: str = "api",
    expected_resource_version: str | None = None,
    via_if_match: bool = False,
) -> dict[str, Any]:
    action_s = (action or "").strip().lower()
    pkg = package_dir(project_dir, package_id)
    if not pkg.is_dir():
        raise FileNotFoundError(f"Package '{package_id}' not found")
    with _package_lock(pkg):
        current, nxt = _transition_locked(
            pkg,
            action_s,
            expected_resource_version=expected_resource_version,
            via_if_match=via_if_match,
        )
    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor=actor,
            action=f"ship.{action_s}",
            resource_type="ship_package",
            resource_id=package_id,
            meta={"from": current, "to": nxt},
        )
    except Exception:
        pass
    return get_package(project_dir, package_id)


def _transition_locked(
    pkg: Path,
    action_s: str,
    *,
    expected_resource_version: str | None,
    via_if_match: bool,
) -> tuple[str, str]:
    man = _load_manifest(pkg)
    _check_resource_version(man, expected_resource_version, via_if_match=via_if_match)
    current = normalize_status(str(man.get("status") or ""))
    # Special: publish from built requires unsigned_allowed or already signed
    if action_s == "publish" and current == "built" and not man.get("unsigned_allowed"):
        raise InvalidPackageTransition(current, action_s)
    nxt = next_status(current, action_s)
    man["status"] = nxt
    man["updated_at"] = _now()
    man["resource_version"] = int(man.get("resource_version") or 1) + 1
    if nxt == "deployed":
        man["deployment_status"] = "deployed"
    if nxt == "failed":
        man["deployment_status"] = "failed"
    _save_manifest(pkg, man)
    return current, nxt


def promote_package(
    project_dir: Path,
    package_id: str,
    *,
    to_env: str,
    approve: bool = False,
    actor: str = "api",
    expected_resource_version: str | None = None,
    via_if_match: bool = False,
) -> dict[str, Any]:
    to = (to_env or "").strip().lower()
    if to not in ("staging", "prod"):
        raise ValueError("to_env must be staging or prod")
    if to == "prod" and not approve:
        raise ValueError("approve=true required to promote ship package to prod")

    pkg = package_dir(project_dir, package_id)
    if not pkg.is_dir():
        raise FileNotFoundError(f"Package '{package_id}' not found")
    with _package_lock(pkg):
        man = _promote_locked(
            pkg,
            to,
            expected_resource_version=expected_resource_version,
            via_if_match=via_if_match,
        )

    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor=actor,
            action="ship.promote",
            resource_type="ship_package",
            resource_id=package_id,
            meta={"to_env": to, "approve": approve, "status": man["status"]},
        )
    except Exception:
        pass

    return {
        "package_id": package_id,
        "env": to,
        "status": normalize_status(str(man["status"])),
    }


def _promote_locked(
    pkg: Path,
    to: str,
    *,
    expected_resource_version: str | None,
    via_if_match: bool,
) -> dict[str, Any]:
    man = _load_manifest(pkg)
    _check_resource_version(man, expected_resource_version, via_if_match=via_if_match)
    current = normalize_status(str(man.get("status") or ""))
    if current in TERMINAL_STATES:
        raise InvalidPackageTransition(current, "promote")
    # Must be at least built (or signed/published/deployed)
    if current in ("draft", "validated"):
        raise InvalidPackageTransition(current, "promote")

    # Advance toward published if needed
    if current == "built":
        if man.get("unsigned_allowed"):
            man["signatures"] = man.get("signatures") or [
                {"alg": "unsigned", "value": "", "key_id": "dev-unsigned"}
            ]
            man["status"] = "signed"
            current = "signed"
        else:
            raise InvalidPackageTransition(current, "promote")
    if current == "signed":
        man["status"] = "published"
        current = "published"

    man["env"] = to
    man["updated_at"] = _now()
    man["resource_version"] = int(man.get("resource_version") or 1) + 1
    _save_manifest(pkg, man)
    return man


def download_package_path(project_dir: Path, package_id: str) -> tuple[Path, dict[str, Any]]:
    """Return (archive_path, manifest). Raises FileNotFoundError / conflict ValueError."""
    pkg = package_dir(project_dir, package_id)
    if not pkg.is_dir():
        raise FileNotFoundError(f"Package '{package_id}' not found")
    man = _load_manifest(pkg)
    status = normalize_status(str(man.get("status") or ""))
    if status in ("draft", "validated", "failed"):
        raise ValueError(f"Package not ready for download (status={status})")
    archive = pkg / "package.zip"
    if not archive.is_file():
        raise FileNotFoundError(f"Package archive missing for '{package_id}'")
    return archive, man
