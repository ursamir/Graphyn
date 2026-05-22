"""AudioExporterNode — write AudioSample objects to WAV files on disk.

Organises output as:
    {output_dir}/{split}/{label}/{id}.wav

Also writes:
    {output_dir}/labels.csv   — id, path, label, split
    {output_dir}/metadata.json — per-sample metadata

Splits samples into train/val/test according to split_ratios.
If a sample already has a 'split' key in its metadata, that value is used
directly (allows upstream nodes to pre-assign splits).
"""
from __future__ import annotations

import csv
import json
import logging
import random
from pathlib import Path
from typing import ClassVar

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample

log = logging.getLogger(__name__)


class AudioExporterNode(Node):
    """Export a list of AudioSample objects to WAV files on disk.

    Organises files as ``{output_dir}/{split}/{label}/{id}.wav``.
    Writes a ``labels.csv`` and ``metadata.json`` summary.

    Config:
        output_dir (str): root directory for exported files
        split_ratios (dict): train/val/test fractions (must sum to 1.0)
        version_tag (str): subdirectory version tag (e.g. "v1")
        random_seed (int): seed for reproducible split assignment
        append (bool): if True, append to existing output; if False, clear first
    """

    node_type: ClassVar[str] = "audio_exporter"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="audio_exporter",
        label="Audio Exporter",
        description=(
            "Export AudioSample objects to WAV files organised by split and label. "
            "Writes labels.csv and metadata.json."
        ),
        category="Audio",
        version="1.0.0",
        tags=["audio", "output", "export", "dataset"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=False,
        deterministic=True,
        cacheable=False,
        streaming_support=False,
        realtime_support=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=list,
            cardinality="single",
            required=True,
            description="List of AudioSample objects to export",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=list,
            description="Pass-through: same list of AudioSample objects",
        )
    }

    class Config(NodeConfig):
        output_dir: str = "output"
        split_ratios: dict = {"train": 0.70, "val": 0.15, "test": 0.15}
        version_tag: str = "v1"
        random_seed: int = 42
        append: bool = False

    # ── SISO process ──────────────────────────────────────────────────────────

    def process(self, samples: list[AudioSample]) -> list[AudioSample]:
        import soundfile as sf  # type: ignore

        cfg = self.config
        out_root = Path(cfg.output_dir) / cfg.version_tag

        if not cfg.append and out_root.exists():
            import shutil
            shutil.rmtree(out_root)
        out_root.mkdir(parents=True, exist_ok=True)

        # Assign splits
        rng = random.Random(cfg.random_seed)
        splits = list(cfg.split_ratios.keys())
        weights = list(cfg.split_ratios.values())

        # Validate ratios
        total = sum(weights)
        if abs(total - 1.0) > 0.01:
            log.warning(
                "AudioExporterNode: split_ratios sum to %.3f, not 1.0 — normalising",
                total,
            )
            weights = [w / total for w in weights]

        rows: list[dict] = []
        meta_entries: list[dict] = []

        for idx, sample in enumerate(samples):
            # Use pre-assigned split if available
            split = sample.metadata.get("split")
            if split not in splits:
                split = rng.choices(splits, weights=weights, k=1)[0]

            label = sample.label or "unknown"
            label_dir = out_root / split / label
            label_dir.mkdir(parents=True, exist_ok=True)

            # Build filename
            stem = Path(str(sample.path)).stem if sample.path else f"sample_{idx:06d}"
            wav_path = label_dir / f"{stem}.wav"

            # Avoid collisions
            counter = 0
            while wav_path.exists():
                counter += 1
                wav_path = label_dir / f"{stem}_{counter:03d}.wav"

            # Write WAV
            data = sample.data
            if data is not None and len(data) > 0:
                sf.write(str(wav_path), data, sample.sample_rate)
            else:
                log.warning("AudioExporterNode: sample %d has no data, skipping", idx)
                continue

            rel_path = str(wav_path.relative_to(out_root.parent))
            rows.append({
                "id": idx,
                "path": rel_path,
                "label": label,
                "split": split,
            })
            meta_entries.append({
                "id": idx,
                "path": rel_path,
                "label": label,
                "split": split,
                "sample_rate": sample.sample_rate,
                "duration_s": round(len(data) / sample.sample_rate, 4) if sample.sample_rate else 0,
                "metadata": sample.metadata,
            })

        # Write labels.csv (append mode: merge with existing)
        labels_csv = out_root / "labels.csv"
        existing_rows: list[dict] = []
        if cfg.append and labels_csv.exists():
            with open(labels_csv, newline="") as f:
                existing_rows = list(csv.DictReader(f))
            # Re-index
            offset = len(existing_rows)
            for r in rows:
                r["id"] = r["id"] + offset

        all_rows = existing_rows + rows
        with open(labels_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["id", "path", "label", "split"])
            writer.writeheader()
            writer.writerows(all_rows)

        # Write metadata.json (append mode: merge)
        meta_json = out_root / "metadata.json"
        existing_meta: list[dict] = []
        if cfg.append and meta_json.exists():
            with open(meta_json) as f:
                existing_meta = json.load(f)

        all_meta = existing_meta + meta_entries
        with open(meta_json, "w") as f:
            json.dump(all_meta, f, indent=2, default=str)

        # Count by split
        split_counts: dict[str, int] = {}
        for r in all_rows:
            split_counts[r["split"]] = split_counts.get(r["split"], 0) + 1

        log.info(
            "AudioExporterNode: wrote %d WAV files to %s — splits: %s",
            len(rows),
            out_root,
            split_counts,
        )

        return samples
