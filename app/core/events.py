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
      - path (str): Directory to watch.
      - pattern (str): Glob pattern for filenames (default "*").
      - poll_interval_s (float): Polling interval in seconds when ``watchfiles``
        is not installed (default 1.0). For high-frequency file events (e.g.
        streaming audio chunks) reduce this value via ``source_config``.

    Yields: {"path": "<absolute_file_path>", "event": "created"|"modified"}

    Req 6.9
    """

    def __init__(self, path: str, pattern: str = "*", poll_interval_s: float = 1.0) -> None:
        self.path = path
        self.pattern = pattern
        self.poll_interval_s = poll_interval_s
        self._stop_event: asyncio.Event | None = None

    async def watch(self) -> AsyncGenerator[dict, None]:
        self._stop_event = asyncio.Event()
        try:
            import watchfiles
            async for changes in watchfiles.awatch(self.path, stop_event=self._stop_event):
                for change_type, file_path in changes:
                    if fnmatch.fnmatch(os.path.basename(file_path), self.pattern):
                        event_type = (
                            "created"
                            if change_type == watchfiles.Change.added
                            else "modified"
                        )
                        yield {"path": file_path, "event": event_type}
        except ImportError:
            # Polling fallback when watchfiles is not installed
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
                except OSError:
                    pass

    async def close(self) -> None:
        """Signal the watcher to stop and wait briefly for the Rust thread to exit."""
        if self._stop_event is not None:
            self._stop_event.set()
        # Give watchfiles' background thread time to wind down cleanly
        await asyncio.sleep(0.3)


class TimerSource(EventSource):
    """Fires at a configurable interval.

    Config keys:
      - interval_s (float): Seconds between fires.

    Yields: {"tick": <int>, "timestamp": "<ISO 8601>"}

    Req 6.10
    """

    def __init__(self, interval_s: float) -> None:
        self.interval_s = interval_s
        self._tick = 0
        self._stop_event: asyncio.Event | None = None

    async def watch(self) -> AsyncGenerator[dict, None]:
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
        if self._stop_event is not None:
            self._stop_event.set()


class QueueSource(EventSource):
    """Reads from an asyncio.Queue.

    Config keys: none (queue is passed directly to constructor).

    Yields: whatever dict is put into the queue.

    Req 6.1
    """

    def __init__(self, queue: asyncio.Queue) -> None:
        self._queue = queue
        self._stop_event: asyncio.Event | None = None

    async def watch(self) -> AsyncGenerator[dict, None]:
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
        if self._stop_event is not None:
            self._stop_event.set()


_SOURCE_REGISTRY: dict[str, type[EventSource]] = {
    "file_watcher": FileWatcherSource,
    "timer": TimerSource,
    "queue": QueueSource,
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
