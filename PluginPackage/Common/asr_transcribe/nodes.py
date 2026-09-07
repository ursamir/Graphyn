"""AsrTranscribeNode — transcribe AudioSample objects to a typed Transcript.

Providers:
    openai_compat  — HTTP POST {base}/audio/transcriptions (OPENAI_API_KEY) [default]
    assemblyai     — upload + create + POLL until completed (ASSEMBLYAI_API_KEY)
    deepgram       — Deepgram listen REST (DEEPGRAM_API_KEY)
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


class AsrTranscribeNode(Node):
    """Transcribe audio to a typed Transcript via HTTP ASR providers."""

    node_type: ClassVar[str] = "asr_transcribe"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="asr_transcribe",
        label="ASR Transcribe",
        description=(
            "Transcribe audio to text with optional word timestamps. "
            "Default provider is openai_compat (requires OPENAI_API_KEY)."
        ),
        category="Processing",
        version="1.0.0",
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
        provider: Literal["openai_compat", "assemblyai", "deepgram"] = Field(default='openai_compat', title="Provider", description="Remote ASR provider. One of: openai_compat, assemblyai, deepgram.")
        language: str = Field(default='en', title="Language", description="BCP-47 / ISO language code (e.g. en).")
        model: str = Field(default='', title="Model", description="Model.")
        base_url: str = Field(default='', title="Base URL", description="Base URL.")
        timeout_s: float = Field(default=30.0, title="Timeout S", description="Timeout in seconds.")

    def process(self, audio):
        samples = _coerce_samples(audio)
        if not samples:
            return Transcript(text="", language=self.config.language, words=[], metadata={"empty": True})

        provider = (self.config.provider or "openai_compat").strip().lower()
        if provider not in _PROVIDER_ENV:
            raise RuntimeError(
                f"AsrTranscribeNode: unknown provider {provider!r}. "
                "Use openai_compat, assemblyai, or deepgram."
            )
        env_key = _PROVIDER_ENV[provider]
        api_key = _resolve_key(env_key)
        if not api_key:
            raise RuntimeError(
                f"AsrTranscribeNode: provider={provider!r} requires secret/env "
                f"{env_key}. Store it with `graphyn secrets set {env_key}` or export "
                f"the env var."
            )
        return self._http_transcribe(provider, api_key, samples)

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
        base = (self.config.base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        url = f"{base}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {api_key}"}
        model = self.config.model or "whisper-1"
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
        return Transcript(text=text, language=str(body.get("language") or self.config.language), words=words, metadata={"provider": "openai_compat"})

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
