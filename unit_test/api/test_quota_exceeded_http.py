"""F18.1: QuotaExceeded from enqueue maps to HTTP 409 quota_exceeded (not 500)."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def patch_threads(real_threads):
    yield


@pytest.mark.asyncio
async def test_quota_exceeded_handler_returns_409():
    from app.api.main import app
    from app.core.distributed.quotas import QuotaExceeded
    from starlette.requests import Request

    assert QuotaExceeded in app.exception_handlers
    handler = app.exception_handlers[QuotaExceeded]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/jobs",
        "raw_path": b"/api/v1/jobs",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 123),
        "server": ("test", 80),
    }
    request = Request(scope)
    resp = await handler(request, QuotaExceeded("Organization queue depth exceeded", kind="org"))
    assert resp.status_code == 409
    body = resp.body
    import json

    data = json.loads(body)
    code = (data.get("error") or {}).get("code") or data.get("code")
    assert code == "quota_exceeded", data
