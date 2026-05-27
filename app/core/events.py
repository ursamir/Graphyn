# app/core/events.py
"""
Bounded Context:  BC5 — Execution Runtime
Responsibility:   Event sources for event-driven pipeline execution. Provides
                  async generators that yield event payloads to trigger nodes.
Owns:             EventSource (ABC), FileWatcherSource, TimerSource,
                  QueueSource, create_event_source() factory.
Public Surface:   EventSource, create_event_source(source_type, source_config)
Must NOT:         Import from app.domain, app.api, or any storage module.
Dependencies:     stdlib (asyncio, abc, fnmatch, os, datetime), watchfiles (optional).
Reason To Change: New event source types are added, or existing source
                  configuration schemas change.
"""
from __future__ import annotations

import abc
import asyncio
import fnmatch
import os
from datetime import datetime, timezone
from typing import Any, AsyncGenerator


class EventSource(abc.ABC):
    """Abstract base for event sources that trigger node execution.

    Req 6.1
    """

    @abc.abstractmethod
    async def watch(self) -> AsyncGenerator[dict, None]:
        """Yield event payload dicts indefinitely until cancelled."""
        ...

    async def close(self) -> None:
        """Release resources. Called when the event-driven run ends."""
        pass


class FileWatcherSource(EventSource):
    """Watches a directory for new or modified files.

    Config keys:
      - path (str): Directory to watch. Must exist and be a directory when
        ``watch()`` is called.
      - pattern (str): Glob pattern for filenames (default "*").
      - poll_interval_s (float): Polling interval in seconds when ``watchfiles``
        is not installed (default 1.0). For high-frequency file events (e.g.
        streaming audio chunks) reduce this value via ``source_config``.

    Yields: {"path": "<absolute_file_path>", "event": "created"|"modified"}

    Performance note: The polling fallback calls ``os.listdir`` + one
    ``stat()`` per file on every interval. For directories with thousands of
    files, install ``watchfiles`` for production use.

    Req 6.9
    """

    def __init__(self, path: str, pattern: str = "*", poll_interval_s: float = 1.0) -> None:
        self.path = path
        self.pattern = pattern
        self.poll_interval_s = poll_interval_s
        self._stop_event: asyncio.Event | None = None
        # Tracks whether close() was called before watch() started so that
        # watch() exits immediately rather than running forever.
        self._closed: bool = False

    async def watch(self) -> AsyncGenerator[dict, None]:
        # Finding 3 fix: honour a close() that arrived before watch() started.
        if self._closed:
            return

        # Finding 2 fix: validate path before entering the watch loop so
        # callers get a clear error instead of a silent no-op.
        if not os.path.isdir(self.path):
            raise FileNotFoundError(
                f"FileWatcherSource: path '{self.path}' does not exist or is not a directory"
            )

        self._stop_event = asyncio.Event()
        try:
            import watchfiles
            # Finding 1 fix: catch non-ImportError backend errors and re-raise
            # with context so the caller (and asyncio.gather) sees a meaningful
            # exception rather than silently losing the event source.
            try:
                async for changes in watchfiles.awatch(self.path, stop_event=self._stop_event):
                    for change_type, file_path in changes:
                        if fnmatch.fnmatch(os.path.basename(file_path), self.pattern):
                            event_type = (
                                "created"
                                if change_type == watchfiles.Change.added
                                else "modified"
                            )
                            yield {"path": file_path, "event": event_type}
            except (OSError, RuntimeError) as exc:
                raise RuntimeError(
                    f"FileWatcherSource: watchfiles backend failed for path "
                    f"'{self.path}': {exc}"
                ) from exc
        except ImportError:
            # Polling fallback when watchfiles is not installed.
            seen: dict[str, float] = {}
            while not (self._stop_event and self._stop_event.is_set()):
                await asyncio.sleep(self.poll_interval_s)
                try:
                    for fname in os.listdir(self.path):
                        if not fnmatch.fnmatch(fname, self.pattern):
                            continue
                        fpath = os.path.join(self.path, fname)
                        mtime = os.path.getmtime(fpath)
                        if fpath not in seen:
                            seen[fpath] = mtime
                            yield {"path": fpath, "event": "created"}
                        elif seen[fpath] != mtime:
                            seen[fpath] = mtime
                            yield {"path": fpath, "event": "modified"}
                except OSError as exc:
                    # Directory was deleted or became inaccessible — surface
                    # the error instead of silently looping forever.
                    raise RuntimeError(
                        f"FileWatcherSource: directory '{self.path}' is no longer "
                        f"accessible: {exc}"
                    ) from exc

    async def close(self) -> None:
        """Signal the watcher to stop and wait briefly for the Rust thread to exit."""
        # Finding 3 fix: set _closed so a subsequent watch() call exits immediately.
        self._closed = True
        if self._stop_event is not None:
            self._stop_event.set()
        # Give watchfiles' background thread time to wind down cleanly
        await asyncio.sleep(0.3)


