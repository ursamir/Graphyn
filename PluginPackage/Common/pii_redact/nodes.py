"""PiiRedactNode — redact PII from transcripts; optionally silence audio spans.

Engines: presidio (spaCy NER + recognizers; errors are raised, never
silently downgraded), regex (email / phone / card), auto (presidio when
installed in the plugin venv, else regex — the audit's ``engine`` says which).
Overlapping findings are merged so no fragment of an entity leaks.
"""
from __future__ import annotations

import importlib
import logging
import re
from typing import Any, ClassVar, Literal
from pydantic import Field

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("pii_redact.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

PiiFinding = _types.PiiFinding
RedactionAudit = _types.RedactionAudit

log = logging.getLogger(__name__)

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?:\+?\d{1,3}[-.\s])?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}")
_CARD = re.compile(r"\b(?:\d[ \-]?){13,19}\b")
_PATTERNS = (("EMAIL", _EMAIL), ("PHONE_NUMBER", _PHONE), ("CREDIT_CARD", _CARD))


def _text_of(transcript: Any) -> str:
    if transcript is None:
        return ""
    if isinstance(transcript, str):
        return transcript
    if isinstance(transcript, dict):
        return str(transcript.get("text") or "")
    return str(getattr(transcript, "text", "") or "")


def _words_of(transcript: Any) -> list:
    if transcript is None:
        return []
    if isinstance(transcript, dict):
        return list(transcript.get("words") or [])
    return list(getattr(transcript, "words", None) or [])


def _lang_of(transcript: Any) -> str:
    if transcript is None:
        return "en"
    if isinstance(transcript, dict):
        return str(transcript.get("language") or "en")
    return str(getattr(transcript, "language", "") or "en")


def _word_text(w: Any) -> str:
    if isinstance(w, dict):
        return str(w.get("word") or "")
    return str(getattr(w, "word", "") or "")


def _word_span(w: Any) -> tuple[float, float]:
    if isinstance(w, dict):
        return float(w.get("start") or 0.0), float(w.get("end") or 0.0)
    return float(getattr(w, "start", 0.0) or 0.0), float(getattr(w, "end", 0.0) or 0.0)


def _rebuild_transcript(original: Any, text: str, words: list) -> Any:
    """Return a duck-typed transcript matching the input type when possible."""
    if original is None or isinstance(original, str):
        return type("Transcript", (), {"text": text, "language": "en", "words": words, "metadata": {}})()
    if isinstance(original, dict):
        out = dict(original)
        out["text"] = text
        out["words"] = words
        return out
    try:
        return original.model_copy(update={"text": text, "words": words})
    except Exception:
        try:
            object.__setattr__(original, "text", text)
            object.__setattr__(original, "words", words)
            return original
        except Exception:
            return original


def _regex_findings(text: str) -> list:
    findings = []
    for etype, pat in _PATTERNS:
        for m in pat.finditer(text):
            findings.append(
                PiiFinding(entity_type=etype, start=m.start(), end=m.end(), score=1.0, text=m.group(0))
            )
    findings.sort(key=lambda f: (f.start, f.end))
    return findings


_ANALYZERS: dict[str, Any] = {}


def presidio_available() -> bool:
    try:
        import presidio_analyzer  # noqa: F401  # type: ignore
        import spacy  # noqa: F401  # type: ignore
    except ImportError:
        return False
    return True


def _spacy_model_path(name: str) -> str:
    """Installed spaCy package name, else the pipeline directory from the
    official ``spacy/<name>`` Hugging Face repo (downloaded once, cached)."""
    import spacy  # type: ignore

    if spacy.util.is_package(name):
        return name
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError(
            f"PiiRedactNode: spaCy model {name!r} is not installed and huggingface_hub is missing") from exc
    return snapshot_download(f"spacy/{name}", ignore_patterns=["*.whl"])


def _analyzer(model: str, language: str) -> Any:
    key = f"{model}:{language}"
    if key not in _ANALYZERS:
        from presidio_analyzer import AnalyzerEngine  # type: ignore
        from presidio_analyzer.nlp_engine import SpacyNlpEngine  # type: ignore

        engine = SpacyNlpEngine(models=[{"lang_code": language, "model_name": _spacy_model_path(model)}])
        engine.load()
        _ANALYZERS[key] = AnalyzerEngine(nlp_engine=engine, supported_languages=[language])
    return _ANALYZERS[key]


def _presidio_findings(text: str, *, model: str, language: str, min_score: float) -> list:
    """Run Presidio; raises RuntimeError on any failure (no silent fallback)."""
    if not presidio_available():
        raise RuntimeError(
            "PiiRedactNode: engine='presidio' needs presidio-analyzer and spaCy in this "
            "plugin's venv (pip install presidio-analyzer).")
    try:
        results = _analyzer(model, language).analyze(text=text, language=language)
    except Exception as exc:
        raise RuntimeError(f"PiiRedactNode: Presidio analysis failed ({type(exc).__name__}: {exc})") from exc
    findings = []
    for r in results:
        score = float(getattr(r, "score", 1.0) or 0.0)
        if score < min_score:
            continue
        start, end = int(r.start), int(r.end)
        findings.append(PiiFinding(entity_type=str(r.entity_type or "PII"), start=start, end=end,
                                   score=score, text=text[start:end]))
    findings.sort(key=lambda f: (f.start, f.end))
    return findings


def _merge_overlaps(findings: list, text: str) -> list:
    """Union overlapping spans so no part of a longer entity leaks; the merged
    span keeps the entity type of its highest-scoring (then longest) member."""
    merged: list = []
    for f in sorted(findings, key=lambda f: (f.start, -f.end)):
        if merged and f.start < merged[-1].end:
            cur = merged[-1]
            best = max((cur, f), key=lambda x: (x.score, x.end - x.start))
            end = max(cur.end, f.end)
            merged[-1] = PiiFinding(entity_type=best.entity_type, start=cur.start, end=end,
                                    score=max(cur.score, f.score), text=text[cur.start:end])
            continue
        merged.append(f)
    return merged


