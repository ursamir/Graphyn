"""DatasetIngestNode — universal audio dataset ingestion.

Supports filesystem, HuggingFace Hub, S3, ZIP, TAR archives, and CSV/JSON manifests.
Migrated and expanded from app/core/nodes/audio/file_input.py.
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import ClassVar

import librosa
import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample

log = logging.getLogger(__name__)

SUPPORTED_AUDIO_EXTENSIONS = (".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac")


class DatasetIngestNode(Node):
    """Universal audio dataset ingestion from filesystem, archives, HuggingFace, S3, and manifests.

    source_type options:
        "filesystem"  — walk directory tree; subdirectory names become labels
        "huggingface" — load via datasets.load_dataset(); requires datasets package
        "s3"          — scan S3 bucket/prefix; requires boto3 package
        "zip"         — extract ZIP to temp dir, then scan as filesystem
        "tar"         — extract TAR archive to temp dir, then scan as filesystem
        "manifest"    — read CSV/JSON with columns path,label; load each file

    Config:
        source_type (str): ingestion backend (default "filesystem")
        path (str): local path, ZIP/TAR path, S3 URI (s3://bucket/prefix/), or HuggingFace dataset ID
        manifest_path (str): path to CSV/JSON manifest (overrides path scanning)
        recursive (bool): walk subdirectories (filesystem mode, default True)
        limit (int): max files per label; 0 = no limit
        label_override (str): force a fixed label for all samples
        hf_split (str): HuggingFace dataset split (default "train")
        hf_audio_column (str): HuggingFace audio column name (default "audio")
        hf_label_column (str): HuggingFace label column name (default "label")
        lazy (bool): reserved for future generator-based loading
        resume_from (str): path to a resume checkpoint JSON file
        validate_integrity (bool): compute SHA256 and verify against .sha256 sidecar files
        deduplicate (bool): skip duplicate waveforms (hash-based)
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="dataset_ingest",
        label="Dataset Ingest",
        description=(
            "Universal audio dataset ingestion from filesystem, archives, "
            "HuggingFace, S3, and manifests."
        ),
        category="Input",
        version="1.1.0",
        tags=["audio", "input", "dataset", "ingestion"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=False,
        deterministic=True,
        cacheable=True,
        streaming_support=False,
        realtime_support=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {}  # source node — no inputs

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=list[AudioSample],
            description="Loaded AudioSample objects",
        )
    }

    class Config(NodeConfig):
        source_type: str = "filesystem"  # "filesystem" | "huggingface" | "s3" | "zip" | "tar" | "manifest"
        path: str = ""
        manifest_path: str = ""
        recursive: bool = True
        limit: int = 0
        label_override: str = ""
        hf_split: str = "train"
        hf_audio_column: str = "audio"
        hf_label_column: str = "label"
        lazy: bool = False               # reserved: generator-based loading (not yet implemented)
        resume_from: str = ""            # path to resume checkpoint file (one path per line)
        validate_integrity: bool = False  # compute SHA256; verify .sha256 sidecar if present
        deduplicate: bool = False

    # ── process (multi-port / source node signature) ──────────────────────────

    def process(self, inputs: dict) -> dict:
        """Source node — multi-port signature (no input ports)."""
        source_type = self.config.source_type

        if self.config.lazy:
            log.warning(
                "DatasetIngestNode: lazy=True is set but generator-based loading is not "
                "yet implemented. Processing all samples eagerly."
            )

        if source_type == "filesystem":
            samples = self._load_filesystem(self.config.path)
        elif source_type == "huggingface":
            samples = self._load_huggingface()
        elif source_type == "s3":
            samples = self._load_s3()
        elif source_type == "zip":
            samples = self._load_zip(self.config.path)
        elif source_type == "tar":
            samples = self._load_tar(self.config.path)
        elif source_type == "manifest":
            manifest = self.config.manifest_path or self.config.path
            samples = self._load_manifest(manifest)
        else:
            raise ValueError(
                f"DatasetIngestNode: unknown source_type '{source_type}'. "
                "Choose from: filesystem, huggingface, s3, zip, tar, manifest"
            )

        if self.config.deduplicate:
            samples = self._deduplicate(samples)

        return {"output": samples}

    # ── filesystem ────────────────────────────────────────────────────────────

    def _load_filesystem(self, path: str) -> list[AudioSample]:
        """Walk directory tree; subdirectory names become labels."""
        root_path = Path(path)
        if not root_path.exists():
            raise ValueError(f"DatasetIngestNode: path does not exist: {root_path}")
        if not root_path.is_dir():
            raise ValueError(f"DatasetIngestNode: path must be a directory: {root_path}")

        # Load resume checkpoint
        already_processed = self._load_checkpoint()

        samples: list[AudioSample] = []
        label_counts: dict[str, int] = {}

        if self.config.recursive:
            for dirpath, dirnames, filenames in os.walk(root_path):
                dirnames.sort()  # deterministic order
                audio_files = sorted(
                    f for f in filenames
                    if f.lower().endswith(SUPPORTED_AUDIO_EXTENSIONS)
                )
                if not audio_files:
                    continue

                dir_label = (
                    self.config.label_override
                    if self.config.label_override
                    else os.path.basename(dirpath)
                )

                for fname in audio_files:
                    if self.config.limit > 0:
                        if label_counts.get(dir_label, 0) >= self.config.limit:
                            continue

                    file_path = os.path.join(dirpath, fname)

                    if file_path in already_processed:
                        log.debug("DatasetIngestNode: skipping (checkpoint) '%s'", file_path)
                        continue

                    sample = self._load_file(file_path, dir_label, {"source_dir": dirpath})
                    if sample is not None:
                        samples.append(sample)
                        label_counts[dir_label] = label_counts.get(dir_label, 0) + 1
                        self._append_checkpoint(file_path)
        else:
            # Non-recursive: only files directly in root_path
            label = (
                self.config.label_override
                if self.config.label_override
                else root_path.name
            )
            audio_files = sorted(
                f for f in os.listdir(root_path)
                if f.lower().endswith(SUPPORTED_AUDIO_EXTENSIONS)
            )
            for fname in audio_files:
                if self.config.limit > 0 and len(samples) >= self.config.limit:
                    break
                file_path = os.path.join(str(root_path), fname)

                if file_path in already_processed:
                    log.debug("DatasetIngestNode: skipping (checkpoint) '%s'", file_path)
                    continue

                sample = self._load_file(file_path, label, {})
                if sample is not None:
                    samples.append(sample)
                    self._append_checkpoint(file_path)

        return samples

    # ── huggingface ───────────────────────────────────────────────────────────

    def _load_huggingface(self) -> list[AudioSample]:
        """Load from HuggingFace Hub via datasets.load_dataset()."""
        try:
            from datasets import load_dataset  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "DatasetIngestNode: 'datasets' package required for source_type='huggingface'. "
                "Install with: pip install datasets>=2.14"
            ) from exc

        dataset_id = self.config.path
        if not dataset_id:
            raise ValueError("DatasetIngestNode: 'path' must be set to a HuggingFace dataset ID")

        log.info("DatasetIngestNode: loading HuggingFace dataset '%s' split='%s'",
                 dataset_id, self.config.hf_split)

        ds = load_dataset(dataset_id, split=self.config.hf_split)

        samples: list[AudioSample] = []
        count = 0

        for row in ds:
            if self.config.limit > 0 and count >= self.config.limit:
                break

            audio_col = self.config.hf_audio_column
            label_col = self.config.hf_label_column

            audio_data = row.get(audio_col)
            if audio_data is None:
                log.warning("DatasetIngestNode: row missing column '%s', skipping", audio_col)
                continue

            # HuggingFace audio column is a dict: {"array": ndarray, "sampling_rate": int, "path": str}
            if isinstance(audio_data, dict):
                y = np.array(audio_data.get("array", []), dtype=np.float32)
                sr = int(audio_data.get("sampling_rate", 16000))
                src_path = audio_data.get("path", "")
            else:
                # Fallback: treat as raw array at 16kHz
                y = np.array(audio_data, dtype=np.float32)
                sr = 16000
                src_path = ""

            label = self.config.label_override or str(row.get(label_col, ""))

            samples.append(AudioSample(
                path=src_path,
                sample_rate=sr,
                data=y,
                label=label,
                metadata={"source": "huggingface", "dataset_id": dataset_id},
            ))
            count += 1

        return samples

    # ── s3 ────────────────────────────────────────────────────────────────────

    def _load_s3(self) -> list[AudioSample]:
        """Scan an S3 bucket/prefix and load matching audio files.

        path format: "s3://bucket-name/prefix/"
        Requires boto3. Each sample gets metadata["s3_key"].
        """
        try:
            import boto3  # type: ignore
        except ImportError:
            raise ImportError(
                "DatasetIngestNode: 'boto3' required for source_type='s3'. "
                "Install with: pip install boto3"
            )

        s3_uri = self.config.path
        if not s3_uri.startswith("s3://"):
            raise ValueError(
                f"DatasetIngestNode: S3 path must start with 's3://', got: {s3_uri}"
            )

        # Parse bucket and prefix from s3://bucket-name/prefix/
        without_scheme = s3_uri[len("s3://"):]
        if "/" in without_scheme:
            bucket, prefix = without_scheme.split("/", 1)
        else:
            bucket = without_scheme
            prefix = ""

        log.info(
            "DatasetIngestNode: scanning S3 bucket='%s' prefix='%s'", bucket, prefix
        )

        s3 = boto3.client("s3")
        paginator = s3.get_paginator("list_objects_v2")

        already_processed = self._load_checkpoint()
        samples: list[AudioSample] = []
        count = 0

        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                if self.config.limit > 0 and count >= self.config.limit:
                    break

                key = obj["Key"]
                if not key.lower().endswith(SUPPORTED_AUDIO_EXTENSIONS):
                    continue

                s3_path = f"s3://{bucket}/{key}"
                if s3_path in already_processed:
                    log.debug("DatasetIngestNode: skipping (checkpoint) '%s'", s3_path)
                    continue

                # Derive label from the last directory component before the filename
                key_parts = key.rstrip("/").split("/")
                if len(key_parts) >= 2:
                    dir_label = key_parts[-2]
                else:
                    dir_label = ""
                label = self.config.label_override or dir_label

                with tempfile.NamedTemporaryFile(
                    suffix=Path(key).suffix, delete=False
                ) as tmp:
                    tmp_path = tmp.name

                try:
                    log.debug("DatasetIngestNode: downloading S3 key '%s'", key)
                    s3.download_file(bucket, key, tmp_path)
                    sample = self._load_file(
                        tmp_path,
                        label,
                        {"s3_key": key, "s3_bucket": bucket},
                    )
                    if sample is not None:
                        # Overwrite path with the canonical S3 URI
                        sample = AudioSample(
                            path=s3_path,
                            sample_rate=sample.sample_rate,
                            data=sample.data,
                            label=sample.label,
                            metadata={**sample.metadata, "s3_key": key},
                        )
                        samples.append(sample)
                        count += 1
                        self._append_checkpoint(s3_path)
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

        return samples

    # ── zip ───────────────────────────────────────────────────────────────────

    def _load_zip(self, zip_path: str) -> list[AudioSample]:
        """Extract ZIP to a temp directory, then scan as filesystem."""
        import zipfile

        zip_path_obj = Path(zip_path)
        if not zip_path_obj.exists():
            raise ValueError(f"DatasetIngestNode: ZIP file not found: {zip_path}")

        with tempfile.TemporaryDirectory() as tmp_dir:
            log.info("DatasetIngestNode: extracting ZIP '%s' to '%s'", zip_path, tmp_dir)
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmp_dir)
            samples = self._load_filesystem(tmp_dir)

        return samples

    # ── tar ───────────────────────────────────────────────────────────────────

    def _load_tar(self, tar_path: str) -> list[AudioSample]:
        """Extract TAR archive to a temp directory, then scan as filesystem.

        Uses a safe member filter to prevent path traversal attacks
        (CVE-2007-4559 pattern).
        """
        import tarfile

        tar_path_obj = Path(tar_path)
        if not tar_path_obj.exists():
            raise ValueError(f"DatasetIngestNode: TAR file not found: {tar_path}")

        def _safe_members(tf: "tarfile.TarFile", dest: str):
            """Yield only members whose resolved path stays inside dest."""
            dest_real = os.path.realpath(dest)
            for member in tf.getmembers():
                member_path = os.path.realpath(os.path.join(dest, member.name))
                if not member_path.startswith(dest_real + os.sep) and member_path != dest_real:
                    log.warning(
                        "DatasetIngestNode: skipping unsafe TAR member '%s'", member.name
                    )
                    continue
                yield member

        with tempfile.TemporaryDirectory() as tmp_dir:
            log.info("DatasetIngestNode: extracting TAR '%s' to '%s'", tar_path, tmp_dir)
            with tarfile.open(tar_path, "r:*") as tf:
                tf.extractall(tmp_dir, members=_safe_members(tf, tmp_dir))
            samples = self._load_filesystem(tmp_dir)

        return samples

    # ── manifest ─────────────────────────────────────────────────────────────

    def _load_manifest(self, manifest_path: str) -> list[AudioSample]:
        """Load from CSV or JSON manifest with columns: path, label."""
        manifest_path_obj = Path(manifest_path)
        if not manifest_path_obj.exists():
            raise ValueError(f"DatasetIngestNode: manifest not found: {manifest_path}")

        suffix = manifest_path_obj.suffix.lower()
        entries: list[dict] = []

        if suffix == ".json":
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                entries = data
            else:
                raise ValueError(
                    "DatasetIngestNode: JSON manifest must be a list of {path, label} dicts"
                )
        elif suffix == ".csv":
            with open(manifest_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                entries = list(reader)
        else:
            raise ValueError(
                f"DatasetIngestNode: unsupported manifest format '{suffix}'. Use .csv or .json"
            )

        already_processed = self._load_checkpoint()
        samples: list[AudioSample] = []
        count = 0

        for entry in entries:
            if self.config.limit > 0 and count >= self.config.limit:
                break

            file_path = entry.get("path", "")
            label = self.config.label_override or entry.get("label", "")

            if not file_path:
                log.warning("DatasetIngestNode: manifest entry missing 'path', skipping: %s", entry)
                continue

            if file_path in already_processed:
                log.debug("DatasetIngestNode: skipping (checkpoint) '%s'", file_path)
                continue

            sample = self._load_file(file_path, label, {"manifest": manifest_path})
            if sample is not None:
                samples.append(sample)
                count += 1
                self._append_checkpoint(file_path)

        return samples

    # ── helpers ───────────────────────────────────────────────────────────────

    def _load_file(
        self,
        file_path: str,
        label: str,
        extra_metadata: dict,
    ) -> AudioSample | None:
        """Load a single audio file with librosa; return None on failure.

        When validate_integrity is True:
        - Computes SHA256 of the raw file bytes and stores in metadata["sha256"]
        - If a sibling .sha256 sidecar file exists, verifies the checksum
        - Returns None (with a warning) on checksum mismatch
        """
        # ── integrity validation ──────────────────────────────────────────────
        if self.config.validate_integrity:
            try:
                raw_bytes = Path(file_path).read_bytes()
            except OSError as exc:
                log.warning(
                    "DatasetIngestNode: cannot read file for integrity check '%s': %s",
                    file_path, exc,
                )
                return None

            sha256_digest = hashlib.sha256(raw_bytes).hexdigest()
            extra_metadata = dict(extra_metadata)  # don't mutate caller's dict
            extra_metadata["sha256"] = sha256_digest

            # Check for a sibling .sha256 sidecar file
            sidecar = Path(file_path).with_suffix(Path(file_path).suffix + ".sha256")
            if sidecar.exists():
                try:
                    expected = sidecar.read_text(encoding="utf-8").strip().split()[0]
                    if sha256_digest != expected:
                        log.warning(
                            "DatasetIngestNode: SHA256 mismatch for '%s' "
                            "(got %s, expected %s) — skipping",
                            file_path, sha256_digest, expected,
                        )
                        return None
                except OSError as exc:
                    log.warning(
                        "DatasetIngestNode: cannot read sidecar '%s': %s", sidecar, exc
                    )

        # ── audio loading ─────────────────────────────────────────────────────
        try:
            y, sr = librosa.load(file_path, sr=None, mono=True)
        except Exception as exc:
            log.warning("DatasetIngestNode: failed to load '%s': %s", file_path, exc)
            return None

        return AudioSample(
            path=file_path,
            sample_rate=sr,
            data=y,
            label=label,
            metadata=extra_metadata,
        )

    def _deduplicate(self, samples: list[AudioSample]) -> list[AudioSample]:
        """Remove duplicate waveforms using an MD5 hash of the data bytes.

        Stores only 32-byte hex strings instead of full waveform arrays,
        avoiding OOM on large datasets.
        """
        seen: set[str] = set()
        unique: list[AudioSample] = []
        for s in samples:
            key = hashlib.md5(s.data.tobytes()).hexdigest()
            if key not in seen:
                seen.add(key)
                unique.append(s)
            else:
                log.debug("DatasetIngestNode: deduplicated sample '%s'", s.path)
        return unique

    # ── resume checkpoint helpers ─────────────────────────────────────────────

    def _load_checkpoint(self) -> set[str]:
        """Load the set of already-processed paths from the checkpoint file.

        Checkpoint format: one absolute path per line (append-only log).
        Returns an empty set if resume_from is not set or the file does not exist.
        """
        if not self.config.resume_from:
            return set()
        checkpoint_path = Path(self.config.resume_from)
        if not checkpoint_path.exists():
            return set()
        try:
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                return {line.rstrip("\n") for line in f if line.strip()}
        except OSError as exc:
            log.warning(
                "DatasetIngestNode: failed to read checkpoint '%s': %s — starting fresh",
                checkpoint_path, exc,
            )
        return set()

    def _append_checkpoint(self, file_path: str) -> None:
        """Append a single processed path to the checkpoint file (O(1) per write).

        Uses an append-only line-per-path format — no full-file rewrite needed.
        Does nothing if resume_from is not configured.
        """
        if not self.config.resume_from:
            return
        checkpoint_path = Path(self.config.resume_from)
        try:
            with open(checkpoint_path, "a", encoding="utf-8") as f:
                f.write(file_path + "\n")
        except OSError as exc:
            log.warning(
                "DatasetIngestNode: failed to append checkpoint '%s': %s",
                checkpoint_path, exc,
            )
