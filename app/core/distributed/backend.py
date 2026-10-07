# app/core/distributed/backend.py
"""
Bounded Context:  BC5 — Execution Runtime
Responsibility:   DistributedRuntimeBackend — wave scheduler that runs local
                  nodes via NodeExecutor and remote nodes via the job queue
                  with artifact URI refs (no full-graph local rematerialize).
                  Like the local orchestrator it scopes outputs to the run and
                  keys graph_hash / node seeds / cache keys off the logical
                  (pre-scoping) graph.
Owns:             DistributedBackend, IR wave helpers, loopback worker helpers.
Public Surface:   DistributedBackend, run_loopback_worker_once,
                  start_loopback_worker_thread, compute_ir_waves.
Must NOT:         Import from app.domain or app.api at module level.
Dependencies:     runtime_backend, distributed.{registry,queue,placement,
                  models,transfer}, ir.models, planner helpers (derive_node_seed),
                  orchestrator (logical_graph_hash, scope_graph_to_run, capture_run_start), node_executor,
                  registry_runtime, stdlib.
Reason To Change: Parallel within-wave execution, cache/pause policy,
                  cancel/lease reclaim, placement pinning, or run-end blob
                  cleanup / output integrity verification.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from app.core.execution.runtime_backend import LocalPythonBackend, RuntimeBackend

if TYPE_CHECKING:
    from app.core.ir.models import GraphIR
    from app.core.runs.run_journal import RunManager

log = logging.getLogger(__name__)


def compute_ir_waves(graph: "GraphIR") -> list[list[str]]:
    """Compute parallel execution waves from GraphIR edges (no node instantiation).

    Mirrors ``PipelineGraph._compute_waves`` / Kahn topo so distributed
    scheduling can place remote node types that are not registered on the
    control plane.
    """
    from collections import deque

    node_ids = [n.id for n in graph.nodes]
    if not node_ids:
        return []
    id_set = set(node_ids)
    in_degree: dict[str, int] = {nid: 0 for nid in node_ids}
    adjacency: dict[str, list[str]] = defaultdict(list)
    predecessors: dict[str, list[str]] = {nid: [] for nid in node_ids}

    for edge in graph.edges:
        if edge.src_id not in id_set or edge.dst_id not in id_set:
            raise RuntimeError(
                f"Edge {edge.src_id!r}→{edge.dst_id!r} references unknown node"
            )
        adjacency[edge.src_id].append(edge.dst_id)
        predecessors[edge.dst_id].append(edge.src_id)
        in_degree[edge.dst_id] += 1

    queue: deque[str] = deque(nid for nid, deg in in_degree.items() if deg == 0)
    order: list[str] = []
    while queue:
        nid = queue.popleft()
        order.append(nid)
        for successor in adjacency[nid]:
            in_degree[successor] -= 1
            if in_degree[successor] == 0:
                queue.append(successor)

    if len(order) != len(node_ids):
        missing = id_set - set(order)
        raise RuntimeError(
            f"Graph contains a cycle — topological sort failed. "
            f"Nodes not reached: {missing}"
        )

    level: dict[str, int] = {}
    for node_id in order:
        preds = predecessors[node_id]
        level[node_id] = max((level[p] + 1 for p in preds), default=0)

    waves_dict: dict[int, list[str]] = defaultdict(list)
    for nid, lv in level.items():
        waves_dict[lv].append(nid)
    max_level = max(level.values())
    return [waves_dict[i] for i in range(max_level + 1)]


def _assemble_inputs(
    node_id: str,
    *,
    incoming: dict[str, list[tuple[str, str, str, str | None]]],
    node_outputs: dict[str, dict[str, Any]],
    input_overrides: dict | None,
) -> dict[str, Any]:
    """Wire upstream outputs → inputs for *node_id*.

    Edges with a condition are evaluated against the source outputs
    (same helper as the local orchestrator). A false condition leaves the
    destination port unwired. Overrides win.
    """
    from app.core.execution.conditions import ConditionEvaluationError, evaluate_condition

    inputs: dict[str, Any] = {}
    if input_overrides and node_id in input_overrides:
        for port, value in (input_overrides[node_id] or {}).items():
            inputs[port] = value

    for src_id, src_port, dst_port, condition in incoming.get(node_id, []):
        if dst_port in inputs:
            continue
        upstream = node_outputs.get(src_id, {})
        if not isinstance(upstream, dict):
            upstream = {}
        if condition:
            try:
                if not evaluate_condition(str(condition), upstream):
                    continue
            except ConditionEvaluationError as exc:
                raise ValueError(
                    f"Conditional edge {src_id}.{src_port}→{node_id}.{dst_port} "
                    f"failed: {exc}"
                ) from exc
        if src_port in upstream:
            inputs[dst_port] = upstream[src_port]
    return inputs


def _cache_load(
    *,
    use_cache: bool,
    node_type: str,
    config: dict[str, Any],
    inputs: dict[str, Any],
    seed: int,
    run_id: str | None = None,
    ir_node: Any = None,
) -> tuple[str | None, Any]:
    """Return ``(cache_key, outputs)``. Outputs is None on miss or when disabled.

    Non-cacheable nodes get ``(None, None)`` (no load, and no save later since
    the key is None). Hits that reference another run's artifact dir are
    re-homed into ``run_id`` (or discarded) by ``rescope_cached_outputs``.
    """
    if not use_cache:
        return None, None
    from app.core.execution.cache_rescope import node_is_cacheable, rescope_cached_outputs
    from app.core.execution.pipeline_cache import PipelineCache

    if not node_is_cacheable(node_type, ir_node):
        return None, None

    version = None
    try:
        from app.core.host.registry_runtime import get_registry

        version = get_registry().get_metadata(node_type).version
    except Exception:
        version = None
    cache = PipelineCache()
    key = cache.compute_key(
        node_type,
        config,
        inputs,
        node_seed=seed,
        node_version=version,
    )
    return key, rescope_cached_outputs(cache.load(key), run_id)


def _flush_run_logs(run: Any, logger: Any) -> None:
    """Persist PipelineLogger events so GET /runs/{id} shows live Mode B progress."""
    if logger is None or not hasattr(logger, "logs"):
        return
    try:
        run.save_logs(logger.logs)
    except Exception:
        log.debug("DistributedBackend: save_logs failed", exc_info=True)


def _forward_job_events(
    queue: Any,
    job_id: str,
    *,
    logger: Any,
    run: Any,
    node_id: str,
    seen: set[int],
) -> None:
    """Copy worker job events into the run journal / NDJSON stream (best-effort)."""
    if logger is None:
        return
    list_fn = getattr(queue, "list_events", None)
    if not callable(list_fn):
        return
    try:
        events = list_fn(job_id) or []
    except Exception:
        return
    for idx, ev in enumerate(events):
        if idx in seen or not isinstance(ev, dict):
            continue
        seen.add(idx)
        et = str(ev.get("type") or ev.get("event") or "")
        if et in ("outputs",):
            continue
        if et == "node_progress" and hasattr(logger, "node_progress"):
            payload = dict(ev)
            payload.setdefault("node_id", node_id)
            try:
                logger.node_progress(payload)
            except Exception:
                pass
        else:
            msg = ev.get("message") or ev.get("error") or et or "worker event"
            try:
                logger.info(f"[worker/{node_id}] {msg}")
            except Exception:
                pass
    _flush_run_logs(run, logger)


def _wait_remote_result(
    queue: Any,
    run: Any,
    job_id: str,
    *,
    timeout_s: float,
    logger: Any = None,
    node_id: str | None = None,
) -> Any:
    """Wait for a remote job, propagating run pause as a claim hold.

    In-flight ``process()`` on a worker is not frozen (same cooperative limit
    as in-process cancel). New claims for this run are held until resume.
    Cancel still aborts the job.

    When ``logger`` is given, worker job events and a periodic waiting note are
    flushed into the run journal so the Editor Execution log is not blank while
    Mode B remote nodes execute.
    """
    import time as _time

    deadline = _time.monotonic() + float(timeout_s)
    noted = False
    seen_events: set[int] = set()
    # Emit the first "Waiting for worker…" immediately so Editor hydrate / NDJSON
    # is never blank while Mode B remote nodes sit in claim/execute.
    last_note = -1e9
    # Back off the result poll: a tight 0.5s loop + worker GET /jobs spam fought
    # for uvicorn capacity and made the Execution log look stuck.
    import os as _os

    try:
        wait_slice = float(_os.environ.get("GRAPHYN_JOB_WAIT_POLL_S", "4.0") or "4.0")
    except ValueError:
        wait_slice = 4.0
    wait_slice = max(0.25, min(wait_slice, 5.0))
    wait_slice_cap = max(wait_slice, min(5.0, wait_slice * 5.0))
    while True:
        if getattr(run, "is_cancelled", False):
            try:
                queue.cancel(job_id)
            except Exception:
                pass
        if getattr(run, "is_paused", False):
            queue.set_run_paused(run.run_id, True)
            if not noted:
                try:
                    run._write_meta_field(
                        "remote_pause",
                        "claims held while paused; an in-flight node process() "
                        "finishes unless the run is cancelled",
                    )
                except Exception:
                    pass
                noted = True
            run.wait_if_paused()
            if not getattr(run, "is_paused", False):
                queue.set_run_paused(run.run_id, False)
        if logger is not None and node_id:
            _forward_job_events(
                queue, job_id, logger=logger, run=run, node_id=node_id, seen=seen_events
            )
            now = _time.monotonic()
            if now - last_note >= 5.0:
                last_note = now
                try:
                    logger.info(
                        f"Waiting for worker on node {node_id} (job={job_id[:8]}…)"
                    )
                    _flush_run_logs(run, logger)
                except Exception:
                    pass
        remaining = deadline - _time.monotonic()
        if remaining <= 0:
            result = queue.wait_for_result(job_id, timeout_s=0)
            if result is not None:
                _ack(queue, job_id)
            return result
        slice_s = min(wait_slice, remaining)
        try:
            result = queue.wait_for_result(
                job_id, timeout_s=slice_s, poll_interval_s=slice_s
            )
        except TypeError:
            # Test doubles / older queue stubs may not take poll_interval_s.
            result = queue.wait_for_result(job_id, timeout_s=slice_s)
        if result is not None:
            if not getattr(run, "is_paused", False):
                queue.set_run_paused(run.run_id, False)
            if logger is not None and node_id:
                _forward_job_events(
                    queue, job_id, logger=logger, run=run, node_id=node_id, seen=seen_events
                )
            _ack(queue, job_id)
            return result
        wait_slice = min(wait_slice_cap, wait_slice * 1.5)


def _ack(queue: Any, job_id: str) -> None:
    """Mark a result consumed so history trimming may drop it later."""
    ack = getattr(queue, "ack_result", None)
    if ack is None:
        return
    try:
        ack(job_id)
    except Exception as exc:  # noqa: BLE001 — ack is best-effort
        log.debug("DistributedBackend: ack_result failed for %s: %s", job_id, exc)


def _keep_blobs() -> bool:
    return (os.environ.get("GRAPHYN_DISTRIBUTED_KEEP_BLOBS") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _cleanup_run_blobs(
    queue: Any,
    *,
    run_id: str,
    job_ids: list[str],
    input_uploads: dict[str, int | None],
    root: Any = None,
) -> None:
    """Delete this run's transfer blobs once the run is terminal.

    * ``jobs/<job_id>/…`` output blobs are generation-scoped and never shared.
    * Content-addressed input blobs are deleted only when no other
      non-terminal job references them and nobody re-put them since this run
      uploaded them (mtime unchanged). Anything missed is swept by
      ``cleanup_workspace`` TTL.
    """
    if _keep_blobs():
        return
    try:
        from app.core.distributed.transfer import (
            safe_path,
            delete_blobs,
            delete_job_blobs,
            uri_to_key,
        )

        active_uris: set[str] = set()
        refs_fn = getattr(queue, "active_blob_refs", None)
        if refs_fn is not None:
            active_uris, _active_jobs = refs_fn(exclude_run_id=run_id)
        delete_job_blobs(list(job_ids), root=root)
        doomed: list[str] = []
        for uri, mtime_ns in input_uploads.items():
            if uri in active_uris or mtime_ns is None:
                continue
            try:
                path = safe_path(uri_to_key(uri), root)
                if path.stat().st_mtime_ns != mtime_ns:
                    continue
            except (OSError, ValueError):
                continue
            doomed.append(uri)
        delete_blobs(doomed, root=root)
    except Exception as exc:  # noqa: BLE001 — cleanup never fails the run
        log.warning("DistributedBackend: blob cleanup for run %s failed: %s", run_id, exc)


def _blob_grace_s() -> float:
    try:
        return max(
            0.0,
            float(os.environ.get("GRAPHYN_DISTRIBUTED_BLOB_GRACE_S", "30") or "30"),
        )
    except ValueError:
        return 30.0


def _schedule_run_blob_cleanup(
    queue: Any,
    *,
    run_id: str,
    job_ids: list[str],
    input_uploads: dict[str, int | None],
) -> None:
    """Run :func:`_cleanup_run_blobs` after ``GRAPHYN_DISTRIBUTED_BLOB_GRACE_S``.

    The short grace keeps a just-finished run's transfer blobs inspectable
    (debugging, late UI reads). If the process exits first, the
    ``cleanup_workspace`` TTL sweep removes them.
    """
    if _keep_blobs() or (not job_ids and not input_uploads):
        return
    try:
        from app.core.distributed.transfer import blob_root

        root = blob_root()  # pin now: env/project may change before the timer fires
    except Exception:
        root = None
    kwargs = {
        "run_id": run_id,
        "job_ids": list(job_ids),
        "input_uploads": dict(input_uploads),
        "root": root,
    }
    grace = _blob_grace_s()
    if grace <= 0:
        _cleanup_run_blobs(queue, **kwargs)
        return
    timer = threading.Timer(grace, _cleanup_run_blobs, args=(queue,), kwargs=kwargs)
    timer.daemon = True
    timer.name = f"graphyn-blob-cleanup-{run_id}"
    timer.start()


def _blob_mtime_ns(uri: str) -> int | None:
    try:
        from app.core.distributed.transfer import safe_path, uri_to_key

        return safe_path(uri_to_key(uri)).stat().st_mtime_ns
    except (OSError, ValueError):
        return None


def _cache_save(cache_key: str | None, node_type: str, outputs: Any) -> None:
    if not cache_key:
        return
    cacheable = True
    try:
        from app.core.host.registry_runtime import get_registry

        cacheable = bool(get_registry().get_metadata(node_type).cacheable)
    except Exception:
        cacheable = True
    if not cacheable:
        return
    from app.core.execution.pipeline_cache import PipelineCache

    PipelineCache().save(cache_key, outputs)


def _is_routed_error_output(outputs: Any, ir_node: Any) -> bool:
    """True when outputs look like IR on_error=route (must not be cached)."""
    if not isinstance(outputs, dict) or not outputs:
        return False
    from app.core.ir.models import routed_error_port

    port = routed_error_port(ir_node)
    if not port or port not in outputs:
        return False
    payload = outputs.get(port)
    return isinstance(payload, dict) and payload.get("ok") is False


def _run_local_node(
    *,
    node_id: str,
    node_type: str,
    config: dict[str, Any],
    seed: int,
    inputs: dict[str, Any],
    run_id: str,
    cancel_check: Any | None = None,
    ir_node: Any = None,
) -> tuple[dict[str, Any], bool]:
    """Execute one node on the control plane via NodeExecutor.

    Returns ``(outputs, failure_policy_applied)``. IR ``on_error`` / ``retry``
    from ``ir_node`` are stamped onto the instance (same as Mode A planner) so
    local distributed nodes honour route/continue and are not cached on failure.
    """
    from app.core.execution.node_executor import NodeExecutor
    from app.core.execution.planner import _policy_dict
    from app.core.host.registry_runtime import get_registry
    from app.core.paths.write_paths import ensure_node_write_dirs

    registry = get_registry()
    node_class = registry.get_class(node_type)
    if node_class is None:
        raise RuntimeError(
            f"Local node {node_id!r}: type {node_type!r} is not registered"
        )
    node = node_class(config=dict(config or {}), seed=seed)
    if ir_node is not None:
        on_err = _policy_dict(getattr(ir_node, "on_error", None))
        retry = _policy_dict(getattr(ir_node, "retry", None))
        if on_err is not None:
            node._graphyn_on_error = on_err  # type: ignore[attr-defined]
        if retry is not None:
            node._graphyn_retry = retry  # type: ignore[attr-defined]
    ensure_node_write_dirs(node)
    executor = NodeExecutor(node, run_id=run_id)
    if cancel_check is not None:
        executor.set_cancel_check(cancel_check)
    executor.setup()
    try:
        outputs = executor.execute(inputs)
        return outputs, bool(getattr(executor, "failure_policy_applied", False))
    finally:
        try:
            executor.teardown()
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "distributed._run_local_node: teardown failed for %s/%s: %s",
                node_type,
                node_id,
                exc,
            )


class DistributedBackend(RuntimeBackend):
    """Wave-scheduled distributed backend with all-local short-circuit.

    Behaviour:
    * If every node resolves to ``\"local\"`` (or nothing requires remote),
      delegate entirely to :class:`LocalPythonBackend`.
    * Otherwise run a wave scheduler: local nodes via ``NodeExecutor``,
      remote nodes via job queue + artifact URI refs. Never rematerializes
      the whole graph through LocalPythonBackend after remotes succeed.
    """

    def __init__(self) -> None:
        self._local = LocalPythonBackend()
        self.last_node_workers: dict[str, str] = {}

    @property
    def backend_id(self) -> str:
        return "distributed"

    def execute(
        self,
        graph: "GraphIR",
        *,
        logger: Any = None,
        use_cache: bool = True,
        checkpoint: bool = False,
        streaming: bool = False,
        parallel: bool = False,
        max_workers: int | None = None,
        resume_run_id: str | None = None,
        include_nodes: list[str] | None = None,
        exclude_nodes: list[str] | None = None,
        input_overrides: dict | None = None,
        event_driven: bool = False,
        observer: Any = None,
        run_manager: "RunManager | None" = None,
    ) -> dict[str, Any]:
        from app.core.distributed.placement import placement_needs_remote, resolve_worker
        from app.core.distributed.registry import get_worker_registry
        from app.core.ir.secret_policy import assert_no_inline_secrets
        from app.core.host.registry_runtime import get_registry, resolve_capability

        assert_no_inline_secrets(graph)

        registry = get_worker_registry()
        alive = registry.alive_workers()
        import warnings

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                node_registry = get_registry()
        except Exception:
            node_registry = None

        placements: dict[str, str | None] = {}
        needs_remote = False
        # Local copy so each resolved assignment bumps the target's load score
        # (spreads multi-node resolution instead of hot-spotting one worker).
        alive = list(alive)
        for node in graph.nodes:
            cap = getattr(node, "capability_metadata", None)
            if node_registry is not None:
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", RuntimeWarning)
                        cap = resolve_capability(node, node_registry)
                except Exception:
                    pass
            target = resolve_worker(
                placement=getattr(node, "placement", None),
                capability=cap,
                workers=alive,
                node_type=node.node_type,
            )
            placements[node.id] = target
            if target not in (None, "local"):
                needs_remote = True
                alive = [
                    w.model_copy(update={"active_jobs": int(w.active_jobs or 0) + 1})
                    if w.worker_id == target
                    else w
                    for w in alive
                ]
            elif target is None:
                if placement_needs_remote(
                    getattr(node, "placement", None), capability=cap
                ):
                    raise RuntimeError(
                        (
                            f"No eligible worker for node {node.id!r} "
                            f"(type={node.node_type!r}, placement={node.placement!r})"
                        )
                        + (
                            " Hint: placement.mode=worker requires a non-empty "
                            "worker id — set worker to a registered id (Deploy → "
                            "Workers) or switch to mode=auto/pool with tags/pool."
                            if node.placement is not None
                            and node.placement.mode == "worker"
                            and not node.placement.worker
                            else ""
                        )
                    )

        if needs_remote:
            unsupported: list[str] = []
            if checkpoint:
                unsupported.append("checkpoint")
            if resume_run_id:
                unsupported.append("resume_run_id")
            if streaming:
                unsupported.append("streaming")
            if parallel:
                unsupported.append("parallel")
            if event_driven:
                unsupported.append("event_driven")
            if not use_cache:
                unsupported.append("use_cache=False")
            if max_workers is not None:
                unsupported.append("max_workers")
            if unsupported:
                raise NotImplementedError(
                    "DistributedBackend remote execution does not support: "
                    + ", ".join(unsupported)
                )

        if not needs_remote:
            log.debug(
                "DistributedBackend: all nodes local — delegating to LocalPythonBackend"
            )
            return self._local.execute(
                graph,
                logger=logger,
                use_cache=use_cache,
                checkpoint=checkpoint,
                streaming=streaming,
                parallel=parallel,
                max_workers=max_workers,
                resume_run_id=resume_run_id,
                include_nodes=include_nodes,
                exclude_nodes=exclude_nodes,
                input_overrides=input_overrides,
                event_driven=event_driven,
                observer=observer,
                run_manager=run_manager,
            )

        return self._execute_with_jobs(
            graph,
            placements=placements,
            logger=logger,
            input_overrides=input_overrides,
            include_nodes=include_nodes,
            exclude_nodes=exclude_nodes,
            run_manager=run_manager,
            use_cache=use_cache,
            checkpoint=checkpoint,
        )

    def _execute_with_jobs(
        self,
        graph: "GraphIR",
        *,
        placements: dict[str, str | None],
        logger: Any,
        input_overrides: dict | None,
        include_nodes: list[str] | None,
        exclude_nodes: list[str] | None,
        run_manager: "RunManager | None",
        use_cache: bool = True,
        checkpoint: bool = False,
    ) -> dict[str, Any]:
        """Wave scheduler: local NodeExecutor + remote jobs with artifact refs."""
        import time as _time

        from app.core.distributed.models import NodeJob
        from app.core.distributed.queue import get_job_queue
        from app.core.distributed.transfer import get_port_value, put_port_value
        from app.core.ir.loader import dump_ir
        from app.core.runs.run_control import deregister_active_run, register_active_run
        from app.core.runs.run_journal import RunManager

        if include_nodes is not None and exclude_nodes is not None:
            raise ValueError("include_nodes and exclude_nodes are mutually exclusive")

        all_node_ids = {n.id for n in graph.nodes}
        for nid in (include_nodes or []) + (exclude_nodes or []):
            if nid not in all_node_ids:
                raise ValueError(f"Unknown node ID '{nid}' in partial execution request")

        if include_nodes is not None:
            active_nodes: set[str] = set(include_nodes)
        elif exclude_nodes is not None:
            active_nodes = all_node_ids - set(exclude_nodes)
        else:
            active_nodes = all_node_ids

        if run_manager is None:
            run_manager = RunManager()
        run = run_manager

        # Editor / Observe read logs.json; Mode B must always journal even when
        # the caller (e.g. /run-async) did not pass a PipelineLogger for NDJSON.
        if logger is None:
            from app.core.logger import PipelineLogger

            logger = PipelineLogger()

        # Logical vs materialized graph (same contract as the local orchestrator):
        # graph_hash, per-node seeds and cache keys come from the logical
        # (pre-run-scoping) graph; execution / jobs use the run-scoped configs.
        from app.core.execution.orchestrator import (
            capture_run_start,
            logical_graph_hash,
            scope_graph_to_run,
        )
        from app.core.execution.planner import plain_jsonable, derive_node_seed

        logical_hash = logical_graph_hash(graph)
        logical_dump = dump_ir(graph)
        logical_configs = {n.id: plain_jsonable(n.config or {}) for n in graph.nodes}
        graph_seed = int(getattr(getattr(graph, "metadata", None), "seed", 0) or 0)
        node_seeds = {
            n.id: derive_node_seed(graph_seed, n.node_type, i, logical_configs[n.id])
            for i, n in enumerate(graph.nodes)
        }
        graph = scope_graph_to_run(graph, run)
        try:
            run.save_graph_ir(dump_ir(graph), logical_hash=logical_hash)
        except TypeError:
            # Custom run managers without the logical_hash keyword.
            run.save_graph_ir(dump_ir(graph))
        # Audit record facts + node labels (same as Mode A).
        capture_run_start(
            run, logger, logical_dump, graph, getattr(run, "_graph_hash", "") or logical_hash
        )
        register_active_run(run)

        queue = get_job_queue()
        run_id = run.run_id
        nodes_by_id = {n.id: n for n in graph.nodes}
        node_stats: list[dict] = []
        start_time = _time.time()
        run._write_meta_field("num_nodes", len(active_nodes))
        terminal_status: str | None = None

        incoming: dict[str, list[tuple[str, str, str, str | None]]] = defaultdict(list)
        for edge in graph.edges:
            incoming[edge.dst_id].append(
                (
                    edge.src_id,
                    edge.src_port,
                    edge.dst_port,
                    getattr(edge, "condition", None),
                )
            )

        waves = compute_ir_waves(graph)
        node_outputs: dict[str, dict[str, Any]] = {}
        node_workers: dict[str, str] = {}
        # Per-job waits use GRAPHYN_DISTRIBUTED_JOB_TIMEOUT / job.timeout_s
        # (no shared graph-wide deadline).

        execution_order = [nid for wave in waves for nid in wave]
        node_index = {nid: i for i, nid in enumerate(execution_order)}
        total_active = len([nid for nid in execution_order if nid in active_nodes])

        # Mode A parity: pending → running + lifecycle events for the Editor log.
        try:
            run.mark_running()
        except Exception:
            log.debug("mark_running failed for %s", run.run_id, exc_info=True)
        if logger is not None:
            try:
                logger.pipeline_start(
                    total_nodes=total_active,
                    partial=active_nodes != all_node_ids,
                    included_nodes=sorted(active_nodes) if active_nodes != all_node_ids else None,
                    run_id=run_id,
                )
            except Exception:
                log.debug("pipeline_start emit failed", exc_info=True)
            _flush_run_logs(run, logger)

        enqueued_job_ids: list[str] = []
        run_job_ids: list[str] = []
        input_uploads: dict[str, int | None] = {}

        def _cancel_enqueued_jobs() -> None:
            for jid in list(enqueued_job_ids):
                try:
                    queue.cancel(jid)
                except Exception as exc:
                    log.warning(
                        "DistributedBackend: failed to cancel job %s: %s", jid, exc
                    )

        try:
            for wave_idx, wave in enumerate(waves):
                run.wait_if_paused()
                if run.is_cancelled:
                    terminal_status = "cancelled"
                    run.mark_cancelled()
                    if logger is not None:
                        try:
                            done = len(node_stats)
                            logger.pipeline_cancelled(
                                run.run_id, done, max(total_active - done, 0)
                            )
                        except Exception:
                            pass
                        _flush_run_logs(run, logger)
                    break
                log.info("DistributedBackend wave %s: %s", wave_idx, wave)
                for node_id in wave:
                    if node_id not in active_nodes:
                        passthrough: dict[str, Any] = {}
                        for src_id, src_port, dst_port, _cond in incoming.get(node_id, []):
                            upstream = node_outputs.get(src_id, {})
                            passthrough[dst_port] = upstream.get(src_port)
                        node_outputs[node_id] = passthrough
                        continue

                    ir_node = nodes_by_id[node_id]
                    inputs = _assemble_inputs(
                        node_id,
                        incoming=incoming,
                        node_outputs=node_outputs,
                        input_overrides=input_overrides,
                    )
                    target = placements.get(node_id)

                    if target in (None, "local"):
                        _node_start = _time.time()
                        idx = node_index.get(node_id, 0)
                        if logger is not None:
                            try:
                                logger.node_start(
                                    ir_node.node_type, idx, total_active, node_id=node_id
                                )
                            except Exception:
                                pass
                            _flush_run_logs(run, logger)
                        cfg = dict(ir_node.config) if ir_node.config else {}
                        node_seed = node_seeds[node_id]
                        cache_key, cached = _cache_load(
                            use_cache=use_cache,
                            node_type=ir_node.node_type,
                            config=logical_configs[node_id],
                            inputs=inputs,
                            seed=node_seed,
                            run_id=run_id,
                            ir_node=ir_node,
                        )
                        try:
                            if cached is not None:
                                outputs = cached
                            else:
                                outputs, failure_policy = _run_local_node(
                                    node_id=node_id,
                                    node_type=ir_node.node_type,
                                    config=cfg,
                                    seed=node_seed,
                                    inputs=inputs,
                                    run_id=run_id,
                                    ir_node=ir_node,
                                )
                                if use_cache and not failure_policy:
                                    _cache_save(cache_key, ir_node.node_type, outputs or {})
                        except Exception as exc:
                            if logger is not None:
                                try:
                                    logger.node_error(
                                        ir_node.node_type, idx, exc, node_id=node_id
                                    )
                                except Exception:
                                    pass
                                _flush_run_logs(run, logger)
                            raise
                        node_outputs[node_id] = outputs or {}
                        node_workers[node_id] = "local"
                        dur = round(_time.time() - _node_start, 4)
                        node_stats.append({
                            "node_id": node_id,
                            "node_type": ir_node.node_type,
                            "duration_s": dur,
                        })
                        run._write_meta_field("node_stats", node_stats)
                        if logger is not None:
                            try:
                                from app.core.logger import port_item_counts

                                logger.node_end(
                                    ir_node.node_type,
                                    idx,
                                    dur,
                                    node_id=node_id,
                                    output_counts=port_item_counts(outputs or {}),
                                    extra={"worker_id": "local"},
                                )
                            except Exception:
                                pass
                            _flush_run_logs(run, logger)
                        continue

                    node_seed = node_seeds[node_id]
                    cache_key, cached = _cache_load(
                        use_cache=use_cache,
                        node_type=ir_node.node_type,
                        config=logical_configs[node_id],
                        inputs=inputs,
                        seed=node_seed,
                        run_id=run_id,
                        ir_node=ir_node,
                    )
                    if cached is not None:
                        idx = node_index.get(node_id, 0)
                        if logger is not None:
                            try:
                                logger.node_start(
                                    ir_node.node_type, idx, total_active, node_id=node_id
                                )
                                from app.core.logger import port_item_counts

                                logger.node_end(
                                    ir_node.node_type,
                                    idx,
                                    0.0,
                                    node_id=node_id,
                                    output_counts=port_item_counts(cached or {}),
                                    extra={"worker_id": "cache", "cache_hit": True},
                                )
                            except Exception:
                                pass
                            _flush_run_logs(run, logger)
                        node_outputs[node_id] = cached
                        node_workers[node_id] = "cache"
                        node_stats.append({
                            "node_id": node_id,
                            "node_type": ir_node.node_type,
                            "duration_s": 0.0,
                            "cache_hit": True,
                        })
                        run._write_meta_field("node_stats", node_stats)
                        continue

                    input_refs: dict[str, str] = {}
                    for port, value in inputs.items():
                        uri = put_port_value(value)
                        input_refs[port] = uri
                        input_uploads[uri] = _blob_mtime_ns(uri)

                    placement = getattr(ir_node, "placement", None)
                    from app.core.distributed.placement import effective_job_constraints
                    from app.core.ir.models import IRPlacement as _IRPlacement

                    cap = getattr(ir_node, "capability_metadata", None)
                    try:
                        from app.core.host.registry_runtime import get_registry, resolve_capability
                        import warnings as _warnings

                        with _warnings.catch_warnings():
                            _warnings.simplefilter("ignore", RuntimeWarning)
                            cap = resolve_capability(ir_node, get_registry())
                    except Exception:
                        pass
                    constraints = effective_job_constraints(placement, capability=cap)

                    # Only an explicit IR ``mode=worker`` pins the job. pool/auto/
                    # capability placements enqueue constraints only, so any
                    # eligible worker claims it (no run-start hotspot pin).
                    job_placement = placement
                    if (
                        placement is not None
                        and getattr(placement, "mode", None) == "worker"
                        and isinstance(target, str)
                        and target not in ("local", "")
                    ):
                        job_placement = _IRPlacement(
                            mode="worker",
                            worker=str(target),
                            pool=constraints["pool"],
                            tags=tuple(constraints["tags"]),
                            require_gpu=bool(constraints["require_gpu"]),
                            min_vram_mib=constraints["min_vram_mib"],
                        )

                    default_timeout = float(
                        os.environ.get("GRAPHYN_DISTRIBUTED_JOB_TIMEOUT", "120") or "120"
                    )
                    from app.core.distributed.security import assert_remote_config_safe

                    safe_cfg = assert_remote_config_safe(
                        dict(ir_node.config) if ir_node.config else {}
                    )
                    job = NodeJob(
                        job_id=str(uuid.uuid4()),
                        run_id=run_id,
                        node_id=node_id,
                        node_type=ir_node.node_type,
                        config=safe_cfg,
                        seed=node_seed,
                        input_refs=input_refs,
                        placement=job_placement,
                        require_gpu=bool(constraints["require_gpu"]),
                        min_vram_mib=constraints["min_vram_mib"],
                        tags=list(constraints["tags"]),
                        pool=constraints["pool"],
                        timeout_s=default_timeout,
                    )
                    _remote_start = _time.time()
                    idx = node_index.get(node_id, 0)
                    if logger is not None:
                        try:
                            logger.node_start(
                                ir_node.node_type, idx, total_active, node_id=node_id
                            )
                            logger.info(
                                f"Enqueued {node_id} → worker target={target!r} "
                                f"(job={job.job_id[:8]}…)"
                            )
                        except Exception:
                            pass
                        _flush_run_logs(run, logger)
                    stored = queue.enqueue(job)
                    enqueued_job_ids.append(stored.job_id)
                    run_job_ids.append(stored.job_id)
                    log.info(
                        "Enqueued remote job %s for node %s → target %s refs=%s "
                        "require_gpu=%s tags=%s",
                        stored.job_id,
                        node_id,
                        target,
                        list(input_refs),
                        stored.require_gpu,
                        stored.tags,
                    )

                    job_timeout = float(
                        stored.timeout_s if stored.timeout_s is not None else default_timeout
                    )
                    try:
                        result = _wait_remote_result(
                            queue,
                            run,
                            stored.job_id,
                            timeout_s=job_timeout,
                            logger=logger,
                            node_id=node_id,
                        )
                        if result is None:
                            raise TimeoutError(
                                f"Timed out waiting for distributed job {stored.job_id} "
                                f"(node={node_id})"
                            )
                        if result.status != "succeeded":
                            raise RuntimeError(
                                f"Distributed job {stored.job_id} (node={node_id}) "
                                f"ended with status={result.status}: {result.error}"
                            )
                    except Exception as exc:
                        if logger is not None:
                            try:
                                logger.node_error(
                                    ir_node.node_type, idx, exc, node_id=node_id
                                )
                            except Exception:
                                pass
                            _flush_run_logs(run, logger)
                        raise
                    try:
                        enqueued_job_ids.remove(stored.job_id)
                    except ValueError:
                        pass

                    outputs = {}
                    if result.output_refs:
                        digests = dict(getattr(result, "output_sha256", None) or {})
                        for port, uri in result.output_refs.items():
                            outputs[port] = get_port_value(
                                uri, expected_sha256=digests.get(port)
                            )
                    else:
                        for ev in result.events or []:
                            if isinstance(ev, dict) and ev.get("type") == "outputs":
                                data = ev.get("data")
                                if isinstance(data, dict):
                                    outputs = data
                                    break
                        if not outputs and result.output_refs == {}:
                            outputs = {}

                    node_outputs[node_id] = outputs
                    # Never cache IR on_error=route payloads (same rule as Mode A).
                    if use_cache and not _is_routed_error_output(outputs, ir_node):
                        _cache_save(cache_key, ir_node.node_type, outputs)
                    if result.worker_id:
                        node_workers[node_id] = result.worker_id
                    else:
                        node_workers[node_id] = str(target)

                    run._write_meta_field("distributed_node_workers", dict(node_workers))

                    dur = round(_time.time() - _remote_start, 4)
                    if logger is not None:
                        try:
                            from app.core.logger import port_item_counts

                            logger.node_end(
                                ir_node.node_type,
                                idx,
                                dur,
                                node_id=node_id,
                                output_counts=port_item_counts(outputs or {}),
                                extra={"worker_id": node_workers[node_id]},
                            )
                        except Exception:
                            pass
                        _flush_run_logs(run, logger)

                    node_stats.append({
                        "node_id": node_id,
                        "node_type": ir_node.node_type,
                        "duration_s": dur,
                    })
                    run._write_meta_field("node_stats", node_stats)

        except Exception as exc:
            _cancel_enqueued_jobs()
            terminal_status = "failed"
            if logger is not None:
                try:
                    logger.pipeline_error(str(exc) or type(exc).__name__)
                except Exception:
                    pass
                _flush_run_logs(run, logger)
            run.mark_failed(str(exc), node_stats=node_stats)
            raise
        finally:
            deregister_active_run(run.run_id)
            _schedule_run_blob_cleanup(
                queue,
                run_id=run_id,
                job_ids=run_job_ids,
                input_uploads=input_uploads,
            )

        self.last_node_workers = dict(node_workers)
        try:
            run._write_meta_field("distributed_node_workers", dict(node_workers))
        except Exception:
            pass

        if terminal_status is None:
            if logger is not None:
                try:
                    logger.summary()
                    logger.pipeline_done(run.run_id, _time.time() - start_time)
                except Exception:
                    pass
            _flush_run_logs(run, logger)
            run.save_metadata({
                "num_nodes": len(active_nodes),
                "node_stats": node_stats,
                "duration_s": round(_time.time() - start_time, 4),
                "distributed": True,
            })
        else:
            _flush_run_logs(run, logger)

        if not execution_order:
            return {}
        last_id = execution_order[-1]
        return node_outputs.get(last_id, {})


def run_loopback_worker_once(
    worker_id: str = "loopback",
    *,
    execute_fn: Any | None = None,
) -> bool:
    """Claim at most one job and complete it (in-process test / --in-process).

    Default path hydrates ``input_refs`` via :mod:`transfer`, runs a registered
    node (or ``execute_fn``), uploads outputs as blobs, and completes with
    real ``output_refs``.

    ``execute_fn`` signatures accepted:
    * ``execute_fn(job) -> dict`` (legacy; values uploaded as blobs)
    * ``execute_fn(job, inputs) -> dict``
    """
    from app.core.distributed.models import JobResult
    from app.core.distributed.queue import get_job_queue
    from app.core.distributed.registry import get_worker_registry
    from app.core.distributed.transfer import (
        get_port_value,
        job_output_key,
        put_port_value_with_digest,
    )

    registry = get_worker_registry()
    worker = registry.get(worker_id)
    if worker is None:
        raise KeyError(f"loopback worker {worker_id!r} is not registered")

    queue = get_job_queue()
    job = queue.claim(worker)
    if job is None:
        return False

    # Hard refuse missing plugin (claim should already skip; belt-and-suspenders).
    plugins = list(worker.plugins or [])
    if plugins and job.node_type not in plugins:
        queue.complete(
            JobResult(
                job_id=job.job_id,
                status="failed",
                error=(
                    f"Worker {worker_id!r} refuses job: node_type "
                    f"{job.node_type!r} not in advertised plugins {plugins}"
                ),
                worker_id=worker_id,
                duration_s=0.0,
                lease_generation=int(job.lease_generation or 0),
            )
        )
        return True

    if queue.is_cancelled(job.job_id):
        return True

    queue.mark_running(job.job_id)
    _pause_sleep = 4.0
    while queue.is_run_paused(job.run_id):
        if queue.is_cancelled(job.job_id):
            return True
        try:
            queue.renew_lease(job.job_id, worker_id=worker_id)
        except Exception:
            pass
        time.sleep(_pause_sleep)
        _pause_sleep = min(10.0, _pause_sleep * 1.5)
    started = time.monotonic()
    error = None
    outputs: dict[str, Any] = {}
    status = "succeeded"
    output_refs: dict[str, str] = {}
    output_sha256: dict[str, str] = {}
    # Fencing: always report the generation we *claimed*, never the queue's
    # current one (a reclaim bumps it and must reject this late complete).
    gen = int(job.lease_generation or 0)
    try:
        if queue.is_cancelled(job.job_id):
            status = "cancelled"
            error = "cancelled by control plane"
            raise RuntimeError(error)
        inputs: dict[str, Any] = {}
        for port, uri in (job.input_refs or {}).items():
            inputs[port] = get_port_value(uri)

        if execute_fn is not None:
            try:
                outputs = execute_fn(job, inputs) or {}
            except TypeError:
                outputs = execute_fn(job) or {}
        else:
            jid = job.job_id
            # Workers do not yet receive IR on_error/retry on NodeJob (MODEB-ON-ERROR-1).
            outputs, _failure_policy = _run_local_node(
                node_id=job.node_id,
                node_type=job.node_type,
                config=dict(job.config or {}),
                seed=int(job.seed or 0),
                inputs=inputs,
                run_id=job.run_id,
                cancel_check=lambda: queue.is_cancelled(jid),
            )

        for port, value in (outputs or {}).items():
            uri, digest = put_port_value_with_digest(
                value, key=job_output_key(job.job_id, gen, port)
            )
            output_refs[port] = uri
            output_sha256[port] = digest
        if queue.is_cancelled(job.job_id):
            status = "cancelled"
            error = "cancelled by control plane"
            output_refs = {}
    except Exception as exc:  # noqa: BLE001 — surface to JobResult
        if queue.is_cancelled(job.job_id) or status == "cancelled":
            status = "cancelled"
            error = "cancelled by control plane"
        else:
            status = "failed"
            error = str(exc)

    # If control cancelled while we ran, prefer cancelled over succeeded/failed.
    if queue.is_cancelled(job.job_id):
        status = "cancelled"
        error = "cancelled by control plane"
        # cancel() already set a result — only complete if not terminal.
        existing = queue.get(job.job_id)
        if existing is not None and existing.status == "cancelled":
            return True

    try:
        queue.complete(
            JobResult(
                job_id=job.job_id,
                status=status,  # type: ignore[arg-type]
                output_refs=output_refs if status == "succeeded" else {},
                output_sha256=output_sha256 if status == "succeeded" else {},
                events=[],
                error=error,
                worker_id=worker_id,
                duration_s=time.monotonic() - started,
                lease_generation=gen,
            )
        )
    except ValueError:
        # Already terminal (e.g. cancelled by control) — ok.
        pass
    return True


def start_loopback_worker_thread(
    worker_id: str = "loopback",
    *,
    poll_interval_s: float = 0.05,
    stop_event: threading.Event | None = None,
    execute_fn: Any | None = None,
) -> tuple[threading.Thread, threading.Event]:
    """Background thread that claims/completes jobs until ``stop_event`` is set."""
    stop = stop_event or threading.Event()

    def _run() -> None:
        while not stop.is_set():
            try:
                claimed = run_loopback_worker_once(
                    worker_id, execute_fn=execute_fn
                )
            except KeyError:
                break
            if not claimed:
                stop.wait(poll_interval_s)

    t = threading.Thread(
        target=_run, name=f"graphyn-loopback-{worker_id}", daemon=True
    )
    t.start()
    return t, stop
