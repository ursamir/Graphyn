"""
Ingestion service for downloading audio from URLs or HuggingFace datasets.

Supports:
- URL-based ingestion: download files to workspace/datasets/input/{label}/
- HuggingFace dataset ingestion: stream and save audio samples
"""

import threading
import time
import uuid
from pathlib import Path
from pydantic import BaseModel, Field, PrivateAttr
from typing import Generator, Optional
from urllib.parse import urlparse

import logging
import os
import re as _re

logger = logging.getLogger(__name__)

# G3-23: regex for sanitizing label strings used as directory names
_SAFE_LABEL_RE = _re.compile(r'[^\w\-]')


def _sanitize_label(label: str) -> str:
    """Sanitize a label string for safe use as a directory name.

    Strips any character that is not alphanumeric, hyphen, or underscore.
    Truncates to 64 characters. Returns 'default' if the result is empty.

    G3-23 fix: prevents path traversal via untrusted label values.
    """
    sanitized = _SAFE_LABEL_RE.sub('_', label)[:64]
    return sanitized if sanitized else "default"


# Supported audio extensions for URL ingestion
SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}

# Maximum number of completed jobs to keep in memory (B-29 fix)
_MAX_COMPLETED_JOBS = 200

# Module-level job store and its lock
# SCALABILITY NOTE (BUG-10 / SCALE-2):
# _jobs is process-local. In a multi-worker deployment (e.g. uvicorn --workers N),
# a job started on worker A cannot be streamed from worker B. The SSE stream
# endpoint will return 404 if routed to a different worker.
# Migration path: replace _jobs with a Redis-backed store (same interface).
_jobs: dict[str, "IngestionJob"] = {}
_jobs_lock = threading.Lock()

from app.core.config import datasets_input_dir as _datasets_input_dir


class IngestionJob(BaseModel):
    """Tracks the state and progress of a single ingestion job.

    Uses Pydantic ``PrivateAttr`` for the threading lock so the lock is
    never serialized and Pydantic's field-assignment guard is not bypassed
    (B-30 fix — replaces the previous ``object.__setattr__`` workaround).
    """

    job_id: str
    status: str  # "running" | "completed" | "failed"
    progress: list[dict] = Field(default_factory=list)

    # Private lock — not a Pydantic field, never serialized
    _lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)

    model_config = {"arbitrary_types_allowed": True}

    def append_progress(self, event: dict) -> None:
        """Thread-safe append to the progress list."""
        with self._lock:
            self.progress.append(event)

    def set_status(self, status: str) -> None:
        """Thread-safe status update (G3-22 fix)."""
        with self._lock:
            self.status = status

    def read_progress(self) -> list[dict]:
        """Return a snapshot of the progress list (thread-safe)."""
        with self._lock:
            return list(self.progress)


def _register_job(job: "IngestionJob") -> None:
    """Add a job to the store, evicting old completed jobs if over the limit (B-29 fix)."""
    with _jobs_lock:
        _jobs[job.job_id] = job
        # Evict oldest completed/failed jobs when over the limit
        if len(_jobs) > _MAX_COMPLETED_JOBS:
            to_remove = [
                jid for jid, j in _jobs.items()
                if j.status in ("completed", "failed") and jid != job.job_id
            ]
            # Remove oldest first (dict insertion order is preserved in Python 3.7+)
            for jid in to_remove[:len(_jobs) - _MAX_COMPLETED_JOBS]:
                del _jobs[jid]


