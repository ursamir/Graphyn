# app/core/plugins/dependencies.py
"""
Bounded Context:  BC3 — Node Catalog (Plugin Ecosystem)
Responsibility:   Verify that all PEP 508 dependency strings declared in a
                  plugin manifest are satisfied by the current Python
                  environment. Optionally auto-install missing packages.
Owns:             DependencyChecker.check(), _parse_requirements(),
                  _find_unsatisfied(), _auto_install().
Public Surface:   DependencyChecker.check(dependencies: list[str])
Must NOT:         Import from app.domain, app.api, or app.models.
                  Must not register node types or touch the registry.
Dependencies:     packaging, importlib.metadata, subprocess, stdlib,
                  app.core.plugins.errors, app.core.config (plugin_auto_install
                  — lazy import).
Reason To Change: Dependency resolution strategy changes, or auto-install
                  mechanism is replaced (e.g. uv instead of pip).

Optional auto-install mode (``GRAPHYN_PLUGIN_AUTO_INSTALL=1``) installs
missing packages via ``pip`` before raising an error.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version as pkg_version

from packaging.requirements import Requirement, InvalidRequirement
from packaging.version import Version

from app.core.plugins.errors import PluginDependencyError, PluginManifestError

logger = logging.getLogger(__name__)


class DependencyChecker:
    """Checks PEP 508 dependency strings against the current Python environment.

    Optionally installs missing packages when ``GRAPHYN_PLUGIN_AUTO_INSTALL`` is
    set to ``"1"`` or ``"true"`` (case-insensitive).
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, dependencies: list[str]) -> None:
        """Verify that every dependency in *dependencies* is satisfied.

        Parameters
        ----------
        dependencies:
            List of PEP 508 requirement strings (e.g. ``["scipy>=1.10",
            "numpy>=1.24"]``).  An empty list is a no-op.

        Raises
        ------
        PluginManifestError
            If any string is not a valid PEP 508 requirement.
        PluginDependencyError
            If one or more requirements are not satisfied and auto-install is
            disabled or fails.
        """
        if not dependencies:
            return

        # Step 1 — validate all strings as PEP 508 before doing any env checks
        parsed: list[Requirement] = self._parse_requirements(dependencies)

        # Step 2 — find unsatisfied requirements
        unsatisfied: list[str] = self._find_unsatisfied(parsed)

        if not unsatisfied:
            return

        # Step 3 — auto-install if the env var is set
        if self._auto_install_enabled():
            self._auto_install(unsatisfied)
            # Re-check: pip can exit 0 but install into a different environment
            # (e.g. system Python vs venv).  Verify packages are now importable.
            still_missing = self._find_unsatisfied(parsed)
            if still_missing:
                joined = ", ".join(still_missing)
                raise PluginDependencyError(
                    f"Auto-install reported success but packages are still not "
                    f"importable in the current environment: {joined}"
                )
            return

        # Step 4 — raise with the full list of unsatisfied deps
        joined = ", ".join(unsatisfied)
        raise PluginDependencyError(
            f"Unsatisfied plugin dependencies: {joined}"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_requirements(dependencies: list[str]) -> list[Requirement]:
        """Parse and validate each dependency string as a PEP 508 requirement.

        Raises
        ------
        PluginManifestError
            On the first malformed dependency string encountered.
        """
        parsed: list[Requirement] = []
        for dep in dependencies:
            try:
                parsed.append(Requirement(dep))
            except InvalidRequirement as exc:
                raise PluginManifestError(
                    f"Malformed PEP 508 dependency string {dep!r}: {exc}"
                ) from exc
        return parsed

    @staticmethod
    def _normalize_dist_name(name: str) -> str:
        """Normalize a distribution name per PEP 503 (lowercase, collapse separators).

        ``importlib.metadata`` on Python 3.9 does not normalize names, so
        ``pkg_version("Pillow")`` may raise ``PackageNotFoundError`` even when
        the distribution is registered as ``"pillow"``.  Normalizing before
        lookup avoids false-positive "unsatisfied" reports.
        """
        import re
        return re.sub(r"[-_.]+", "_", name).lower()

    @classmethod
    def _find_unsatisfied(cls, requirements: list[Requirement]) -> list[str]:
        """Return the subset of *requirements* not satisfied in the current env.

        A requirement is satisfied when:
        - The package is installed (``importlib.metadata.version`` succeeds), AND
        - The installed version matches the requirement's version specifier
          (an empty specifier always matches).

        Distribution names are normalized per PEP 503 before lookup to avoid
        false positives on Python 3.9 where ``importlib.metadata`` is
        case-sensitive.

        Returns
        -------
        list[str]
            The original requirement strings for each unsatisfied requirement,
            preserving order.  Empty list means all are satisfied.
        """
        unsatisfied: list[str] = []
        for req in requirements:
            normalized = cls._normalize_dist_name(req.name)
            try:
                installed = pkg_version(normalized)
            except PackageNotFoundError:
                # Fall back to the original name in case the dist is registered
                # under a non-normalized form (rare but possible).
                try:
                    installed = pkg_version(req.name)
                except PackageNotFoundError:
                    unsatisfied.append(str(req))
                    continue

            if req.specifier and Version(installed) not in req.specifier:
                unsatisfied.append(str(req))

        return unsatisfied

    @staticmethod
    def _auto_install_enabled() -> bool:
        """Return ``True`` when ``GRAPHYN_PLUGIN_AUTO_INSTALL`` is ``"1"`` or
        ``"true"`` (case-insensitive).

        Returns ``False`` on any import or runtime error so that a broken
        ``app.core.config`` module does not propagate an ``ImportError``
        through ``check()``.
        """
        try:
            from app.core.config import plugin_auto_install as _plugin_auto_install
            return _plugin_auto_install()
        except Exception:
            return False

    @classmethod
    def _auto_install(cls, unsatisfied: list[str]) -> None:
        """Attempt to install *unsatisfied* packages via pip.

        On success, logs the installed packages at INFO level.
        On failure, raises :class:`PluginDependencyError` with pip's stderr.

        Parameters
        ----------
        unsatisfied:
            List of PEP 508 requirement strings to install.

        Raises
        ------
        PluginDependencyError
            If ``pip install`` exits with a non-zero return code.
        """
        cmd = [sys.executable, "-m", "pip", "install", *unsatisfied]
        logger.debug("Auto-installing plugin dependencies: %s", unsatisfied)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # G4-28 fix: 5-minute timeout prevents indefinite hang
            )
        except subprocess.TimeoutExpired:
            joined = ", ".join(unsatisfied)
            raise PluginDependencyError(
                f"Auto-install timed out after 300 seconds for [{joined}]. "
                "Check your network connection or install the packages manually."
            )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            joined = ", ".join(unsatisfied)
            raise PluginDependencyError(
                f"Auto-install failed for [{joined}].\npip stderr:\n{stderr}"
            )

        logger.info(
            "Auto-installed plugin dependencies: %s",
            ", ".join(unsatisfied),
        )
