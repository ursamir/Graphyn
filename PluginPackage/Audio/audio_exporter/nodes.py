"""AudioExporterNode — write AudioSample objects to WAV files on disk.

Organises output as:
    {output_dir}/{version_tag}/{split}/{label}/{id}.wav

Also writes under the version dir:
    labels.csv     — id, path, label, split (paths relative to version dir)
    metadata.json  — per-sample metadata
    lineage.json   — version + optional run_id for Projects lineage

Splits samples into train/val/test according to split_ratios.
If a sample already has a 'split' key in its metadata, that value is used
directly (allows upstream nodes to pre-assign splits).
"""
from __future__ import annotations

import csv
import json
import logging
import re
import random
from pathlib import Path
from typing import ClassVar, Literal
from pydantic import Field

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
        output_dir: str = Field(default="workspace/datasets/output/audio_export", title="Output dir", description="Project root under workspace/datasets/output/{project}; version_tag is appended.")
        project: str = Field(default='', title="Project", description="Optional project name; when set, output_dir becomes workspace/datasets/output/{project}.")
        format: Literal["wav"] = Field(default='wav', title="Format", description="Output audio format. Currently wav only (soundfile PCM). One of: wav.")
        split_ratios: dict = Field(default={'train': 0.7, 'val': 0.15, 'test': 0.15}, title="Split ratios", description="Train/val/test ratios as JSON; should sum to ~1.0.")
        version_tag: str = Field(default='v1', title="Version tag", description="Canonical version tag matching vN / vN.N.N (e.g. v1, v1.0.0).")
        random_seed: int = Field(default=42, title="Random seed", description="RNG seed for reproducible splits and sampling.")
        append: bool = Field(default=False, title="Append", description="Append files into an existing export tree instead of replacing it (On/Off).")

    # ── SISO process ──────────────────────────────────────────────────────────

    # Maximum filename-collision retries before raising
    _MAX_COLLISION_RETRIES: ClassVar[int] = 9999
    _VERSION_RE: ClassVar[re.Pattern[str]] = re.compile(r"^v\d+(\.\d+)*$")

    def process(self, samples: list[AudioSample]) -> list[AudioSample]:
        import soundfile as sf  # type: ignore

        cfg = self.config
        version_tag = str(cfg.version_tag or "v1").strip() or "v1"
        if not self._VERSION_RE.match(version_tag):
            raise ValueError(
                f"AudioExporterNode: version_tag {version_tag!r} must match "
                "vN / vN.N.N (e.g. v1, v1.0.0) — not hash-style tags."
            )
        output_dir = str(cfg.output_dir or "").strip()
        project = str(getattr(cfg, "project", "") or "").strip()
        if project:
            output_dir = f"workspace/datasets/output/{project}"
        out_root = Path(output_dir) / version_tag

        # Ensure project.json exists when exporting into datasets/output/{project}
        if project or "/datasets/output/" in output_dir.replace("\\", "/"):
            self._ensure_project_meta(Path(output_dir), project)

        # CRITICAL: validate output_dir is inside the workspace root to prevent
        # shutil.rmtree from deleting arbitrary filesystem directories.
        out_root_resolved = out_root.resolve()
        workspace_root = Path.cwd().resolve()
        if not str(out_root_resolved).startswith(str(workspace_root)):
            raise ValueError(
                f"AudioExporterNode: output_dir '{output_dir}' resolves to "
                f"'{out_root_resolved}' which is outside the workspace root "
                f"'{workspace_root}'. Refusing to proceed."
            )

        if not cfg.append and out_root.exists():
            import shutil
            shutil.rmtree(out_root)
        out_root.mkdir(parents=True, exist_ok=True)

        # Always stamp a version dir (labels.csv + lineage) so Projects Versions
        # populates even when upstream produced zero samples.
        if not samples:
            self._write_manifests(cfg, out_root, [], [])
            self._write_lineage(out_root, version_tag, 0)
            self._register_version(Path(output_dir), version_tag)
            log.info(
                "AudioExporterNode: no samples — stamped empty version at %s",
                out_root,
            )
            return []

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

                rel_path = str(wav_path.relative_to(out_root)).replace("\\", "/")
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
                self._write_lineage(out_root, version_tag, len(rows))

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
        self._register_version(Path(output_dir), version_tag)

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

    def _ensure_project_meta(self, project_dir: Path, project: str) -> None:
        """Create project.json when missing so Projects sidebar discovers the export."""
        try:
            project_dir = Path(project_dir)
            name = project or project_dir.name
            if not name or name in {"output", "datasets", "workspace"}:
                return
            project_dir.mkdir(parents=True, exist_ok=True)
            meta_path = project_dir / "project.json"
            if meta_path.exists():
                return
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc).isoformat()
            meta_path.write_text(
                json.dumps(
                    {
                        "name": name,
                        "status": "draft",
                        "created_at": now,
                        "updated_at": now,
                        "versions": [],
                    },
                    indent=2,
                )
                + '\n',
                encoding="utf-8",
            )
        except OSError as exc:
            log.warning("AudioExporterNode: could not write project.json: %s", exc)

    def _register_version(self, project_dir: Path, version_tag: str) -> None:
        """Ensure project.json lists the stamped version (for UI / meta)."""
        try:
            project_dir = Path(project_dir)
            meta_path = project_dir / "project.json"
            if not meta_path.exists():
                return
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if not isinstance(meta, dict):
                return
            versions = meta.get("versions")
            if not isinstance(versions, list):
                versions = []
            if version_tag not in versions:
                versions.append(version_tag)
                meta["versions"] = versions
                from datetime import datetime, timezone
                meta["updated_at"] = datetime.now(timezone.utc).isoformat()
                meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("AudioExporterNode: could not update project.json versions: %s", exc)

    def _write_lineage(self, out_root: Path, version_tag: str, n_samples: int) -> None:
        """Write lineage.json with run_id when the executor set ``self._run_id``."""
        from datetime import datetime, timezone

        lineage = {
            "version": version_tag,
            "n_samples": n_samples,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "node_type": self.node_type,
        }
        run_id = str(getattr(self, "_run_id", "") or getattr(self, "_current_run_id", "") or "").strip()
        if run_id:
            lineage["run_id"] = run_id
        try:
            with open(out_root / "lineage.json", "w", encoding="utf-8") as f:
                json.dump(lineage, f, indent=2)
        except OSError as exc:
            log.warning("AudioExporterNode: could not write lineage.json: %s", exc)

