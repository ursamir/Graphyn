# app/api/gzip_selective.py
"""
Bounded Context:  REST API Layer
Responsibility:   GZip compression for JSON-sized responses only — never for
                  live streams, already-compressed downloads or range replies.
Owns:             SelectiveGZipMiddleware, EXCLUDED_CONTENT_TYPES.
Public Surface:   SelectiveGZipMiddleware (added in app/api/main.py).
Must NOT:         Buffer streaming responses: gzip holds bytes until zlib's
                  window fills, so NDJSON run streams would reach the Editor
                  in bursts (or only at the end of the run). Must not depend on
                  starlette's private GZip responder classes (they differ
                  between the venv and the image's starlette versions).
Dependencies:     stdlib gzip/io, starlette.datastructures.
Reason To Change: A new streaming / binary media type is served by the API.
"""
from __future__ import annotations

import gzip
import io

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

EXCLUDED_CONTENT_TYPES: tuple[str, ...] = (
    "text/event-stream",
    "application/x-ndjson",
    "application/zip",
    "application/gzip",
    "application/x-gzip",
    "application/x-tar",
    "application/octet-stream",
    "audio/",
    "video/",
    "image/",
)


def _excluded(message: Message) -> bool:
    headers = Headers(raw=message.get("headers") or [])
    ctype = headers.get("content-type", "").lower()
    if ctype.startswith(EXCLUDED_CONTENT_TYPES):
        return True
    if "content-encoding" in headers:
        return True
    return int(message.get("status") or 200) == 206 or "content-range" in headers


class SelectiveGZipMiddleware:
    """GZip for responses ≥ ``minimum_size`` that are not excluded (see module docstring)."""

    def __init__(self, app: ASGIApp, minimum_size: int = 500, compresslevel: int = 9) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or "gzip" not in Headers(scope=scope).get("Accept-Encoding", ""):
            await self.app(scope, receive, send)
            return

        start: Message | None = None
        passthrough = False
        buf: io.BytesIO | None = None
        gz: gzip.GzipFile | None = None

        async def wrapped_send(message: Message) -> None:
            nonlocal start, passthrough, buf, gz
            mtype = message["type"]
            if mtype == "http.response.start":
                start = message
                passthrough = _excluded(message)
                if passthrough:
                    await send(message)
                return
            if mtype != "http.response.body" or passthrough:
                await send(message)
                return
            assert start is not None
            body = message.get("body", b"")
            more = message.get("more_body", False)
            if gz is None:
                if not more and len(body) < self.minimum_size:
                    await send(start)
                    await send(message)
                    passthrough = True
                    return
                buf = io.BytesIO()
                gz = gzip.GzipFile(mode="wb", fileobj=buf, compresslevel=self.compresslevel)
                headers = MutableHeaders(raw=start["headers"])
                headers["Content-Encoding"] = "gzip"
                headers.add_vary_header("Accept-Encoding")
                if more:
                    del headers["Content-Length"]
                gz.write(body)
                if not more:
                    gz.close()
                    data = buf.getvalue()
                    headers["Content-Length"] = str(len(data))
                    await send(start)
                    await send({"type": "http.response.body", "body": data})
                    return
                await send(start)
            else:
                gz.write(body)
                if not more:
                    gz.close()
            assert buf is not None
            data = buf.getvalue()
            buf.seek(0)
            buf.truncate()
            await send({"type": "http.response.body", "body": data, "more_body": more})

        await self.app(scope, receive, wrapped_send)
