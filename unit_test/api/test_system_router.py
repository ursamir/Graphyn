# unit_test/api/test_system_router.py
"""Tests for /api/v1/system router."""
from __future__ import annotations

from datetime import timezone


class TestHealthCheck:
    def test_returns_200_with_status_and_timestamp(self, api_client):
        """GET /api/v1/system/health returns 200 with status and timestamp fields."""
        resp = api_client.get("/api/v1/system/health")
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body
        assert "timestamp" in body

    def test_status_is_ok(self, api_client):
        """GET /api/v1/system/health returns status == 'ok'."""
        resp = api_client.get("/api/v1/system/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_timestamp_is_utc(self, api_client):
        """GET /api/v1/system/health timestamp is UTC (ends with +00:00 or Z)."""
        resp = api_client.get("/api/v1/system/health")
        assert resp.status_code == 200
        timestamp = resp.json()["timestamp"]
        assert isinstance(timestamp, str)
        # UTC ISO 8601 ends with +00:00 or Z
        assert timestamp.endswith("+00:00") or timestamp.endswith("Z"), (
            f"Timestamp '{timestamp}' is not UTC (expected +00:00 or Z suffix)"
        )

    def test_timestamp_is_parseable_iso8601(self, api_client):
        """GET /api/v1/system/health timestamp is a valid ISO 8601 datetime string."""
        from datetime import datetime

        resp = api_client.get("/api/v1/system/health")
        assert resp.status_code == 200
        timestamp = resp.json()["timestamp"]
        # Should parse without error
        dt = datetime.fromisoformat(timestamp)
        # Should be timezone-aware
        assert dt.tzinfo is not None
