"""YoloDatasetYamlBuildNode — Build Ultralytics data.yaml + path layout

Default config.stub=False runs the real implementation.
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


def _write_solid_png(path: Path, *, width: int = 64, height: int = 64, rgb: tuple[int, int, int] = (40, 120, 200)) -> None:
    """Write a tiny valid RGB PNG (stdlib only) for Ultralytics OOB seeds."""
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    path.write_bytes(png)


def _seed_yolo_images_from_root(root_path: Path, *, train: str, val: str) -> None:
    """Copy/create images into Ultralytics train/val dirs for OOB demos.

    Classification seeds (``cat/1.jpg``) are often 1×1 placeholders that
    Ultralytics drops; we copy usable files and always synthesize a couple of
    solid PNGs so train never sees an empty set.
    """
    import shutil

    exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    found: list[Path] = []
    search_roots = [root_path, Path("workspace/datasets/input/vision-demo"), Path("examples/30_vision_demo/data")]
    for base in search_roots:
        if not base.is_dir():
            continue
        candidates = [p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in exts]
        candidates.sort(key=lambda x: (-x.stat().st_size, str(x)))
        for p in candidates:
            try:
                rel = p.relative_to(root_path).as_posix() if p.is_relative_to(root_path) else str(p)
            except Exception:
                rel = str(p)
            if "images/" in rel.replace("\\", "/"):
                continue
            if p.stat().st_size < 200:
                continue
            found.append(p)
            if len(found) >= 6:
                break
        if found:
            break

    train_dir = Path(train) if Path(train).is_absolute() else (root_path / train)
    val_dir = Path(val) if Path(val).is_absolute() else (root_path / val)
    train_dir.mkdir(parents=True, exist_ok=True)
    val_dir.mkdir(parents=True, exist_ok=True)
    labels_train = root_path / "labels" / "train"
    labels_val = root_path / "labels" / "val"
    labels_train.mkdir(parents=True, exist_ok=True)
    labels_val.mkdir(parents=True, exist_ok=True)

    written = 0
    for i, src in enumerate(found):
        dest_dir = train_dir if i % 2 == 0 else val_dir
        label_dir = labels_train if dest_dir == train_dir else labels_val
        dest = dest_dir / f"seed_{i}{src.suffix.lower()}"
        try:
            shutil.copy2(src, dest)
        except OSError as exc:
            log.warning("yolo_dataset_yaml_build: copy %s failed: %s", src, exc)
            continue
        (label_dir / f"{dest.stem}.txt").write_text("0 0.5 0.5 1.0 1.0\n", encoding="utf-8")
        written += 1

    # Always synthesize valid PNGs so Ultralytics has labeled train+val samples.
    for i, (dest_dir, label_dir, color) in enumerate(
        (
            (train_dir, labels_train, (40, 120, 200)),
            (train_dir, labels_train, (200, 80, 40)),
            (val_dir, labels_val, (80, 200, 80)),
            (val_dir, labels_val, (180, 40, 180)),
        )
    ):
        dest = dest_dir / f"synth_{i}.png"
        _write_solid_png(dest, rgb=color)
        (label_dir / f"{dest.stem}.txt").write_text("0 0.5 0.5 0.8 0.8\n", encoding="utf-8")
        written += 1

    log.info(
        "yolo_dataset_yaml_build: seeded %d images into %s / %s",
        written,
        train_dir,
        val_dir,
    )


class YoloDatasetYamlBuildNode(Node):
    """Build Ultralytics data.yaml + path layout from Vision dataset artifacts"""

    node_type: ClassVar[str] = "yolo_dataset_yaml_build"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="yolo_dataset_yaml_build",
        label="Yolo Dataset Yaml Build",
        description="Build Ultralytics data.yaml + path layout from Vision dataset artifacts",
        category="Preprocessing",
        version="0.2.0",
        tags=["vision"],
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
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
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

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'vision' / 'yolo_dataset_yaml_build'
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            fallback = Path(str(getattr(self.config, "path", "") or "").strip() or ".")
            out_dir = fallback / ".graphyn" / "yolo_dataset_yaml_build"
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
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

        # Ensure relative train/val dirs exist; if empty, seed a few images from
        # classification-style folders (cat/dog/*.jpg) so Ultralytics can train OOB.
        for rel in (train, val):
            p = Path(rel)
            target = p if p.is_absolute() else (root_path / p)
            target.mkdir(parents=True, exist_ok=True)

        train_dir = Path(train) if Path(train).is_absolute() else (root_path / train)
        if not any(train_dir.glob("*")):
            _seed_yolo_images_from_root(root_path, train=train, val=val)

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
        receipt = out_dir / "last_build.json"
        payload = json.dumps(meta, indent=2)
        try:
            receipt.write_text(payload, encoding="utf-8")
        except OSError:
            receipt = yaml_path.parent / "last_build.json"
            receipt.write_text(payload, encoding="utf-8")
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
