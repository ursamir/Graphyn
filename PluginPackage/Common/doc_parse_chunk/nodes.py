"""DocParseChunkNode — ingest text/md/html files and split into chunks."""
from __future__ import annotations

import hashlib
import importlib
import logging
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import ClassVar
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
        _types = importlib.import_module("doc_parse_chunk.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

Chunk = _types.Chunk

log = logging.getLogger(__name__)

_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".html", ".htm", ".text"}
_HEADING = re.compile(r"(?m)^(#{1,6}\s+.+|[A-Z][^\n]{0,80}\n[=-]{3,}\s*)$")


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self._skip = True
        if tag in {"p", "div", "h1", "h2", "h3", "h4", "br", "li", "tr"}:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "".join(self._parts))


def _read_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in {".html", ".htm"}:
        parser = _HTMLText()
        parser.feed(raw)
        return parser.text()
    return raw


def _try_unstructured(path: Path) -> str | None:
    try:
        from unstructured.partition.auto import partition  # type: ignore
    except ImportError:
        return None
    try:
        elements = partition(filename=str(path))
        return "\n\n".join(str(el) for el in elements if str(el).strip())
    except Exception as exc:
        log.warning("DocParseChunkNode: unstructured failed on %s (%s)", path, exc)
        return None


def _split_structure(text: str, max_chars: int) -> list[str]:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []
    # Split on markdown/underline headings, then paragraphs.
    parts = re.split(r"(?m)(?=^#{1,6}\s+)", text)
    chunks: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        paras = re.split(r"\n\s*\n", part)
        buf = ""
        for para in paras:
            para = para.strip()
            if not para:
                continue
            if buf and len(buf) + 2 + len(para) > max_chars:
                chunks.append(buf.strip())
                buf = para
            else:
                buf = f"{buf}\n\n{para}".strip() if buf else para
        if buf:
            chunks.append(buf.strip())
    # Hard-wrap oversize
    out: list[str] = []
    for c in chunks:
        if len(c) <= max_chars:
            out.append(c)
            continue
        for i in range(0, len(c), max_chars):
            out.append(c[i : i + max_chars])
    return out


def _iter_files(root: Path, recursive: bool) -> list[Path]:
    if root.is_file():
        return [root]
    if not root.is_dir():
        return []
    pattern = "**/*" if recursive else "*"
    files = []
    for p in sorted(root.glob(pattern)):
        if p.is_file() and p.suffix.lower() in _TEXT_SUFFIXES:
            files.append(p)
    return files


class DocParseChunkNode(Node):
    """Parse local text/md/html files (or a folder) into Chunk objects."""

    node_type: ClassVar[str] = "doc_parse_chunk"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="doc_parse_chunk",
        label="Doc Parse Chunk",
        description=(
            "Ingest text/markdown/HTML files and split on headings/paragraphs into "
            "Chunk objects. Optional unstructured parser; default is stdlib."
        ),
        category="Input",
        version="1.0.0",
        tags=["document", "chunk", "ingest", "common"],
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
            data_type=object | None,
            cardinality="single",
            required=False,
            description="Optional override path (str) or list of paths; else config.path",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=list,
            description="List of Chunk objects",
        )
    }

    class Config(NodeConfig):
        path: str = Field(default='', title="Path", description="Path under workspace/datasets/input (or another workspace path).")
        recursive: bool = Field(default=True, title="Recursive", description="Walk subdirectories.")
        max_chars: int = Field(default=1200, title="Max Chars", description="Max Chars.")
        use_unstructured: bool = Field(default=False, title="Use Unstructured", description="Enable use unstructured.")

    def process(self, value):
        paths: list[Path] = []
        if isinstance(value, str) and value.strip():
            paths.append(Path(value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    paths.append(Path(item))
                elif isinstance(item, Path):
                    paths.append(item)
        cfg_path = (self.config.path or "").strip()
        if cfg_path:
            paths.append(Path(cfg_path))
        if not paths:
            return []

        files: list[Path] = []
        for p in paths:
            files.extend(_iter_files(p, self.config.recursive))
        if not files:
            return []

        chunks: list = []
        idx = 0
        for fp in files:
            text = None
            if self.config.use_unstructured:
                text = _try_unstructured(fp)
            if text is None:
                try:
                    text = _read_text(fp)
                except OSError as exc:
                    log.warning("DocParseChunkNode: cannot read %s (%s)", fp, exc)
                    continue
            pieces = _split_structure(text, int(self.config.max_chars) or 1200)
            for piece in pieces:
                digest = hashlib.sha256(f"{fp}:{idx}:{piece[:64]}".encode("utf-8")).hexdigest()[:12]
                chunks.append(
                    Chunk(
                        text=piece,
                        source=str(fp),
                        page=None,
                        chunk_id=f"{fp.stem}-{idx:04d}-{digest}",
                        metadata={"suffix": fp.suffix.lower()},
                    )
                )
                idx += 1
        return chunks
