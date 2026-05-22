# app/core/config.py
"""
Graphyn — centralised path and environment variable resolution.

All platform code reads paths from this module. Never read env vars directly.

## Environment variables

  GRAPHYN_HOME               Default: ~/.graphyn/
  GRAPHYN_PROJECT_DIR        Default: workspace/
  GRAPHYN_API_TOKEN          Default: "" (no auth)
  GRAPHYN_PLUGINS_DIR        Default: plugins/
  GRAPHYN_PLUGIN_AUTO_INSTALL Default: "" (disabled)
  GRAPHYN_PLUGIN_INDEX_URL   Default: "" (no remote index)

## Three-tier directory model

  GRAPHYN_HOME          (~/.graphyn/)
      Platform-level state: plugins, shared cache, credentials.
      Survives workspace changes. Shared across all projects.

  GRAPHYN_PROJECT_DIR   (./workspace/ or any user-chosen path)
      Project-level runtime data: runs, artifacts, provenance,
      datasets, project files. Can live on an external drive.

  Platform source tree  (read-only, shipped with the package)
      Built-in nodes, templates, schemas. Never written at runtime.
"""

from __future__ import annotations

import os
from pathlib import Path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _env(name: str, default: str = "") -> str:
    """Return the value of env var *name*, stripped, or *default* if unset/empty."""
    return os.environ.get(name, "").strip() or default


# ---------------------------------------------------------------------------
# Tier 1 — Platform home  (plugins, shared cache, credentials)
# ---------------------------------------------------------------------------

def graphyn_home() -> Path:
    """Return the Graphyn platform home directory.

    Default: ~/.graphyn/
    Override: GRAPHYN_HOME env var.

    This is platform-level state — shared across all projects on this machine.
    Plugins are installed here, not in the project workspace.
    """
    return Path(_env("GRAPHYN_HOME", default=str(Path.home() / ".graphyn")))


def plugins_home() -> Path:
    """Return the directory where installed plugin packages live.

    Default: ``{graphyn_home()}/plugins/installed/``
    Override: ``GRAPHYN_PLUGINS_DIR`` env var (absolute or relative to CWD).

    Previously this returned a CWD-relative ``"plugins"`` path, which was
    inconsistent with ``plugin_registry_path()`` which lives under
    ``graphyn_home()``. Both now default to subdirectories of ``graphyn_home()``
    so the registry and the installed packages are always co-located.
    """
    override = os.environ.get("GRAPHYN_PLUGINS_DIR", "").strip()
    if override:
        return Path(override)
    return graphyn_home() / "plugins" / "installed"


def plugin_registry_path() -> Path:
    """Return the path to the plugin registry JSON file.

    Lives in GRAPHYN_HOME, not in the project workspace.
    """
    return graphyn_home() / "plugins" / "registry.json"


def plugin_index_url() -> str:
    """Return the remote plugin index URL, or empty string if not configured.

    Override: GRAPHYN_PLUGIN_INDEX_URL env var.
    """
    return _env("GRAPHYN_PLUGIN_INDEX_URL")


def plugin_index_local_path() -> Path:
    """Return the local plugin index fallback path.

    Lives in GRAPHYN_HOME, not in the project workspace.
    """
    return graphyn_home() / "plugins" / "index.json"


def plugin_auto_install() -> bool:
    """Return True when automatic pip install of plugin deps is enabled.

    Override: GRAPHYN_PLUGIN_AUTO_INSTALL=1 or =true.
    """
    return _env("GRAPHYN_PLUGIN_AUTO_INSTALL").lower() in ("1", "true")


# ---------------------------------------------------------------------------
# Tier 2 — Project directory  (runs, artifacts, datasets, provenance)
# ---------------------------------------------------------------------------

def project_dir() -> Path:
    """Return the Graphyn project directory (runtime data root).

    Default: workspace/ (relative to CWD)
    Override: GRAPHYN_PROJECT_DIR env var.

    The returned path is resolved to an absolute path so that ``..``
    components and relative paths are normalised consistently regardless
    of the current working directory.
    """
    return Path(_env("GRAPHYN_PROJECT_DIR", default="workspace")).resolve()


def runs_dir() -> Path:
    """Return the runs directory: {project_dir}/runs/"""
    return project_dir() / "runs"


def artifacts_dir() -> Path:
    """Return the artifacts directory: {project_dir}/artifacts/"""
    return project_dir() / "artifacts"


def cache_dir() -> Path:
    """Return the pipeline cache directory: {project_dir}/cache/"""
    return project_dir() / "cache"


def provenance_dir() -> Path:
    """Return the provenance directory: {project_dir}/provenance/"""
    return project_dir() / "provenance"


def datasets_input_dir() -> Path:
    """Return the ingestion input directory: {project_dir}/datasets/input/"""
    return project_dir() / "datasets" / "input"


def datasets_output_dir() -> Path:
    """Return the project output directory: {project_dir}/datasets/output/"""
    return project_dir() / "datasets" / "output"


def webhooks_path() -> Path:
    """Return the webhooks config file path: {project_dir}/webhooks.json"""
    return project_dir() / "webhooks.json"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def api_token() -> str:
    """Return the Graphyn API token, or empty string if not configured.

    Override: GRAPHYN_API_TOKEN env var.
    Empty string means no authentication required.
    """
    return _env("GRAPHYN_API_TOKEN")
