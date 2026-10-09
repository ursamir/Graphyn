"""Shared ffmpeg/ffprobe helpers for the Graphyn Video pack.

Each Video plugin ships its own copy of this module (plugins install
independently). Everything here shells out to the ``ffmpeg`` / ``ffprobe``
binaries; no OpenCV is needed. Items flowing between Video nodes may be
pydantic objects (in-process) or plain dicts (after an isolated worker), so
accessors accept both.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

import numpy as np

VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".ogv", ".ogg")


def binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"Video pack: '{name}' binary not found on PATH (install ffmpeg)")
    return path


def run(args: list[str], *, timeout: float = 600.0, binary_name: str = "ffmpeg") -> bytes:
    cmd = [binary(binary_name), *args]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-6:]
        raise RuntimeError(f"{binary_name} failed (exit {proc.returncode}): {' | '.join(err)}")
    return proc.stdout


def run_stderr(args: list[str], *, timeout: float = 600.0) -> str:
    """Run ffmpeg and return stderr (filters like blackdetect/showinfo log there)."""
    cmd = [binary("ffmpeg"), "-hide_banner", "-nostats", *args]
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=timeout, check=False)
    text = proc.stderr.decode("utf-8", "replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {proc.returncode}): {' | '.join(text.strip().splitlines()[-6:])}")
    return text


def _ratio(v: str | None) -> float:
    if not v or v in ("0/0", "N/A"):
        return 0.0
    if "/" in v:
        a, b = v.split("/", 1)
        try:
            return float(a) / float(b) if float(b) else 0.0
        except ValueError:
            return 0.0
    try:
        return float(v)
    except ValueError:
        return 0.0


def probe(path: str | Path) -> dict[str, Any]:
    """ffprobe a media file → duration/fps/size/codec/audio facts."""
    out = run(
        ["-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        binary_name="ffprobe", timeout=120,
    )
    info = json.loads(out.decode("utf-8") or "{}")
    streams = info.get("streams") or []
    fmt = info.get("format") or {}
    v = next((s for s in streams if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if v is None:
        raise ValueError(f"{path}: no video stream")
    duration = _ratio(fmt.get("duration")) or _ratio(v.get("duration"))
    fps = _ratio(v.get("avg_frame_rate")) or _ratio(v.get("r_frame_rate"))
    n_frames = int(v.get("nb_frames") or 0) or (int(round(duration * fps)) if duration and fps else 0)
    return {
        "duration_s": round(float(duration), 3),
        "fps": round(float(fps), 3),
        "width": int(v.get("width") or 0),
        "height": int(v.get("height") or 0),
        "n_frames": n_frames,
        "codec": str(v.get("codec_name") or ""),
        "has_audio": a is not None,
        "audio_codec": str(a.get("codec_name") or "") if a else "",
        "audio_sample_rate": int(a.get("sample_rate") or 0) if a else 0,
        "size_bytes": int(fmt.get("size") or Path(path).stat().st_size),
        "container": str(fmt.get("format_name") or ""),
    }


def get(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, dict) and "output" in value and len(value) == 1:
        value = value["output"]
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def media_path(item: Any) -> str:
    if isinstance(item, (str, Path)):
        return str(item)
    p = get(item, "path") or get(item, "source_path")
    if not p:
        raise ValueError(f"Video pack: item has no path: {type(item).__name__}")
    return str(p)


def span(item: Any) -> tuple[float, float | None]:
    """(start_s, end_s) of the item's segment inside its file (end None = to EOF)."""
    start = float(get(item, "start_s", 0.0) or 0.0)
    end = get(item, "end_s")
    if end is None:
        dur = get(item, "duration_s")
        end = start + float(dur) if dur else None
    return start, (float(end) if end is not None else None)


def frames_at(path: str, times: Iterable[float], *, width: int = 0, height: int = 0) -> list[np.ndarray]:
    """Decode RGB frames at the given timestamps (seconds)."""
    out: list[np.ndarray] = []
    info = None
    for t in times:
        vf = []
        if width and height:
            vf = ["-vf", f"scale={int(width)}:{int(height)}"]
        seek = ["-ss", f"{float(t):.3f}"] if float(t) > 0 else []  # -ss 0 yields nothing on still images
        raw = run(["-v", "error", *seek, "-i", str(path), "-frames:v", "1",
                   *vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], timeout=120)
        if not raw:
            continue
        if width and height:
            w, h = int(width), int(height)
        else:
            info = info or probe(path)
            w, h = info["width"], info["height"]
        if len(raw) < w * h * 3:
            continue
        out.append(np.frombuffer(raw[: w * h * 3], dtype=np.uint8).reshape(h, w, 3))
    return out


def uniform_times(duration: float, n: int, start: float = 0.0) -> list[float]:
    n = max(1, int(n))
    duration = max(0.0, float(duration))
    return [start + duration * (i + 0.5) / n for i in range(n)]


def audio_pcm(path: str, *, sample_rate: int = 16000, start: float = 0.0, end: float | None = None) -> np.ndarray:
    """Decode the audio track as mono float32 PCM."""
    args = ["-v", "error", "-ss", f"{max(0.0, start):.3f}"]
    if end is not None:
        args += ["-to", f"{float(end):.3f}"]
    args += ["-i", str(path), "-vn", "-ac", "1", "-ar", str(int(sample_rate)), "-f", "f32le", "pipe:1"]
    raw = run(args, timeout=600)
    return np.frombuffer(raw, dtype=np.float32).copy()


def write_jpeg(rgb: np.ndarray, dest: Path, quality: int = 3) -> None:
    h, w = rgb.shape[:2]
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [binary("ffmpeg"), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
           "-i", "pipe:0", "-frames:v", "1", "-q:v", str(int(quality)), str(dest)]
    proc = subprocess.run(cmd, input=np.ascontiguousarray(rgb).tobytes(), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=60, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg jpeg encode failed: {proc.stderr.decode('utf-8', 'replace')[-300:]}")


def jpeg_bytes_at(path: str, t: float, *, width: int = 0, quality: int = 3) -> bytes:
    """One JPEG-encoded frame at time ``t`` (optionally downscaled to ``width``)."""
    vf = ["-vf", f"scale='min({int(width)},iw)':-2"] if width else []
    return run(["-v", "error", "-ss", f"{max(0.0, float(t)):.3f}", "-i", str(path), "-frames:v", "1", *vf,
                "-q:v", str(int(quality)), "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"], timeout=120)


def jpeg_bytes_of_image(path: str, *, width: int = 0, quality: int = 3) -> bytes:
    """Re-encode an image file to JPEG (downscaled to ``width`` when wider)."""
    vf = ["-vf", f"scale='min({int(width)},iw)':-2"] if width else []
    return run(["-v", "error", "-i", str(path), "-frames:v", "1", *vf, "-q:v", str(int(quality)),
                "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"], timeout=60)
