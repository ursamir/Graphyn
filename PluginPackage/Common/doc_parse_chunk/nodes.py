"""DocParseChunkNode — ingest text/md/html files and split into chunks."""
from __future__ import annotations

import hashlib
import importlib
import logging
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import ClassVar, Literal
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


def _try_unstructured(path: Path) -> str:
    try:
        from unstructured.partition.auto import partition  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "DocParseChunkNode: use_unstructured=True needs the unstructured package "
            "(pip install 'unstructured[local-inference]'). Leave use_unstructured=False "
            "to use the built-in text/md/html reader."
        ) from exc
    elements = partition(filename=str(path))
    text = "\n\n".join(str(el) for el in elements if str(el).strip())
    if not text.strip():
        raise ValueError(f"DocParseChunkNode: unstructured produced no text from {path}")
    return text


def _split_fixed(text: str, max_chars: int, overlap: int) -> list[str]:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []
    max_chars = max(1, int(max_chars) or 1200)
    overlap = max(0, min(int(overlap) or 0, max_chars - 1))
    step = max(1, max_chars - overlap)
    return [text[i : i + max_chars] for i in range(0, len(text), step)]


def _split_recursive(text: str, max_chars: int, overlap: int) -> list[str]:
    """Split on blank lines, then sentences, then hard wrap; apply overlap."""
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []
    max_chars = max(1, int(max_chars) or 1200)
    units = [u.strip() for u in re.split(r"\n\s*\n", text) if u.strip()]
    if len(units) == 1 and len(units[0]) > max_chars:
        units = [s.strip() for s in re.split(r"(?<=[.!?])\s+", units[0]) if s.strip()] or units
    chunks: list[str] = []
    buf = ""
    for u in units:
        if buf and len(buf) + 1 + len(u) > max_chars:
            chunks.append(buf)
            if overlap > 0 and len(buf) > overlap:
                buf = buf[-overlap:] + " " + u
            else:
                buf = u
        else:
            buf = f"{buf} {u}".strip() if buf else u
        while len(buf) > max_chars:
            chunks.append(buf[:max_chars])
            buf = buf[max(0, max_chars - max(0, int(overlap) or 0)) :]
    if buf:
        chunks.append(buf)
    return chunks


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
        version="1.1.0",
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
        path: str = Field(default='', title="Path", description="Dataset path under workspace/ (relative path preferred).")
        recursive: bool = Field(default=True, title="Recursive", description="Walk subdirectories when scanning the filesystem (On/Off).")
        max_chars: int = Field(default=1200, title="Max chars", description="Maximum characters per chunk when splitting documents.")
        use_unstructured: bool = Field(default=False, title="Use Unstructured", description="Parse with the optional unstructured package (PDF/DOCX/etc). False = built-in text/md/html reader.")
        chunk_strategy: Literal["structure", "fixed", "recursive", "markdown"] = Field(
            default="structure",
            title="Chunk strategy",
            description="Chunking strategy. One of: structure, fixed, recursive, markdown.",
        )
        overlap: int = Field(default=0, title="Overlap", description="Character overlap between adjacent chunks (0 disables).")
        metadata_keys: list[str] = Field(
            default_factory=list,
            title="Metadata keys",
            description="File attributes copied onto each Chunk's metadata: name, stem, suffix, parent, size, mtime (suffix is always set).",
        )

    _META_KEYS = ("name", "stem", "suffix", "parent", "size", "mtime")

    def _file_meta(self, fp: Path) -> dict:
        meta: dict = {"suffix": fp.suffix.lower()}
        for key in self.config.metadata_keys or []:
            if key not in self._META_KEYS:
                raise ValueError(
                    f"DocParseChunkNode: unknown metadata key {key!r}; choose from {', '.join(self._META_KEYS)}"
                )
            if key in ("size", "mtime"):
                st = fp.stat()
                meta[key] = st.st_size if key == "size" else st.st_mtime
            elif key == "parent":
                meta[key] = str(fp.parent)
            else:
                meta[key] = getattr(fp, key) if key != "suffix" else fp.suffix.lower()
        return meta

    def process(self, value):
        # Canonical payload contract (F-06): strings, Paths, wrappers (python_code,
        # csv_table, http_request …), dicts with path/paths/files, ArtifactRefs.
        try:
            from app.core.nodes.payload import payload_paths
            raw = payload_paths(value)
        except Exception:  # pragma: no cover - older core
            raw = [value] if isinstance(value, str) else [v for v in (value or []) if isinstance(v, (str, Path))] if isinstance(value, list) else []
        paths: list[Path] = [Path(str(p)) for p in raw if str(p).strip()]
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
            else:
                try:
                    text = _read_text(fp)
                except OSError as exc:
                    log.warning("DocParseChunkNode: cannot read %s (%s)", fp, exc)
                    continue
            max_c = int(self.config.max_chars) or 1200
            ov = int(self.config.overlap) or 0
            strat = self.config.chunk_strategy
            if strat in ("structure", "markdown"):
                pieces = _split_structure(text, max_c)
                if ov > 0 and len(pieces) > 1:
                    # Soft overlap: prepend the tail of the previous chunk.
                    with_ov: list[str] = [pieces[0]]
                    for i in range(1, len(pieces)):
                        prev = pieces[i - 1]
                        with_ov.append((prev[-ov:] + "\n\n" + pieces[i]).strip() if len(prev) > ov else pieces[i])
                    pieces = with_ov
            elif strat == "fixed":
                pieces = _split_fixed(text, max_c, ov)
            elif strat == "recursive":
                pieces = _split_recursive(text, max_c, ov)
            else:
                raise ValueError(
                    f"DocParseChunkNode: unknown chunk_strategy {strat!r}. "
                    "Choose from: structure, fixed, recursive, markdown"
                )
            for piece in pieces:
                digest = hashlib.sha256(f"{fp}:{idx}:{piece[:64]}".encode("utf-8")).hexdigest()[:12]
                chunks.append(
                    Chunk(
                        text=piece,
                        source=str(fp),
                        page=None,
                        chunk_id=f"{fp.stem}-{idx:04d}-{digest}",
                        metadata=self._file_meta(fp),
                    )
                )
                idx += 1
        return chunks
