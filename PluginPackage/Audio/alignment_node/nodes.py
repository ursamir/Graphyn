"""AlignmentNode — temporal alignment between audio and transcripts.

Backends:
    ctc   — CTC forced alignment via ctc-forced-aligner (word/phoneme/char level)
    mfa   — Montreal Forced Aligner (word/phoneme level, requires mfa CLI)
    auto  — try ctc, fall back to mfa

Output: AudioSample.metadata["alignment"] = {
    "words": [{"word": str, "start": float, "end": float}, ...],
    "backend": str,
    "language": str,
    "level": str,
}
"""
from __future__ import annotations

import copy
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import ClassVar

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample

log = logging.getLogger(__name__)


class AlignmentNode(Node):
    """Temporal alignment between audio samples and transcripts.

    Produces word-level (or phoneme/char-level) timestamps stored in
    ``AudioSample.metadata["alignment"]``.

    Input ports:
        audio       — list[AudioSample]
        transcripts — list[dict] each: {"path": str, "text": str}
                      Matched to audio samples by index (zip).
                      If transcripts list is shorter, remaining samples
                      are passed through without alignment.

    Output ports:
        output — list[AudioSample] with metadata["alignment"] populated

    Config:
        backend (str): "ctc" | "mfa" | "auto"
        language (str): BCP-47 language code, e.g. "en", "de", "fr"
        level (str): "word" | "phoneme" | "char"
        model_path (str): optional path to custom alignment model
        device (str): "cpu" | "cuda" — for CTC backend
    """

    node_type: ClassVar[str] = "alignment_node"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="alignment_node",
        label="Alignment Node",
        description=(
            "Temporal alignment between audio and transcripts. "
            "Produces word/phoneme timestamps via CTC forced alignment or MFA."
        ),
        category="Preprocessing",
        version="1.0.0",
        tags=["audio", "alignment", "asr", "ctc", "mfa", "timestamps", "transcript"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=False,
        deterministic=True,
        cacheable=True,
        streaming_support=False,
        realtime_support=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "audio": InputPort(
            name="audio",
            data_type=list[AudioSample],
            cardinality="single",
            required=True,
            description="Audio samples to align",
        ),
        "transcripts": InputPort(
            name="transcripts",
            data_type=list[dict],
            cardinality="single",
            required=False,
            description=(
                "Transcript dicts: [{\"path\": str, \"text\": str}, ...]. "
                "Matched to audio by index. Falls back to sample.metadata[\"transcript\"] "
                "if not provided."
            ),
        ),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=list[AudioSample],
            description="Audio samples with metadata['alignment'] populated",
        )
    }

    class Config(NodeConfig):
        backend: str = "ctc"       # "ctc" | "mfa" | "auto"
        language: str = "en"
        level: str = "word"        # "word" | "phoneme" | "char"
        model_path: str = ""       # optional custom model path
        device: str = "cpu"        # "cpu" | "cuda"
        mfa_timeout_s: int = 300   # MFA subprocess timeout in seconds

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def setup(self) -> None:
        """Pre-load the CTC model once so it is not reloaded on every process() call."""
        self._ctc_model = None
        self._ctc_tokenizer = None
        if self.config.backend in ("ctc", "auto"):
            try:
                from ctc_forced_aligner import load_alignment_model  # type: ignore
                import torch  # type: ignore
                device = self.config.device
                if device == "cuda" and not torch.cuda.is_available():
                    device = "cpu"
                model_path = self.config.model_path or "MahmoudAshraf/mms-300m-1130-forced-aligner"
                self._ctc_model, self._ctc_tokenizer = load_alignment_model(model_path, device=device)
                self._ctc_device = device
                log.info("AlignmentNode: CTC model loaded from '%s' on %s", model_path, device)
            except ImportError:
                pass  # ctc-forced-aligner not installed — will raise at align time if needed

    # ── multi-port process ────────────────────────────────────────────────────

    def process(self, inputs: dict) -> dict:
        audio_samples: list[AudioSample] = inputs.get("audio") or []
        transcripts: list[dict] = inputs.get("transcripts") or []

        output: list[AudioSample] = []

        for i, sample in enumerate(audio_samples):
            new_sample = copy.deepcopy(sample)

            # Resolve transcript text
            text: str = ""
            if i < len(transcripts):
                text = str(transcripts[i].get("text", ""))
            elif "transcript" in sample.metadata:
                text = str(sample.metadata["transcript"])

            if not text.strip():
                log.warning(
                    "AlignmentNode: no transcript for sample %d (%s) — skipping alignment",
                    i, sample.path,
                )
                new_sample.metadata["alignment"] = {
                    "words": [],
                    "backend": self.config.backend,
                    "language": self.config.language,
                    "level": self.config.level,
                    "note": "no transcript provided",
                }
                output.append(new_sample)
                continue

            alignment = self._align(new_sample, text)
            new_sample.metadata["alignment"] = alignment
            output.append(new_sample)

        return {"output": output}

    # ── backend dispatch ──────────────────────────────────────────────────────

    def _align(self, sample: AudioSample, text: str) -> dict:
        backend = self.config.backend

        if backend == "ctc":
            return self._align_ctc(sample, text)
        elif backend == "mfa":
            return self._align_mfa(sample, text)
        elif backend == "auto":
            try:
                return self._align_ctc(sample, text)
            except ImportError:
                log.info("AlignmentNode: ctc-forced-aligner not available — trying MFA")
                try:
                    return self._align_mfa(sample, text)
                except (ImportError, FileNotFoundError) as exc:
                    raise ImportError(
                        "AlignmentNode: no alignment backend available. "
                        "Install ctc-forced-aligner: pip install ctc-forced-aligner>=2.0 "
                        "or install MFA: conda install -c conda-forge montreal-forced-aligner"
                    ) from exc
        else:
            raise ValueError(
                f"AlignmentNode: unknown backend '{backend}'. "
                "Choose from: ctc, mfa, auto"
            )

    # ── CTC forced alignment ──────────────────────────────────────────────────

    def _align_ctc(self, sample: AudioSample, text: str) -> dict:
        """CTC forced alignment via ctc-forced-aligner library."""
        try:
            from ctc_forced_aligner import (  # type: ignore
                generate_emissions,
                get_alignments,
                get_spans,
                load_alignment_model,
                postprocess_results,
                preprocess_text,
            )
        except ImportError as exc:
            raise ImportError(
                "AlignmentNode: 'ctc-forced-aligner' package required for backend='ctc'. "
                "Install with: pip install ctc-forced-aligner>=2.0"
            ) from exc

        import torch  # type: ignore

        device = self.config.device
        if device == "cuda" and not torch.cuda.is_available():
            log.warning("AlignmentNode: CUDA not available — falling back to CPU")
            device = "cpu"

        model_path = self.config.model_path or "MahmoudAshraf/mms-300m-1130-forced-aligner"
        language = self.config.language

        # Use cached model from setup(); fall back to loading if setup() was not called
        if getattr(self, "_ctc_model", None) is not None:
            alignment_model = self._ctc_model
            alignment_tokenizer = self._ctc_tokenizer
            device = getattr(self, "_ctc_device", device)
        else:
            alignment_model, alignment_tokenizer = load_alignment_model(
                model_path,
                device=device,
            )

        # Prepare audio tensor — CTC aligner expects float32 mono at 16kHz
        y = sample.data.astype(np.float32)
        sr = sample.sample_rate
        if sr != 16000:
            import librosa  # type: ignore
            y = librosa.resample(y=y, orig_sr=sr, target_sr=16000)

        audio_tensor = torch.from_numpy(y).unsqueeze(0).to(device)

        # Preprocess text
        text_preprocessed = preprocess_text(
            text,
            language=language,
            split_size=self.config.level,
        )

        # Generate emissions
        emissions, stride = generate_emissions(
            alignment_model,
            audio_tensor,
            batch_size=1,
        )

        # Get alignments
        tokens_starred, text_starred = preprocess_text(
            text,
            language=language,
            split_size=self.config.level,
            star_frequency="edges",
        )

        segments, scores, blank_token = get_alignments(
            emissions,
            tokens_starred,
            alignment_tokenizer,
        )

        spans = get_spans(tokens_starred, segments, blank_token)

        word_timestamps = postprocess_results(text_starred, spans, stride, scores)

        # Normalise to our schema
        words = []
        for entry in word_timestamps:
            words.append({
                "word": entry.get("label", ""),
                "start": float(entry.get("start", 0.0)),
                "end": float(entry.get("end", 0.0)),
                "score": float(entry.get("score", 1.0)),
            })

        return {
            "words": words,
            "backend": "ctc",
            "language": language,
            "level": self.config.level,
            "model": model_path,
        }

    # ── MFA alignment ─────────────────────────────────────────────────────────

    def _align_mfa(self, sample: AudioSample, text: str) -> dict:
        """Montreal Forced Aligner via subprocess.

        Requires `mfa` CLI installed (conda install montreal-forced-aligner).
        Writes audio + transcript to a temp dir, runs mfa align, parses TextGrid.
        """
        # Check mfa is available
        try:
            result = subprocess.run(
                ["mfa", "version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise FileNotFoundError("mfa returned non-zero exit code")
        except FileNotFoundError as exc:
            raise ImportError(
                "AlignmentNode: Montreal Forced Aligner (mfa) not found. "
                "Install with: conda install -c conda-forge montreal-forced-aligner"
            ) from exc

        import soundfile as sf  # type: ignore

        language = self.config.language
        model_path = self.config.model_path or f"{language}_mfa"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            audio_path = tmp / "audio.wav"
            lab_path = tmp / "audio.lab"
            out_dir = tmp / "output"
            out_dir.mkdir()

            # Write audio
            y = sample.data.astype(np.float32)
            sr = sample.sample_rate
            sf.write(str(audio_path), y, sr)

            # Write transcript (.lab file)
            lab_path.write_text(text.strip(), encoding="utf-8")

            # Run MFA
            cmd = [
                "mfa", "align",
                str(tmp),          # corpus dir
                model_path,        # acoustic model
                model_path,        # dictionary (same name convention)
                str(out_dir),      # output dir
                "--clean",
                "--quiet",
            ]
            try:
                subprocess.run(cmd, capture_output=True, text=True, timeout=self.config.mfa_timeout_s, check=True)
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(
                    f"AlignmentNode: MFA alignment failed: {exc.stderr}"
                ) from exc

            # Parse TextGrid output
            tg_path = out_dir / "audio.TextGrid"
            if not tg_path.exists():
                raise RuntimeError(
                    "AlignmentNode: MFA did not produce a TextGrid output. "
                    "Check that the acoustic model and dictionary are installed."
                )

            words = self._parse_textgrid(tg_path, tier=self.config.level)

        return {
            "words": words,
            "backend": "mfa",
            "language": language,
            "level": self.config.level,
            "model": model_path,
        }

    def _parse_textgrid(self, tg_path: Path, tier: str = "word") -> list[dict]:
        """Minimal TextGrid parser — extracts intervals from the named tier.

        Tries multiple tier name variants to handle different MFA versions:
        "words"/"word" for word-level, "phones"/"phone" for phoneme-level.
        """
        content = tg_path.read_text(encoding="utf-8")
        words: list[dict] = []

        # Build candidate tier names to try
        if tier in ("word", "words"):
            tier_candidates = ["words", "word"]
        elif tier in ("phoneme", "phone", "phones"):
            tier_candidates = ["phones", "phone"]
        else:
            tier_candidates = [tier]

        in_tier = False
        xmin = xmax = text_val = None

        for line in content.splitlines():
            line = line.strip()
            # Check if this line names one of our candidate tiers
            if not in_tier:
                for candidate in tier_candidates:
                    if f'name = "{candidate}"' in line:
                        in_tier = True
                        break
            if not in_tier:
                continue
            if line.startswith("xmin ="):
                xmin = float(line.split("=", 1)[1].strip())
            elif line.startswith("xmax ="):
                xmax = float(line.split("=", 1)[1].strip())
            elif line.startswith("text ="):
                text_val = line.split("=", 1)[1].strip().strip('"')
                if text_val and text_val not in ("", "sp", "sil", "<eps>"):
                    words.append({
                        "word": text_val,
                        "start": xmin,
                        "end": xmax,
                    })
                xmin = xmax = text_val = None

        return words
