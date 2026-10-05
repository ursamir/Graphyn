# app/core/runs/run_replay.py
"""
Bounded Context:  BC6 — Observability & Storage (reproduce a run)
Responsibility:   Start a new run from a past run's stored LOGICAL graph
                  (same config, same seed), linked by ``replay_of``; optionally
                  refuse when the recorded external inputs changed since.
Owns:             load_replay_graph(), start_replay(), InputsChanged,
                  ReplayGraphMissing, the replay thread pool.
Public Surface:   load_replay_graph(run_dir) -> GraphIR,
                  start_replay(run_dir, *, actor, check_inputs, force,
                  submit=None) -> dict
Must NOT:         Import app.api / app.domain / orchestrator directly (execution
                  goes through get_backend().execute()).
Dependencies:     app.core.runs.audit_record, app.core.runs.run_journal,
                  app.core.ir.loader, app.core.execution.runtime_backend (lazy),
                  app.core.trust.audit (lazy), concurrent.futures.
Reason To Change: Replay semantics (input pinning, graph source) change.

The materialized ``graph.json`` embeds ``runs/<old_id>/`` output paths;
replaying it verbatim would write into the old run's folders. The logical
graph (``graph.logical.json``, or graph.json with run scoping undone for
legacy runs) is re-scoped to the new run by the orchestrator.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="graphyn-replay")


class ReplayGraphMissing(FileNotFoundError):
    """The run has no stored graph."""


class ReplayInputsUnavailable(RuntimeError):
    """The run was started with inputs (webhook body / run inputs) that were not retained."""


class InputsChanged(RuntimeError):
    """Recorded external inputs differ from the current content."""

    def __init__(self, changes: list[dict[str, Any]]) -> None:
        self.changes = changes
        super().__init__(
            f"{len(changes)} external input(s) changed since the run "
            "(pass force=true to replay anyway)"
        )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_replay_graph(run_dir: str | Path):
    """GraphIR of the run's logical graph (raises ReplayGraphMissing)."""
    from app.core.ir.loader import load_ir
    from app.core.runs.audit_record import logical_graph_for_run

    run_dir = Path(run_dir)
    if not (run_dir / "graph.json").is_file() and not (run_dir / "graph.logical.json").is_file():
        raise ReplayGraphMissing(f"graph.json not found for run '{run_dir.name}'")
    data = logical_graph_for_run(run_dir)
    if not isinstance(data, dict):
        raise ReplayGraphMissing(f"graph.json unreadable for run '{run_dir.name}'")
    return load_ir(data)


def input_changes(run_dir: str | Path) -> list[dict[str, Any]]:
    """Non-passing external-input checks (changed / missing) for a run."""
    from app.core.runs.audit_record import check_external_inputs

    run_dir = Path(run_dir)
    record = _read_json(run_dir / "prove.json") or {}
    meta = _read_json(run_dir / "meta.json") or {}
    recorded = record.get("external_inputs") if isinstance(record, dict) else None
    if not isinstance(recorded, list):
        recorded = meta.get("external_inputs") if isinstance(meta, dict) else None
    rows = check_external_inputs(recorded if isinstance(recorded, list) else [])
    return [
        {"path": r.get("target"), "node_id": r.get("node_id"), "status": r.get("status"),
         "expected": r.get("expected"), "actual": r.get("actual")}
        for r in rows if r.get("status") != "pass"
    ]


