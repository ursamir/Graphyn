# app/core/nodes/base.py
"""
Bounded Context:  BC2 — Node Contract
Responsibility:   Define the base class and lifecycle protocol for all pipeline
                  nodes. The single contract every node implementation must satisfy.
Owns:             Node (generic base class), SISO wrapper installation logic,
                  _maybe_wrap_siso(), _install_siso_wrapper().
Public Surface:   Node[InputT, OutputT] — subclass to implement a node;
                  Node.publish_files / take_published_file_trees for path
                  side-effect announcements (plain dicts; no BC6 imports);
                  Node.record_external_call / take_external_calls for the
                  egress audit side-channel (redacted URL + body hashes).
Must NOT:         Import from app.domain, app.api, app.core.execution.orchestrator,
                  app.core.execution.planner, or any BC4/BC5/BC6 module.
Dependencies:     BC2 (nodes.config, nodes.ports, nodes.retry, nodes.compat,
                  nodes.observers), stdlib (inspect, logging, typing).
Reason To Change: Node lifecycle protocol changes (new hooks, new port
                  conventions), or SISO wrapper detection logic evolves.
"""
from __future__ import annotations

import inspect
import logging
from typing import Any, AsyncGenerator, ClassVar, Generic, TypeVar

from app.core.nodes.config import NodeConfig, sanitize_node_config_dict
from app.core.nodes.ports import InputPort, OutputPort
from app.core.nodes.retry import RetryPolicy
# SA-B5 fix: import the public name at module level so static analysis can see
# the dependency. The private _type_to_schema alias is kept in compat.py for
# backward compatibility with any existing call sites.
from app.core.nodes.compat import type_to_schema as _type_to_schema
from app.core.nodes.metadata import stable_node_type

