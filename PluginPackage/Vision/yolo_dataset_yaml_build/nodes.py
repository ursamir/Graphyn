"""YoloDatasetYamlBuildNode — Build Ultralytics data.yaml + path layout

Default config.stub=True returns typed minimal outputs without heavy deps.
When stub=False, writes a real Ultralytics data.yaml from config + input metadata
(stdlib only — no ultralytics import required).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import ClassVar, Any
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

from app.models.dataset_artifact import DatasetArtifact

log = logging.getLogger(__name__)


def _as_names(val: Any) -> list[str]:
    if val is None:
        return []
    if isinstance(val, dict):
        # ultralytics style {0: "a", 1: "b"} or {"names": [...]}
        if "names" in val:
            return _as_names(val["names"])
        try:
            return [str(val[k]) for k in sorted(val, key=lambda x: int(x) if str(x).isdigit() else str(x))]
        except Exception:
            return [str(v) for v in val.values()]
    if isinstance(val, (list, tuple)):
        return [str(x) for x in val]
    return [str(val)]


def _yaml_escape(s: str) -> str:
    if any(c in s for c in ":#{}[],&*!|>%@`'\"" ) or s != s.strip() or not s:
        return json.dumps(s)
    return s


def _write_data_yaml(path: Path, *, root: str, train: str, val: str, names: list[str], task: str) -> None:
    lines = [
        f"path: {_yaml_escape(root)}",
        f"train: {_yaml_escape(train)}",
        f"val: {_yaml_escape(val)}",
        f"# task: {task}",
        "names:",
    ]
    if names:
        for i, n in enumerate(names):
            lines.append(f"  {i}: {_yaml_escape(n)}")
    else:
        lines.append("  0: object")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class YoloDatasetYamlBuildNode(Node):
    """Build Ultralytics data.yaml + path layout from Vision dataset artifacts"""

    node_type: ClassVar[str] = "yolo_dataset_yaml_build"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="yolo_dataset_yaml_build",
        label="Yolo Dataset Yaml Build",
        description="Build Ultralytics data.yaml + path layout from Vision dataset artifacts",
        category="Preprocessing",
        version="0.2.0",
        tags=["vision", "wave1"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="DatasetArtifact"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="DatasetArtifact"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return typed minimal outputs without heavy ML deps.")
        task: str = Field(default='detect', title="Task", description="Task.")
        names: list = Field(default_factory=list)
        path: str = Field(default='', title="Path", description="Dataset root path.")
        train: str = Field(default='images/train', title="Train", description="Train.")
        val: str = Field(default='images/val', title="Val", description="Val.")
        output_yaml: str = Field(default='', title="Output yaml", description="Optional explicit data.yaml path.")

    def process(self, inputs=None, **kwargs):
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', True))
        out_dir = Path('workspace/artifacts') / 'vision' / 'yolo_dataset_yaml_build'
        out_dir.mkdir(parents=True, exist_ok=True)
        if stub:
            result = DatasetArtifact(labels=[], input_shape=(), n_classes=0, metadata={"stub": True})
            return {"output": result}
        return self._process_real(inputs, out_dir)

    def _process_real(self, inputs: dict, out_dir: Path):
        raw = inputs.get("input") or inputs.get("dataset")
        meta_in: dict[str, Any] = {}
        labels_in: list[str] = []
        n_classes = 0
        if raw is not None:
            meta_in = dict(getattr(raw, "metadata", None) or {})
            if isinstance(raw, dict):
                meta_in = dict(raw.get("metadata") or meta_in)
                labels_in = _as_names(raw.get("labels") or raw.get("names") or [])
                n_classes = int(raw.get("n_classes") or 0)
            else:
                labels_in = _as_names(getattr(raw, "labels", None) or getattr(raw, "names", None) or [])
                n_classes = int(getattr(raw, "n_classes", 0) or 0)

        names = _as_names(getattr(self.config, "names", None) or []) or _as_names(meta_in.get("names")) or labels_in
        if not names:
            names = ["object"]
        if not n_classes:
            n_classes = len(names)

        root = (
            str(getattr(self.config, "path", "") or "").strip()
            or str(meta_in.get("root") or meta_in.get("path") or getattr(raw, "root", "") or "")
            or str(out_dir / "dataset")
        )
        root_path = Path(root)
        root_path.mkdir(parents=True, exist_ok=True)
        train = str(getattr(self.config, "train", None) or "images/train")
        val = str(getattr(self.config, "val", None) or "images/val")
        task = str(getattr(self.config, "task", None) or "detect")

        # Ensure relative train/val dirs exist (empty OK — train smoke may use coco8)
        for rel in (train, val):
            p = Path(rel)
            target = p if p.is_absolute() else (root_path / p)
            target.mkdir(parents=True, exist_ok=True)

        yaml_cfg = str(getattr(self.config, "output_yaml", "") or "").strip()
        yaml_path = Path(yaml_cfg) if yaml_cfg else (root_path / "data.yaml")
        yaml_path.parent.mkdir(parents=True, exist_ok=True)
        _write_data_yaml(yaml_path, root=str(root_path.resolve()), train=train, val=val, names=names, task=task)

        meta = {
            "stub": False,
            "backend": "yolo_dataset_yaml_build",
            "task": task,
            "yaml_path": str(yaml_path.resolve()),
            "root": str(root_path.resolve()),
            "train": train,
            "val": val,
            "names": names,
        }
        (out_dir / "last_build.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        log.info("yolo_dataset_yaml_build wrote %s (%d classes)", yaml_path, n_classes)
        return {
            "output": DatasetArtifact(
                labels=list(names),
                input_shape=(),
                n_classes=n_classes,
                metadata=meta,
                manifest_path=str(yaml_path.resolve()),
            )
        }
