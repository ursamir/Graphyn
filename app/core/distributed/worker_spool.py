# app/core/distributed/worker_spool.py
"""
Bounded Context:  BC5 — Execution Runtime (Mode B WAVE-2)
Responsibility:   Offline store-and-forward for worker → control traffic when
                  the control plane is unreachable: spool completes, events,
                  and optional blob files; flush on reconnect with
                  lease_generation fencing.
Owns:             WorkerSpool, spool_enabled(), default_spool_dir().
Public Surface:   WorkerSpool and helpers above.
Must NOT:         Import app.api / app.domain.
Dependencies:     stdlib, app.core.config (graphyn_home, lazy).
Reason To Change: Spool layout, fencing policy, or flush ordering evolves.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

_ENV_SPOOL = "GRAPHYN_WORKER_SPOOL"
_ENV_MAX_BYTES = "GRAPHYN_WORKER_SPOOL_MAX_BYTES"
_ENV_MAX_ITEMS = "GRAPHYN_WORKER_SPOOL_MAX_ITEMS"
_DEFAULT_MAX_BYTES = 512 * 1024 * 1024  # 512 MiB
_DEFAULT_MAX_ITEMS = 256


def spool_enabled() -> bool:
    """Default ON for workers unless explicitly disabled with ``0``/``false``."""
    raw = (os.environ.get(_ENV_SPOOL) or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def spool_max_bytes() -> int:
    try:
        return max(1, int(os.environ.get(_ENV_MAX_BYTES) or _DEFAULT_MAX_BYTES))
    except ValueError:
        return _DEFAULT_MAX_BYTES


def spool_max_items() -> int:
    try:
        return max(1, int(os.environ.get(_ENV_MAX_ITEMS) or _DEFAULT_MAX_ITEMS))
    except ValueError:
        return _DEFAULT_MAX_ITEMS


def default_spool_dir() -> Path:
    override = (os.environ.get("GRAPHYN_WORKER_SPOOL_DIR") or "").strip()
    if override:
        p = Path(override)
    else:
        try:
            from app.core.config import graphyn_home

            p = Path(graphyn_home()) / "worker_spool"
        except Exception:
            p = Path.home() / ".graphyn" / "worker_spool"
    p.mkdir(parents=True, exist_ok=True)
    return p


def is_network_error(exc: BaseException) -> bool:
    """True for transient control-unreachable failures (not 4xx fencing)."""
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    name = type(exc).__name__
    if name in {
        "URLError",
        "RemoteDisconnected",
        "ConnectionResetError",
        "ConnectionRefusedError",
        "ConnectionAbortedError",
        "BrokenPipeError",
        "TimeoutError",
        "SSLError",
        "CertificateError",
    }:
        # SSLError during downtime still counts; cert misconfig is permanent
        # but we still spool so the operator can fix CA and flush.
        return True
    msg = str(exc).lower()
    if "timed out" in msg or "connection refused" in msg or "temporarily unavailable" in msg:
        return True
    if "name or service not known" in msg or "nodename nor servname" in msg:
        return True
    # HTTP 5xx / network wrappers from worker CLI
    if msg.startswith("http 5") or "http 502" in msg or "http 503" in msg or "http 504" in msg:
        return True
    return False


class WorkerSpool:
    """Filesystem spool under ``{GRAPHYN_HOME}/worker_spool/``.

    Item kinds:
      * ``blob`` — optional file payload + metadata (uploaded before complete)
      * ``complete`` — job result JSON (includes lease_generation)
      * ``events`` — pending event batches

    Flush order: blobs → completes → events. Fenced completes (409 / wrong
    generation) are dropped with an audit line in ``dropped.jsonl``.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_spool_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "blobs").mkdir(exist_ok=True)
        (self.root / "items").mkdir(exist_ok=True)

    def _item_path(self, seq: str, kind: str) -> Path:
        return self.root / "items" / f"{seq}_{kind}.json"

    def _next_seq(self) -> str:
        # time + uuid keeps lexicographic order ≈ enqueue order
        return f"{int(time.time() * 1000):015d}_{uuid.uuid4().hex[:10]}"

    def _total_bytes(self) -> int:
        total = 0
        for p in self.root.rglob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except OSError:
                pass
        return total

    def _item_count(self) -> int:
        return sum(1 for p in (self.root / "items").glob("*.json") if p.is_file())

    def _enforce_caps(self) -> None:
        max_items = spool_max_items()
        max_bytes = spool_max_bytes()
        items = sorted((self.root / "items").glob("*.json"))
        while len(items) > max_items:
            victim = items.pop(0)
            self._drop_item(victim, reason="max_items")
        while self._total_bytes() > max_bytes and items:
            victim = items.pop(0)
            self._drop_item(victim, reason="max_bytes")
            items = sorted((self.root / "items").glob("*.json"))

    def _drop_item(self, path: Path, *, reason: str) -> None:
        meta: dict[str, Any] = {"reason": reason, "path": path.name}
        try:
            meta["item"] = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
        blob_rel = (meta.get("item") or {}).get("blob_rel")
        if blob_rel:
            bp = self.root / blob_rel
            try:
                if bp.is_file():
                    bp.unlink()
            except OSError:
                pass
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        self._audit_drop(meta)

    def _audit_drop(self, meta: dict[str, Any]) -> None:
        line = json.dumps({"ts": time.time(), **meta}, default=str)
        record = self.root / "dropped.jsonl"
        try:
            with open(record, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError as exc:
            log.warning("worker_spool audit drop failed: %s", exc)
        log.warning("worker_spool dropped item: %s", line[:500])

    def enqueue_complete(self, result: dict[str, Any]) -> Path:
        seq = self._next_seq()
        path = self._item_path(seq, "complete")
        payload = {
            "kind": "complete",
            "seq": seq,
            "enqueued_at": time.time(),
            "result": result,
            "lease_generation": result.get("lease_generation"),
            "job_id": result.get("job_id"),
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        self._enforce_caps()
        return path

    def enqueue_events(self, job_id: str, events: list[dict[str, Any]]) -> Path:
        seq = self._next_seq()
        path = self._item_path(seq, "events")
        payload = {
            "kind": "events",
            "seq": seq,
            "enqueued_at": time.time(),
            "job_id": job_id,
            "events": events,
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        self._enforce_caps()
        return path

    def enqueue_blob(
        self,
        *,
        key: str | None,
        data: bytes,
        worker_id: str | None = None,
        job_id: str | None = None,
        lease_generation: int | None = None,
    ) -> Path:
        seq = self._next_seq()
        blob_rel = f"blobs/{seq}.bin"
        blob_path = self.root / blob_rel
        blob_path.write_bytes(data)
        path = self._item_path(seq, "blob")
        payload = {
            "kind": "blob",
            "seq": seq,
            "enqueued_at": time.time(),
            "key": key,
            "worker_id": worker_id,
            "job_id": job_id,
            "lease_generation": lease_generation,
            "blob_rel": blob_rel,
            "sha256": __import__("hashlib").sha256(data).hexdigest(),
            "nbytes": len(data),
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        self._enforce_caps()
        return path

    def pending(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for path in sorted((self.root / "items").glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data["_path"] = str(path)
                items.append(data)
            except Exception as exc:
                log.warning("worker_spool: skip corrupt %s: %s", path, exc)
        # blobs first, then completes, then events — stable within kind by seq
        rank = {"blob": 0, "complete": 1, "events": 2}
        items.sort(key=lambda x: (rank.get(x.get("kind"), 9), x.get("seq") or ""))
        return items

    def flush(
        self,
        *,
        put_blob: Callable[..., str] | None = None,
        complete: Callable[[str, dict[str, Any]], Any] | None = None,
        post_events: Callable[[str, list], Any] | None = None,
        is_fenced: Callable[[BaseException], bool] | None = None,
    ) -> dict[str, int]:
        """Flush spool in order. Returns counts ``{flushed, dropped, remaining}``."""
        flushed = dropped = 0

        def _fenced(exc: BaseException) -> bool:
            if is_fenced is not None:
                return is_fenced(exc)
            code = getattr(exc, "code", None)
            if code == 409:
                return True
            msg = str(exc).lower()
            return "lease" in msg and ("generation" in msg or "fenced" in msg or "409" in msg)

        for item in self.pending():
            path = Path(item["_path"])
            kind = item.get("kind")
            try:
                if kind == "blob":
                    if put_blob is None:
                        continue
                    blob_rel = item.get("blob_rel")
                    data = (self.root / blob_rel).read_bytes() if blob_rel else b""
                    put_blob(
                        data,
                        key=item.get("key"),
                        worker_id=item.get("worker_id"),
                    )
                elif kind == "complete":
                    if complete is None:
                        continue
                    result = dict(item.get("result") or {})
                    job_id = str(result.get("job_id") or item.get("job_id") or "")
                    complete(job_id, result)
                elif kind == "events":
                    if post_events is None:
                        continue
                    post_events(str(item.get("job_id") or ""), list(item.get("events") or []))
                else:
                    self._drop_item(path, reason="unknown_kind")
                    dropped += 1
                    continue
            except Exception as exc:
                if _fenced(exc):
                    self._audit_drop(
                        {
                            "reason": "fenced",
                            "path": path.name,
                            "error": str(exc)[:500],
                            "item": {k: item.get(k) for k in ("kind", "job_id", "lease_generation", "seq")},
                        }
                    )
                    blob_rel = item.get("blob_rel")
                    if blob_rel:
                        try:
                            (self.root / blob_rel).unlink(missing_ok=True)
                        except OSError:
                            pass
                    path.unlink(missing_ok=True)
                    dropped += 1
                    continue
                if is_network_error(exc):
                    log.info("worker_spool flush paused (control unreachable): %s", exc)
                    break
                # Permanent non-fence error — drop to avoid poison loop
                self._audit_drop(
                    {
                        "reason": "permanent_error",
                        "path": path.name,
                        "error": str(exc)[:500],
                        "item": {k: item.get(k) for k in ("kind", "job_id", "seq")},
                    }
                )
                blob_rel = item.get("blob_rel")
                if blob_rel:
                    try:
                        (self.root / blob_rel).unlink(missing_ok=True)
                    except OSError:
                        pass
                path.unlink(missing_ok=True)
                dropped += 1
                continue
            # success
            blob_rel = item.get("blob_rel")
            if blob_rel:
                try:
                    (self.root / blob_rel).unlink(missing_ok=True)
                except OSError:
                    pass
            path.unlink(missing_ok=True)
            flushed += 1
        remaining = self._item_count()
        return {"flushed": flushed, "dropped": dropped, "remaining": remaining}

    def clear(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "blobs").mkdir(exist_ok=True)
        (self.root / "items").mkdir(exist_ok=True)
