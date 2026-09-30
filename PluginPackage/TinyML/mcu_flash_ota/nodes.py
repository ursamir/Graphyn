"""McuFlashOtaNode — Flash/OTA to MCU (needs-API honesty)

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import hashlib
import json

import importlib
import logging
from pathlib import Path
from typing import ClassVar, Any
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

from app.models.deployment_artifact import DeploymentArtifact

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("mcu_flash_ota.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

FlashReceipt = _types.FlashReceipt

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

def _text(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, list):
        return "\n".join(_text(x) for x in obj)
    data = _dump(obj)
    if isinstance(data, dict):
        for key in ("text", "query", "content", "answer", "user", "path", "value", "final"):
            if data.get(key):
                return str(data[key])
        return json.dumps(data, default=str)
    return str(obj)

def _sha(data: bytes, algo: str) -> str:
    h = hashlib.new(algo if algo in hashlib.algorithms_available else "sha256")
    h.update(data)
    return h.hexdigest()

def _bytes_of(obj: Any) -> bytes:
    if isinstance(obj, bytes):
        return obj
    data = _dump(obj)
    if isinstance(data, dict) and isinstance(data.get("bytes"), (bytes, bytearray)):
        return bytes(data["bytes"])
    if isinstance(data, dict) and data.get("path"):
        path = Path(str(data["path"]))
        if path.is_file():
            return path.read_bytes()
    return _text(obj).encode("utf-8")

def _flash(config, inputs, types):
    raw = _bytes_of(inputs.get("input"))
    digest = _sha(raw, "sha256")
    device = str(_cfg(config, "device_id", "") or "")
    transport = str(_cfg(config, "transport", "swd") or "swd")
    dry = bool(_cfg(config, "dry_run", True))
    plan = {"transport": transport, "device_id": device, "sha256": digest, "bytes": len(raw), "programmed": False}
    path = Path("workspace/artifacts/tinyml/flash_plan.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan), encoding="utf-8")
    if not dry:
        raise RuntimeError(
            f"mcu_flash_ota: no programmer invoked for device {device or '(unset)'}. "
            "Plan written; device was not flashed."
        )
    return _T(types, "FlashReceipt", status="dry-run", device_id=device, message=f"Plan written to {path}. Device was not programmed.", metadata=plan)



class McuFlashOtaNode(Node):
    """Flash/OTA to MCU (needs-API honesty)"""

    node_type: ClassVar[str] = "mcu_flash_ota"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="mcu_flash_ota",
        label="Mcu Flash Ota",
        description="Flash/OTA to MCU (needs-API honesty)",
        category="Output",
        version="0.1.0",
        tags=["tinyml", "stub"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="DeploymentArtifact"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="FlashReceipt NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in honesty placeholder. Default writes a dry-run flash plan and does not program a device.")
        transport: str = Field(default='swd', title="Transport", description="Transport.")
        device_id: str = Field(default='', title="Device id", description="Device id.")
        dry_run: bool = Field(default=True, title="Dry run", description="Dry run.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, "stub", False))
        if not stub:
            return {"output": _flash(self.config, inputs, _types)}

        # Explicit stub=True keeps the needs-api receipt and never claims a flash.
        dry = bool(getattr(self.config, 'dry_run', True))
        receipt = FlashReceipt(
            status="needs-api",
            device_id=str(getattr(self.config, "device_id", "") or ""),
            message="MCU flash/OTA requires Devices API — mark needs-api; never fake device control.",
            metadata={"dry_run": dry, "node_type": "mcu_flash_ota"},
        )
        if not dry:
            raise RuntimeError(receipt.message + " Set config.dry_run=True for honesty stub.")
        log.warning("mcu_flash_ota: %s", receipt.message)
        return {"output": receipt}