log = logging.getLogger(__name__)

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class Node(Generic[InputT, OutputT]):
    """Domain-agnostic base class for all pipeline nodes.

    Every node is a self-contained processing unit that declares:

    - Named, typed **input ports** and **output ports** (``InputPort`` / ``OutputPort``)
    - A Pydantic **configuration model** (inner ``Config(NodeConfig)`` class)
    - A ``process`` method that transforms inputs into outputs

    **SISO shorthand**: nodes with exactly one input port named ``"input"`` and
    one output port named ``"output"`` may override ``process(self, data)`` instead
    of the canonical ``process(self, inputs: dict) -> dict``.  The SISO wrapper
    installed by ``__init_subclass__`` translates between the two conventions
    transparently.

    **Multi-port nodes**: override ``process(self, inputs: dict[str, Any]) -> dict[str, Any]``
    directly.  ``inputs`` keys are port names; ``"multi"`` cardinality ports receive
    a ``list`` of values.

    Subclasses MUST declare::

        node_type: ClassVar[str]           # or rely on auto-derived name
        metadata:  ClassVar[NodeMetadata]
        input_ports:  ClassVar[dict[str, InputPort]]
        output_ports: ClassVar[dict[str, OutputPort]]

        class Config(NodeConfig): ...      # inner Pydantic config model
    """

    # ── class-level declarations (overridden by subclasses) ──────────────────
    node_type: ClassVar[str] = ""
    input_ports: ClassVar[dict[str, InputPort]] = {}
    output_ports: ClassVar[dict[str, OutputPort]] = {}
    retry_policy: ClassVar[RetryPolicy | None] = None
    class Config(NodeConfig):
        """Default empty config — subclasses replace this."""
        pass

    # ── construction ─────────────────────────────────────────────────────────
    def __init__(
        self,
        config: "Config | dict[str, Any] | None" = None,
        seed: int = 0,
        observer: Any = None,
    ) -> None:
        if config is None:
            config = {}
        if isinstance(config, dict):
            cleaned = sanitize_node_config_dict(self.Config, config)
            self.config: NodeConfig = self.Config.model_validate(cleaned)
        elif isinstance(config, self.Config):
            self.config = config
        else:
            # Accept any NodeConfig subclass (e.g. when called from tests).
            # Only fields declared on self.Config are accepted; extra fields on
            # the passed config raise ValidationError (extra="forbid" is the
            # Pydantic default for NodeConfig).  Re-raise with a clear message
            # so callers understand the type mismatch rather than seeing a raw
            # Pydantic field error.
            try:
                dumped = config.model_dump() if hasattr(config, "model_dump") else dict(config)
                cleaned = sanitize_node_config_dict(self.Config, dumped)
                self.config = self.Config.model_validate(cleaned)
            except Exception as exc:
                raise TypeError(
                    f"{type(self).__name__} expects config type "
                    f"{self.Config.__name__!r}, got {type(config).__name__!r}. "
                    f"Ensure the passed config has no extra fields relative to "
                    f"{self.Config.__name__!r}."
                ) from exc
        self.seed = seed
        self.observer = observer
        self._run_id: str = ""  # set by pipeline executor per execution
        # Path side-effects announced during process(); drained by the run
        # layer into file_tree artifacts. Plain dicts only — no BC6 imports.
        self._published_file_trees: list[dict[str, Any]] = []
        # External (network) calls made during process(); drained by the run
        # layer into meta ``external_calls`` and the sealed audit record.
        self._external_calls: list[dict[str, Any]] = []

    # ── External call audit side-channel (G6) ─────────────────────────────────
    @staticmethod
    def redact_url(url: str) -> str:
        """Strip userinfo, query string and fragment from *url* (keep scheme/host/port/path)."""
        from urllib.parse import urlsplit, urlunsplit

        raw = str(url or "")
        try:
            parts = urlsplit(raw)
        except ValueError:
            return raw.split("?", 1)[0].split("#", 1)[0]
        host = parts.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        try:
            port = parts.port
        except ValueError:
            port = None
        netloc = f"{host}:{port}" if port else host
        return urlunsplit((parts.scheme, netloc, parts.path, "", ""))

    @staticmethod
    def body_sha256(data: Any) -> str | None:
        """``sha256:<hex>`` of a request/response body (bytes/str/JSON-able); None for None."""
        if data is None:
            return None
        import hashlib as _hashlib
        import json as _json

        if isinstance(data, (bytes, bytearray, memoryview)):
            raw = bytes(data)
        elif isinstance(data, str):
            raw = data.encode("utf-8")
        else:
            raw = _json.dumps(data, sort_keys=True, default=str).encode("utf-8")
        return "sha256:" + _hashlib.sha256(raw).hexdigest()

    def record_external_call(
        self,
        kind: str,
        method: str,
        url: str,
        status: int | str | None = None,
        *,
        request_sha256: "str | bytes | None" = None,
        response_sha256: "str | bytes | None" = None,
        duration_ms: float | None = None,
        connection_id: str | None = None,
        error: str | None = None,
    ) -> None:
        """Announce one outbound call (HTTP, SMTP, LLM API, …) for the run audit.

        Never stores secrets: the URL is redacted (no userinfo / query /
        fragment) and bodies are recorded only as hashes. ``request_sha256`` /
        ``response_sha256`` accept a ready ``sha256:<hex>`` digest, or raw
        bytes / str / JSON-able data which is hashed here. The executor drains these into run meta
        ``external_calls`` and the sealed ``prove.json`` record.
        """
        def _digest(v: Any) -> str | None:
            if v is None:
                return None
            if isinstance(v, str) and v.startswith("sha256:"):
                return v
            return self.body_sha256(v)

        entry: dict[str, Any] = {
            "kind": str(kind or "http"),
            "method": str(method or "").upper(),
            "url": self.redact_url(url),
            "status": status,
            "request_sha256": _digest(request_sha256),
            "response_sha256": _digest(response_sha256),
            "duration_ms": round(float(duration_ms), 2) if duration_ms is not None else None,
            "connection_id": str(connection_id) if connection_id else None,
        }
        if error:
            entry["error"] = str(error)[:300]
        try:
            from datetime import datetime as _dt, timezone as _tz

            entry["ts"] = _dt.now(_tz.utc).isoformat()
        except Exception:
            pass
        if not hasattr(self, "_external_calls"):
            self._external_calls = []
        self._external_calls.append(entry)

    def take_external_calls(self) -> list[dict[str, Any]]:
        """Drain queued ``record_external_call`` entries (run layer only)."""
        calls = list(getattr(self, "_external_calls", None) or [])
        if hasattr(self, "_external_calls"):
            self._external_calls.clear()
        return calls

    def accept_external_calls(self, calls: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> None:
        """Re-queue entries returned from an isolated worker (host-side)."""
        if not hasattr(self, "_external_calls"):
            self._external_calls = []
        for item in calls or ():
            if isinstance(item, dict) and item.get("url") is not None:
                self._external_calls.append(item)

    def publish_files(
        self,
        root: "str | Path",
        files: "list[str] | list[dict[str, Any]] | Path",
        *,
        total: int | None = None,
    ) -> None:
        """Announce a path-published file tree for this node (generic).

        Call from ``process()`` after writing files under ``root``. The run
        layer registers a platform ``file_tree`` artifact — no domain formats
        (labels.csv, wav trees, …) are inferred by core.

        Args:
            root: Jailed directory (or file parent) containing the published files.
            files: Explicit relative paths, entry dicts ``{path, size?}``, or a
                path to a JSON inventory ``{"files": [...], "total"?}``.
            total: Optional full count when ``files`` is a sample; defaults to
                ``len(files)``.
        """
        from pathlib import Path as _Path

        root_path = _Path(root)
        root_str = str(root).replace("\\", "/").strip()
        if not root_str:
            raise ValueError("publish_files: root must be non-empty")

        entries: list[dict[str, Any]] = []
        if isinstance(files, _Path) or (
            isinstance(files, str) and str(files).endswith(".json")
        ):
            inv_path = _Path(files)
            try:
                import json as _json

                raw = _json.loads(inv_path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise ValueError(f"publish_files: cannot read inventory {inv_path}: {exc}") from exc
            if not isinstance(raw, dict):
                raise ValueError("publish_files: inventory JSON must be an object")
            if total is None and isinstance(raw.get("total"), int):
                total = int(raw["total"])
            raw_files = raw.get("files") or []
            if not isinstance(raw_files, list):
                raise ValueError("publish_files: inventory.files must be a list")
            files = raw_files  # type: ignore[assignment]

        if not isinstance(files, list):
            raise TypeError("publish_files: files must be a list or inventory Path")

        for item in files:
            if isinstance(item, str) and item.strip():
                rel = item.replace("\\", "/").lstrip("./")
                # Prefer paths relative to root when absolute under root.
                try:
                    abs_item = _Path(item)
                    if abs_item.is_absolute():
                        rel = str(abs_item.relative_to(root_path.resolve())).replace("\\", "/")
                except (OSError, ValueError):
                    pass
                entries.append({"path": rel})
            elif isinstance(item, dict):
                path = item.get("path")
                if not isinstance(path, str) or not path.strip():
                    continue
                rel = path.replace("\\", "/").lstrip("./")
                entry: dict[str, Any] = {"path": rel}
                size = item.get("size")
                if isinstance(size, (int, float)) and size >= 0:
                    entry["size"] = int(size)
                name = item.get("name")
                if isinstance(name, str) and name.strip():
                    entry["name"] = name
                entries.append(entry)

        self._published_file_trees.append(
            {
                "root": root_str,
                "files": entries,
                "total": int(total) if isinstance(total, int) and total >= 0 else len(entries),
            }
        )

    def take_published_file_trees(self) -> list[dict[str, Any]]:
        """Drain queued ``publish_files`` announcements (run layer only)."""
        trees = list(self._published_file_trees)
        self._published_file_trees.clear()
        return trees

    def accept_published_file_trees(self, trees: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> None:
        """Re-queue inventories returned from an isolated worker (host-side)."""
        for item in trees or ():
            if isinstance(item, dict) and item.get("root"):
                self._published_file_trees.append(item)

    # ── SISO wrapper installation ─────────────────────────────────────────────
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        _maybe_wrap_siso(cls)

    # ── SISO convenience properties ───────────────────────────────────────────
    @classmethod
    def _is_siso(cls) -> bool:
        """Return True if this node has exactly one input port 'input' and one output port 'output'."""
        return (
            set(cls.input_ports.keys()) == {"input"}
            and set(cls.output_ports.keys()) == {"output"}
        )

    @property
    def input_type(self) -> type | None:
        """Convenience accessor for SISO nodes — returns ``input_ports["input"].data_type``.

        Raises:
            AttributeError: if this is not a SISO node.
        """
        if not self._is_siso():
            raise AttributeError(
                f"{type(self).__name__} is not a SISO node; "
                "use input_ports directly"
            )
        return self.input_ports["input"].data_type

    @property
    def output_type(self) -> type | None:
        """Convenience accessor for SISO nodes — returns ``output_ports["output"].data_type``.

        Raises:
            AttributeError: if this is not a SISO node.
        """
        if not self._is_siso():
            raise AttributeError(
                f"{type(self).__name__} is not a SISO node; "
                "use output_ports directly"
            )
        return self.output_ports["output"].data_type

    # ── port schema introspection ─────────────────────────────────────────────
    @classmethod
    def port_schemas(cls) -> dict[str, Any]:
        """Return JSON Schema representations of all ports.

        Returns::

            {
                "inputs":  {port_name: json_schema_dict | null},
                "outputs": {port_name: json_schema_dict | null},
            }
        """
        return {
            "inputs": {
                name: _type_to_schema(port.data_type)
                for name, port in cls.input_ports.items()
            },
            "outputs": {
                name: _type_to_schema(port.data_type)
                for name, port in cls.output_ports.items()
            },
        }

    # ── streaming detection ───────────────────────────────────────────────────
    @classmethod
    def _is_streaming(cls) -> bool:
        """Return True when this class overrides process_stream."""
        return cls.process_stream is not Node.process_stream  # type: ignore[comparison-overlap]

    @property
    def is_streaming(self) -> bool:
        """True when this node overrides process_stream."""
        return type(self)._is_streaming()

    # ── canonical multi-port process signature ────────────────────────────────
    def process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Override in multi-port nodes.

        SISO nodes override ``process(self, data)`` instead; the wrapper
        installed by ``__init_subclass__`` translates between conventions.

        Args:
            inputs: Dict mapping port names to their input values.
                    ``"multi"`` cardinality ports receive a ``list`` of values.

        Returns:
            Dict mapping output port names to their produced values.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement process()"
        )

    # ── streaming ─────────────────────────────────────────────────────────────
    async def process_stream(
        self, inputs: dict[str, Any]
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Override in streaming nodes.

        Default implementation wraps ``process()`` as a single-item async generator.
        CPU-bound work is offloaded to the default ``ThreadPoolExecutor`` so the
        asyncio event loop is not blocked while ``process()`` runs.

        SA-B3: The default executor uses threads, not processes. Python's GIL
        means CPU-bound ``process()`` implementations do NOT get true parallelism
        here. If your node is CPU-bound, override ``process_stream`` and submit
        work to a ``concurrent.futures.ProcessPoolExecutor`` instead.

        Note: if a subclass overrides ``process`` as ``async def``, it is awaited
        directly rather than submitted to a thread pool (submitting a coroutine
        to ``run_in_executor`` would return the coroutine object unawaited).
        """
        import asyncio as _asyncio
        loop = _asyncio.get_running_loop()
        if inspect.iscoroutinefunction(self.process):
            result = await self.process(inputs)
        else:
            result = await loop.run_in_executor(None, self.process, inputs)
        yield result

    # ── lifecycle hooks (no-op defaults) ─────────────────────────────────────
    def setup(self) -> None:
        """Called once before the first ``on_start()``.

        Use for expensive one-time initialisation (e.g. loading model weights,
        opening file handles).  NOT called by ``__init__``.
        """

    def on_start(self) -> None:
        """Called immediately before each ``process()`` invocation."""
        if self.observer is not None:
            try:
                self.observer.on_node_start(
                    node_type=stable_node_type(self),
                    run_id=self._run_id,
                )
            except Exception:
                pass  # observer failures must never crash the node

    def on_end(self) -> None:
        """Called immediately after ``process()`` returns without raising."""
        if self.observer is not None:
            try:
                self.observer.on_node_end(
                    node_type=stable_node_type(self),
                    run_id=self._run_id,
                    duration_s=getattr(self, "_last_duration", 0.0),
                    input_counts=getattr(self, "_last_input_counts", {}),
                    output_counts=getattr(self, "_last_output_counts", {}),
                )
            except Exception:
                pass  # observer failures must never crash the node

    def on_error(self, exc: Exception) -> None:
        """Called when ``process()`` raises, before the exception propagates."""
        if self.observer is not None:
            try:
                self.observer.on_node_error(
                    node_type=stable_node_type(self),
                    run_id=self._run_id,
                    exc=exc,
                )
            except Exception:
                pass  # observer failures must never crash the node

    def teardown(self) -> None:
        """Called once after the final ``on_end()`` or after ``on_error()`` if not retried.

        Use for releasing resources (e.g. closing file handles, freeing GPU memory).
        """


# ── SISO wrapper helper ───────────────────────────────────────────────────────

def _maybe_wrap_siso(cls: type) -> None:
    """If ``cls`` is a SISO node that overrides ``process(self, data)``, wrap it.

    Detection order (BUG-8 fix — explicit flag takes precedence over fragile
    parameter-name inference):

    1. If the class sets ``_siso: ClassVar[bool] = True`` explicitly, wrap it.
    2. If the class sets ``_siso: ClassVar[bool] = False`` explicitly, skip it.
    3. Fall back to parameter-name inference: wrap if the second parameter is
       NOT named ``"inputs"``.

    The wrapper:
    1. Unpacks ``inputs["input"]`` → ``data``
    2. Calls the original ``process(self, data)``
    3. Repacks the result as ``{"output": result}``

    The original method is stored as ``process.__wrapped__`` for testing.
    """
    # SA-B4 fix: skip abstract intermediary classes — wrapping them incorrectly
    # if they define process() with a non-"inputs" parameter name.
    if inspect.isabstract(cls):
        return

    if "process" not in cls.__dict__:
        return  # no override in this class

    raw_process = cls.__dict__["process"]

    # Skip if it's already a wrapped function
    if getattr(raw_process, "__wrapped__", None) is not None:
        return

    # Check explicit _siso flag first (avoids fragile parameter-name inference)
    explicit_siso = cls.__dict__.get("_siso")
    if explicit_siso is False:
        return  # explicitly declared as multi-port — never wrap
    if explicit_siso is True:
        # Explicitly declared as SISO — wrap unconditionally
        _install_siso_wrapper(cls, raw_process)
        return

    # Fall back to parameter-name inference for backward compatibility
    try:
        params = list(inspect.signature(raw_process).parameters.keys())
    except (ValueError, TypeError):
        return

    # Multi-port signature: (self, inputs) — leave alone
    if len(params) >= 2 and params[1] == "inputs":
        return

    # SISO signature: (self, data) or (self, samples) etc.
    _install_siso_wrapper(cls, raw_process)


def _install_siso_wrapper(cls: type, raw_process) -> None:
    """Install the SISO dict-unpacking wrapper on cls.process.

    Raises:
        TypeError: if ``_siso = True`` is set explicitly on a node that declares
            more than one output port.  A SISO wrapper on a multi-output node
            would silently double-wrap any partial return dict.
    """
    # Guard: _siso=True on a multi-output node is a contract violation.
    # The wrapper's pass-through guard (set(result.keys()) == set(output_ports.keys()))
    # only fires when ALL output port keys are present.  A partial return dict
    # (e.g. only "output" when ports are {"output", "aux"}) would be double-wrapped
    # as {"output": {"output": ...}}.  Catch this at class-definition time.
    if len(cls.output_ports) > 1:
        raise TypeError(
            f"{cls.__name__}: _siso=True is not valid for nodes with more than "
            f"one output port (found: {sorted(cls.output_ports.keys())}). "
            "Remove _siso=True or reduce output_ports to a single 'output' port."
        )
    def _siso_process(
        self: "Node",
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        # SA-B2 fix: validate that inputs is a dict before calling .get().
        # A non-dict raises AttributeError with a confusing message otherwise.
        if not isinstance(inputs, dict):
            raise TypeError(
                f"{type(self).__name__}.process() expected a dict of port inputs, "
                f"got {type(inputs).__name__}"
            )
        data = inputs.get("input")
        result = raw_process(self, data)
        # Guard: if the node was refactored to return a full multi-port dict
        # (keys match the declared output ports), pass it through unchanged to
        # avoid double-wrapping as {"output": {"output": ...}}.
        if isinstance(result, dict) and set(result.keys()) == set(cls.output_ports.keys()):
            return result
        return {"output": result}

    _siso_process.__wrapped__ = raw_process  # type: ignore[attr-defined]
    _siso_process.__doc__ = raw_process.__doc__
    cls.process = _siso_process  # type: ignore[method-assign]
