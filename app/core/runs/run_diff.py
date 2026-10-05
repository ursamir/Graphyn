# app/core/runs/run_diff.py
"""
Bounded Context:  BC6 — Observability (Compare: what changed between runs)
Responsibility:   Side-by-side diff of 2–5 runs from their stored graph
                  snapshots and sealed records: node settings, external data
                  inputs, node code (plugin version + code hash), environment,
                  and per-path metrics (same best-path / path-label logic as
                  run summaries).
Owns:             diff_runs(), MIN_RUNS, MAX_RUNS.
Public Surface:   diff_runs(run_dirs, *, include_all=False) -> dict (shape in
                  docs/API_REFERENCE.md "GET /runs/compare/diff").
Must NOT:         Import app.api / app.domain / execution; mutate run files.
Dependencies:     stdlib; app.core.runs.audit_record (load_record,
                  logical_graph_for_run); app.core.runs.run_summary
                  (run_insights, headline_metrics, node_labels);
                  app.core.nodes.registry (config defaults, lazy).
Reason To Change: Compare page needs or record schema change.

Settings come from the LOGICAL graph (``graph.logical.json``, else de-scoped
``graph.json``) so per-run output scoping (``…/runs/<id>/…``) is not reported
as a change. Each section row carries ``values`` aligned with ``runs`` order
and ``differs``; only differing rows are returned unless ``include_all``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MIN_RUNS = 2
MAX_RUNS = 5

_ENV_KEYS = ("python", "implementation", "os", "machine", "image", "graphyn_version", "git_commit", "backend")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _canon(v: Any) -> str:
    return json.dumps(v, sort_keys=True, default=str)


def _differs(values: list[Any]) -> bool:
    return len({_canon(v) for v in values}) > 1


def _nodes(graph: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(graph, dict):
        return []
    return [n for n in graph.get("nodes") or [] if isinstance(n, dict) and n.get("id")]


def _ntype(node: dict[str, Any]) -> str:
    return str(node.get("node_type") or node.get("type") or "")


def _config_default(node_type: str, key: str) -> tuple[bool, Any]:
    try:
        from app.core.nodes import registry

        cls = registry.get_class(node_type)
        field = getattr(getattr(cls, "Config", None), "model_fields", {}).get(key)
    except Exception:
        return False, None
    if field is None:
        return False, None
    try:
        if field.is_required():
            return False, None
        return True, field.get_default(call_default_factory=True)
    except Exception:
        return False, None


class _Run:
    def __init__(self, run_dir: Path) -> None:
        from app.core.runs.audit_record import load_record, logical_graph_for_run

        self.dir = run_dir
        self.run_id = run_dir.name
        meta = _read_json(run_dir / "meta.json")
        self.meta: dict[str, Any] = meta if isinstance(meta, dict) else {}
        self.record: dict[str, Any] = load_record(run_dir) or {}
        g = logical_graph_for_run(run_dir)
        if not isinstance(g, dict):
            g = _read_json(run_dir / "graph.json")
        self.graph: dict[str, Any] = g if isinstance(g, dict) else {}
        try:
            from app.core.runs.run_summary import run_insights

            self.insights = run_insights(self.run_id, run_dir, self.meta)
        except Exception:
            self.insights = {}
        labels = self.record.get("node_labels") or self.meta.get("node_labels")
        if not isinstance(labels, dict) or not labels:
            try:
                from app.core.runs.run_summary import node_labels

                labels = node_labels(self.graph)
            except Exception:
                labels = {}
        self.node_labels: dict[str, str] = {str(k): str(v) for k, v in (labels or {}).items()}
        summary = self.insights.get("summary") if isinstance(self.insights.get("summary"), dict) else {}
        self.summary = summary
        self.path_of: dict[str, tuple[str, str]] = {}
        for p in summary.get("paths") or []:
            if not isinstance(p, dict):
                continue
            for nid in p.get("node_ids") or []:
                self.path_of.setdefault(str(nid), (str(p.get("path_id")), str(p.get("label") or p.get("path_id"))))
        self.nodes = {str(n["id"]): n for n in _nodes(self.graph)}

    @property
    def seed(self) -> Any:
        if self.record.get("seed") is not None:
            return self.record.get("seed")
        md = self.graph.get("metadata") if isinstance(self.graph.get("metadata"), dict) else {}
        return md.get("seed", self.meta.get("seed"))

    @property
    def graph_hash(self) -> str | None:
        return self.record.get("graph_hash") or self.meta.get("graph_hash") or None

    def row(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "short": self.run_id[:8],
            "name": self.insights.get("display_name") or self.meta.get("graph_name") or self.run_id,
            "started_at": self.meta.get("started_at") or self.meta.get("created_at") or self.record.get("created_at"),
            "status": self.meta.get("status") or self.record.get("status"),
            "graph_hash": self.graph_hash,
            "seed": self.seed,
            "sealed": bool(self.record),
        }

    def inputs(self) -> list[dict[str, Any]]:
        rows = self.record.get("external_inputs")
        if not isinstance(rows, list):
            rows = self.meta.get("external_inputs")
        return [r for r in rows or [] if isinstance(r, dict)]

    def impls(self) -> dict[str, Any]:
        impls = self.record.get("node_implementation_versions") or self.meta.get("node_implementations")
        return impls if isinstance(impls, dict) else {}

    def environment(self) -> dict[str, Any]:
        env = self.record.get("environment") or self.meta.get("environment_info")
        return env if isinstance(env, dict) else {}


def _ordered_node_ids(runs: list[_Run]) -> list[str]:
    order: list[str] = []
    for r in runs:
        try:
            from app.core.runs.run_summary import _topo_order

            ids = _topo_order(r.graph)
        except Exception:
            ids = list(r.nodes)
        for nid in ids or list(r.nodes):
            if nid not in order:
                order.append(nid)
    return order


def _settings(runs: list[_Run], include_all: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for nid in _ordered_node_ids(runs):
        present = [nid in r.nodes for r in runs]
        holder = next(r for r in runs if nid in r.nodes)
        ntype = _ntype(holder.nodes[nid])
        cfgs = [(r.nodes[nid].get("config") or {}) if nid in r.nodes else {} for r in runs]
        keys: list[str] = []
        for c in cfgs:
            for k in c:
                if k not in keys:
                    keys.append(k)
        label = holder.node_labels.get(nid) or str(holder.nodes[nid].get("label") or nid)
        path = holder.path_of.get(nid)
        for key in keys:
            has_default, default = _config_default(ntype, key)
            values = []
            for c, p in zip(cfgs, present):
                if not p:
                    values.append(None)
                elif key in c:
                    values.append(c[key])
                else:
                    values.append(default if has_default else None)
            diff = _differs(values) or not all(present)
            if not diff and not include_all:
                continue
            row = {
                "node_id": nid,
                "node_type": ntype,
                "node_label": label,
                "path_id": path[0] if path else None,
                "path_label": path[1] if path else None,
                "key": key,
                "values": values,
                "present": present,
                "differs": diff,
            }
            if has_default:
                row["default"] = default
            rows.append(row)
    return rows


def _input_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("node_id") or ""), str(row.get("key") or "")


def _data(runs: list[_Run], include_all: bool) -> tuple[list[dict[str, Any]], bool]:
    per = [{_input_key(i): i for i in r.inputs()} for r in runs]
    keys: list[tuple[str, str]] = []
    for m in per:
        for k in m:
            if k not in keys:
                keys.append(k)
    rows: list[dict[str, Any]] = []
    same = True
    for k in keys:
        cells = [m.get(k) for m in per]
        hashes = [c.get("content_hash") if c else None for c in cells]
        diff = _differs(hashes)
        same = same and not diff
        if not diff and not include_all:
            continue
        first = next(c for c in cells if c)
        rows.append({
            "node_id": k[0],
            "key": k[1],
            "label": first.get("label") or f"{first.get('node_label') or k[0]} · {k[1]}",
            "paths": [c.get("path") if c else None for c in cells],
            "content_hashes": hashes,
            "file_counts": [c.get("file_count") if c else None for c in cells],
            "dataset_versions": [((c.get("dataset") or {}).get("version") if c and isinstance(c.get("dataset"), dict) else None) for c in cells],
            "differs": diff,
        })
    return rows, same


def _code(runs: list[_Run], include_all: bool) -> tuple[list[dict[str, Any]], bool]:
    impls = [r.impls() for r in runs]
    types: list[str] = []
    for r in runs:
        for n in r.nodes.values():
            t = _ntype(n)
            if t and t not in types:
                types.append(t)
    rows: list[dict[str, Any]] = []
    same = True
    for t in types:
        cells = [i.get(t) if isinstance(i.get(t), dict) else None for i in impls]
        versions = [c.get("version") if c else None for c in cells]
        hashes = [c.get("plugin_code_hash") if c else None for c in cells]
        diff = _differs(versions) or _differs(hashes)
        same = same and not diff
        if not diff and not include_all:
            continue
        rows.append({
            "node_type": t,
            "plugins": [c.get("plugin") if c else None for c in cells],
            "versions": versions,
            "code_hashes": hashes,
            "version_differs": _differs(versions),
            "code_differs": _differs(hashes),
            "differs": diff,
        })
    return rows, same


def _environment(runs: list[_Run], include_all: bool) -> tuple[list[dict[str, Any]], bool]:
    envs = [r.environment() for r in runs]
    rows: list[dict[str, Any]] = []
    same = True
    keys = list(_ENV_KEYS)
    libs: list[str] = []
    for e in envs:
        for name in (e.get("libraries") or {}) if isinstance(e.get("libraries"), dict) else {}:
            if name not in libs:
                libs.append(name)
    for key in keys + [f"library:{n}" for n in libs]:
        if key.startswith("library:"):
            name = key.split(":", 1)[1]
            values = [((e.get("libraries") or {}).get(name) if isinstance(e.get("libraries"), dict) else None) for e in envs]
        else:
            values = [e.get(key) for e in envs]
        if all(v is None for v in values):
            continue
        diff = _differs(values)
        if key not in ("os",):  # host OS string churns with kernels; still shown, not counted
            same = same and not diff
        if not diff and not include_all:
            continue
        rows.append({"key": key, "values": values, "differs": diff})
    return rows, same


def _metrics(runs: list[_Run]) -> dict[str, Any]:
    from app.core.runs.run_summary import headline_metrics

    by_path: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    heads = []
    for idx, r in enumerate(runs):
        head = headline_metrics(r.summary) if r.summary else None
        heads.append(head)
        for p in (head or {}).get("metrics_by_path") or []:
            pid = str(p.get("path_id"))
            if pid not in by_path:
                by_path[pid] = {"labels": [None] * len(runs), "metrics": {}, "best": [False] * len(runs)}
                order.append(pid)
            slot = by_path[pid]
            slot["labels"][idx] = p.get("label")
            slot["best"][idx] = bool(p.get("best"))
            for name, val in (p.get("metrics") or {}).items():
                slot["metrics"].setdefault(name, [None] * len(runs))[idx] = val
    rows: list[dict[str, Any]] = []
    for pid in order:
        slot = by_path[pid]
        label = next((x for x in slot["labels"] if x), pid)
        for name, values in slot["metrics"].items():
            rows.append({
                "path_id": pid,
                "path_label": label,
                "path_labels": slot["labels"],
                "best": slot["best"],
                "metric": name,
                "values": values,
                "differs": _differs(values),
            })
    headline: list[dict[str, Any]] = []
    names: list[str] = []
    for h in heads:
        for n in (h or {}).get("metrics") or {}:
            if n not in names:
                names.append(n)
    for n in names:
        headline.append({
            "metric": n,
            "values": [((h or {}).get("metrics") or {}).get(n) for h in heads],
            "path_labels": [(h or {}).get("path_label") for h in heads],
        })
    primary = next(((h or {}).get("primary_metric") for h in heads if (h or {}).get("primary_metric")), None)
    return {"paths": rows, "headline": headline, "primary_metric": primary}


def diff_runs(run_dirs: list[str | Path], *, include_all: bool = False) -> dict[str, Any]:
    """Diff 2–5 runs (see module docstring). Raises ValueError on a bad count."""
    dirs = [Path(d) for d in run_dirs]
    if not (MIN_RUNS <= len(dirs) <= MAX_RUNS):
        raise ValueError(f"compare needs {MIN_RUNS}-{MAX_RUNS} runs, got {len(dirs)}")
    runs = [_Run(d) for d in dirs]
    settings = _settings(runs, include_all)
    data, data_same = _data(runs, include_all)
    code, code_same = _code(runs, include_all)
    env, env_same = _environment(runs, include_all)
    hashes = [r.graph_hash for r in runs]
    return {
        "runs": [r.row() for r in runs],
        "summary": {
            "settings_changed": sum(1 for s in settings if s["differs"]),
            "data_same": data_same,
            "code_same": code_same,
            "environment_same": env_same,
            "graph_same": all(hashes) and not _differs(hashes),
            "seed_same": not _differs([r.seed for r in runs]),
        },
        "settings": settings,
        "data": data,
        "code": code,
        "environment": env,
        "metrics": _metrics(runs),
        "include_all": bool(include_all),
    }


__all__ = ["MAX_RUNS", "MIN_RUNS", "diff_runs"]
