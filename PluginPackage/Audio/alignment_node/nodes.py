"""AlignmentNode — forced alignment of transcripts to audio (word / char).

Backend ``ctc``: torchaudio's MMS forced aligner (``torchaudio.pipelines.MMS_FA``,
a multilingual wav2vec2 CTC model trained for alignment; weights download once
from dl.fbaipublicfiles.com). Text is lower-cased and romanised with ``uroman``
for non-Latin scripts, then aligned with ``torchaudio.functional.forced_align``.

Output: each AudioSample gets ``metadata["alignment"]`` =
    {"words": [{"word", "start", "end", "score"}, ...], "backend", "language",
     "level", "model"}
where ``word`` is the original token (``level="word"``) or a single
character (``level="char"``). Times are seconds.
"""
from __future__ import annotations

import copy
import logging
import re
import unicodedata
from typing import Any, ClassVar, Literal

import numpy as np
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample

log = logging.getLogger(__name__)

_BUNDLES: dict[str, Any] = {}


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _transcript_texts(transcripts: Any, n: int) -> list[str]:
    """Normalise the transcripts port to one text per audio sample.

    Accepts a list of {"text"} dicts / strings / Transcript objects, or one
    Transcript whose ``metadata["items"]`` holds per-sample texts (the shape
    asr_transcribe emits for several samples)."""
    if transcripts is None:
        return []
    if isinstance(transcripts, (str, dict)) or hasattr(transcripts, "text"):
        items = (_get(transcripts, "metadata", {}) or {}).get("items") if not isinstance(transcripts, str) else None
        if items:
            return [str(_get(it, "text", "") or "") for it in items]
        text = transcripts if isinstance(transcripts, str) else str(_get(transcripts, "text", "") or "")
        return [text]
    out = []
    for t in transcripts:
        out.append(t if isinstance(t, str) else str(_get(t, "text", "") or ""))
    return out


def _romanize(text: str, language: str) -> str:
    if all(ord(c) < 0x250 for c in text):  # Latin script: strip accents only
        return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    try:
        import uroman  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "AlignmentNode: non-Latin text needs the 'uroman' package in this plugin's venv") from exc
    return str(uroman.Uroman().romanize_string(text, lcode=_ISO3.get(language, None)))


_ISO3 = {"en": "eng", "de": "deu", "fr": "fra", "es": "spa", "hi": "hin", "ru": "rus", "zh": "cmn",
         "ja": "jpn", "ar": "ara", "ko": "kor", "it": "ita", "pt": "por", "bn": "ben", "ta": "tam"}


class AlignmentNode(Node):
    """Forced-align transcripts to audio with the MMS CTC aligner."""

    node_type: ClassVar[str] = "alignment_node"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="alignment_node",
        label="Alignment Node",
        description=(
            "Forced alignment of transcripts to audio (word or character timestamps) "
            "with torchaudio's multilingual MMS CTC aligner."
        ),
        category="Preprocessing",
        version="2.0.0",
        tags=["audio", "alignment", "asr", "ctc", "timestamps", "transcript"],
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
            data_type=object | None,
            cardinality="single",
            required=False,
            description=(
                "Per-sample transcripts: list of {text} dicts / strings, or a Transcript "
                "(asr_transcribe). Matched by index; else sample.metadata['transcript']."
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
        language: str = Field(default="en", title="Language", description="ISO 639-1 code of the transcript (used for romanisation of non-Latin text).")
        level: Literal["word", "char"] = Field(default="word", title="Level", description="Timestamp granularity: word or char.")
        device: Literal["cpu", "cuda"] = Field(default="cpu", title="Device", description="Compute device (cuda falls back to cpu when unavailable).")

    def _bundle(self):
        try:
            import torch  # type: ignore
            from torchaudio.pipelines import MMS_FA  # type: ignore
        except ImportError as exc:
            raise RuntimeError("AlignmentNode: needs torch + torchaudio in this plugin's venv") from exc
        device = "cuda" if self.config.device == "cuda" and torch.cuda.is_available() else "cpu"
        if device not in _BUNDLES:
            model = MMS_FA.get_model(with_star=False).to(device).eval()
            _BUNDLES[device] = (model, MMS_FA.get_dict(star=None), MMS_FA.sample_rate, device)
        return _BUNDLES[device]

    def process(self, inputs: dict) -> dict:
        audio_samples = list(inputs.get("audio") or [])
        texts = _transcript_texts(inputs.get("transcripts"), len(audio_samples))
        output: list = []
        for i, sample in enumerate(audio_samples):
            new_sample = copy.deepcopy(sample)
            text = texts[i] if i < len(texts) else str((sample.metadata or {}).get("transcript") or "")
            if not text.strip():
                new_sample.metadata["alignment"] = {
                    "words": [], "backend": "ctc", "language": self.config.language,
                    "level": self.config.level, "note": "no transcript provided",
                }
            else:
                new_sample.metadata["alignment"] = self._align(new_sample, text)
            output.append(new_sample)
        return {"output": output}

    def _align(self, sample: AudioSample, text: str) -> dict:
        import torch  # type: ignore
        import torchaudio.functional as F  # type: ignore

        model, dictionary, model_sr, device = self._bundle()
        if sample.data is None or len(sample.data) == 0:
            raise ValueError(f"AlignmentNode: empty audio for sample '{sample.path}'")
        y = np.asarray(sample.data, dtype=np.float32).reshape(-1)
        if int(sample.sample_rate) != model_sr:
            from math import gcd

            from scipy.signal import resample_poly

            g = gcd(int(sample.sample_rate), model_sr)
            y = resample_poly(y, model_sr // g, int(sample.sample_rate) // g).astype(np.float32)

        originals = [w for w in text.split() if w.strip()]
        norm_words: list[str] = []
        kept: list[str] = []
        for w in originals:
            n = re.sub(r"[^a-z']", "", _romanize(w, self.config.language).lower())
            n = "".join(c for c in n if c in dictionary)
            if n:
                norm_words.append(n)
                kept.append(w)
        if not norm_words:
            raise ValueError(f"AlignmentNode: transcript {text!r} has no alignable characters")
        tokens = [dictionary[c] for w in norm_words for c in w]

        with torch.inference_mode():
            emission, _ = model(torch.from_numpy(y).unsqueeze(0).to(device))
        if emission.shape[1] < len(tokens):
            raise ValueError(
                f"AlignmentNode: audio too short ({len(y) / model_sr:.2f}s) for {len(tokens)} characters")
        targets = torch.tensor([tokens], dtype=torch.int32, device=device)
        aligned, scores = F.forced_align(emission, targets, blank=0)
        token_spans = F.merge_tokens(aligned[0], scores[0].exp())
        sec_per_frame = (len(y) / model_sr) / emission.shape[1]

        out: list[dict] = []
        pos = 0
        for orig, w in zip(kept, norm_words):
            spans = token_spans[pos: pos + len(w)]
            pos += len(w)
            if self.config.level == "char":
                for ch, sp in zip(w, spans):
                    out.append({"word": ch, "start": round(sp.start * sec_per_frame, 3),
                                "end": round(sp.end * sec_per_frame, 3), "score": round(float(sp.score), 4)})
            else:
                score = sum(float(s.score) * len(s) for s in spans) / max(sum(len(s) for s in spans), 1)
                out.append({"word": orig, "start": round(spans[0].start * sec_per_frame, 3),
                            "end": round(spans[-1].end * sec_per_frame, 3), "score": round(score, 4)})
        return {"words": out, "backend": "ctc", "language": self.config.language,
                "level": self.config.level, "model": "torchaudio.pipelines.MMS_FA"}
