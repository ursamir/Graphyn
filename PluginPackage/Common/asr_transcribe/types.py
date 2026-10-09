"""Transcript types for asr_transcribe.

Do NOT use `from __future__ import annotations` — breaks Pydantic v2 rebuild.
"""
from typing import Any

from pydantic import Field

from app.core.nodes.ports import PortDataType


class WordTiming(PortDataType):
    """A single timed word in a transcript."""

    word: str = ""
    start: float = 0.0
    end: float = 0.0
    speaker: str = ""


class Transcript(PortDataType):
    """Typed ASR output: text, language, optional word timings."""

    text: str = ""
    language: str = "en"
    words: list = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
