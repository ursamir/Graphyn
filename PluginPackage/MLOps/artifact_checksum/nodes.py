"""ArtifactChecksumNode — SHA256 checksum + sidecar

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import hashlib

import importlib
import logging
from pathlib import Path
from typing import ClassVar, Any, Literal
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

from app.models.deployment_artifact import DeploymentArtifact
from app.models.model_artifact import ModelArtifact
from app.models.tflite_artifact import TFLiteArtifact

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("artifact_checksum.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

ChecksumRecord = _types.ChecksumRecord

log = logging.getLogger(__name__)

def _cfg(config: Any, name: str, default: Any = None) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(name, default)
    return getattr(config, name, default)

def _T(types: Any, name: str, **kwargs: Any) -> Any:
    cls = getattr(types, name, None) if types is not None else None
    if cls is None:
        return kwargs
    fields = getattr(cls, "model_fields", None)
    if isinstance(fields, dict) and fields:
        kwargs = {k: v for k, v in kwargs.items() if k in fields}
    return cls(**kwargs)

def _dump(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj

SUPPORTED_ALGOS = (
    "sha256", "sha512", "sha384", "sha224", "sha1", "md5",
    "blake2b", "blake2s", "sha3_256", "sha3_512", "sha3_384", "sha3_224",
)
_PATH_KEYS = ("path", "model_path", "artifact_path", "tflite_path", "file_path", "weights")
_CHUNK = 1 << 20


def _new_hash(algo: str):
    if algo not in SUPPORTED_ALGOS:
        raise ValueError(
            f"artifact_checksum: unsupported algo {algo!r}; choose one of {', '.join(SUPPORTED_ALGOS)}"
        )
    return hashlib.new(algo)


def _feed_file(h, path: Path) -> None:
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            h.update(chunk)


def _hash_path(path: Path, algo: str) -> tuple[str, int]:
    """Stream-hash a file, or a directory as sorted (relative path, size, content) records."""
    h = _new_hash(algo)
    if path.is_file():
        _feed_file(h, path)
        return h.hexdigest(), 1
    if path.is_dir():
        files = sorted(
            (p for p in path.rglob("*") if p.is_file()),
            key=lambda p: p.relative_to(path).as_posix(),
        )
        for f in files:
            rel = f.relative_to(path).as_posix().encode("utf-8")
            h.update(b"F")
            h.update(len(rel).to_bytes(8, "big"))
            h.update(rel)
            h.update(f.stat().st_size.to_bytes(8, "big"))
            _feed_file(h, f)
        return h.hexdigest(), len(files)
    raise FileNotFoundError(f"artifact_checksum: path does not exist: {path}")


def _resolve_path(obj: Any) -> str:
    for key in _PATH_KEYS:
        val = obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
        if val:
            return str(val)
    return ""


def _checksum(config, inputs, types):
    algo = str(_cfg(config, "algo", "sha256") or "sha256").lower()
    _new_hash(algo)  # validate before any I/O
    obj = inputs.get("input")
    if obj is None:
        raise ValueError("artifact_checksum: input is required")
    path = ""
    if isinstance(obj, (bytes, bytearray)):
        h = _new_hash(algo)
        h.update(bytes(obj))
        digest = h.hexdigest()
    elif isinstance(obj, (str, Path)) and Path(str(obj)).exists():
        path = str(obj)
        digest, _ = _hash_path(Path(path), algo)
    elif isinstance(obj, str):
        h = _new_hash(algo)
        h.update(obj.encode("utf-8"))
        digest = h.hexdigest()
    else:
        raw = obj.get("bytes") if isinstance(obj, dict) else getattr(obj, "bytes", None)
        path = _resolve_path(obj)
        if path:
            digest, _ = _hash_path(Path(path), algo)
        elif isinstance(raw, (bytes, bytearray)):
            h = _new_hash(algo)
            h.update(bytes(raw))
            digest = h.hexdigest()
        else:
            raise ValueError(
                "artifact_checksum: input has no file path "
                f"({'/'.join(_PATH_KEYS)}) or bytes to hash ({type(obj).__name__})"
            )
    if bool(_cfg(config, "write_sidecar", True)) and path:
        target = Path(path)
        sidecar = target.parent / f"{target.name}.{algo}"
        sidecar.write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    return _T(types, "ChecksumRecord", algo=algo, digest=digest, path=path)



class ArtifactChecksumNode(Node):
    """SHA256 checksum + sidecar"""

    node_type: ClassVar[str] = "artifact_checksum"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="artifact_checksum",
        label="Artifact Checksum",
        description="SHA256 checksum + sidecar",
        category="MLOps",
        version="0.1.0",
        tags=["mlops"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="ModelArtifact|DeploymentArtifact|TFLiteArtifact"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="ChecksumRecord NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        algo: Literal["sha256", "sha512", "sha384", "sha224", "sha1", "md5", "blake2b", "blake2s", "sha3_256", "sha3_512", "sha3_384", "sha3_224"] = Field(default="sha256", title="Algo", description="Hash algorithm (shake_* unsupported: variable length).")
        write_sidecar: bool = Field(default=True, title="Write sidecar", description="Write sidecar.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'mlops' / 'artifact_checksum'
        if stub:
            log.warning(
                "%s: stub mode (config.stub=True) returned a placeholder, not a real result",
                getattr(self, "node_type", type(self).__name__),
            )
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            _out = out_dir / 'stub'
            result = ChecksumRecord()
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"artifact_checksum: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _checksum(self.config, inputs, _types)}
