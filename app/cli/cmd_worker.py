# app/cli/cmd_worker.py
"""
Bounded Context:  CLI Interface
Responsibility:   worker start subcommand and its HTTP client.
Owns:             cmd_worker_start
Public Surface:   cmd_worker_start
Must NOT:         Contain pipeline execution logic. Must not import app.api.
Dependencies:     app.core.sdk and the core package each command calls.
Reason To Change: That subcommand's flags or output change.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import yaml

_LEGACY_DEFAULT_WORKER_ID = "worker-local"


def _worker_heartbeat_payload(
    resources: dict,
    status: str,
    *,
    active_jobs: int = 0,
    active_job_ids: list | None = None,
) -> dict:
    """JSON body for POST /workers/{id}/heartbeat (P3-14 helper).

    ``active_job_ids`` (heartbeat v2) scopes lease renewal to the jobs this
    worker instance is really running; always sent by current workers.
    """
    ids = list(active_job_ids or [])
    return {
        "resources": resources,
        "status": status,
        "active_jobs": active_jobs if active_jobs else len(ids),
        "active_job_ids": ids,
    }


class _WorkerHTTPError(RuntimeError):
    """HTTP error from the control plane with its status ``code``."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = int(code)


def _auto_worker_id() -> str:
    """``<hostname>-<8 hex>`` — unique per worker process start."""
    import re as _re
    import socket
    import uuid as _uuid

    host = _re.sub(r"[^A-Za-z0-9_.-]", "-", socket.gethostname() or "worker").strip("-.")
    return f"{(host or 'worker')[:48]}-{_uuid.uuid4().hex[:8]}"


def _resolve_worker_id(explicit: str | None, *, http_mode: bool) -> str:
    """Pick the worker id: flag → GRAPHYN_WORKER_ID → auto ``host-uuid``.

    In Mode B (HTTP worker) the legacy shared default ``worker-local`` would
    make every unconfigured worker collide on one identity, so it is replaced
    by an auto-generated id with a loud warning.
    """
    wid = (explicit or os.environ.get("GRAPHYN_WORKER_ID") or "").strip()
    if not wid:
        return _auto_worker_id()
    if http_mode and wid == _LEGACY_DEFAULT_WORKER_ID:
        new_id = _auto_worker_id()
        print(
            f"[worker] WARNING: worker id {wid!r} is the legacy shared default and "
            f"collides across machines in Mode B — using {new_id!r} instead. "
            "Pass a unique --worker-id / GRAPHYN_WORKER_ID.",
            file=sys.stderr,
        )
        return new_id
    return wid


def _retry_http(fn, *, attempts: int | None = None, base_delay_s: float = 1.0, sleep=None, label: str = "request"):
    """Call ``fn()`` retrying transient failures with exponential backoff.

    4xx control-plane answers (``_WorkerHTTPError`` with code < 500) are final
    and re-raised immediately (e.g. 409 = job already terminal / fenced).
    """
    import time as _time

    sleep = sleep or _time.sleep
    if attempts is None:
        try:
            attempts = int(os.environ.get("GRAPHYN_WORKER_COMPLETE_RETRIES", "6") or "6")
        except ValueError:
            attempts = 6
    attempts = max(1, attempts)
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except _WorkerHTTPError as exc:
            if exc.code < 500:
                raise
            last = exc
        except Exception as exc:  # network / timeout
            import re as _re

            m = _re.match(r"^HTTP (\d{3})\b", str(exc))
            if m and int(m.group(1)) < 500:
                raise
            last = exc
        if i + 1 < attempts:
            delay = min(30.0, base_delay_s * (2 ** i))
            print(
                f"[worker] {label} failed ({last}); retry {i + 1}/{attempts - 1} in {delay:.1f}s",
                file=sys.stderr,
            )
            sleep(delay)
    assert last is not None
    raise last


