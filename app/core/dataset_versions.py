# app/core/dataset_versions.py
"""
Bounded Context:  BC6 — Data / datasets
Responsibility:   Dataset version manifest sha256 (DATA-VER-002) and
                  referenced-version delete guard (DATA-VER-006).
Owns:             compute/write/read manifest, find_references, delete helpers.
Public Surface:   Same.
Must NOT:         Import app.api.
Dependencies:     hashlib, json, pathlib, app.core.config.
Reason To Change: Manifest schema or reference scan rules change.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"
_SKIP_DIR_NAMES = frozenset({"ship", "pipelines", "snapshots", ".git"})


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def compute_manifest(version_dir: Path) -> dict[str, Any]:
    """Walk version dir and build ``{files[], content_hash, schema_version}``."""
    root = version_dir.resolve()
    files: list[dict[str, Any]] = []
    digests: list[str] = []
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            # Skip nested ship/pipeline trees if accidentally under version
            parts = set(path.relative_to(root).parts[:-1])
            if parts & _SKIP_DIR_NAMES:
                continue
            if path.name == MANIFEST_NAME and path.parent == root:
                continue
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                continue
            try:
                digest = _sha256_file(path)
                size = path.stat().st_size
            except OSError as exc:
                logger.warning("dataset manifest skip %s: %s", path, exc)
                continue
            files.append({"path": rel, "sha256": digest, "size": size})
            digests.append(f"{digest}:{rel}")
    aggregate = (
        hashlib.sha256("\n".join(digests).encode("utf-8")).hexdigest()
        if digests
        else hashlib.sha256(b"").hexdigest()
    )
    return {
        "schema_version": "1.0",
        "files": files,
        "content_hash": aggregate,
        "sha256": aggregate,
        "file_count": len(files),
    }


def write_manifest(version_dir: Path, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """Atomically write manifest.json under *version_dir*."""
    man = manifest or compute_manifest(version_dir)
    version_dir.mkdir(parents=True, exist_ok=True)
    dest = version_dir / MANIFEST_NAME
    tmp = dest.with_suffix(".json.tmp")
    payload = json.dumps(man, indent=2, sort_keys=True) + "\n"
    tmp.write_text(payload, encoding="utf-8")
    os.replace(str(tmp), str(dest))
    return man


def read_manifest(
    version_dir: Path,
    *,
    ensure: bool = True,
    enforce_sha256: bool = True,
) -> dict[str, Any]:
    """Load manifest; optionally compute+write when missing (ensure=True)."""
    path = version_dir / MANIFEST_NAME
    man: dict[str, Any] | None = None
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                man = raw
        except Exception as exc:
            logger.warning("corrupt dataset manifest at %s: %s", path, exc)
            man = None
    if man is None:
        if not ensure:
            raise FileNotFoundError(f"Dataset manifest missing under {version_dir}")
        return write_manifest(version_dir)
    if enforce_sha256 and not (man.get("content_hash") or man.get("sha256")):
        return write_manifest(version_dir)
    if man.get("content_hash") and not man.get("sha256"):
        man["sha256"] = man["content_hash"]
    if man.get("sha256") and not man.get("content_hash"):
        man["content_hash"] = man["sha256"]
    return man


def _scan_json_for_ref(obj: Any, project: str, version: str) -> bool:
    """True only for explicit project/version references (avoid bare 'v1' false positives)."""
    needle_pair = f"{project}/{version}"
    if isinstance(obj, str):
        s = obj.strip()
        if not s:
            return False
        # Require project-qualified forms — bare version alone is too ambiguous
        return (
            s == needle_pair
            or s.endswith(f"/{needle_pair}")
            or f"/{needle_pair}/" in f"/{s}/"
            or s.startswith(f"{needle_pair}/")
        )
    if isinstance(obj, dict):
        # Structured dataset version refs
        if obj.get("project") == project and obj.get("version") == version:
            return True
        if obj.get("dataset_version") == version and (
            not obj.get("project") or obj.get("project") == project
        ):
            return True
        # Explicit label_or_version / ref fields that include project/version
        for key in ("ref", "label_or_version", "path", "dataset"):
            val = obj.get(key)
            if isinstance(val, str) and _scan_json_for_ref(val, project, version):
                return True
        for v in obj.values():
            if isinstance(v, (dict, list)):
                if _scan_json_for_ref(v, project, version):
                    return True
            elif isinstance(v, str) and _scan_json_for_ref(v, project, version):
                return True
        return False
    if isinstance(obj, list):
        return any(_scan_json_for_ref(x, project, version) for x in obj)
    return False


def find_references(
    project: str,
    version: str,
    *,
    base_dir: Path | None = None,
) -> list[dict[str, str]]:
    """Return reference descriptors if any run/package/lineage cites this version."""
    from app.core.config import datasets_output_dir, project_dir, runs_dir

    refs: list[dict[str, str]] = []
    root = Path(base_dir) if base_dir is not None else project_dir()

    # Runs meta
    try:
        rdir = runs_dir() if base_dir is None else root / "runs"
        if rdir.is_dir():
            for meta_path in rdir.glob("*/meta.json"):
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if _scan_json_for_ref(meta, project, version):
                    refs.append({"kind": "run", "id": meta_path.parent.name})
    except Exception as exc:
        logger.debug("find_references runs scan: %s", exc)

    # Sibling lineage under same project
    try:
        out_root = datasets_output_dir() if base_dir is None else root / "datasets" / "output"
        proj = out_root / project
        if proj.is_dir():
            for lineage_path in proj.glob("*/lineage.json"):
                if lineage_path.parent.name == version:
                    continue
                try:
                    lin = json.loads(lineage_path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if _scan_json_for_ref(lin, project, version):
                    refs.append(
                        {
                            "kind": "lineage",
                            "id": f"{project}/{lineage_path.parent.name}",
                        }
                    )
    except Exception as exc:
        logger.debug("find_references lineage scan: %s", exc)

    # Ship package manifests (project ship packages dir)
    try:
        from app.core.ship_packages import packages_root

        proj_dir = (
            (datasets_output_dir() if base_dir is None else root / "datasets" / "output")
            / project
        )
        if proj_dir.is_dir():
            ship_root = packages_root(proj_dir)
            if ship_root.is_dir():
                for man_path in ship_root.glob("*/manifest.json"):
                    try:
                        man = json.loads(man_path.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    if _scan_json_for_ref(man, project, version):
                        refs.append({"kind": "ship_package", "id": man_path.parent.name})
    except Exception as exc:
        logger.debug("find_references ship scan: %s", exc)

    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for r in refs:
        key = (r["kind"], r["id"])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


class DatasetVersionInUse(Exception):
    def __init__(self, project: str, version: str, references: list[dict[str, str]]):
        self.project = project
        self.version = version
        self.references = references
        super().__init__(f"Dataset version {project}/{version} is referenced")
