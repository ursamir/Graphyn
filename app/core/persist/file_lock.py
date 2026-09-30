# app/core/persist/file_lock.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Cross-process advisory file locks that fail closed when the
                  platform cannot lock (never proceed unlocked).
Owns:             acquire(), release(), LockUnavailable.
Public Surface:   acquire, release, LockUnavailable.
Must NOT:         Import app.domain, app.api, or orchestrator.
Dependencies:     stdlib (fcntl on POSIX, msvcrt on Windows).
Reason To Change: Lock primitive or fail-closed policy changes.
"""
from __future__ import annotations

import os
from typing import IO, Any


class LockUnavailable(OSError):
    """No cross-process lock primitive is available on this interpreter."""


def _fcntl():
    try:
        import fcntl
    except ImportError:
        return None
    return fcntl


def _msvcrt():
    try:
        import msvcrt
    except ImportError:
        return None
    return msvcrt


def acquire(fileobj: IO[Any], *, exclusive: bool, nonblocking: bool = False) -> None:
    """Lock ``fileobj``.

    POSIX uses ``fcntl.flock`` (shared or exclusive). Windows uses
    ``msvcrt.locking``, which has no shared mode, so shared requests are
    taken as exclusive (stricter, still race-free).

    Raises:
        BlockingIOError: non-blocking acquire found the lock held.
        LockUnavailable: neither fcntl nor msvcrt exists — callers must not
            continue the critical section.
    """
    fcntl = _fcntl()
    if fcntl is not None:
        flags = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        if nonblocking:
            flags |= fcntl.LOCK_NB
        try:
            fcntl.flock(fileobj.fileno(), flags)
        except BlockingIOError:
            raise
        except OSError as exc:
            if nonblocking and exc.errno in (11, 35):  # EAGAIN / EWOULDBLOCK
                raise BlockingIOError(exc.errno, exc.strerror) from exc
            raise
        return

    msvcrt = _msvcrt()
    if msvcrt is None:
        raise LockUnavailable(
            "Cross-process file locking requires fcntl (POSIX) or msvcrt (Windows). "
            "Refusing to continue without a lock."
        )

    # msvcrt locks a byte range from the current position and needs ≥1 byte.
    fileobj.seek(0, os.SEEK_END)
    if fileobj.tell() < 1:
        if not getattr(fileobj, "writable", lambda: False)():
            raise LockUnavailable(
                "Windows file locks need a writable handle when the file is empty. "
                "Open lock files with 'a+b' or 'r+b'. Refusing to continue unlocked."
            )
        fileobj.write(b"\0")
        fileobj.flush()
    fileobj.seek(0)
    mode = msvcrt.LK_NBLCK if nonblocking else msvcrt.LK_LOCK
    try:
        msvcrt.locking(fileobj.fileno(), mode, 1)
    except OSError as exc:
        # Windows reports a held lock as EACCES / EDEADLOCK, not BlockingIOError.
        if nonblocking and getattr(exc, "errno", None) in (13, 16, 33, 36):
            raise BlockingIOError(exc.errno or 13, "file lock held") from exc
        if nonblocking:
            raise BlockingIOError(13, "file lock held") from exc
        raise
    # Remember that this fd holds a Windows byte lock so release() can undo it.
    setattr(fileobj, "_graphyn_msvcrt_locked", True)


def release(fileobj: IO[Any]) -> None:
    """Release a lock taken by :func:`acquire`. Missing primitives are ignored."""
    fcntl = _fcntl()
    if fcntl is not None:
        try:
            fcntl.flock(fileobj.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        return
    msvcrt = _msvcrt()
    if msvcrt is None or not getattr(fileobj, "_graphyn_msvcrt_locked", False):
        return
    try:
        fileobj.seek(0)
        msvcrt.locking(fileobj.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    finally:
        setattr(fileobj, "_graphyn_msvcrt_locked", False)
