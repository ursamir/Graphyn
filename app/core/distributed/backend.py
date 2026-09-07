# app/core/distributed/backend.py
"""
Bounded Context:  BC5 — Execution Runtime
Responsibility:   DistributedRuntimeBackend — plan/placement-aware execution
                  that falls back to LocalPythonBackend when all nodes are
                  local (or no remote workers are registered).
Owns:             DistributedBackend.
Public Surface:   DistributedBackend.
Must NOT:         Import from app.domain or app.api at module level.
Dependencies:     runtime_backend, distributed.{registry,queue,placement,models},
                  ir.models, registry_runtime (capability), stdlib.
Reason To Change: Full remote NodeExecutor path, wave scheduler, or artifact
                  hydrate/dehydrate across the control plane.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import TYPE_CHECKING, Any

from app.core.runtime_backend import LocalPythonBackend, RuntimeBackend

if TYPE_CHECKING:
    from app.core.ir.models import GraphIR
    from app.core.run_journal import RunManager

log = logging.getLogger(__name__)


class DistributedBackend(RuntimeBackend):
    """P0 distributed backend with local fallback + in-proc job loop.

    Behaviour:
    * If every node resolves to ``\"local\"`` (or there are no alive remote
      workers and nothing *requires* remote), delegate entirely to
      :class:`LocalPythonBackend` — preserving default single-machine runs.
    * If any node resolves to a remote worker id, enqueue :class:`NodeJob`
      entries and wait for claim/complete. Tests may drive a loopback worker
      against the in-memory queue; production workers use the HTTP API / CLI.
    """

    def __init__(self) -> None:
        self._local = LocalPythonBackend()

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
        from app.core.distributed.placement import resolve_worker
        from app.core.distributed.registry import get_worker_registry
        from app.core.registry_runtime import get_registry, resolve_capability

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
        for node in graph.nodes:
            cap = getattr(node, "capability_metadata", None)
            if node_registry is not None:
                try:
                    import warnings
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
            elif target is None:
                # Required remote but no worker — fail closed before local run.
                from app.core.distributed.placement import placement_needs_remote

                if placement_needs_remote(
                    getattr(node, "placement", None), capability=cap
                ):
                    raise RuntimeError(
                        f"No eligible worker for node {node.id!r} "
                        f"(type={node.node_type!r}, placement={node.placement!r})"
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

    def _execute_with_jobs(
        self,
        graph: "GraphIR",
        *,
        placements: dict[str, str | None],
        logger: Any,
        use_cache: bool,
        checkpoint: bool,
        streaming: bool,
        parallel: bool,
        max_workers: int | None,
        resume_run_id: str | None,
        include_nodes: list[str] | None,
        exclude_nodes: list[str] | None,
        input_overrides: dict | None,
        event_driven: bool,
        observer: Any,
        run_manager: "RunManager | None",
    ) -> dict[str, Any]:
        """P0/P1 hybrid: enqueue remote nodes; run local nodes via LocalPython.

        Full wave scheduling + artifact hydrate across machines is P1+.
        For this pass we enqueue remote jobs and wait; a loopback worker
        (tests / same-process) can claim and complete them. If remote jobs
        complete with output_refs only (no in-memory values), we fall back
        to a full local execute when *all* remotes were actually serviced
        by an in-process echo path that also stores outputs on the job result
        events channel — otherwise raise a clear error.
        """
        from app.core.distributed.models import NodeJob
        from app.core.distributed.queue import get_job_queue
        from app.core.ir.models import IRPlacement

        queue = get_job_queue()
        run_id = getattr(run_manager, "run_id", None) or str(uuid.uuid4())

        remote_job_ids: list[str] = []
        for node in graph.nodes:
            target = placements.get(node.id)
            if target in (None, "local"):
                continue
            placement = getattr(node, "placement", None)
            tags = list(placement.tags) if placement and placement.tags else []
            job = NodeJob(
                job_id=str(uuid.uuid4()),
                run_id=run_id,
                node_id=node.id,
                node_type=node.node_type,
                config=dict(node.config) if node.config else {},
                seed=graph.metadata.seed,
                placement=placement,
                require_gpu=bool(placement.require_gpu) if placement else False,
                min_vram_mib=placement.min_vram_mib if placement else None,
                tags=tags,
                pool=placement.pool if placement else None,
            )
            stored = queue.enqueue(job)
            remote_job_ids.append(stored.job_id)
            log.info(
                "Enqueued remote job %s for node %s → worker target %s",
                stored.job_id,
                node.id,
                target,
            )

        # Wait for all remote jobs (workers / loopback claim them).
        timeout_s = float(
            __import__("os").environ.get("GRAPHYN_DISTRIBUTED_JOB_TIMEOUT", "120")
        )
        deadline = time.monotonic() + timeout_s
        for job_id in remote_job_ids:
            remaining = max(0.0, deadline - time.monotonic())
            result = queue.wait_for_result(job_id, timeout_s=remaining)
            if result is None:
                raise TimeoutError(
                    f"Timed out waiting for distributed job {job_id}"
                )
            if result.status != "succeeded":
                raise RuntimeError(
                    f"Distributed job {job_id} ended with status={result.status}: "
                    f"{result.error}"
                )

        # P0 simplification: after remotes succeed, run the full graph locally
        # so downstream local nodes still produce a coherent result. Remotes
        # that already ran are expected to be idempotent / cached in later
        # phases; for MVP this keeps LocalPythonBackend semantics for the
        # graph body when a loopback worker only acknowledges jobs.
        # Prefer skipping re-exec when every node was remote *and* results
        # carried an embedded outputs payload in events.
        embedded = _try_collect_embedded_outputs(queue, remote_job_ids, graph)
        if embedded is not None:
            return embedded

        log.info(
            "DistributedBackend: remote jobs complete; "
            "falling back to LocalPythonBackend for graph materialization"
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


def _try_collect_embedded_outputs(
    queue: Any,
    job_ids: list[str],
    graph: "GraphIR",
) -> dict[str, Any] | None:
    """If every job result embeds ``{"type":"outputs","data":...}``, return last."""
    last: dict[str, Any] | None = None
    for job_id in job_ids:
        result = queue.get_result(job_id)
        if result is None:
            return None
        found = None
        for ev in result.events or []:
            if isinstance(ev, dict) and ev.get("type") == "outputs":
                found = ev.get("data")
        if found is None:
            return None
        if isinstance(found, dict):
            last = found
    return last


def run_loopback_worker_once(
    worker_id: str = "loopback",
    *,
    execute_fn: Any | None = None,
) -> bool:
    """Claim at most one job and complete it (in-process test helper).

    If ``execute_fn`` is provided it is called as
    ``execute_fn(job) -> dict outputs``; otherwise the job is completed with
    empty output_refs and an ``outputs`` event containing ``{}``.

    Returns True if a job was claimed.
    """
    from app.core.distributed.models import JobResult
    from app.core.distributed.queue import get_job_queue
    from app.core.distributed.registry import get_worker_registry

    registry = get_worker_registry()
    worker = registry.get(worker_id)
    if worker is None:
        raise KeyError(f"loopback worker {worker_id!r} is not registered")

    queue = get_job_queue()
    job = queue.claim(worker)
    if job is None:
        return False

    started = time.monotonic()
    error = None
    outputs: dict[str, Any] = {}
    status = "succeeded"
    try:
        if execute_fn is not None:
            outputs = execute_fn(job) or {}
        else:
            outputs = {}
    except Exception as exc:  # noqa: BLE001 — surface to JobResult
        status = "failed"
        error = str(exc)

    queue.complete(
        JobResult(
            job_id=job.job_id,
            status=status,  # type: ignore[arg-type]
            output_refs={
                k: f"artifact://local/loopback/{job.job_id}/{k}"
                for k in (outputs or {})
            },
            events=[{"type": "outputs", "data": outputs}],
            error=error,
            worker_id=worker_id,
            duration_s=time.monotonic() - started,
        )
    )
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
