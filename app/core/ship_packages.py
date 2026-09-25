# app/core/ship_packages.py
"""
Bounded Context:  BC6 — Observability & Storage / Ship packages
Responsibility:   File-backed ship package store + lifecycle (§19 / §9.2.14).
Owns:             create/list/get/download/promote/transition helpers.
Public Surface:   Same helpers for API / MCP; InvalidPackageTransition.
Must NOT:         Import app.api or app.domain.
Dependencies:     stdlib; model_registry (lazy); audit (lazy).
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
    from app.core.model_registry import get_model

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
    model_name: str,
    model_stage_or_version: str,
    target: dict[str, Any],
    env: str = "draft",
    actor: str = "api",
    notes: str | None = None,
    unsigned_allowed: bool = True,
    package_id: str | None = None,
) -> dict[str, Any]:
    """Create package, write archive+manifest, advance to ``built`` (SHIP-001)."""
    if not isinstance(target, dict) or not target:
        raise ValueError("target object required (runtime/arch)")
    runtime = str(target.get("runtime") or "").strip()
    if not runtime:
        raise ValueError("target.runtime is required")
    env_s = (env or "draft").strip().lower()
    if env_s not in ("draft", "staging", "prod"):
        raise ValueError("env must be draft, staging, or prod")

    model_ref = _resolve_model_ref(model_name, model_stage_or_version)
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
        f"model={model_name}@{model_ref.get('stage_or_version')}\n"
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
        from app.core.audit import record_audit

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
    }


def transition_package(
    project_dir: Path,
    package_id: str,
    action: str,
    *,
    actor: str = "api",
) -> dict[str, Any]:
    action_s = (action or "").strip().lower()
    pkg = package_dir(project_dir, package_id)
    if not pkg.is_dir():
        raise FileNotFoundError(f"Package '{package_id}' not found")
    man = _load_manifest(pkg)
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
    try:
        from app.core.audit import record_audit

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


def promote_package(
    project_dir: Path,
    package_id: str,
    *,
    to_env: str,
    approve: bool = False,
    actor: str = "api",
) -> dict[str, Any]:
    to = (to_env or "").strip().lower()
    if to not in ("staging", "prod"):
        raise ValueError("to_env must be staging or prod")
    if to == "prod" and not approve:
        raise ValueError("approve=true required to promote ship package to prod")

    pkg = package_dir(project_dir, package_id)
    if not pkg.is_dir():
        raise FileNotFoundError(f"Package '{package_id}' not found")
    man = _load_manifest(pkg)
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

    try:
        from app.core.audit import record_audit

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