class IngestionService:
    @property
    def BASE_INPUT(self):
        return _datasets_input_dir()

    # ------------------------------------------------------------------
    # URL ingestion
    # ------------------------------------------------------------------

    def start_url_job(self, urls: list[str], label: str) -> str:
        """Start a background job to download each URL into workspace/datasets/input/{label}/.

        Returns the job_id immediately.
        """
        job_id = uuid.uuid4().hex
        job = IngestionJob(job_id=job_id, status="running")
        _register_job(job)

        thread = threading.Thread(
            target=self._run_url_job,
            args=(job, urls, label),
            daemon=True,
        )
        thread.start()
        return job_id

    def _run_url_job(self, job: IngestionJob, urls: list[str], label: str) -> None:
        """Background worker: download each URL, validate, and check for corruption."""
        try:
            import httpx
        except ImportError:
            job.append_progress({
                "type": "error",
                "message": "httpx is not installed; cannot download URLs",
            })
            job.set_status("failed")
            return

        dest_dir = self.BASE_INPUT / _sanitize_label(label)
        dest_dir.mkdir(parents=True, exist_ok=True)

        total_files = 0
        total_duration = 0.0
        label_distribution: dict[str, int] = {}

        for url in urls:
            # Validate extension before downloading
            parsed = urlparse(url)
            url_path = parsed.path
            suffix = Path(url_path).suffix.lower()

            if suffix not in SUPPORTED_EXTENSIONS:
                job.append_progress({
                    "type": "progress",
                    "url": url,
                    "status": "error",
                    "message": (
                        f"Unsupported file extension '{suffix}'. "
                        f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
                    ),
                })
                continue

            # Determine destination filename — sanitize to prevent path traversal
            raw_filename = Path(url_path).name or f"download_{uuid.uuid4().hex}{suffix}"
            # Strip any directory components and prefix with a UUID to avoid collisions
            filename = f"{uuid.uuid4().hex[:8]}_{Path(raw_filename).name}"
            dest_path = dest_dir / filename

            # Download the file with a size limit to prevent memory exhaustion (SEC-4 fix).
            # 500 MB is a generous upper bound for a single audio file.
            _MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024  # 500 MB
            try:
                with httpx.Client(follow_redirects=True, timeout=60.0) as client:
                    with client.stream("GET", url) as response:
                        response.raise_for_status()
                        total_bytes = 0
                        with open(dest_path, "wb") as out_f:
                            for chunk in response.iter_bytes(chunk_size=65536):
                                total_bytes += len(chunk)
                                if total_bytes > _MAX_DOWNLOAD_BYTES:
                                    out_f.close()
                                    dest_path.unlink(missing_ok=True)
                                    raise ValueError(
                                        f"Download exceeds size limit of "
                                        f"{_MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB"
                                    )
                                out_f.write(chunk)
            except Exception as exc:
                job.append_progress({
                    "type": "progress",
                    "url": url,
                    "status": "error",
                    "message": f"Download failed: {type(exc).__name__}: {exc}",
                })
                continue

            # Corruption check via librosa.load()
            duration = _get_audio_duration(str(dest_path))
            if duration is None:
                # Corrupted — remove the file and record failure
                try:
                    dest_path.unlink(missing_ok=True)
                except Exception:
                    pass
                job.append_progress({
                    "type": "progress",
                    "url": url,
                    "status": "error",
                    "message": "File appears corrupted: audio library could not decode it",
                })
                continue

            # Success
            total_files += 1
            total_duration += duration
            label_distribution[label] = label_distribution.get(label, 0) + 1

            job.append_progress({
                "type": "progress",
                "url": url,
                "status": "success",
                "message": f"Downloaded to {dest_path} ({duration:.2f}s)",
            })

        # Emit summary event
        job.append_progress({
            "type": "summary",
            "total_files": total_files,
            "total_duration_seconds": total_duration,
            "label_distribution": label_distribution,
        })
        job.set_status("completed")

    # ------------------------------------------------------------------
    # HuggingFace ingestion
    # ------------------------------------------------------------------

    def start_hf_job(
        self,
        repo_id: str,
        split: str,
        audio_col: str,
        label_col: Optional[str],
        label_override: Optional[str],
    ) -> str:
        """Start a background job to stream a HuggingFace dataset and save audio samples.

        Returns the job_id immediately.
        """
        job_id = uuid.uuid4().hex
        job = IngestionJob(job_id=job_id, status="running")
        _register_job(job)

        thread = threading.Thread(
            target=self._run_hf_job,
            args=(job, repo_id, split, audio_col, label_col, label_override),
            daemon=True,
        )
        thread.start()
        return job_id

    def _run_hf_job(
        self,
        job: IngestionJob,
        repo_id: str,
        split: str,
        audio_col: str,
        label_col: Optional[str],
        label_override: Optional[str],
    ) -> None:
        """Background worker: stream HuggingFace dataset and save audio samples."""
        try:
            from datasets import load_dataset  # type: ignore
        except ImportError:
            job.append_progress({
                "type": "error",
                "message": "The 'datasets' library is not installed; cannot ingest from HuggingFace",
            })
            job.set_status("failed")
            return

        try:
            dataset = load_dataset(repo_id, split=split, streaming=True)
        except Exception as exc:
            job.append_progress({
                "type": "error",
                "message": f"Failed to load HuggingFace dataset '{repo_id}': {type(exc).__name__}: {exc}",
            })
            job.set_status("failed")
            return

        total_files = 0
        total_duration = 0.0
        label_distribution: dict[str, int] = {}
        files_failed = 0

        try:
            for i, sample in enumerate(dataset):
                # Determine label for this sample
                if label_override:
                    label = _sanitize_label(label_override)
                elif label_col and label_col in sample:
                    label = _sanitize_label(str(sample[label_col]))
                else:
                    label = "default"

                dest_dir = self.BASE_INPUT / label
                # Boundary check (defence-in-depth, G3-23)
                if not dest_dir.resolve().is_relative_to(self.BASE_INPUT.resolve()):
                    logger.warning(
                        "Label '%s' would escape BASE_INPUT — using 'default'", label
                    )
                    label = "default"
                    dest_dir = self.BASE_INPUT / label
                dest_dir.mkdir(parents=True, exist_ok=True)

                # Extract audio data from the sample
                audio_data = sample.get(audio_col) if audio_col else None
                if audio_data is None:
                    job.append_progress({
                        "type": "progress",
                        "url": f"sample_{i}",
                        "status": "error",
                        "message": f"Audio column '{audio_col}' not found in sample {i}",
                    })
                    files_failed += 1
                    continue

                # audio_data is typically a dict with 'array', 'sampling_rate', and 'path'
                saved_path = _save_hf_audio_sample(audio_data, dest_dir, i)
                if saved_path is None:
                    job.append_progress({
                        "type": "progress",
                        "url": f"sample_{i}",
                        "status": "error",
                        "message": f"Failed to save audio sample {i}",
                    })
                    files_failed += 1
                    continue

                # Get duration
                duration = _get_audio_duration(str(saved_path))
                if duration is None:
                    duration = 0.0

                total_files += 1
                total_duration += duration
                label_distribution[label] = label_distribution.get(label, 0) + 1

                job.append_progress({
                    "type": "progress",
                    "url": f"sample_{i}",
                    "status": "success",
                    "message": f"Saved to {saved_path} (label={label}, {duration:.2f}s)",
                })

        except Exception as exc:
            job.append_progress({
                "type": "error",
                "message": f"Streaming error: {type(exc).__name__}: {exc}",
            })
            job.set_status("failed")
            return

        # Emit summary event
        job.append_progress({
            "type": "summary",
            "total_files": total_files,
            "total_duration_seconds": total_duration,
            "label_distribution": label_distribution,
        })
        job.set_status("completed")

    # ------------------------------------------------------------------
    # Job access
    # ------------------------------------------------------------------

    def get_job(self, job_id: str) -> IngestionJob:
        """Return the IngestionJob for the given job_id.

        Raises KeyError if the job does not exist.
        """
        with _jobs_lock:
            if job_id not in _jobs:
                raise KeyError(f"No ingestion job with id '{job_id}'")
            return _jobs[job_id]

    def stream_job(self, job_id: str) -> Generator[dict, None, None]:
        """Yield progress events from the job as they arrive.

        Polls job.progress with a short sleep until the job is no longer running.
        Uses read_progress() for thread-safe snapshot reads.
        """
        job = self.get_job(job_id)
        cursor = 0

        while True:
            # Take a thread-safe snapshot of current events
            current_events = job.read_progress()
            while cursor < len(current_events):
                yield current_events[cursor]
                cursor += 1

            # If job is done and we've yielded all events, stop
            if job.status != "running":
                # Drain any final events that may have been added
                current_events = job.read_progress()
                while cursor < len(current_events):
                    yield current_events[cursor]
                    cursor += 1
                break

            time.sleep(0.1)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _get_audio_duration(path: str) -> Optional[float]:
    """Return audio duration in seconds, or None if the file cannot be decoded."""
    # Try soundfile first (fast, no resampling)
    try:
        import soundfile as sf  # type: ignore
        info = sf.info(path)
        return info.duration
    except Exception:
        pass

    # Fall back to librosa (handles more formats like mp3, m4a)
    try:
        import librosa  # type: ignore
        duration = librosa.get_duration(path=path)
        return duration
    except Exception:
        pass

    return None


def _save_hf_audio_sample(audio_data: dict, dest_dir: Path, index: int) -> Optional[Path]:
    """Save a HuggingFace audio sample dict to dest_dir as a WAV file.

    audio_data is expected to be a dict with keys:
      - 'array': numpy array of audio samples
      - 'sampling_rate': int sample rate
      - 'path': optional original filename

    Returns the saved Path on success, or None on failure.
    """
    try:
        import numpy as np
        import soundfile as sf  # type: ignore

        array = audio_data.get("array")
        sampling_rate = audio_data.get("sampling_rate", 16000)
        original_path = audio_data.get("path")

        if array is None:
            return None

        # Determine output filename
        if original_path:
            stem = Path(original_path).stem
            filename = f"{stem}.wav"
        else:
            filename = f"sample_{index:06d}.wav"

        # Ensure unique filename
        dest_path = dest_dir / filename
        if dest_path.exists():
            dest_path = dest_dir / f"sample_{index:06d}_{uuid.uuid4().hex[:6]}.wav"

        audio_array = np.asarray(array, dtype=np.float32)
        sf.write(str(dest_path), audio_array, sampling_rate)
        return dest_path

    except Exception as exc:
        logger.warning("Failed to save HF audio sample %d: %s", index, exc)
        return None
