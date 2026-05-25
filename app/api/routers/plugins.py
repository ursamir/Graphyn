# app/api/routers/plugins.py
"""
Bounded Context:  REST API Layer
Responsibility:   HTTP endpoints for plugin lifecycle management.
                  All logic delegates to PluginManager and PluginIndexClient.
Owns:             Route definitions, request/response models, error mapping,
                  remote-vs-local source detection, background task dispatch.
Public Surface:   GET/POST/DELETE /api/v1/plugins/* endpoints
Must NOT:         Contain plugin business logic — delegate to PluginManager.
                  Must not import PluginLoader, PluginStore, or PluginInstaller
                  directly.
Dependencies:     fastapi, app.core.plugins.{manager, index, errors}.
Security:         InstallRequest.expected_sha256 forwarded to PluginManager
                  for HTTP archive checksum verification (SEC-6 fix).
                  Source allowlist enforced inside PluginInstaller — rejected
                  sources surface as PluginInstallError → HTTP 502.
Reason To Change: New plugin endpoint added, or install request schema changes.

Requirements: req-07 §8.1–§8.10
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from app.core.plugins.errors import (
    PluginAlreadyInstalledError,
    PluginCompatibilityError,
    PluginDependencyError,
    PluginIndexError,
    PluginInstallError,
    PluginNotFoundError,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/plugins", tags=["plugins"])

# Shared executor for async (remote) installs
_install_executor = ThreadPoolExecutor(max_workers=4)

# ── Remote-source detection ───────────────────────────────────────────────────

_REMOTE_PREFIXES = ("git+", "http://", "https://")


def _is_remote_source(source: str) -> bool:
    """Return True when *source* is a remote URL (git+, http://, https://)."""
    return source.startswith(_REMOTE_PREFIXES)


def _parse_name_from_source(source: str) -> str:
    """Best-effort extraction of a plugin name from an arbitrary source string.

    For remote URLs the last path segment (without .git / archive extension)
    is used.  For plain names / version specifiers the name portion is returned.
    """
    from app.core.plugins.installer import PluginInstaller  # local import

    installer = PluginInstaller()
    name, _ = installer._parse_name_version(source)
    # For remote URLs _parse_name_version returns the full URL as the name;
    # extract the last meaningful path segment in that case.
    if source.startswith(_REMOTE_PREFIXES):
        # Strip query string / fragment, then take the last path segment
        clean = source.split("?")[0].split("#")[0].rstrip("/")
        segment = clean.rsplit("/", 1)[-1]
        # Remove common suffixes
        for suffix in (".git", ".zip", ".tar.gz", ".tgz"):
            if segment.endswith(suffix):
                segment = segment[: -len(suffix)]
                break
        return segment or name
    return name


# ── Error helper ──────────────────────────────────────────────────────────────

_ERROR_STATUS: dict[type, int] = {
    PluginNotFoundError: 404,
    PluginAlreadyInstalledError: 409,
    PluginCompatibilityError: 422,
    PluginDependencyError: 422,
    PluginInstallError: 502,
    PluginIndexError: 502,
}


def _plugin_http_error(exc: Exception) -> HTTPException:
    """Convert a known plugin exception to an HTTPException with a standard body."""
    status = _ERROR_STATUS.get(type(exc), 500)
    return HTTPException(
        status_code=status,
        detail={"error": type(exc).__name__, "detail": str(exc)},
    )


# ── Request / response models ─────────────────────────────────────────────────


class InstallRequest(BaseModel):
    source: str
    upgrade: bool = False
    expected_sha256: str | None = None
    """Optional SHA-256 hex digest of the downloaded archive.

    When provided for HTTP archive sources (``http://`` / ``https://`` ending
    in ``.zip`` or ``.tar.gz``), the digest is verified before extraction.
    A mismatch causes the install to fail with HTTP 502.  Ignored for local
    path and git sources (SEC-6 fix).
    """


# ── GET /plugins ──────────────────────────────────────────────────────────────


@router.get("", summary="List all installed plugins")
def list_plugins() -> list[dict[str, Any]]:
    """Return a JSON array of all installed PluginRecord objects.

    Requirements: req-07 §8.2
    """
    from app.core.plugins.manager import PluginManager

    manager = PluginManager()
    records = manager.list_installed()
    return [r.model_dump() for r in records]


# ── GET /plugins/search ───────────────────────────────────────────────────────
# NOTE: this route MUST be declared before GET /plugins/{name} so FastAPI
# matches /plugins/search before treating "search" as a {name} path param.


@router.get("/search", summary="Search the plugin index")
def search_plugins(
    q: str = Query("", description="Search query"),
) -> list[dict[str, Any]]:
    """Search the plugin index and return matching entries.

    Requirements: req-07 §8.8
    """
    from app.core.plugins.index import PluginIndexClient

    client = PluginIndexClient()
    try:
        results = client.search(q)
    except PluginIndexError as exc:
        raise _plugin_http_error(exc) from exc
    return [entry.model_dump() for entry in results]


# ── POST /plugins/install ─────────────────────────────────────────────────────


@router.post("/install", summary="Install a plugin", status_code=200)
def install_plugin(
    body: InstallRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Install a plugin from *source*.

    - **Remote sources** (git+, http://, https://): install runs in the
      background; returns ``{"status": "installing", "name": "<name>"}``
      immediately.  Poll ``GET /plugins/{name}`` for the final result.
    - **Local sources**: install runs synchronously; returns
      ``{"name": ..., "version": ..., "status": "installed"}``.

    When ``GRAPHYN_PLUGIN_ALLOWED_SOURCES`` is set, remote sources not
    matching any listed prefix are rejected with HTTP 502 (SEC-6 fix).

    Requirements: req-07 §8.3, §8.10
    """
    from app.core.plugins.manager import PluginManager

    source = body.source
    upgrade = body.upgrade
    expected_sha256 = body.expected_sha256

    if _is_remote_source(source):
        # Async path — return immediately, install in background
        parsed_name = _parse_name_from_source(source)

        def _bg_install() -> None:
            try:
                mgr = PluginManager()
                mgr.install(source, upgrade=upgrade, expected_sha256=expected_sha256)
                log.info("Background install of '%s' completed.", parsed_name)
            except Exception as exc:
                log.error(
                    "Background install of '%s' failed: %s",
                    parsed_name,
                    exc,
                    exc_info=True,
                )

        background_tasks.add_task(_bg_install)
        return {"status": "installing", "name": parsed_name}

    # Synchronous path — local source
    manager = PluginManager()
    try:
        record = manager.install(source, upgrade=upgrade, expected_sha256=expected_sha256)
    except (
        PluginNotFoundError,
        PluginAlreadyInstalledError,
        PluginCompatibilityError,
        PluginDependencyError,
        PluginInstallError,
        PluginIndexError,
    ) as exc:
        raise _plugin_http_error(exc) from exc

    return {"name": record.name, "version": record.version, "status": "installed"}


# ── POST /plugins/{name}/enable ───────────────────────────────────────────────


@router.post("/{name}/enable", summary="Enable a plugin")
def enable_plugin(name: str) -> dict[str, Any]:
    """Enable the plugin named *name* and reload its node types.

    Requirements: req-07 §8.4
    """
    from app.core.plugins.manager import PluginManager

    manager = PluginManager()
    try:
        record = manager.enable(name)
    except PluginNotFoundError as exc:
        raise _plugin_http_error(exc) from exc
    except (PluginCompatibilityError, PluginDependencyError) as exc:
        raise _plugin_http_error(exc) from exc

    return {"name": record.name, "enabled": record.enabled}


# ── POST /plugins/{name}/disable ──────────────────────────────────────────────


@router.post("/{name}/disable", summary="Disable a plugin")
def disable_plugin(name: str) -> dict[str, Any]:
    """Disable the plugin named *name* and unload its node types.

    Requirements: req-07 §8.5
    """
    from app.core.plugins.manager import PluginManager

    manager = PluginManager()
    try:
        record = manager.disable(name)
    except PluginNotFoundError as exc:
        raise _plugin_http_error(exc) from exc

    return {"name": record.name, "enabled": record.enabled}


# ── DELETE /plugins/{name} ────────────────────────────────────────────────────


@router.delete("/{name}", summary="Uninstall a plugin")
def uninstall_plugin(name: str) -> dict[str, Any]:
    """Uninstall the plugin named *name*.

    Requirements: req-07 §8.6
    """
    from app.core.plugins.manager import PluginManager

    manager = PluginManager()
    try:
        manager.uninstall(name)
    except PluginNotFoundError as exc:
        raise _plugin_http_error(exc) from exc

    return {"name": name, "status": "uninstalled"}


# ── GET /plugins/{name} ───────────────────────────────────────────────────────


@router.get("/{name}", summary="Get a specific installed plugin")
def get_plugin(name: str) -> dict[str, Any]:
    """Return the full PluginRecord for the installed plugin named *name*.

    Requirements: req-07 §8.7
    """
    from app.core.plugins.manager import PluginManager

    manager = PluginManager()
    try:
        record = manager.get(name)
    except PluginNotFoundError as exc:
        raise _plugin_http_error(exc) from exc

    return record.model_dump()