class TimerSource(EventSource):
    """Fires at a configurable interval.

    Config keys:
      - interval_s (float): Seconds between fires.

    Yields: {"tick": <int>, "timestamp": "<ISO 8601>"}

    ``tick`` is a monotonic counter that is NOT reset between ``watch()``
    calls on the same instance. Consumers that need to detect a restart
    should compare timestamps rather than checking ``tick == 1``.

    Req 6.10
    """

    def __init__(self, interval_s: float) -> None:
        self.interval_s = interval_s
        self._tick = 0
        self._stop_event: asyncio.Event | None = None
        # Tracks whether close() was called before watch() started.
        self._closed: bool = False

    async def watch(self) -> AsyncGenerator[dict, None]:
        # Finding 3 fix: honour a close() that arrived before watch() started.
        if self._closed:
            return
        self._stop_event = asyncio.Event()
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.interval_s
                )
                # stop_event was set — exit cleanly
                return
            except asyncio.TimeoutError:
                pass  # interval elapsed normally
            self._tick += 1
            yield {
                "tick": self._tick,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    async def close(self) -> None:
        """Signal the timer to stop after the current interval."""
        # Finding 3 fix: set _closed so a subsequent watch() call exits immediately.
        self._closed = True
        if self._stop_event is not None:
            self._stop_event.set()


class QueueSource(EventSource):
    """Reads from an asyncio.Queue.

    Config keys: none (queue is passed directly to constructor).

    Yields: whatever dict is put into the queue.

    **Construction note:** ``QueueSource`` requires a live ``asyncio.Queue``
    object and therefore CANNOT be instantiated via ``create_event_source()``
    from an IR ``event_trigger`` config (which is JSON-deserialized). Always
    construct ``QueueSource`` directly in Python code and pass it to the
    orchestrator programmatically.

    Req 6.1
    """

    def __init__(self, queue: asyncio.Queue) -> None:
        self._queue = queue
        self._stop_event: asyncio.Event | None = None
        # Tracks whether close() was called before watch() started.
        self._closed: bool = False

    async def watch(self) -> AsyncGenerator[dict, None]:
        # Finding 3 fix: honour a close() that arrived before watch() started.
        if self._closed:
            return
        self._stop_event = asyncio.Event()
        while not self._stop_event.is_set():
            try:
                # Use wait_for so close() can interrupt a blocked get()
                payload = await asyncio.wait_for(self._queue.get(), timeout=0.5)
                yield payload
            except asyncio.TimeoutError:
                pass  # re-check stop_event on next iteration

    async def close(self) -> None:
        """Signal the queue reader to stop."""
        # Finding 3 fix: set _closed so a subsequent watch() call exits immediately.
        self._closed = True
        if self._stop_event is not None:
            self._stop_event.set()


_SOURCE_REGISTRY: dict[str, type[EventSource]] = {
    "file_watcher": FileWatcherSource,
    "timer": TimerSource,
    # QueueSource is intentionally excluded: it requires a live asyncio.Queue
    # object that cannot be represented in a JSON IR source_config.
    # Construct QueueSource directly in Python code.
}


def create_event_source(source_type: str, source_config: dict) -> EventSource:
    """Instantiate an EventSource by type name.

    Args:
        source_type: One of "file_watcher", "timer", "queue".
        source_config: Keyword arguments passed to the EventSource constructor.

    Raises:
        ValueError: If source_type is not registered, or if source_config
                    contains keys that are not valid constructor parameters.

    Req 6.1
    """
    import inspect

    cls = _SOURCE_REGISTRY.get(source_type)
    if cls is None:
        raise ValueError(
            f"Unknown event source type '{source_type}'. "
            f"Available: {sorted(_SOURCE_REGISTRY)}"
        )

    # Validate source_config keys against the constructor signature so callers
    # get a clear ValueError instead of a confusing TypeError from __init__.
    sig = inspect.signature(cls.__init__)
    valid_params = set(sig.parameters) - {"self"}
    unknown_keys = set(source_config) - valid_params
    if unknown_keys:
        raise ValueError(
            f"Unknown config key(s) {sorted(unknown_keys)} for event source "
            f"'{source_type}'. Valid keys: {sorted(valid_params)}"
        )

    return cls(**source_config)
