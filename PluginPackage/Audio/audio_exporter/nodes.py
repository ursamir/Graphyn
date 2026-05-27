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

    # Maximum filename-collision retries before raising
    _MAX_COLLISION_RETRIES: ClassVar[int] = 9999

    def process(self, samples: list[AudioSample]) -> list[AudioSample]:
        import soundfile as sf  # type: ignore

        # LOW: None/empty guard — return early rather than crashing on enumerate
        if not samples:
            return []

        cfg = self.config
        out_root = Path(cfg.output_dir) / cfg.version_tag

        # CRITICAL: validate output_dir is inside the workspace root to prevent
        # shutil.rmtree from deleting arbitrary filesystem directories.
        out_root_resolved = out_root.resolve()
        workspace_root = Path.cwd().resolve()
        if not str(out_root_resolved).startswith(str(workspace_root)):
            raise ValueError(
                f"AudioExporterNode: output_dir '{cfg.output_dir}' resolves to "
                f"'{out_root_resolved}' which is outside the workspace root "
                f"'{workspace_root}'. Refusing to proceed."
            )

        if not cfg.append and out_root.exists():
            import shutil
            shutil.rmtree(out_root)
        out_root.mkdir(parents=True, exist_ok=True)

        # Assign splits
        rng = random.Random(cfg.random_seed)
        splits = list(cfg.split_ratios.keys())
        weights = list(cfg.split_ratios.values())

        # HIGH: guard against empty split_ratios before rng.choices
        if not splits:
            raise ValueError(
                "AudioExporterNode: split_ratios must not be empty"
            )

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

        try:
            for idx, sample in enumerate(samples):
                # MEDIUM: skip samples with invalid sample_rate before sf.write
                if not sample.sample_rate or sample.sample_rate <= 0:
                    log.warning(
                        "AudioExporterNode: sample %d has invalid sample_rate (%s), skipping",
                        idx,
                        sample.sample_rate,
                    )
                    continue

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

                # Avoid collisions — bounded to prevent infinite loop
                counter = 0
                while wav_path.exists():
                    counter += 1
                    if counter > self._MAX_COLLISION_RETRIES:
                        raise RuntimeError(
                            f"AudioExporterNode: too many filename collisions for stem '{stem}' "
                            f"(>{self._MAX_COLLISION_RETRIES})"
                        )
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
                    "duration_s": round(len(data) / sample.sample_rate, 4),
                    "metadata": sample.metadata,
                })
        finally:
            # HIGH: write partial manifest even if the loop raises mid-batch,
            # so successfully written WAV files are not orphaned.
            if rows or meta_entries:
                self._write_manifests(cfg, out_root, rows, meta_entries)

        # Count by split for logging (uses the rows already written)
        split_counts: dict[str, int] = {}
        for r in rows:
            split_counts[r["split"]] = split_counts.get(r["split"], 0) + 1

        log.info(
            "AudioExporterNode: wrote %d WAV files to %s — splits: %s",
            len(rows),
            out_root,
            split_counts,
        )

        return samples

    def _write_manifests(
        self,
        cfg: "AudioExporterNode.Config",
        out_root: Path,
        rows: list[dict],
        meta_entries: list[dict],
    ) -> None:
        """Write (or merge) labels.csv and metadata.json.

        Called from the try/finally block so a partial batch still produces
        a manifest for the WAV files that were successfully written.
        """
        # Write labels.csv (append mode: merge with existing)
        labels_csv = out_root / "labels.csv"
        existing_rows: list[dict] = []
        if cfg.append and labels_csv.exists():
            with open(labels_csv, newline="") as f:
                existing_rows = list(csv.DictReader(f))
            # MEDIUM: re-index both rows and meta_entries consistently
            offset = len(existing_rows)
            for r, m in zip(rows, meta_entries):
                r["id"] = r["id"] + offset
                m["id"] = m["id"] + offset

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
