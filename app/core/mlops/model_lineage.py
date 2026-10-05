# app/core/mlops/model_lineage.py
"""
Bounded Context:  BC6 — Observability & Storage / ML lifecycle (lineage)
Responsibility:   Model lineage in both directions for one registered model:
                  what each stage was MADE FROM (source run, dataset inputs,
                  graph hash, seed, node plugin version + code hash, the
                  node's step config) and where it was USED (runs whose sealed
                  record declares / consumed the model, ship packages built
                  from it).
Owns:             model_lineage(), clear_lineage_cache(); the cached index of
                  sealed run records (keyed by runs-dir mtime + per-record
                  prove.json mtime).
Public Surface:   model_lineage(name, *, base_dir=None, project_dirs=None)
                  -> {name, stages, pending_prod, used_in, packages}.
Must NOT:         Import app.api / app.domain; mutate registry or run files.
Dependencies:     stdlib; app.core.mlops.model_registry (get_model,
                  _runs_root); app.core.runs.audit_record (load_record,
                  resolve_path, hash_path); app.core.runs.run_listing
                  (ARCHIVE_MARKER); app.core.mlops.ship_packages (lazy).
Reason To Change: Lineage payload, record schema or registry schema changes.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()
# runs_root → {"key": mtime_ns, "rows": [...], "unsealed": set[str]}
_SCAN: dict[str, dict[str, Any]] = {}
# run_dir → (prove.json mtime_ns, slim row)
_RECORDS: dict[str, tuple[int, dict[str, Any]]] = {}


def clear_lineage_cache() -> None:
    with _lock:
        _SCAN.clear()
        _RECORDS.clear()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _abs(raw: Any) -> str | None:
    if not raw:
        return None
    try:
        from app.core.runs.audit_record import resolve_path

        return os.path.abspath(resolve_path(str(raw)))
    except Exception:
        return None


def _same_or_nested(a: str, b: str) -> bool:
    return a == b or a.startswith(b.rstrip(os.sep) + os.sep) or b.startswith(a.rstrip(os.sep) + os.sep)


def _sha256(content_hash: Any) -> str | None:
    s = str(content_hash or "")
    return s.split(":", 1)[1] if s.startswith("sha256:") else None


def _slim(run_dir: Path, rec: dict[str, Any]) -> dict[str, Any]:
    from app.core.runs.run_listing import ARCHIVE_MARKER

    lineage = rec.get("lineage") if isinstance(rec.get("lineage"), dict) else {}
    models = [
        {"name": m.get("name"), "stage": m.get("stage"), "match": m.get("match")}
        for m in lineage.get("models") or [] if isinstance(m, dict)
    ]
    inputs = []
    for row in rec.get("external_inputs") or []:
        if isinstance(row, dict) and row.get("path"):
            inputs.append({"abs": _abs(row.get("resolved") or row.get("path")), "label": row.get("label"),
                           "node_id": row.get("node_id"), "path": row.get("path")})
    outputs = [
        {"path": o.get("path"), "node_id": o.get("node_id"), "content_hash": o.get("content_hash"),
         "hash_mode": o.get("hash_mode"), "kind": o.get("kind")}
        for o in rec.get("outputs") or [] if isinstance(o, dict) and o.get("path")
    ]
    return {
        "run_id": rec.get("run_id") or run_dir.name,
        "created_at": rec.get("created_at") or rec.get("timestamp"),
        "status": rec.get("status"),
        "trigger": rec.get("trigger"),
        "actor": rec.get("actor"),
        "actor_verified": bool(rec.get("actor_verified")),
        "graph_name": rec.get("graph_name"),
        "project": rec.get("project"),
        "record_hash": rec.get("record_hash"),
        "archived": (run_dir / ARCHIVE_MARKER).exists(),
        "models": models,
        "inputs": inputs,
        "outputs": outputs,
    }


def _record_index(runs_root: Path) -> list[dict[str, Any]]:
    """Slim rows of every sealed run record (cached; see module docstring)."""
    root_s = str(runs_root)
    try:
        key = runs_root.stat().st_mtime_ns
    except OSError:
        return []
    with _lock:
        hit = _SCAN.get(root_s)
        if hit is not None and hit["key"] == key and not any(
            (runs_root / rid / "prove.json").exists() for rid in hit["unsealed"]
        ):
            return list(hit["rows"])
    rows: list[dict[str, Any]] = []
    unsealed: set[str] = set()
    try:
        children = [c for c in runs_root.iterdir() if c.is_dir()]
    except OSError:
        children = []
    for child in children:
        prove = child / "prove.json"
        try:
            mtime = prove.stat().st_mtime_ns
        except OSError:
            unsealed.add(child.name)
            continue
        with _lock:
            cached = _RECORDS.get(str(child))
        if cached is not None and cached[0] == mtime:
            rows.append(cached[1])
            continue
        rec = _read_json(prove)
        if not isinstance(rec, dict):
            continue
        slim = _slim(child, rec)
        with _lock:
            _RECORDS[str(child)] = (mtime, slim)
        rows.append(slim)
    with _lock:
        _SCAN[root_s] = {"key": key, "rows": rows, "unsealed": unsealed}
    return list(rows)


def _node_from_graph(graph: Any, node_id: str | None) -> dict[str, Any] | None:
    if not node_id or not isinstance(graph, dict):
        return None
    for n in graph.get("nodes") or []:
        if isinstance(n, dict) and str(n.get("id")) == str(node_id):
            return n
    return None


def _made_from(run_dir: Path, node_id: str | None) -> dict[str, Any]:
    from app.core.runs.audit_record import load_record

    rec = load_record(run_dir) or {}
    meta = _read_json(run_dir / "meta.json")
    meta = meta if isinstance(meta, dict) else {}
    graph = _read_json(run_dir / "graph.json")
    node = _node_from_graph(graph, node_id)
    ntype = str((node or {}).get("node_type") or (node or {}).get("type") or "") or None
    impls = rec.get("node_implementation_versions") or meta.get("node_implementations") or {}
    impl = impls.get(ntype) if isinstance(impls, dict) and ntype else None
    inputs = rec.get("external_inputs") if isinstance(rec.get("external_inputs"), list) else meta.get("external_inputs")
    datasets = []
    for row in inputs or []:
        if not isinstance(row, dict):
            continue
        ds = row.get("dataset") if isinstance(row.get("dataset"), dict) else None
        datasets.append({
            "node_id": row.get("node_id"),
            "key": row.get("key"),
            "label": row.get("label"),
            "path": row.get("path"),
            "content_hash": row.get("content_hash"),
            "file_count": row.get("file_count"),
            "dataset_version": ds,
        })
    seed = rec.get("seed")
    if seed is None and isinstance(graph, dict):
        seed = (graph.get("metadata") or {}).get("seed") if isinstance(graph.get("metadata"), dict) else None
    return {
        "run_id": run_dir.name,
        "sealed": bool(rec),
        "record_hash": rec.get("record_hash"),
        "graph_hash": rec.get("graph_hash") or meta.get("graph_hash"),
        "graph_name": rec.get("graph_name") or meta.get("graph_name"),
        "seed": seed,
        "datasets": datasets,
        "node": {
            "node_id": node_id,
            "node_type": ntype,
            "label": (rec.get("node_labels") or {}).get(node_id) if isinstance(rec.get("node_labels"), dict) and node_id else None,
            "plugin": (impl or {}).get("plugin"),
            "plugin_version": (impl or {}).get("version"),
            "code_hash": (impl or {}).get("plugin_code_hash"),
        } if node_id else None,
        "step_config": dict((node or {}).get("config") or {}) if node else None,
        "environment": {
            k: (rec.get("environment") or {}).get(k)
            for k in ("python", "image", "graphyn_version", "git_commit")
        } if isinstance(rec.get("environment"), dict) else None,
    }


def _stage_row(stage: str, srec: dict[str, Any], runs_root: Path) -> dict[str, Any]:
    from app.core.runs.audit_hashing import hash_path

    art = srec.get("artifact_path") or srec.get("path")
    model_hash = None
    file_count = None
    a = _abs(art)
    if a:
        try:
            res = hash_path(a)
            model_hash, file_count = res.get("content_hash"), res.get("file_count")
        except Exception:
            pass
    run_id = str(srec.get("run_id") or "")
    run_dir = runs_root / run_id if run_id else None
    return {
        "stage": stage,
        "run_id": run_id or None,
        "node_id": srec.get("node_id"),
        "path_id": srec.get("path_id"),
        "artifact_path": art,
        "format": srec.get("format"),
        "model_hash": model_hash,
        "model_file_count": file_count,
        "updated_at": srec.get("updated_at") or srec.get("requested_at"),
        "made_from": _made_from(run_dir, srec.get("node_id")) if run_dir and run_dir.is_dir() else None,
    }


def _package_for(row: dict[str, Any]) -> dict[str, Any] | None:
    """Package-like output of a consuming run: ``{path, node_id, sha256, content_hash}``.

    ``sha256`` is the file digest when the output is a single file, or the
    first ``*.zip`` directly inside an output folder; otherwise None.
    """
    outs = row.get("outputs") or []
    pick = next((o for o in outs if str(o.get("path") or "").lower().endswith((".zip", ".tar", ".tar.gz", ".tgz"))), None)
    if pick is None and outs:
        pick = outs[-1]
    if not pick:
        return None
    path = pick.get("path")
    sha = None
    if pick.get("kind") == "file" and pick.get("hash_mode") in (None, "content"):
        sha = _sha256(pick.get("content_hash"))
    else:
        a = _abs(path)
        try:
            zips = sorted(Path(a).glob("*.zip")) if a and Path(a).is_dir() else []
        except OSError:
            zips = []
        if zips:
            try:
                from app.core.runs.audit_hashing import hash_file
                from app.core.runs.audit_record import to_rel

                sha = hash_file(zips[0])
                path = to_rel(zips[0])
            except Exception:
                sha = None
    return {
        "path": path,
        "node_id": pick.get("node_id"),
        "sha256": sha,
        "content_hash": pick.get("content_hash"),
    }


def _packages(name: str, project_dirs: list[Path] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not project_dirs:
        return out
    try:
        from app.core.mlops.ship_packages import packages_root
    except Exception:
        return out
    for pdir in project_dirs:
        root = packages_root(pdir)
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            man = _read_json(child / "manifest.json")
            if not isinstance(man, dict):
                continue
            ref = man.get("model_ref") if isinstance(man.get("model_ref"), dict) else {}
            lin = man.get("lineage") if isinstance(man.get("lineage"), dict) else {}
            if ref.get("name") != name and lin.get("model_name") != name:
                continue
            out.append({
                "package_id": man.get("package_id") or child.name,
                "project": Path(pdir).name,
                "status": man.get("status"),
                "env": man.get("env"),
                "stage": ref.get("stage_or_version"),
                "run_id": ref.get("run_id") or lin.get("run_id"),
                "created_at": man.get("created_at"),
                "sha256": (man.get("checksums") or {}).get("sha256") if isinstance(man.get("checksums"), dict) else None,
            })
    out.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return out


def model_lineage(
    name: str,
    *,
    base_dir: str | Path | None = None,
    project_dirs: list[Path] | None = None,
) -> dict[str, Any]:
    """Both-direction lineage of a registered model (raises FileNotFoundError /
    ValueError like :func:`model_registry.get_model`)."""
    from app.core.mlops.model_registry import _runs_root, get_model

    rec = get_model(name, base_dir=base_dir)
    runs_root = _runs_root(base_dir)
    stages_in = rec.get("stages") if isinstance(rec.get("stages"), dict) else {}
    stages = {s: _stage_row(s, srec, runs_root) for s, srec in stages_in.items() if isinstance(srec, dict)}
    pending = rec.get("pending_prod")
    pending_row = _stage_row("pending_prod", pending, runs_root) if isinstance(pending, dict) else None

    targets: list[tuple[str, str]] = []
    for s, row in stages.items():
        a = _abs(row.get("artifact_path"))
        if a:
            targets.append((s, a))
    source_runs = {str(r.get("run_id")) for r in stages.values() if r.get("run_id")}

    used_in: list[dict[str, Any]] = []
    for row in _record_index(runs_root):
        stage = None
        match = None
        for m in row.get("models") or []:
            if m.get("name") == name:
                stage, match = m.get("stage"), m.get("match") or "declared"
                break
        if match is None and row.get("run_id") not in source_runs:
            for inp in row.get("inputs") or []:
                ia = inp.get("abs")
                if not ia:
                    continue
                hit = next((s for s, a in targets if _same_or_nested(ia, a)), None)
                if hit:
                    stage, match = hit, "input_path"
                    break
        if match is None:
            continue
        used_in.append({
            "run_id": row["run_id"],
            "short": str(row["run_id"])[:8],
            "created_at": row.get("created_at"),
            "status": row.get("status"),
            "trigger": row.get("trigger"),
            "actor": row.get("actor"),
            "actor_verified": row.get("actor_verified"),
            "graph_name": row.get("graph_name"),
            "project": row.get("project"),
            "archived": row.get("archived"),
            "stage": stage,
            "match": match,
            "package": _package_for(row),
        })
    used_in.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return {
        "name": name,
        "description": rec.get("description"),
        "stages": stages,
        "pending_prod": pending_row,
        "used_in": used_in,
        "packages": _packages(name, project_dirs),
    }


__all__ = ["clear_lineage_cache", "model_lineage"]
