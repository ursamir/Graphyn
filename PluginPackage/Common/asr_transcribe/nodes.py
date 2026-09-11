"""AsrTranscribeNode — transcribe AudioSample objects to a typed Transcript.

Providers:
    openai_compat  — HTTP POST {base}/audio/transcriptions (OPENAI_API_KEY) [default]
    assemblyai     — upload + create + POLL until completed (ASSEMBLYAI_API_KEY)
    deepgram       — Deepgram listen REST (DEEPGRAM_API_KEY)
    local_whisper  — on-box faster-whisper (CPU; no paid API key)
    faster_whisper — alias of local_whisper
"""
from __future__ import annotations

import importlib
import logging
import os
import time
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
        _types = importlib.import_module("asr_transcribe.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

Transcript = _types.Transcript
WordTiming = _types.WordTiming

log = logging.getLogger(__name__)

_PROVIDER_ENV = {
    "openai_compat": "OPENAI_API_KEY",
    "assemblyai": "ASSEMBLYAI_API_KEY",
    "deepgram": "DEEPGRAM_API_KEY",
}

_LOCAL_PROVIDERS = frozenset({"local_whisper", "faster_whisper"})
_REMOTE_PROVIDERS = frozenset(_PROVIDER_ENV.keys())
_ALL_PROVIDERS = tuple(sorted(_REMOTE_PROVIDERS | _LOCAL_PROVIDERS))

# Process-local WhisperModel cache: (model_name, device, compute_type) -> model
_WHISPER_MODELS: dict[tuple[str, str, str], Any] = {}


def _resolve_key(env_key: str) -> str:
    try:
        from app.core.secrets import resolve_secret
        return resolve_secret(env_key)
    except Exception:
        return os.environ.get(env_key, "").strip()


def _coerce_samples(audio: Any) -> list:
    if audio is None:
        return []
    if isinstance(audio, list):
        return [s for s in audio if s is not None]
    return [audio]


def _base_looks_like_groq(base: str) -> bool:
    b = (base or "").strip().lower()
    return "groq.com" in b


def _resolve_openai_compat_key(base_url: str) -> str:
    """OPENAI_API_KEY, or GROQ_API_KEY when base_url points at Groq."""
    key = _resolve_key("OPENAI_API_KEY")
    if key:
        return key
    base = (base_url or os.environ.get("OPENAI_BASE_URL") or "").strip()
    if _base_looks_like_groq(base):
        return _resolve_key("GROQ_API_KEY")
    return ""


class AsrTranscribeNode(Node):
    """Transcribe audio to a typed Transcript via HTTP ASR or local Whisper."""

    node_type: ClassVar[str] = "asr_transcribe"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="asr_transcribe",
        label="ASR Transcribe",
        description=(
            "Transcribe audio to text with optional word timestamps. "
            "Providers: openai_compat (default), assemblyai, deepgram, "
            "local_whisper / faster_whisper (CPU, no paid key)."
        ),
        category="Processing",
        version="1.1.0",
        tags=["asr", "speech", "transcript", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=True,
        streaming_support=False,
        realtime_support=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=list,
            cardinality="single",
            required=True,
            description="List of AudioSample objects (or a single sample)",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=object,
            description="Transcript with text, language, optional word timings",
        )
    }

    class Config(NodeConfig):
        provider: Literal[
            "openai_compat", "assemblyai", "deepgram", "local_whisper", "faster_whisper"
        ] = Field(
            default="openai_compat",
            title="Provider",
            description=(
                "ASR provider. Remote: openai_compat, assemblyai, deepgram. "
                "Local (free): local_whisper / faster_whisper via faster-whisper."
            ),
        )
        language: str = Field(default="en", title="Language", description="BCP-47 / ISO language code (e.g. en).")
        model: str = Field(
            default="",
            title="Model",
            description="Provider model id (e.g. whisper-1, tiny, base). Empty = provider default.",
        )
        base_url: str = Field(
            default="",
            title="Base URL",
            description="OpenAI-compatible base URL override (openai_compat only). Groq: https://api.groq.com/openai/v1",
        )
        timeout_s: float = Field(default=30.0, title="Timeout (s)", description="Request/operation timeout in seconds.")

    def process(self, audio):
        samples = _coerce_samples(audio)
        if not samples:
            return Transcript(text="", language=self.config.language, words=[], metadata={"empty": True})

        provider = (self.config.provider or "openai_compat").strip().lower()
        if provider in _LOCAL_PROVIDERS:
            return self._local_whisper(samples, provider_label=provider)
        if provider not in _PROVIDER_ENV:
            raise RuntimeError(
                f"AsrTranscribeNode: unknown provider {provider!r}. "
                f"Use {', '.join(_ALL_PROVIDERS)}."
            )
        if provider == "openai_compat":
            api_key = _resolve_openai_compat_key(self.config.base_url or "")
            env_hint = "OPENAI_API_KEY (or GROQ_API_KEY when base_url is Groq)"
        else:
            env_key = _PROVIDER_ENV[provider]
            api_key = _resolve_key(env_key)
            env_hint = env_key
        if not api_key:
            raise RuntimeError(
                f"AsrTranscribeNode: provider={provider!r} requires secret/env "
                f"{env_hint}. Store it with `graphyn secrets set …` or export "
                f"the env var. For a free local path use provider='local_whisper'."
            )
        return self._http_transcribe(provider, api_key, samples)

    def _local_whisper(self, samples: list, *, provider_label: str = "local_whisper") -> Transcript:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "AsrTranscribeNode: provider='local_whisper' requires the "
                "'faster-whisper' package in the runtime venv "
                "(pip install faster-whisper)."
            ) from exc

        sample = samples[0]
        path = getattr(sample, "path", "") or ""
        model_name = (self.config.model or "tiny").strip() or "tiny"
        device = "cpu"
        compute_type = "int8"
        cache_key = (model_name, device, compute_type)
        model = _WHISPER_MODELS.get(cache_key)
        if model is None:
            log.info("AsrTranscribeNode: loading faster-whisper model=%s device=%s", model_name, device)
            model = WhisperModel(model_name, device=device, compute_type=compute_type)
            _WHISPER_MODELS[cache_key] = model

        language = (self.config.language or "en").strip() or None
        # Prefer file path; fall back to in-memory float32 mono at sample_rate
        audio_arg: Any
        if path and os.path.isfile(path):
            audio_arg = path
        else:
            data = getattr(sample, "data", None)
            if data is None:
                raise RuntimeError(
                    "AsrTranscribeNode: local_whisper requires AudioSample.path "
                    "or AudioSample.data."
                )
            audio_arg = np.asarray(data, dtype=np.float32).reshape(-1)

        segments_iter, info = model.transcribe(
            audio_arg,
            language=language if language and language != "auto" else None,
            word_timestamps=True,
            vad_filter=False,
        )
        texts: list[str] = []
        words: list = []
        for seg in segments_iter:
            texts.append(seg.text or "")
            for w in getattr(seg, "words", None) or []:
                words.append(
                    WordTiming(
                        word=str(getattr(w, "word", "") or "").strip(),
                        start=float(getattr(w, "start", 0.0) or 0.0),
                        end=float(getattr(w, "end", 0.0) or 0.0),
                        speaker="",
                    )
                )
        text = " ".join(t.strip() for t in texts if t and t.strip()).strip()
        detected = getattr(info, "language", None) or self.config.language
        return Transcript(
            text=text,
            language=str(detected or self.config.language),
            words=words,
            metadata={
                "provider": provider_label,
                "model": model_name,
                "device": device,
                "compute_type": compute_type,
            },
        )

    def _http_transcribe(self, provider: str, api_key: str, samples: list) -> Transcript:
        sample = samples[0]
        path = getattr(sample, "path", "") or ""
        if provider == "openai_compat":
            return self._openai_compat(api_key, path, sample)
        if provider == "assemblyai":
            return self._assemblyai(api_key, path)
        return self._deepgram(api_key, path)

    def _http_post(self, url: str, *, headers: dict, json_body=None, data=None, files=None, timeout=30.0) -> dict:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "AsrTranscribeNode: HTTP providers require the 'httpx' package. "
                "Install httpx (e.g. pip install httpx)."
            ) from exc
        resp = httpx.post(
            url,
            headers=headers,
            json=json_body,
            data=data,
            files=files,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def _http_get(self, url: str, *, headers: dict, timeout=30.0) -> dict:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "AsrTranscribeNode: HTTP providers require the 'httpx' package. "
                "Install httpx (e.g. pip install httpx)."
            ) from exc
        resp = httpx.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def _openai_compat(self, api_key: str, path: str, sample) -> Transcript:
        base = (
            self.config.base_url
            or os.environ.get("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        url = f"{base}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {api_key}"}
        model = self.config.model or ("whisper-large-v3-turbo" if _base_looks_like_groq(base) else "whisper-1")
        if not path:
            raise RuntimeError(
                "AsrTranscribeNode: openai_compat requires AudioSample.path to a readable audio file."
            )
        with open(path, "rb") as fh:
            files = {"file": (os.path.basename(path), fh, "application/octet-stream")}
            data = {"model": model, "language": self.config.language, "response_format": "verbose_json"}
            body = self._http_post(url, headers=headers, data=data, files=files, timeout=self.config.timeout_s)
        text = str(body.get("text") or "")
        words = []
        for w in body.get("words") or []:
            words.append(
                WordTiming(
                    word=str(w.get("word") or ""),
                    start=float(w.get("start") or 0.0),
                    end=float(w.get("end") or 0.0),
                    speaker=str(w.get("speaker") or ""),
                )
            )
        return Transcript(
            text=text,
            language=str(body.get("language") or self.config.language),
            words=words,
            metadata={"provider": "openai_compat", "base_url": base},
        )

    def _assemblyai(self, api_key: str, path: str) -> Transcript:
        if not path:
            raise RuntimeError(
                "AsrTranscribeNode: assemblyai requires AudioSample.path to a readable audio file."
            )
        return self._assemblyai_run(api_key, path)

    def _assemblyai_run(self, api_key: str, path: str) -> Transcript:
        headers = {"authorization": api_key}
        with open(path, "rb") as fh:
            up = self._http_post(
                "https://api.assemblyai.com/v2/upload",
                headers=headers,
                data=fh.read(),
                timeout=self.config.timeout_s,
            )
        audio_url = up.get("upload_url")
        if not audio_url:
            raise RuntimeError("AsrTranscribeNode: AssemblyAI upload did not return upload_url.")
        created = self._http_post(
            "https://api.assemblyai.com/v2/transcript",
            headers={**headers, "content-type": "application/json"},
            json_body={"audio_url": audio_url, "language_code": self.config.language},
            timeout=self.config.timeout_s,
        )
        tid = created.get("id")
        if not tid:
            raise RuntimeError(
                "AsrTranscribeNode: AssemblyAI create-transcript JSON is not the final "
                "transcript (missing id). Poll GET /v2/transcript/{id} until completed."
            )
        body = created
        deadline = time.monotonic() + max(float(self.config.timeout_s or 30.0), 5.0)
        while True:
            status = str(body.get("status") or "").lower()
            if status == "completed":
                break
            if status in ("error", "failed"):
                raise RuntimeError(
                    f"AsrTranscribeNode: AssemblyAI transcript failed: {body.get('error') or body}"
                )
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"AsrTranscribeNode: AssemblyAI poll timed out waiting for transcript {tid}."
                )
            time.sleep(0.25)
            body = self._http_get(
                f"https://api.assemblyai.com/v2/transcript/{tid}",
                headers=headers,
                timeout=self.config.timeout_s,
            )
        text = str(body.get("text") or "")
        words = []
        for w in body.get("words") or []:
            words.append(
                WordTiming(
                    word=str(w.get("text") or ""),
                    start=float(w.get("start") or 0) / 1000.0,
                    end=float(w.get("end") or 0) / 1000.0,
                    speaker=str(w.get("speaker") or ""),
                )
            )
        return Transcript(
            text=text,
            language=self.config.language,
            words=words,
            metadata={"provider": "assemblyai", "id": tid, "status": "completed"},
        )

    def _deepgram(self, api_key: str, path: str) -> Transcript:
        if not path:
            raise RuntimeError("AsrTranscribeNode: deepgram requires AudioSample.path to a readable audio file.")
        headers = {"Authorization": f"Token {api_key}", "Content-Type": "application/octet-stream"}
        with open(path, "rb") as fh:
            raw = fh.read()
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "AsrTranscribeNode: HTTP providers require the 'httpx' package. "
                "Install httpx (e.g. pip install httpx)."
            ) from exc
        model = self.config.model or "nova-2"
        url = f"https://api.deepgram.com/v1/listen?model={model}&punctuate=true"
        resp = httpx.post(url, headers=headers, content=raw, timeout=self.config.timeout_s)
        resp.raise_for_status()
        body = resp.json()
        alt = (((body.get("results") or {}).get("channels") or [{}])[0].get("alternatives") or [{}])[0]
        text = str(alt.get("transcript") or "")
        words = []
        for w in alt.get("words") or []:
            words.append(
                WordTiming(
                    word=str(w.get("word") or ""),
                    start=float(w.get("start") or 0.0),
                    end=float(w.get("end") or 0.0),
                    speaker=str(w.get("speaker") or ""),
                )
            )
        return Transcript(text=text, language=self.config.language, words=words, metadata={"provider": "deepgram"})
