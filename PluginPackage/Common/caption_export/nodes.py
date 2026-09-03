"""CaptionExportNode — write SRT/VTT/JSON caption files from a timed transcript."""
from __future__ import annotations

import importlib
import json
import logging
from pathlib import Path
from typing import Any, ClassVar
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("caption_export.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

CaptionExportResult = _types.CaptionExportResult

log = logging.getLogger(__name__)


def _text_of(tr: Any) -> str:
    if tr is None:
        return ""
    if isinstance(tr, str):
        return tr
    if isinstance(tr, dict):
        return str(tr.get("text") or "")
    return str(getattr(tr, "text", "") or "")


def _words_of(tr: Any) -> list[dict]:
    raw = []
    if isinstance(tr, dict):
        raw = list(tr.get("words") or [])
    elif tr is not None:
        raw = list(getattr(tr, "words", None) or [])
    out = []
    for w in raw:
        if isinstance(w, dict):
            out.append(
                {
                    "word": str(w.get("word") or ""),
                    "start": float(w.get("start") or 0.0),
                    "end": float(w.get("end") or 0.0),
                    "speaker": str(w.get("speaker") or ""),
                }
            )
        else:
            out.append(
                {
                    "word": str(getattr(w, "word", "") or ""),
                    "start": float(getattr(w, "start", 0.0) or 0.0),
                    "end": float(getattr(w, "end", 0.0) or 0.0),
                    "speaker": str(getattr(w, "speaker", "") or ""),
                }
            )
    return out


def _fmt_ts(seconds: float, vtt: bool = False) -> str:
    if seconds < 0:
        seconds = 0.0
    ms = int(round(seconds * 1000.0))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    sep = "." if vtt else ","
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _cues_from_words(words: list[dict], max_words: int) -> list[tuple[float, float, str]]:
    if not words:
        return []
    cues = []
    buf: list[str] = []
    start = words[0]["start"]
    end = words[0]["end"]
    speaker = words[0].get("speaker") or ""
    for w in words:
        sp = w.get("speaker") or ""
        if buf and (len(buf) >= max_words or (sp and speaker and sp != speaker)):
            text = " ".join(buf)
            if speaker:
                text = f"[{speaker}] {text}"
            cues.append((start, end, text))
            buf = []
            start = w["start"]
            speaker = sp
        buf.append(w.get("word") or "")
        end = w.get("end") or end
        if not speaker:
            speaker = sp
    if buf:
        text = " ".join(buf)
        if speaker:
            text = f"[{speaker}] {text}"
        cues.append((start, end, text))
    return cues


def _render_srt(cues) -> str:
    lines = []
    for i, (start, end, text) in enumerate(cues, 1):
        lines.append(str(i))
        lines.append(f"{_fmt_ts(start)} --> {_fmt_ts(end)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_vtt(cues) -> str:
    lines = ["WEBVTT", ""]
    for start, end, text in cues:
        lines.append(f"{_fmt_ts(start, vtt=True)} --> {_fmt_ts(end, vtt=True)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


class CaptionExportNode(Node):
    """Write SRT, VTT, and/or JSON caption files from a timed transcript."""

    node_type: ClassVar[str] = "caption_export"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="caption_export",
        label="Caption Export",
        description="Export a diarized / word-timed transcript to SRT, VTT, or JSON files.",
        category="Output",
        version="1.0.0",
        tags=["captions", "srt", "vtt", "export", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
        streaming_support=False,
        realtime_support=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=object,
            cardinality="single",
            required=True,
            description="Transcript with optional words[{word,start,end,speaker}]",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=object,
            description="CaptionExportResult with written file paths",
        )
    }

    class Config(NodeConfig):
        output_dir: str = Field(default="workspace/artifacts/captions", title="Output Dir", description="Write under workspace/artifacts (relative to the Graphyn workspace).")
        basename: str = Field(default='captions', title="Basename", description="Basename.")
        formats: list = Field(default=['srt', 'vtt', 'json'], title="Formats", description="Formats.")
        max_words_per_cue: int = Field(default=12, title="Max Words Per Cue", description="Max Words Per Cue.")

    def process(self, transcript):
        if transcript is None:
            return CaptionExportResult(paths=[], format="", n_cues=0, metadata={"empty": True})
        words = _words_of(transcript)
        text = _text_of(transcript)
        if not words and text:
            # One cue covering the whole transcript if no timings.
            words = [{"word": text, "start": 0.0, "end": max(1.0, 0.4 * len(text.split())), "speaker": ""}]
        cues = _cues_from_words(words, int(self.config.max_words_per_cue) or 12)
        out_dir = Path(self.config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        base = self.config.basename or "captions"
        formats = [str(f).lower() for f in (self.config.formats or ["srt"])]
        paths = []
        payload = {
            "text": text,
            "cues": [{"start": s, "end": e, "text": t} for s, e, t in cues],
            "words": words,
        }
        if "srt" in formats:
            p = out_dir / f"{base}.srt"
            p.write_text(_render_srt(cues), encoding="utf-8")
            paths.append(str(p))
        if "vtt" in formats:
            p = out_dir / f"{base}.vtt"
            p.write_text(_render_vtt(cues), encoding="utf-8")
            paths.append(str(p))
        if "json" in formats:
            p = out_dir / f"{base}.json"
            p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            paths.append(str(p))
        return CaptionExportResult(
            paths=paths,
            format=",".join(formats),
            n_cues=len(cues),
            metadata={"output_dir": str(out_dir)},
        )
