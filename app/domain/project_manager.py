# app/domain/project_manager.py
"""
Bounded Context:  Domain — Project Management
Responsibility:   Full project lifecycle for audio dataset projects stored
                  under workspace/datasets/output/{project}/.
Owns:             ProjectManager class — create, get, update, delete, clone,
                  list versions, taxonomy, contract, spec, annotations,
                  quality reports, snapshots, curation decisions.
Public Surface:   ProjectManager (all methods)
Must NOT:         Import from app.core.nodes, app.core.orchestrator, or
                  app.core.executor. Must not register node types.
Dependencies:     app.core.config (datasets_output_dir), stdlib (csv,
                  datetime, hashlib, io, json, pathlib, shutil, uuid).
Reason To Change: Project schema changes, new project-level operation added,
                  or storage layout changes.
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import io
import json
import os
import random
import re
import shutil
import struct
import wave
from pathlib import Path
from typing import Any

from app.core.config import project_dir as _project_dir

class ProjectManager:
    @property
    def BASE(self):
        return _project_dir() / "datasets" / "output"

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    # G3-30: regex for safe project names used as directory components
    _SAFE_NAME_RE = re.compile(r'^[\w\-]{1,128}$')

    @classmethod
    def _validate_name(cls, name: str) -> None:
        """Raise ValueError if name is not safe for use as a directory component (G3-30 fix)."""
        if not cls._SAFE_NAME_RE.match(name):
            raise ValueError(
                f"Invalid project name {name!r}. "
                "Names must contain only letters, digits, hyphens, and underscores "
                "(1–128 characters)."
            )

    def _project_dir(self, name: str) -> Path:
        return self.BASE / name

    def _require_project(self, name: str) -> Path:
        d = self._project_dir(name)
        if not d.exists():
            raise FileNotFoundError(f"Project '{name}' not found")
        return d

    @staticmethod
    def _now() -> str:
        """Return current UTC time as an ISO 8601 string with timezone info (B-32 fix)."""
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    # ------------------------------------------------------------------ #
    # Project lifecycle                                                    #
    # ------------------------------------------------------------------ #

    def create(self, name: str) -> dict:
        """Create a new project directory and project.json."""
        self._validate_name(name)
        d = self._project_dir(name)
        if d.exists():
            raise ValueError(f"Project '{name}' already exists")
        d.mkdir(parents=True, exist_ok=True)
        now = self._now()
        meta = {
            "name": name,
            "status": "draft",
            "created_at": now,
            "updated_at": now,
            "versions": [],
        }
        self._write_json(d / "project.json", meta)
        return meta

    def rename(self, name: str, new_name: str) -> dict:
        """Move project directory and update project.json name field."""
        self._validate_name(name)
        self._validate_name(new_name)
        src = self._require_project(name)
        dst = self._project_dir(new_name)
        if dst.exists():
            raise ValueError(f"Project '{new_name}' already exists")
        shutil.move(str(src), str(dst))
        proj_file = dst / "project.json"
        meta = self._read_json(proj_file, {})
        meta["name"] = new_name
        meta["updated_at"] = self._now()
        self._write_json(proj_file, meta)
        return meta

    def delete(self, name: str, confirm: str) -> None:
        """Remove project directory; confirm must equal name."""
        self._validate_name(name)
        if confirm != name:
            raise ValueError(
                f"Confirmation string '{confirm}' does not match project name '{name}'"
            )
        d = self._require_project(name)
        shutil.rmtree(str(d))

    def set_status(self, name: str, status: str) -> dict:
        """Update project status field."""
        valid = {"draft", "in-progress", "ready", "archived"}
        if status not in valid:
            raise ValueError(
                f"Invalid status '{status}'. Must be one of: {', '.join(sorted(valid))}"
            )
        d = self._require_project(name)
        proj_file = d / "project.json"
        meta = self._read_json(proj_file, {})
        meta["status"] = status
        meta["updated_at"] = self._now()
        self._write_json(proj_file, meta)
        return meta

    def clone(self, name: str, new_name: str) -> dict:
        """Copy metadata files only (no version subdirs or audio files)."""
        self._validate_name(name)
        self._validate_name(new_name)
        src = self._require_project(name)
        dst = self._project_dir(new_name)
        if dst.exists():
            raise ValueError(f"Project '{new_name}' already exists")
        dst.mkdir(parents=True, exist_ok=True)

        # Copy metadata files only
        for fname in ("taxonomy.json", "contract.json", "spec.md"):
            src_file = src / fname
            if src_file.exists():
                shutil.copy2(str(src_file), str(dst / fname))

        # Create fresh project.json for the clone
        now = self._now()
        meta = {
            "name": new_name,
            "status": "draft",
            "created_at": now,
            "updated_at": now,
            "versions": [],
        }
        self._write_json(dst / "project.json", meta)
        return meta

    def list_all(self) -> list[dict]:
        """Return list of all project.json contents."""
        self.BASE.mkdir(parents=True, exist_ok=True)
        result = []
        for d in sorted(self.BASE.iterdir()):
            if d.is_dir():
                proj_file = d / "project.json"
                if proj_file.exists():
                    result.append(self._read_json(proj_file, {}))
        return result

    # ------------------------------------------------------------------ #
    # Taxonomy                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate_taxonomy_siblings(nodes: list[dict], path: str = "") -> None:
        """Recursively validate that sibling names are unique."""
        seen: set[str] = set()
        for node in nodes:
            node_name = node.get("name", "")
            if node_name in seen:
                location = f" at {path}" if path else ""
                raise ValueError(
                    f"Duplicate sibling taxonomy name '{node_name}'{location}"
                )
            seen.add(node_name)
            children = node.get("children", [])
            if children:
                child_path = f"{path}/{node_name}" if path else node_name
                ProjectManager._validate_taxonomy_siblings(children, child_path)

    def set_taxonomy(self, name: str, tree: list[dict]) -> None:
        """Write taxonomy.json; validate sibling-scope uniqueness."""
        self._require_project(name)
        self._validate_taxonomy_siblings(tree)
        d = self._project_dir(name)
        self._write_json(d / "taxonomy.json", tree)

    def get_taxonomy(self, name: str) -> list[dict]:
        """Read taxonomy.json; return [] if not found."""
        self._require_project(name)
        d = self._project_dir(name)
        return self._read_json(d / "taxonomy.json", [])

    # ------------------------------------------------------------------ #
    # Contract                                                             #
    # ------------------------------------------------------------------ #

    def set_contract(self, name: str, contract: dict) -> None:
        """Write contract.json; validate min_duration_ms < max_duration_ms."""
        self._require_project(name)
        min_ms = contract.get("min_duration_ms")
        max_ms = contract.get("max_duration_ms")
        if min_ms is not None and max_ms is not None:
            if min_ms >= max_ms:
                raise ValueError(
                    f"min_duration_ms ({min_ms}) must be less than max_duration_ms ({max_ms})"
                )
        d = self._project_dir(name)
        self._write_json(d / "contract.json", contract)

    def get_contract(self, name: str) -> dict:
        """Read contract.json; return {} if not found."""
        self._require_project(name)
        d = self._project_dir(name)
        return self._read_json(d / "contract.json", {})

    # ------------------------------------------------------------------ #
    # Spec                                                                 #
    # ------------------------------------------------------------------ #

    def set_spec(self, name: str, markdown: str) -> None:
        """Write spec.md."""
        self._require_project(name)
        d = self._project_dir(name)
        spec_file = d / "spec.md"
        spec_file.write_text(markdown, encoding="utf-8")

    def get_spec(self, name: str) -> str:
        """Read spec.md; return '' if not found."""
        self._require_project(name)
        d = self._project_dir(name)
        spec_file = d / "spec.md"
        if not spec_file.exists():
            return ""
        return spec_file.read_text(encoding="utf-8")

    # ------------------------------------------------------------------ #
    # Annotations                                                          #
    # ------------------------------------------------------------------ #

    def _annotations_path(self, name: str) -> Path:
        return self._project_dir(name) / "annotations.jsonl"

    def _read_annotations_dict(self, name: str) -> dict[str, dict]:
        """Read annotations.jsonl into a dict keyed by sample_path."""
        path = self._annotations_path(name)
        result: dict[str, dict] = {}
        if not path.exists():
            return result
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        obj = json.loads(line)
                        sp = obj.get("sample_path")
                        if sp:
                            result[sp] = obj
                    except json.JSONDecodeError:
                        pass
        return result

    def _write_annotations_dict(self, name: str, data: dict[str, dict]) -> None:
        path = self._annotations_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for obj in data.values():
                f.write(json.dumps(obj) + "\n")

    def add_annotations(self, name: str, annotations: list[dict]) -> None:
        """Append/overwrite to annotations.jsonl (overwrite existing for same sample_path)."""
        self._require_project(name)
        existing = self._read_annotations_dict(name)
        for ann in annotations:
            sp = ann.get("sample_path")
            if sp:
                existing[sp] = ann
        self._write_annotations_dict(name, existing)

    def get_annotations(self, name: str) -> list[dict]:
        """Read all annotations.jsonl lines."""
        self._require_project(name)
        return list(self._read_annotations_dict(name).values())

    def export_annotations(self, name: str, fmt: str) -> str:
        """Return JSONL string or CSV string."""
        self._require_project(name)
        annotations = list(self._read_annotations_dict(name).values())

        if fmt == "jsonl":
            return "\n".join(json.dumps(a) for a in annotations)

        if fmt == "csv":
            output = io.StringIO()
            fieldnames = ["sample_path", "label", "start_ms", "end_ms", "annotator"]
            writer = csv.DictWriter(
                output, fieldnames=fieldnames, extrasaction="ignore"
            )
            writer.writeheader()
            for ann in annotations:
                row = {f: ann.get(f, "") for f in fieldnames}
                writer.writerow(row)
            return output.getvalue()

        raise ValueError(f"Unsupported format '{fmt}'. Use 'jsonl' or 'csv'.")

    def import_annotations(
        self, name: str, content: str, fmt: str
    ) -> dict:
        """Parse JSONL or CSV, validate, merge into annotations.jsonl."""
        self._require_project(name)
        records: list[dict] = []
        errors: list[str] = []

        if fmt == "jsonl":
            for i, line in enumerate(content.splitlines(), start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    records.append(obj)
                except json.JSONDecodeError as e:
                    errors.append(f"Line {i}: JSON parse error — {e}")

        elif fmt == "csv":
            reader = csv.DictReader(io.StringIO(content))
            for i, row in enumerate(reader, start=2):  # row 1 is header
                records.append(dict(row))

        else:
            raise ValueError(f"Unsupported format '{fmt}'. Use 'jsonl' or 'csv'.")

        valid: list[dict] = []
        invalid: list[dict] = []
        for rec in records:
            if rec.get("sample_path") and rec.get("label"):
                valid.append(rec)
            else:
                invalid.append(rec)
                errors.append(
                    f"Record missing sample_path or label: {json.dumps(rec)}"
                )

        if valid:
            self.add_annotations(name, valid)

        return {
            "imported": len(valid),
            "invalid": len(invalid),
            "errors": errors,
        }

    def validate_annotations(self, name: str) -> dict:
        """Return {total_samples, annotated_count, unannotated_count, missing_labels}."""
        self._require_project(name)
        d = self._project_dir(name)

        # Collect all WAV files across version dirs and working area
        all_wav: set[str] = set()
        for wav in d.rglob("*.wav"):
            # Use path relative to project dir
            rel = str(wav.relative_to(d))
            all_wav.add(rel)

        annotations = self._read_annotations_dict(name)
        annotated = set(annotations.keys())

        # Samples that appear in WAV files but have no annotation
        missing = sorted(all_wav - annotated)

        total = len(all_wav)
        annotated_count = len(all_wav & annotated)
        unannotated_count = len(missing)

        return {
            "total_samples": total,
            "annotated_count": annotated_count,
            "unannotated_count": unannotated_count,
            "missing_labels": missing,
        }

    def bulk_annotate(self, name: str, paths: list[str], label: str) -> None:
        """Assign label to all specified paths as whole-file annotations."""
        self._require_project(name)
        annotations = [
            {"sample_path": p, "label": label, "start_ms": None, "end_ms": None}
            for p in paths
        ]
        self.add_annotations(name, annotations)

    # ------------------------------------------------------------------ #
    # Curation                                                             #
    # ------------------------------------------------------------------ #

    def _curation_path(self, name: str) -> Path:
        return self._project_dir(name) / "curation_decisions.json"

    def add_curation_decision(self, name: str, path: str, decision: str) -> None:
        """Write to curation_decisions.json."""
        self._require_project(name)
        curation_file = self._curation_path(name)
        data: dict = self._read_json(curation_file, {})
        data[path] = {"decision": decision, "timestamp": self._now()}
        self._write_json(curation_file, data)

    def get_curation_decisions(self, name: str) -> list[dict]:
        """Read curation_decisions.json as a list of dicts."""
        self._require_project(name)
        curation_file = self._curation_path(name)
        data: dict = self._read_json(curation_file, {})
        result = []
        for sample_path, info in data.items():
            result.append({"sample_path": sample_path, **info})
        return result

    # ------------------------------------------------------------------ #
    # Versions                                                             #
    # ------------------------------------------------------------------ #

    _VERSION_RE = re.compile(r"^v\d+(\.\d+)*$")

    def _is_version_dir(self, d: Path) -> bool:
        return d.is_dir() and bool(self._VERSION_RE.match(d.name))

    def list_versions(self, name: str) -> list[dict]:
        """List subdirs that look like versions (v1, v1.0.0, etc.)."""
        d = self._require_project(name)
        versions = []
        for sub in sorted(d.iterdir()):
            if self._is_version_dir(sub):
                meta_file = sub / "metadata.json"
                meta = self._read_json(meta_file, {})
                versions.append({"version": sub.name, **meta})
        return versions

    def restore_version(self, name: str, version: str) -> None:
        """Copy version dir contents back to project root working area.

        Uses a temp directory + atomic rename so the project is never left in
        a partially-restored state if the copy fails midway (B-33 fix).
        """
        import uuid as _uuid
        d = self._require_project(name)
        version_dir = d / version
        if not version_dir.exists():
            raise FileNotFoundError(
                f"Version '{version}' not found in project '{name}'"
            )
        # Stage into a temp dir first, then atomically move each item
        tmp_dir = d.parent / f".restore_tmp_{_uuid.uuid4().hex[:8]}"
        try:
            tmp_dir.mkdir(parents=True, exist_ok=True)
            for item in version_dir.iterdir():
                dst_tmp = tmp_dir / item.name
                if item.is_file():
                    shutil.copy2(str(item), str(dst_tmp))
                elif item.is_dir():
                    shutil.copytree(str(item), str(dst_tmp))
            # All copies succeeded — now atomically replace in project root
            for item in tmp_dir.iterdir():
                dst = d / item.name
                if dst.exists():
                    if dst.is_dir():
                        shutil.rmtree(str(dst))
                    else:
                        dst.unlink()
                shutil.move(str(item), str(dst))
        except Exception:
            shutil.rmtree(str(tmp_dir), ignore_errors=True)
            raise
        else:
            shutil.rmtree(str(tmp_dir), ignore_errors=True)

    def get_lineage(self, name: str, version: str) -> dict:
        """Read {version}/lineage.json."""
        d = self._require_project(name)
        lineage_file = d / version / "lineage.json"
        return self._read_json(lineage_file, {})

    # ------------------------------------------------------------------ #
    # Snapshots                                                            #
    # ------------------------------------------------------------------ #

    def _snapshots_dir(self, name: str) -> Path:
        return self._project_dir(name) / "snapshots"

    def create_snapshot(self, name: str, snapshot_name: str) -> None:
        """Copy current working files to snapshots/{snapshot_name}/."""
        d = self._require_project(name)
        snap_dir = self._snapshots_dir(name) / snapshot_name
        snap_dir.mkdir(parents=True, exist_ok=True)

        # Copy working files (not version dirs, not snapshots dir itself)
        for item in d.iterdir():
            if item.name == "snapshots":
                continue
            if self._is_version_dir(item):
                continue
            dst = snap_dir / item.name
            if item.is_file():
                shutil.copy2(str(item), str(dst))
            elif item.is_dir():
                if dst.exists():
                    shutil.rmtree(str(dst))
                shutil.copytree(str(item), str(dst))

    def list_snapshots(self, name: str) -> list[dict]:
        """List snapshots/ subdirs."""
        self._require_project(name)
        snaps_dir = self._snapshots_dir(name)
        if not snaps_dir.exists():
            return []
        result = []
        for sub in sorted(snaps_dir.iterdir()):
            if sub.is_dir():
                result.append({"snapshot_name": sub.name})
        return result

    def restore_snapshot(self, name: str, snapshot_name: str) -> None:
        """Copy snapshot files back to project root.

        Uses a temp directory + atomic move so the project is never left in
        a partially-restored state if the copy fails midway (B-33 fix).
        """
        import uuid as _uuid
        d = self._require_project(name)
        snap_dir = self._snapshots_dir(name) / snapshot_name
        if not snap_dir.exists():
            raise FileNotFoundError(
                f"Snapshot '{snapshot_name}' not found in project '{name}'"
            )
        tmp_dir = d.parent / f".restore_tmp_{_uuid.uuid4().hex[:8]}"
        try:
            tmp_dir.mkdir(parents=True, exist_ok=True)
            for item in snap_dir.iterdir():
                dst_tmp = tmp_dir / item.name
                if item.is_file():
                    shutil.copy2(str(item), str(dst_tmp))
                elif item.is_dir():
                    shutil.copytree(str(item), str(dst_tmp))
            # All copies succeeded — atomically replace in project root
            for item in tmp_dir.iterdir():
                dst = d / item.name
                if dst.exists():
                    if dst.is_dir():
                        shutil.rmtree(str(dst))
                    else:
                        dst.unlink()
                shutil.move(str(item), str(dst))
        except Exception:
            shutil.rmtree(str(tmp_dir), ignore_errors=True)
            raise
        else:
            shutil.rmtree(str(tmp_dir), ignore_errors=True)

    # ------------------------------------------------------------------ #
    # Dataset operations                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _read_labels_csv(path: Path) -> dict[str, str]:
        """Read labels.csv → {filename: label}."""
        if not path.exists():
            return {}
        result: dict[str, str] = {}
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                fname = row.get("filename") or row.get("file") or ""
                label = row.get("label") or ""
                if fname:
                    result[fname] = label
        return result

    def diff_versions(self, name: str, version_a: str, version_b: str) -> dict:
        """Compare labels.csv files, return {added, removed, changed} sample counts."""
        d = self._require_project(name)
        labels_a = self._read_labels_csv(d / version_a / "labels.csv")
        labels_b = self._read_labels_csv(d / version_b / "labels.csv")

        keys_a = set(labels_a.keys())
        keys_b = set(labels_b.keys())

        added = len(keys_b - keys_a)
        removed = len(keys_a - keys_b)
        changed = sum(
            1
            for k in keys_a & keys_b
            if labels_a[k] != labels_b[k]
        )

        return {"added": added, "removed": removed, "changed": changed}

    @staticmethod
    def _wav_info(wav_path: Path) -> tuple[float, int]:
        """Return (duration_s, sample_rate) for a WAV file in a single open (B-35 fix)."""
        try:
            with wave.open(str(wav_path), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                duration = frames / rate if rate > 0 else 0.0
                return duration, rate
        except Exception:
            return 0.0, 0

    @staticmethod
    def _wav_duration_s(wav_path: Path) -> float:
        """Return duration in seconds for a WAV file."""
        duration, _ = ProjectManager._wav_info(wav_path)
        return duration

    @staticmethod
    def _wav_sample_rate(wav_path: Path) -> int:
        """Return sample rate for a WAV file."""
        _, rate = ProjectManager._wav_info(wav_path)
        return rate

    def get_stats(self, name: str, version: str) -> dict:
        """Compute stats from version dir including histograms and class imbalance."""
        d = self._require_project(name)
        version_dir = d / version
        if not version_dir.exists():
            raise FileNotFoundError(
                f"Version '{version}' not found in project '{name}'"
            )

        wav_files = list(version_dir.rglob("*.wav"))
        total_samples = len(wav_files)
        total_duration_s = 0.0
        label_distribution: dict[str, int] = {}
        sample_rate_distribution: dict[str, int] = {}
        durations: list[float] = []
        snr_values: list[float] = []

        for wav in wav_files:
            dur, sr = self._wav_info(wav)
            total_duration_s += dur
            durations.append(dur)
            sr_key = str(sr)
            sample_rate_distribution[sr_key] = (
                sample_rate_distribution.get(sr_key, 0) + 1
            )

            # Infer label from directory structure: split/label/file.wav
            parts = wav.relative_to(version_dir).parts
            if len(parts) >= 2:
                label = parts[-2]
            else:
                label = "unknown"
            label_distribution[label] = label_distribution.get(label, 0) + 1

            # Estimate SNR from first 100ms as noise profile
            snr = self._estimate_snr(wav, sr)
            snr_values.append(snr)

        # Build histograms
        duration_histogram = self._build_histogram(
            durations, n_bins=10, unit="s", fmt=".1f"
        )
        snr_histogram = self._build_histogram(
            snr_values, n_bins=10, unit="dB", fmt=".0f"
        )

        # Class imbalance detection
        class_imbalance_warning = False
        imbalanced_labels: list[str] = []
        if len(label_distribution) >= 2:
            counts = list(label_distribution.values())
            max_count = max(counts)
            min_count = min(counts)
            if min_count > 0 and max_count / min_count > 5:
                class_imbalance_warning = True
                mean_count = sum(counts) / len(counts)
                imbalanced_labels = [
                    lbl
                    for lbl, cnt in label_distribution.items()
                    if cnt < mean_count * 0.2
                ]

        return {
            "total_samples": total_samples,
            "total_duration_s": round(total_duration_s, 3),
            "label_distribution": label_distribution,
            "sample_rate_distribution": sample_rate_distribution,
            "duration_histogram": duration_histogram,
            "snr_histogram": snr_histogram,
            "class_imbalance_warning": class_imbalance_warning,
            "imbalanced_labels": imbalanced_labels,
        }

    @staticmethod
    def _estimate_snr(wav_path: Path, sample_rate: int) -> float:
        """Estimate SNR using first 100ms as noise profile. Returns dB value.

        Supports 16-bit, 24-bit, and 32-bit PCM WAV files. For unsupported
        bit depths a warning is logged and 20.0 dB is returned as a fallback
        (B-34 fix — previously silently returned 20.0 for all non-16-bit files).
        """
        import math
        import logging as _logging
        _log = _logging.getLogger(__name__)
        try:
            with wave.open(str(wav_path), "rb") as wf:
                n_channels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                framerate = wf.getframerate()
                n_frames = wf.getnframes()

                # Read first 100ms as noise profile
                noise_frames = min(int(framerate * 0.1), n_frames)
                raw_noise = wf.readframes(noise_frames)
                # Read rest as signal
                raw_signal = wf.readframes(n_frames - noise_frames)

            def _unpack_samples(raw: bytes, sampwidth: int) -> list[float]:
                """Unpack raw PCM bytes to a list of float samples."""
                if sampwidth == 2:
                    n = len(raw) // 2
                    return list(struct.unpack(f"{n}h", raw))
                elif sampwidth == 3:
                    # 24-bit: 3 bytes per sample, little-endian signed
                    samples = []
                    for i in range(0, len(raw) - 2, 3):
                        val = raw[i] | (raw[i + 1] << 8) | (raw[i + 2] << 16)
                        if val >= 0x800000:
                            val -= 0x1000000
                        samples.append(float(val))
                    return samples
                elif sampwidth == 4:
                    n = len(raw) // 4
                    return [float(x) for x in struct.unpack(f"{n}i", raw)]
                else:
                    return []

            noise_samples = _unpack_samples(raw_noise, sampwidth)
            signal_samples = _unpack_samples(raw_signal, sampwidth) if raw_signal else []

            if not noise_samples:
                if sampwidth not in (2, 3, 4):
                    _log.warning(
                        "_estimate_snr: unsupported sample width %d bytes in %s — returning 20.0 dB fallback",
                        sampwidth, wav_path.name,
                    )
                return 20.0

            # Average channels to mono
            if n_channels > 1:
                noise_arr = [
                    sum(noise_samples[i:i + n_channels]) / n_channels
                    for i in range(0, len(noise_samples), n_channels)
                ]
                signal_arr = [
                    sum(signal_samples[i:i + n_channels]) / n_channels
                    for i in range(0, len(signal_samples), n_channels)
                ] if signal_samples else [0.0]
            else:
                noise_arr = noise_samples
                signal_arr = signal_samples if signal_samples else [0.0]

            noise_rms = (sum(x ** 2 for x in noise_arr) / max(len(noise_arr), 1)) ** 0.5
            signal_rms = (sum(x ** 2 for x in signal_arr) / max(len(signal_arr), 1)) ** 0.5

            if noise_rms < 1e-6:
                return 60.0  # very clean signal

            return round(20.0 * math.log10(max(signal_rms / noise_rms, 1e-6)), 1)
        except Exception:
            return 20.0  # fallback

    @staticmethod
    def _build_histogram(
        values: list[float], n_bins: int, unit: str, fmt: str
    ) -> list[dict]:
        """Build equal-width histogram bins from a list of float values."""
        if not values:
            return []
        min_val = min(values)
        max_val = max(values)
        if max_val == min_val:
            # All values identical — single bin
            label = f"{min_val:{fmt}}{unit}"
            return [{"bin": label, "count": len(values)}]

        bin_width = (max_val - min_val) / n_bins
        bins: list[dict] = []
        for i in range(n_bins):
            lo = min_val + i * bin_width
            hi = min_val + (i + 1) * bin_width
            count = sum(1 for v in values if lo <= v < hi)
            # Last bin is inclusive on right edge
            if i == n_bins - 1:
                count = sum(1 for v in values if lo <= v <= hi)
            label = f"{lo:{fmt}}–{hi:{fmt}}{unit}"
            bins.append({"bin": label, "count": count})
        return bins

    def list_samples(
        self,
        name: str,
        version: str,
        filters: dict,
        page: int,
        page_size: int,
    ) -> dict:
        """List WAV files with pagination and optional label/split filters."""
        d = self._require_project(name)
        version_dir = d / version
        if not version_dir.exists():
            raise FileNotFoundError(
                f"Version '{version}' not found in project '{name}'"
            )

        filter_label = filters.get("label") if filters else None
        filter_split = filters.get("split") if filters else None

        # G3-26 fix: collect paths first (cheap), paginate, then read metadata
        # only for the page slice — avoids O(N) file opens per page request.
        all_wavs = []
        for wav in sorted(version_dir.rglob("*.wav")):
            parts = wav.relative_to(version_dir).parts
            split = parts[0] if len(parts) >= 3 else ""
            label = parts[1] if len(parts) >= 3 else (parts[0] if len(parts) >= 2 else "")
            if filter_label and label != filter_label:
                continue
            if filter_split and split != filter_split:
                continue
            all_wavs.append((wav, split, label))

        total = len(all_wavs)
        start = (page - 1) * page_size
        end = start + page_size
        page_wavs = all_wavs[start:end]

        # Read WAV metadata only for the page slice
        page_items = []
        for wav, split, label in page_wavs:
            page_items.append(
                {
                    "path": str(wav.relative_to(d)),
                    "filename": wav.name,
                    "split": split,
                    "label": label,
                    "duration_s": self._wav_duration_s(wav),
                    "sample_rate": self._wav_sample_rate(wav),
                }
            )

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": page_items,
        }

    def random_samples(
        self,
        name: str,
        version: str,
        n: int,
        seed: int | None,
    ) -> list[dict]:
        """Return n random samples."""
        result = self.list_samples(name, version, {}, 1, 10**9)
        items = result["items"]
        rng = random.Random(seed)
        chosen = rng.sample(items, min(n, len(items)))
        return chosen

    @staticmethod
    def _sha256_wav(wav_path: Path) -> str:
        """Compute SHA-256 of raw WAV bytes."""
        h = hashlib.sha256()
        with wav_path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def deduplicate(self, name: str, version: str, mode: str) -> dict:
        """Find duplicate WAV files by SHA-256 hash."""
        d = self._require_project(name)
        version_dir = d / version
        if not version_dir.exists():
            raise FileNotFoundError(
                f"Version '{version}' not found in project '{name}'"
            )

        hash_to_files: dict[str, list[Path]] = {}
        for wav in sorted(version_dir.rglob("*.wav")):
            h = self._sha256_wav(wav)
            hash_to_files.setdefault(h, []).append(wav)

        duplicates: list[dict] = []
        removed = 0
        for h, files in hash_to_files.items():
            if len(files) > 1:
                # Keep first, rest are duplicates
                for dup in files[1:]:
                    duplicates.append(
                        {
                            "original": str(files[0].relative_to(d)),
                            "duplicate": str(dup.relative_to(d)),
                            "hash": h,
                        }
                    )
                    if mode == "remove":
                        dup.unlink()
                        removed += 1

        return {
            "duplicates_found": len(duplicates),
            "removed": removed,
            "duplicates": duplicates if mode == "report" else [],
        }

    # ------------------------------------------------------------------ #
    # Export gate and quality report export                                #
    # ------------------------------------------------------------------ #

    def get_export_gate(self, name: str) -> dict:
        """Return export readiness based on quality_report.json.

        Returns:
            {can_export: bool, blocking_issues: list[dict], reason: str}
        """
        self._require_project(name)
        d = self._project_dir(name)
        report_path = d / "quality_report.json"

        if not report_path.exists():
            return {
                "can_export": False,
                "blocking_issues": [],
                "reason": "no_report",
            }

        report = self._read_json(report_path, {})
        findings = report.get("findings", [])
        blocking = [f for f in findings if f.get("severity") == "error"]
        return {
            "can_export": len(blocking) == 0,
            "blocking_issues": blocking,
            "reason": "ok" if len(blocking) == 0 else "blocking_errors",
        }

    def export_quality_report(self, name: str, fmt: str) -> str:
        """Serialize quality_report.json as JSON or CSV string.

        Args:
            name: project name
            fmt: "json" or "csv"

        Returns:
            Serialized string

        Raises:
            FileNotFoundError: if quality_report.json does not exist
            ValueError: if fmt is not "json" or "csv"
        """
        self._require_project(name)
        d = self._project_dir(name)
        report_path = d / "quality_report.json"

        if not report_path.exists():
            raise FileNotFoundError(
                f"No quality report found for project '{name}'. Run quality checks first."
            )

        report = self._read_json(report_path, {})

        if fmt == "json":
            return json.dumps(report, indent=2)

        if fmt == "csv":
            findings = report.get("findings", [])
            output = io.StringIO()
            fieldnames = ["sample_path", "check_name", "severity", "detail"]
            writer = csv.DictWriter(
                output, fieldnames=fieldnames, extrasaction="ignore"
            )
            writer.writeheader()
            for finding in findings:
                row = {f: finding.get(f, "") for f in fieldnames}
                writer.writerow(row)
            return output.getvalue()

        raise ValueError(
            f"Unsupported format '{fmt}'. Use 'json' or 'csv'."
        )

    def generate_dataset_card(self, name: str, version: str) -> str:
        """Generate README.md markdown with stats, label distribution, citation template."""
        d = self._require_project(name)
        proj_meta = self._read_json(d / "project.json", {})
        spec_text = self.get_spec(name)

        try:
            stats = self.get_stats(name, version)
        except FileNotFoundError:
            stats = {
                "total_samples": 0,
                "total_duration_s": 0.0,
                "label_distribution": {},
                "sample_rate_distribution": {},
            }

        label_dist = stats.get("label_distribution", {})
        sr_dist = stats.get("sample_rate_distribution", {})

        label_rows = "\n".join(
            f"| {label} | {count} |"
            for label, count in sorted(label_dist.items())
        )
        sr_rows = "\n".join(
            f"| {sr} Hz | {count} |"
            for sr, count in sorted(sr_dist.items())
        )

        card = f"""# {name} — {version}

## Dataset Summary

- **Project:** {name}
- **Version:** {version}
- **Status:** {proj_meta.get('status', 'unknown')}
- **Total Samples:** {stats['total_samples']}
- **Total Duration:** {stats['total_duration_s']:.1f} s
- **Created:** {proj_meta.get('created_at', 'unknown')}

## Dataset Specification

{spec_text if spec_text else '_No specification provided._'}

## Label Distribution

| Label | Count |
|-------|-------|
{label_rows if label_rows else '| — | — |'}

## Sample Rate Distribution

| Sample Rate | Count |
|-------------|-------|
{sr_rows if sr_rows else '| — | — |'}

## Citation

```bibtex
@dataset{{{name}_{version},
  title = {{{name}}},
  version = {{{version}}},
  year = {{{datetime.datetime.utcnow().year}}},
}}
```
"""
        return card
