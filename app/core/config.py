# app/core/config.py
"""
Bounded Context:  Platform Infrastructure (shared by all BCs)
Responsibility:   Centralised path and environment variable resolution.
                  Single source of truth for all filesystem paths and
                  environment-driven configuration.
Owns:             All path accessor functions (graphyn_home, plugins_home,
                  project_dir, runs_dir, artifacts_dir, cache_dir,
                  provenance_dir, datasets_input_dir, datasets_output_dir,
                  webhooks_path) and api_token(), redis_url(),
                  plugin_allowed_sources().
Public Surface:   All functions above.
Must NOT:         Import from any other app module. Pure stdlib only.
                  Must never cache env var reads at module level (token
                  rotation must take effect without process restart).
Dependencies:     stdlib (os, pathlib).
Reason To Change: New environment variables are added, directory layout
                  changes, or the three-tier model is restructured.

## Environment variables

  GRAPHYN_HOME                    Default: ~/.graphyn/
  GRAPHYN_PROJECT_DIR             Default: workspace/
  GRAPHYN_API_TOKEN               Default: "" (no auth in development)
  GRAPHYN_ENV                     Default: development
  GRAPHYN_AUTH_REQUIRED           Default: "" (see auth_required())
  GRAPHYN_PLUGINS_DIR             Default: plugins/
  GRAPHYN_PLUGIN_AUTO_INSTALL     Default: "" (disabled — pip deps)
  GRAPHYN_AUTO_INSTALL_PLUGINS    Default: true when GRAPHYN_ENV=production
  GRAPHYN_PLUGIN_PACKAGE_DIR      Default: <repo>/PluginPackage
  GRAPHYN_SKIP_PLUGIN_LOAD        Default: "" (set 1 to skip bundled install+load)
  GRAPHYN_PLUGIN_INDEX_URL        Default: "" (no remote index)
  GRAPHYN_PLUGIN_ALLOWED_SOURCES  Default: "" (all sources allowed)
  GRAPHYN_PLUGIN_VENVS_DIR        Default: {GRAPHYN_HOME}/plugins/venvs/
  GRAPHYN_PLUGIN_ISOLATED_TIMEOUT Default: 3600 (seconds; isolated worker subprocess)
  GRAPHYN_REDIS_URL               Default: "" (use in-process store)

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
    """Return the value of env var *name*, stripped, or *default* if unset/empty.

    If the env var is set to a non-empty but whitespace-only string (e.g. ``"   "``),
    a warning is emitted and *default* is returned.  This prevents silent
    security bypasses such as a whitespace-only ``GRAPHYN_API_TOKEN`` silently
    disabling authentication.
    """
    import logging
    raw = os.environ.get(name, "")
    stripped = raw.strip()
    if raw and not stripped:
        logging.getLogger(__name__).warning(
            "Env var %s is set to whitespace-only; using default %r", name, default
        )
    return stripped or default


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


def plugin_package_dir() -> Path:
    """Return the bundled PluginPackage source tree.

    Default: ``{repo_root}/PluginPackage`` (two parents above this file).
    Override: ``GRAPHYN_PLUGIN_PACKAGE_DIR``.
    """
    override = os.environ.get("GRAPHYN_PLUGIN_PACKAGE_DIR", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "PluginPackage"


def skip_plugin_load() -> bool:
    """True when GRAPHYN_SKIP_PLUGIN_LOAD is 1/true/yes."""
    return _env("GRAPHYN_SKIP_PLUGIN_LOAD").lower() in ("1", "true", "yes")


def auto_install_plugins() -> bool:
    """Whether to install every PluginPackage/*/*/plugin.toml at startup.

    GRAPHYN_AUTO_INSTALL_PLUGINS=1/true/yes forces on.
    GRAPHYN_AUTO_INSTALL_PLUGINS=0/false/no forces off (empty catalog still
    triggers install — see initialize_registry).
    Unset defaults to True when GRAPHYN_ENV is production/prod.
    """
    raw = os.environ.get("GRAPHYN_AUTO_INSTALL_PLUGINS")
    if raw is not None and raw.strip() != "":
        return raw.strip().lower() in ("1", "true", "yes")
    return graphyn_env() in ("production", "prod")


def plugin_venvs_dir() -> Path:
    """Return the directory for per-plugin isolated virtualenvs.

    Default: ``{graphyn_home()}/plugins/venvs/``
    Override: ``GRAPHYN_PLUGIN_VENVS_DIR`` env var.
    """
    override = os.environ.get("GRAPHYN_PLUGIN_VENVS_DIR", "").strip()
    if override:
        return Path(override)
    return graphyn_home() / "plugins" / "venvs"


def plugin_allowed_sources() -> list[str]:
    """Return the list of allowed plugin source URL prefixes.

    Override: GRAPHYN_PLUGIN_ALLOWED_SOURCES env var — comma-separated URL
    prefixes (e.g. ``"https://plugins.example.com/,git+https://github.com/myorg/"``).

    When the env var is unset or empty, all sources are allowed (backward
    compatible default). When set, ``PluginInstaller.resolve()`` rejects any
    remote source that does not start with one of the listed prefixes.

    Local path sources (no ``git+``, ``http://``, ``https://`` prefix) are
    never subject to the allowlist — they are always permitted.

    When the env var is set, the same prefix check must also be applied to
    plugin-index ``download_url`` values, HTTP redirect targets, and PEP 508
    direct-reference URLs in plugin requirements.
    """
    raw = _env("GRAPHYN_PLUGIN_ALLOWED_SOURCES")
    if not raw:
        return []
    result = [prefix.strip() for prefix in raw.split(",") if prefix.strip()]
    if not result:
        raise ValueError(
            f"GRAPHYN_PLUGIN_ALLOWED_SOURCES={raw!r} parsed to an empty list; "
            "check for stray commas. Set to empty string to allow all sources."
        )
    return result



def plugin_source_is_allowed(source: str) -> bool:
    """Return True if *source* is permitted by GRAPHYN_PLUGIN_ALLOWED_SOURCES.

    Empty allowlist (unset env) → allow all. Local paths without a remote
    scheme are always allowed.
    """
    if not source.startswith(("git+", "http://", "https://")):
        return True
    allowed = plugin_allowed_sources()
    if not allowed:
        return True
    return any(source.startswith(prefix) for prefix in allowed)


def plugin_isolated_timeout() -> float:
    """Return isolated worker subprocess timeout in seconds.

    Override: ``GRAPHYN_PLUGIN_ISOLATED_TIMEOUT`` (float/int seconds).
    Default: 3600. Must be finite and positive.
    """
    raw = os.environ.get("GRAPHYN_PLUGIN_ISOLATED_TIMEOUT", "").strip()
    if not raw:
        return 3600.0
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(
            f"GRAPHYN_PLUGIN_ISOLATED_TIMEOUT={raw!r} is not a number"
        ) from exc
    if value <= 0:
        raise ValueError(
            f"GRAPHYN_PLUGIN_ISOLATED_TIMEOUT={raw!r} must be > 0"
        )
    return value


# ---------------------------------------------------------------------------
# Tier 2 — Project directory  (runs, artifacts, datasets, provenance)
# ---------------------------------------------------------------------------

def project_dir() -> Path:
    """Return the Graphyn project directory (runtime data root).

    Default: workspace/ (relative to CWD)
    Override: GRAPHYN_PROJECT_DIR env var.

    The returned path is made absolute so that ``..`` components and relative
    paths are normalised consistently regardless of the current working
    directory.  ``.absolute()`` is used instead of ``.resolve()`` to avoid
    an ``OSError`` on platforms where the process CWD has been deleted while
    the server is running (``resolve()`` follows symlinks and stat()s the
    path, which fails if CWD is gone).
    """
    return Path(_env("GRAPHYN_PROJECT_DIR", default="workspace")).absolute()


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

def secrets_dir() -> Path:
    """Return the named-secret directory: {graphyn_home}/secrets/ (mode 0700)."""
    return graphyn_home() / "secrets"


def graphyn_env() -> str:
    """Return GRAPHYN_ENV (default development)."""
    return _env("GRAPHYN_ENV", default="development").lower()


def auth_required() -> bool:
    """True when API/MCP must reject empty GRAPHYN_API_TOKEN (fail-closed).

    GRAPHYN_AUTH_REQUIRED=1/true forces this on.
    GRAPHYN_AUTH_REQUIRED=0/false forces it off.
    Otherwise GRAPHYN_ENV in {production, prod, staging} requires a token.
    Local default GRAPHYN_ENV=development stays convenient (auth optional).
    """
    flag = _env("GRAPHYN_AUTH_REQUIRED").lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    if flag in ("0", "false", "no", "off"):
        return False
    return graphyn_env() in ("production", "prod", "staging")


def api_token() -> str:
    """Return the Graphyn API token, or empty string if not configured.

    Override: GRAPHYN_API_TOKEN env var.
    Empty string means no authentication required *unless* auth_required().
    """
    return _env("GRAPHYN_API_TOKEN")


def redis_url() -> str:
    """Return the Redis connection URL, or empty string if not configured.

    Override: GRAPHYN_REDIS_URL env var (e.g. ``"redis://localhost:6379/0"``).
    Empty string means use the in-process (dict-backed) store — backward
    compatible default for single-worker deployments.
    """
    return _env("GRAPHYN_REDIS_URL")