def start_replay(
    run_dir: str | Path,
    *,
    actor: str = "api",
    check_inputs: bool = False,
    force: bool = False,
    submit: Callable[[Callable[[], Any]], Any] | None = None,
    run_manager: Any = None,
) -> dict[str, Any]:
    """Create the replay run (status pending) and submit its execution."""
    run_dir = Path(run_dir)
    old_id = run_dir.name
    if check_inputs and not force:
        changes = input_changes(run_dir)
        if changes:
            raise InputsChanged(changes)
    graph = load_replay_graph(run_dir)
    old_meta = _read_json(run_dir / "meta.json") or {}
    # Runs started with inputs (webhook body, POST inputs) replay with exactly
    # those inputs — verified against the recorded sha256 — or not at all.
    replay_inputs = None
    if old_meta.get("inputs_sha256"):
        from app.core.execution.run_inputs import load_retained_inputs

        try:
            replay_inputs = load_retained_inputs(run_dir, str(old_meta.get("inputs_sha256")))
        except ValueError as exc:
            raise ReplayInputsUnavailable(f"Run inputs failed verification: {exc}") from exc
        if replay_inputs is None:
            raise ReplayInputsUnavailable(
                "This run was started with inputs (e.g. a webhook payload) that were not retained "
                "(GRAPHYN_RETAIN_RUN_INPUTS=0 or a run from before inputs were kept), so it cannot be "
                "replayed exactly."
            )

    if run_manager is None:
        from app.core.runs.run_journal import RunManager

        run_manager = RunManager()
    new_id = run_manager.run_id
    writer = getattr(run_manager, "_write_meta_field", None)
    if callable(writer):
        try:
            from app.core.trust.identity import bind_actor

            actor, verified, claimed, _origin = bind_actor(actor)
        except Exception:
            verified, claimed = False, None
        fields: dict[str, Any] = {"replay_of": old_id, "actor": actor, "actor_verified": bool(verified),
                                  "trigger": "replay"}
        if claimed:
            fields["claimed_actor"] = claimed
        for key in ("project", "version_tag"):
            if old_meta.get(key):
                fields[key] = old_meta[key]
        ref = old_meta.get("pipeline_ref")
        if isinstance(ref, dict) and ref.get("name"):
            fields["pipeline_name"] = ref.get("name")
            if ref.get("env"):
                fields["pipeline_env"] = ref.get("env")
            if ref.get("version"):
                fields["pipeline_version_id"] = ref.get("version")
        if replay_inputs is not None:
            for key in ("inputs_sha256", "input_keys", "inputs_bytes"):
                if old_meta.get(key) is not None:
                    fields[key] = old_meta[key]
        for key, value in fields.items():
            try:
                writer(key, value)
            except Exception:
                pass
        if replay_inputs is not None:
            from app.core.execution.run_inputs import persist_run_inputs

            persist_run_inputs(run_manager, replay_inputs)

    try:
        from app.core.trust.audit import record_audit

        record_audit(actor=actor, action="run.replay", resource_type="run", resource_id=new_id,
                     meta={"replay_of": old_id, "graph_hash": old_meta.get("graph_hash"),
                           "project": old_meta.get("project"),
                           "check_inputs": bool(check_inputs), "force": bool(force)})
        record_audit(actor=actor, action="run.start", resource_type="run", resource_id=new_id,
                     meta={"graph_name": old_meta.get("graph_name"), "mode": "replay", "replay_of": old_id,
                           "trigger": "replay", "project": old_meta.get("project")})
    except Exception:
        pass

    def _run() -> None:
        from app.core.execution.runtime_backend import get_backend

        try:
            if replay_inputs is not None:
                get_backend().execute(graph, run_manager=run_manager, input_overrides=replay_inputs)
            else:
                get_backend().execute(graph, run_manager=run_manager)
        except Exception as exc:  # recorded on the run
            log.error("replay of %s (new run %s) failed: %s", old_id, new_id, exc)
            try:
                run_manager.mark_failed(str(exc) or type(exc).__name__)
            except Exception:
                pass

    try:
        (submit or _EXECUTOR.submit)(_run)
    except Exception as exc:
        try:
            run_manager.mark_failed(str(exc))
        except Exception:
            pass
        raise
    return {
        "run_id": new_id,
        "replay_of": old_id,
        "status": "pending",
        "graph_hash": old_meta.get("graph_hash"),
    }
