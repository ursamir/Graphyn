"""SelectiveGZipMiddleware: compress JSON, never streams / downloads."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.testclient import TestClient

from app.api.gzip_selective import SelectiveGZipMiddleware


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SelectiveGZipMiddleware, minimum_size=10)

    @app.get("/json")
    def j():
        return JSONResponse({"x": "y" * 5000})

    @app.get("/ndjson")
    def nd():
        def gen():
            for i in range(50):
                yield ('{"i": %d, "pad": "%s"}\n' % (i, "z" * 100)).encode()

        return StreamingResponse(gen(), media_type="application/x-ndjson")

    @app.get("/zip")
    def z():
        return Response(b"PK" + b"0" * 5000, media_type="application/zip")

    @app.get("/range")
    def r():
        return Response(b"a" * 5000, status_code=206, media_type="text/plain",
                        headers={"Content-Range": "bytes 0-4999/10000"})

    return app


def test_json_compressed_streams_and_downloads_not():
    c = TestClient(_app())
    h = {"Accept-Encoding": "gzip"}
    assert c.get("/json", headers=h).headers.get("content-encoding") == "gzip"
    nd = c.get("/ndjson", headers=h)
    assert "content-encoding" not in nd.headers
    assert nd.text.count("\n") == 50
    assert "content-encoding" not in c.get("/zip", headers=h).headers
    assert "content-encoding" not in c.get("/range", headers=h).headers