def cmd_worker_start(args):
    """Register with the control plane and run heartbeat + claim loop.

    P1: hydrate input_refs from local blob store or control HTTP API,
    run NodeExecutor, upload output blobs, complete with output_refs.
    """
    import json
    import time
    import urllib.error
    import urllib.request

    control_url = (args.control_url or os.environ.get("GRAPHYN_CONTROL_URL") or "").rstrip("/")
    in_process = bool(getattr(args, "in_process", False))
    worker_id = _resolve_worker_id(args.worker_id, http_mode=not in_process)
    labels = [x.strip() for x in (args.labels or "").split(",") if x.strip()]
    pools = []
    if args.pool:
        pools = [args.pool]
    token = os.environ.get("GRAPHYN_API_TOKEN", "")
    heartbeat_s = float(getattr(args, "heartbeat", 15) or 15)
    once = bool(getattr(args, "once", False))

    def _headers():
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if token:
            h["Authorization"] = f"Bearer {token}"
        return h

    def _http_json(method: str, path: str, payload=None):
        url = f"{control_url}{path}"
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=_headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise _WorkerHTTPError(exc.code, f"HTTP {exc.code} {path}: {detail}") from exc

    def _detect_resources():
        resources = {"gpu": False, "cpus": os.cpu_count() or 1}
        try:
            import shutil
            import subprocess
            if shutil.which("nvidia-smi"):
                out = subprocess.check_output(
                    [
                        "nvidia-smi",
                        "--query-gpu=name,memory.total,memory.free",
                        "--format=csv,noheader,nounits",
                    ],
                    text=True,
                    timeout=5,
                ).strip()
                if out:
                    line = out.splitlines()[0]
                    parts = [p.strip() for p in line.split(",")]
                    resources["gpu"] = True
                    resources["gpu_name"] = parts[0] if parts else None
                    if len(parts) > 1:
                        resources["vram_mib_total"] = int(float(parts[1]))
                    if len(parts) > 2:
                        resources["vram_mib_free"] = int(float(parts[2]))
        except Exception:
            pass
        return resources

    resources = _detect_resources()
    if "gpu" in {l.lower() for l in labels}:
        resources["gpu"] = True

    info = {
        "worker_id": worker_id,
        "labels": labels,
        "pools": pools,
        "resources": resources,
        "plugins": [],
        "graphyn_version": None,
        "status": "idle",
    }

    # Prefer advertising known registry node types when available.
    plugins_override = [
        x.strip()
        for x in (getattr(args, "plugins", None) or "").split(",")
        if x.strip()
    ]
    if plugins_override:
        info["plugins"] = plugins_override
    else:
        try:
            from app.core.host.registry_runtime import get_registry
            reg = get_registry()
            info["plugins"] = [
                getattr(m, "node_type", None) or getattr(m, "name", "")
                for m in reg.list_nodes()
            ]
            info["plugins"] = [p for p in info["plugins"] if p]
        except Exception as exc:
            print(
                f"[worker] warning: failed to load registry plugins "
                f"(hard-refuse inactive if empty): {exc}",
                file=sys.stderr,
            )
    if not info["plugins"]:
        print(
            f"[worker] warning: advertising empty plugins for {worker_id!r} — "
            "hard-refuse is inactive (any node_type may be claimed). "
            "Check registry load or pass --plugins.",
            file=sys.stderr,
        )

    def _hydrate_inputs(input_refs: dict) -> dict:
        """Resolve input_refs to in-memory port values (local store or HTTP)."""
        from pathlib import Path as _Path
        from app.core.distributed.transfer import (
            get_blob,
            http_get_blob,
            load_port_value,
        )

        inputs = {}
        for port, ref in (input_refs or {}).items():
            if not isinstance(ref, str):
                inputs[port] = ref
                continue
            if ref.startswith("/") or ref.startswith("file://"):
                path = ref[7:] if ref.startswith("file://") else ref
                data = _Path(path).read_bytes()
                try:
                    inputs[port] = load_port_value(data)
                except Exception:
                    inputs[port] = path
                continue
            if ref.startswith("artifact://"):
                data = None
                try:
                    data = get_blob(ref)
                except FileNotFoundError:
                    data = None
                except Exception as exc:
                    # e.g. local hash mismatch — refetch; HTTP bytes are verified.
                    print(
                        f"[worker] local blob {ref!r} unusable ({exc}); fetching via HTTP",
                        file=sys.stderr,
                    )
                    data = None
                if data is None:
                    if not control_url or in_process:
                        raise RuntimeError(
                            f"Cannot hydrate input ref {ref!r}: blob missing locally "
                            "and no control URL for HTTP fetch"
                        )
                    # http_get_blob verifies sha256/ key digests (fail closed).
                    data = http_get_blob(control_url, ref, token=token or None)
                inputs[port] = load_port_value(data)
                continue
            inputs[port] = ref
        return inputs

    def _upload_outputs(outputs: dict, job: dict) -> tuple:
        """Serialize outputs to generation-scoped blobs.

        Returns ``(output_refs, output_sha256)``. Keys use the *claimed*
        lease generation; the control plane only accepts the upload while
        this worker still holds that claim.
        """
        import hashlib as _hashlib

        from app.core.distributed.transfer import (
            dump_port_value,
            http_put_blob,
            job_output_key,
            put_blob,
        )

        job_id = str(job.get("job_id") or "job")
        gen = int(job.get("lease_generation") or 0)
        refs = {}
        digests = {}
        for port, value in (outputs or {}).items():
            raw = dump_port_value(value)
            key = job_output_key(job_id, gen, str(port))
            digests[port] = _hashlib.sha256(raw).hexdigest()
            if in_process or not control_url:
                refs[port] = put_blob(raw, key=key)
            else:
                refs[port] = _retry_http(
                    lambda raw=raw, key=key: http_put_blob(
                        control_url,
                        raw,
                        key=key,
                        token=token or None,
                        worker_id=worker_id,
                    ),
                    label=f"blob upload {key}",
                )
        return refs, digests

    def _execute_job(job: dict, *, cancel_check=None) -> tuple:
        """Hydrate inputs, run NodeExecutor, return (outputs, output_refs, output_sha256).

        ``cancel_check`` — optional callable polled during execute / isolated
        subprocess wait so mid-flight cancel can terminate the process group.
        """
        from app.core.distributed.models import NodeJob as _NodeJob
        from app.core.execution.node_executor import NodeExecutor
        from app.core.host.registry_runtime import get_registry
        from app.core.paths.write_paths import ensure_node_write_dirs

        node_job = _NodeJob.model_validate(job)
        inputs = _hydrate_inputs(node_job.input_refs or {})

        registry = get_registry()
        try:
            node_class = registry.get_class(node_job.node_type)
        except Exception as exc:
            raise RuntimeError(
                f"Node type {node_job.node_type!r} is not registered on this worker: {exc}"
            ) from exc
        if node_class is None:
            raise RuntimeError(
                f"Node type {node_job.node_type!r} is not registered on this worker"
            )
        seed = node_job.seed if node_job.seed is not None else 0
        node = node_class(config=dict(node_job.config or {}), seed=seed)
        ensure_node_write_dirs(node)
        executor = NodeExecutor(node, run_id=node_job.run_id)
        if cancel_check is not None:
            executor.set_cancel_check(cancel_check)
        executor.setup()
        try:
            if cancel_check is not None and cancel_check():
                raise RuntimeError("cancelled by control plane")
            outputs = executor.execute(inputs)
        finally:
            try:
                executor.teardown()
            except Exception:
                pass
        refs, digests = _upload_outputs(outputs or {}, job)
        return outputs or {}, refs, digests

    def _claim_and_run_in_process():
        from app.core.distributed.models import JobResult, WorkerInfo
        from app.core.distributed.queue import get_job_queue
        from app.core.distributed.registry import get_worker_registry

        reg = get_worker_registry()
        w = WorkerInfo.model_validate(info)
        reg.register(w)
        # New instance: requeue anything a previous process claimed as us.
        get_job_queue().release_jobs_for_worker(worker_id)
        print(f"[worker] in-process registered {worker_id} labels={labels} pools={pools}")
        iterations = 0
        while True:
            iterations += 1
            reg.heartbeat(worker_id, resources=w.resources, status="idle")
            job = get_job_queue().claim(reg.get(worker_id))
            if job is None:
                if once:
                    print("[worker] no job; exiting (--once)")
                    return
                time.sleep(heartbeat_s)
                continue
            print(f"[worker] claimed job {job.job_id} node={job.node_id} type={job.node_type}")
            # Hard refuse missing plugin (claim should already skip).
            advertised = list(info.get("plugins") or [])
            if advertised and job.node_type not in advertised:
                get_job_queue().complete(
                    JobResult(
                        job_id=job.job_id,
                        status="failed",
                        error=(
                            f"Worker {worker_id!r} refuses job: node_type "
                            f"{job.node_type!r} not in advertised plugins"
                        ),
                        worker_id=worker_id,
                        duration_s=0.0,
                        lease_generation=int(job.lease_generation or 0),
                    )
                )
                if once:
                    return
                continue
            if get_job_queue().is_cancelled(job.job_id):
                print(f"[worker] job {job.job_id} cancelled before start")
                if once:
                    return
                continue
            get_job_queue().mark_running(job.job_id)
            while get_job_queue().is_run_paused(str(job.run_id or "")):
                if get_job_queue().is_cancelled(job.job_id):
                    break
                try:
                    get_job_queue().renew_lease(job.job_id, worker_id=worker_id)
                except Exception:
                    pass
                time.sleep(0.25)
            started = time.time()
            import threading as _threading

            _lease_stop = _threading.Event()
            _lease_interval = max(5.0, min(heartbeat_s, 30.0))

            _active_ids = [job.job_id]

            def _lease_heartbeat_inproc() -> None:
                while not _lease_stop.wait(_lease_interval):
                    try:
                        get_job_queue().renew_leases_for_worker(
                            worker_id, active_job_ids=_active_ids
                        )
                    except Exception:
                        pass

            _lease = _threading.Thread(
                target=_lease_heartbeat_inproc,
                name=f"graphyn-lease-heartbeat-{job.job_id}",
                daemon=True,
            )
            try:
                if get_job_queue().is_cancelled(job.job_id):
                    raise RuntimeError("cancelled by control plane")
                jid = job.job_id
                _lease.start()
                outputs, output_refs, output_sha256 = _execute_job(
                    job.model_dump(mode="json"),
                    cancel_check=lambda: get_job_queue().is_cancelled(jid),
                )
                if get_job_queue().is_cancelled(job.job_id):
                    raise RuntimeError("cancelled by control plane")
                # Embed outputs only when tiny (debug); control hydrates via refs.
                events = []
                try:
                    from app.core.plugins.isolated_executor import recast_plugin_types

                    if sum(len(repr(v)) for v in (outputs or {}).values()) < 2048:
                        events = [
                            {
                                "type": "outputs",
                                "data": recast_plugin_types(outputs),
                            }
                        ]
                except Exception:
                    events = []
                get_job_queue().complete(
                    JobResult(
                        job_id=job.job_id,
                        status="succeeded",
                        output_refs=output_refs,
                        output_sha256=output_sha256,
                        events=events,
                        worker_id=worker_id,
                        duration_s=time.time() - started,
                        # Claimed generation (fencing) — never the queue's current.
                        lease_generation=int(job.lease_generation or 0),
                    )
                )
                print(f"[worker] completed job {job.job_id}")
            except Exception as exc:
                cancelled = (
                    get_job_queue().is_cancelled(job.job_id)
                    or "cancelled by control plane" in str(exc)
                )
                if cancelled:
                    existing = get_job_queue().get(job.job_id)
                    if existing is None or existing.status != "cancelled":
                        try:
                            get_job_queue().complete(
                                JobResult(
                                    job_id=job.job_id,
                                    status="cancelled",
                                    error="cancelled by control plane",
                                    worker_id=worker_id,
                                    duration_s=time.time() - started,
                                    lease_generation=int(job.lease_generation or 0),
                                )
                            )
                        except ValueError:
                            pass
                    print(f"[worker] job {job.job_id} cancelled", file=sys.stderr)
                else:
                    try:
                        get_job_queue().complete(
                            JobResult(
                                job_id=job.job_id,
                                status="failed",
                                error=str(exc),
                                worker_id=worker_id,
                                duration_s=time.time() - started,
                                lease_generation=int(job.lease_generation or 0),
                            )
                        )
                    except (KeyError, ValueError) as complete_exc:
                        # Fenced (reclaimed / already terminal) — drop our result.
                        print(
                            f"[worker] complete for {job.job_id} rejected: {complete_exc}",
                            file=sys.stderr,
                        )
                    print(f"[worker] job {job.job_id} failed: {exc}", file=sys.stderr)
            finally:
                _lease_stop.set()
            if once:
                return

    def _claim_and_run_http():
        if not control_url:
            print(
                "error: --control-url or GRAPHYN_CONTROL_URL is required "
                "(or pass --in-process for local registry loop)",
                file=sys.stderr,
            )
            sys.exit(2)
        import threading as _threading
        from urllib.parse import quote as _quote

        _active: set = set()  # job ids this instance is running right now
        _active_lock = _threading.Lock()

        def _active_ids() -> list:
            with _active_lock:
                return sorted(_active)

        def _register() -> None:
            """(Re-)register; lists running jobs so the control plane keeps them."""
            ids = _active_ids()
            path = "/workers/register"
            if ids:
                path += "?active_job_ids=" + _quote(",".join(ids), safe="")
            _http_json("POST", path, info)

        def _heartbeat(status: str) -> None:
            """Heartbeat with active_job_ids; re-register on 404 (control lost us)."""
            payload = _worker_heartbeat_payload(
                resources, status, active_job_ids=_active_ids()
            )
            try:
                _http_json("POST", f"/workers/{worker_id}/heartbeat", payload)
            except _WorkerHTTPError as exc:
                if exc.code != 404:
                    raise
                print(
                    f"[worker] control plane does not know {worker_id} (404); re-registering",
                    file=sys.stderr,
                )
                _register()
                _http_json("POST", f"/workers/{worker_id}/heartbeat", payload)

        def _complete(job_id: str, result: dict) -> None:
            """POST complete with retry/backoff on transient (network/5xx) errors."""
            _retry_http(
                lambda: _http_json("POST", f"/jobs/{job_id}/complete", result),
                label=f"complete {job_id}",
            )

        print(f"[worker] registering with {control_url} as {worker_id}")
        _register()
        while True:
            try:
                _heartbeat("idle")
                try:
                    claimed = _http_json("POST", "/jobs/claim", {"worker_id": worker_id})
                except _WorkerHTTPError as exc:
                    if exc.code != 404:
                        raise
                    _register()
                    claimed = _http_json("POST", "/jobs/claim", {"worker_id": worker_id})
                job = (claimed or {}).get("job")
                if not job:
                    if once:
                        print("[worker] no job; exiting (--once)")
                        return
                    time.sleep(heartbeat_s)
                    continue
                print(
                    f"[worker] claimed job {job.get('job_id')} "
                    f"node={job.get('node_id')} type={job.get('node_type')}"
                )
                # The generation we claimed — fencing token for uploads/complete.
                claimed_gen = int(job.get("lease_generation") or 0)
                with _active_lock:
                    _active.add(job["job_id"])
                advertised = list(info.get("plugins") or [])
                node_type = job.get("node_type") or ""
                if advertised and node_type not in advertised:
                    try:
                        _complete(
                            job["job_id"],
                            {
                                "job_id": job["job_id"],
                                "status": "failed",
                                "output_refs": {},
                                "events": [],
                                "error": (
                                    f"Worker {worker_id!r} refuses job: node_type "
                                    f"{node_type!r} not in advertised plugins"
                                ),
                                "worker_id": worker_id,
                                "duration_s": 0.0,
                                "lease_generation": claimed_gen,
                            },
                        )
                    finally:
                        with _active_lock:
                            _active.discard(job["job_id"])
                    if once:
                        return
                    continue

                def _job_status() -> dict:
                    # Read-only (GET never renews leases; heartbeats do).
                    return _http_json("GET", f"/jobs/{job['job_id']}") or {}

                def _job_cancelled() -> bool:
                    try:
                        j = _job_status().get("job") or {}
                        return j.get("status") == "cancelled"
                    except Exception:
                        return False

                if _job_cancelled():
                    print(f"[worker] job {job.get('job_id')} cancelled before start")
                    with _active_lock:
                        _active.discard(job["job_id"])
                    if once:
                        return
                    continue
                _last_hb = time.time()
                while True:
                    try:
                        st = _job_status()
                    except Exception:
                        break
                    if not (st or {}).get("run_paused"):
                        break
                    if ((st or {}).get("job") or {}).get("status") == "cancelled":
                        break
                    if time.time() - _last_hb >= max(1.0, min(heartbeat_s, 10.0)):
                        # Paused wait still needs lease renewal (GET no longer renews).
                        try:
                            _heartbeat("busy")
                        except Exception:
                            pass
                        _last_hb = time.time()
                    time.sleep(0.25)
                started = time.time()
                try:
                    _heartbeat("busy")
                    if _job_cancelled():
                        raise RuntimeError("cancelled by control plane")
                    # Poll cancel more often during long execute; NodeExecutor /
                    # isolated subprocess terminate the process group on signal.
                    _cancel_flag = _threading.Event()
                    _watch_stop = _threading.Event()
                    _lease_stop = _threading.Event()
                    _lease_interval = max(5.0, min(heartbeat_s, 30.0))

                    def _cancel_watch() -> None:
                        # ~2 Hz read-only status poll during execute.
                        while not _watch_stop.wait(0.5):
                            if _job_cancelled():
                                _cancel_flag.set()
                                return

                    def _lease_heartbeat() -> None:
                        """Keep claimed job leases alive for long executions (P1-11)."""
                        while not _lease_stop.wait(_lease_interval):
                            try:
                                _heartbeat("busy")
                            except Exception:
                                pass

                    _watch = _threading.Thread(
                        target=_cancel_watch,
                        name=f"graphyn-cancel-watch-{job.get('job_id')}",
                        daemon=True,
                    )
                    _lease = _threading.Thread(
                        target=_lease_heartbeat,
                        name=f"graphyn-lease-heartbeat-{job.get('job_id')}",
                        daemon=True,
                    )
                    _watch.start()
                    _lease.start()
                    try:
                        outputs, output_refs, output_sha256 = _execute_job(
                            job,
                            cancel_check=lambda: (
                                _cancel_flag.is_set() or _job_cancelled()
                            ),
                        )
                    finally:
                        _watch_stop.set()
                        _lease_stop.set()
                    if _job_cancelled() or _cancel_flag.is_set():
                        raise RuntimeError("cancelled by control plane")
                    events = []
                    try:
                        from app.core.plugins.isolated_executor import recast_plugin_types

                        if sum(len(repr(v)) for v in (outputs or {}).values()) < 2048:
                            events = [
                                {
                                    "type": "outputs",
                                    "data": recast_plugin_types(outputs),
                                }
                            ]
                    except Exception:
                        events = []
                    result = {
                        "job_id": job["job_id"],
                        "status": "succeeded",
                        "output_refs": output_refs,
                        "output_sha256": output_sha256,
                        "events": events,
                        "error": None,
                        "worker_id": worker_id,
                        "duration_s": time.time() - started,
                        "lease_generation": claimed_gen,
                    }
                except Exception as exc:
                    cancelled = (
                        "cancelled by control plane" in str(exc) or _job_cancelled()
                    )
                    result = {
                        "job_id": job["job_id"],
                        "status": "cancelled" if cancelled else "failed",
                        "output_refs": {},
                        "events": [],
                        "error": (
                            "cancelled by control plane" if cancelled else str(exc)
                        ),
                        "worker_id": worker_id,
                        "duration_s": time.time() - started,
                        "lease_generation": claimed_gen,
                    }
                    print(
                        f"[worker] job {'cancelled' if cancelled else 'failed'}: {exc}",
                        file=sys.stderr,
                    )
                try:
                    _complete(job["job_id"], result)
                    print(f"[worker] reported completion for {job['job_id']}")
                except Exception as complete_exc:
                    # 409: already terminal (cancelled) or fenced by a reclaim.
                    print(
                        f"[worker] complete report for {job['job_id']} failed: {complete_exc}",
                        file=sys.stderr,
                    )
                finally:
                    with _active_lock:
                        _active.discard(job["job_id"])
                try:
                    _heartbeat("idle")
                except Exception:
                    pass
                if once:
                    return
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print(f"[worker] loop error: {exc}", file=sys.stderr)
                if once:
                    sys.exit(1)
                time.sleep(heartbeat_s)

    if in_process:
        _claim_and_run_in_process()
    else:
        _claim_and_run_http()

# Public names. A leading underscore stays private to this module.
LEGACY_DEFAULT_WORKER_ID = _LEGACY_DEFAULT_WORKER_ID
WorkerHTTPError = _WorkerHTTPError
resolve_worker_id = _resolve_worker_id
retry_http = _retry_http
worker_heartbeat_payload = _worker_heartbeat_payload
