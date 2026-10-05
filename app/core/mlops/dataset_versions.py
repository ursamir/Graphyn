# app/core/mlops/dataset_versions.py
"""
Bounded Context:  BC6 — Data / datasets
Responsibility:   Dataset version manifest sha256 (DATA-VER-002),
                  referenced-version delete guard (DATA-VER-006) and the
                  immutable-version helpers (next free version, existence).
Owns:             compute/write/read manifest, aggregate_content_hash,
                  find_references, VERSION_RE, version_has_content,
                  next_free_version, delete helpers.
Public Surface:   Same.
Must NOT:         Import app.api.
Dependencies:     hashlib, json, os, tempfile, pathlib, app.core.config.
Reason To Change: Manifest schema or reference scan rules change.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"
# Canonical dataset version directory names: v1, v2, v1.0.0 …
VERSION_RE = re.compile(r"^v\d+(\.\d+)*$")
_SKIP_DIR_NAMES = frozenset({"ship", "pipelines", "snapshots", ".git"})
# Per-run documents scanned by the delete guard (meta first, then the graph).
_RUN_REF_FILES = ("meta.json", "graph.json", "ir.json", "pipeline.graph.json")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def aggregate_content_hash(entries: list[tuple[str, str]]) -> str:
    """Aggregate ``[(rel_posix_path, sha256)]`` into one content hash.

    Same algorithm as :func:`compute_manifest` (entries sorted part-wise like
    ``sorted(Path.rglob())``, joined as ``"<sha256>:<path>"`` lines) so streamed zips and ingest jobs can report
    a hash that equals the manifest a later snapshot would compute.
    """
    lines = [f"{digest}:{rel}" for rel, digest in sorted(entries, key=lambda e: tuple(e[0].split("/")))]
    if not lines:
        return hashlib.sha256(b"").hexdigest()
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def version_has_content(version_dir: Path) -> bool:
    """True when *version_dir* exists and holds at least one entry."""
    try:
        return version_dir.is_dir() and any(version_dir.iterdir())
    except OSError:
        return False


def _bump(tag: str) -> str:
    """v3 → v4; v1.0.2 → v1.0.3 (last numeric component)."""
    nums = tag[1:].split(".")
    nums[-1] = str(int(nums[-1]) + 1)
    return "v" + ".".join(nums)


def next_free_version(parent: Path, requested: str | None = None) -> str:
    """Next unused version under *parent*.

    With *requested* (``vN`` / ``vN.N.N``): that tag when free (missing or
    empty dir), else the tag bumped until free. Without: ``v<max major + 1>``
    over existing ``vN…`` dirs (``v1`` when none).
    """
    if requested:
        if not VERSION_RE.match(requested):
            raise ValueError(f"Invalid version {requested!r} (expected vN / vN.N.N)")
        tag = requested
        for _ in range(100_000):
            if not version_has_content(parent / tag):
                return tag
            tag = _bump(tag)
        raise RuntimeError(f"No free dataset version under {parent}")
    top = 0
    try:
        for child in parent.iterdir():
            if child.is_dir() and VERSION_RE.match(child.name):
                try:
                    top = max(top, int(child.name[1:].split(".")[0]))
                except ValueError:
                    continue
    except OSError:
        pass
    return f"v{top + 1}"


def compute_manifest(version_dir: Path) -> dict[str, Any]:
    """Walk version dir and build ``{files[], content_hash, schema_version}``."""
    root = version_dir.resolve()
    files: list[dict[str, Any]] = []
    digests: list[tuple[str, str]] = []
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            # Skip nested ship/pipeline trees if accidentally under version
            parts = set(path.relative_to(root).parts[:-1])
            if parts & _SKIP_DIR_NAMES:
                continue
            if path.parent == root and (
                path.name == MANIFEST_NAME
                or (path.name.startswith(f".{MANIFEST_NAME}.") and path.name.endswith(".tmp"))
            ):
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
            digests.append((rel, digest))
    aggregate = aggregate_content_hash(digests)
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
    payload = json.dumps(man, indent=2, sort_keys=True) + "\n"
    # Unique tmp per writer: concurrent GETs that lazily (re)write the manifest
    # must not share one ``.json.tmp`` (the loser's os.replace would fail).
    fd, tmp_name = tempfile.mkstemp(
        dir=str(version_dir), prefix=f".{MANIFEST_NAME}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        try:
            os.chmod(tmp_name, 0o644)
        except OSError:
            pass
        os.replace(tmp_name, str(dest))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
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

    # Runs: meta.json plus the persisted graph (a run that ingested
    # ``datasets/output/<project>/<version>`` only cites it in its graph).
    try:
        rdir = runs_dir() if base_dir is None else root / "runs"
        if rdir.is_dir():
            for run_path in rdir.iterdir():
                if not run_path.is_dir():
                    continue
                for fname in _RUN_REF_FILES:
                    doc_path = run_path / fname
                    if not doc_path.is_file():
                        continue
                    try:
                        doc = json.loads(doc_path.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    if _scan_json_for_ref(doc, project, version):
                        refs.append({"kind": "run", "id": run_path.name})
                        break
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
        from app.core.mlops.ship_packages import packages_root

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