def _apply_redactions(text: str, findings: list, placeholder: str) -> str:
    if not findings:
        return text
    out = []
    cursor = 0
    for f in findings:
        start, end = int(f.start), int(f.end)
        if start < cursor:
            continue
        out.append(text[cursor:start])
        label = placeholder or f"[{f.entity_type}]"
        out.append(label)
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def _silence_audio(samples: list, word_spans: list[tuple[float, float]]) -> list:
    if not samples or not word_spans:
        return samples
    redacted = []
    for sample in samples:
        data = getattr(sample, "data", None)
        sr = int(getattr(sample, "sample_rate", 0) or 0)
        if data is None or sr <= 0:
            redacted.append(sample)
            continue
        arr = np.asarray(data, dtype=np.float32).copy()
        n = arr.reshape(-1).shape[0]
        flat = arr.reshape(-1)
        for start, end in word_spans:
            i0 = max(0, int(start * sr))
            i1 = min(n, int(end * sr))
            if i1 > i0:
                flat[i0:i1] = 0.0
        new_data = flat.reshape(arr.shape)
        try:
            redacted.append(sample.model_copy(update={"data": new_data}))
        except Exception:
            try:
                object.__setattr__(sample, "data", new_data)
            except Exception:
                pass
            redacted.append(sample)
    return redacted


class PiiRedactNode(Node):
    """Redact emails, phones, and cards from a transcript; optionally silence audio."""

    node_type: ClassVar[str] = "pii_redact"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="pii_redact",
        label="PII Redact",
        description=(
            "Redact PII from transcripts using Presidio when installed, "
            "otherwise regex (email, phone, card). Optionally silence timed audio spans."
        ),
        category="Processing",
        version="1.0.0",
        tags=["pii", "privacy", "redaction", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=True,
        streaming_support=False,
        realtime_support=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "transcript": InputPort(
            name="transcript",
            data_type=object,
            cardinality="single",
            required=True,
            description="Transcript (or dict/str with .text)",
        ),
        "audio": InputPort(
            name="audio",
            data_type=object | None,
            cardinality="single",
            required=False,
            description="Optional list of AudioSample objects to silence at PII word spans",
        ),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "transcript": OutputPort(
            name="transcript",
            data_type=object,
            description="Redacted transcript",
        ),
        "audio": OutputPort(
            name="audio",
            data_type=object,
            description="Optional redacted audio (silence spans)",
        ),
        "audit": OutputPort(
            name="audit",
            data_type=object,
            description="RedactionAudit with findings",
        ),
    }

    class Config(NodeConfig):
        placeholder: str = Field(default='', title="Placeholder", description="Replacement text inserted for redacted PII spans.")
        engine: Literal["auto", "regex", "presidio"] = Field(default='auto', title="Engine", description="presidio: NER + pattern recognizers (names, places, IDs…); regex: email/phone/card patterns only; auto: presidio when installed, else regex (the audit records which ran).")
        spacy_model: str = Field(default="en_core_web_sm", title="spaCy model", description="spaCy pipeline for Presidio NER (installed package, else downloaded from huggingface.co/spacy/<name>).")
        min_score: float = Field(default=0.4, ge=0.0, le=1.0, title="Min score", description="Drop Presidio findings below this confidence.")

    def process(self, inputs: dict) -> dict:
        transcript = (inputs or {}).get("transcript")
        audio = (inputs or {}).get("audio")
        if transcript is None:
            audit = RedactionAudit(findings=[], engine="none", n_redacted=0, metadata={"empty": True})
            return {"transcript": transcript, "audio": audio, "audit": audit}

        text = _text_of(transcript)
        engine = (self.config.engine or "auto").lower()
        if engine == "auto":
            engine = "presidio" if presidio_available() else "regex"
        if engine == "presidio":
            language = (_lang_of(transcript) or "en").split("-")[0].lower() or "en"
            findings = _presidio_findings(text, model=self.config.spacy_model, language=language,
                                          min_score=float(self.config.min_score))
        else:
            findings = _regex_findings(text)
        used = engine
        findings = _merge_overlaps(findings, text)

        redacted_text = _apply_redactions(text, findings, self.config.placeholder)
        words = _words_of(transcript)
        redacted_words = []
        silence_spans: list[tuple[float, float]] = []
        # Mark words whose surface form still contains a finding substring.
        finding_texts = [f.text for f in findings if f.text]
        for w in words:
            wt = _word_text(w)
            hit = any(ft and ft in wt or (wt and wt in ft) for ft in finding_texts)
            if hit:
                start, end = _word_span(w)
                silence_spans.append((start, end))
                if isinstance(w, dict):
                    nw = dict(w)
                    nw["word"] = self.config.placeholder or "[REDACTED]"
                    redacted_words.append(nw)
                else:
                    try:
                        redacted_words.append(w.model_copy(update={"word": self.config.placeholder or "[REDACTED]"}))
                    except Exception:
                        redacted_words.append(w)
            else:
                redacted_words.append(w)

        new_tr = _rebuild_transcript(transcript, redacted_text, redacted_words)
        samples = audio if isinstance(audio, list) else ([audio] if audio is not None else [])
        new_audio = _silence_audio(samples, silence_spans) if samples else audio
        audit = RedactionAudit(
            findings=findings,
            engine=used,
            n_redacted=len(findings),
            metadata={"n_audio_spans": len(silence_spans)},
        )
        return {"transcript": new_tr, "audio": new_audio, "audit": audit}
