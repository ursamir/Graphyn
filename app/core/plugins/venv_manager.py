# app/core/plugins/venv_manager.py
"""
Bounded Context:  BC3 — Node Catalog (Plugin Ecosystem)
Responsibility:   Create and maintain per-plugin virtualenvs for isolated
                  runtime plugins, write lockfiles, and garbage-collect
                  unused venvs.
Owns:             PluginVenvManager
Public Surface:   PluginVenvManager
Must NOT:         Import from app.domain or app.api.
Dependencies:     stdlib, app.core.config, app.core.plugins.dependencies/errors
Reason To Change: Venv layout, lockfile format, or installer backend changes.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

from app.core.plugins.dependencies import DependencyChecker
from app.core.plugins.errors import PluginDependencyError, PluginInstallError

log = logging.getLogger(__name__)


class PluginVenvManager:
    """Manage ``{GRAPHYN_PLUGIN_VENVS_DIR}/<plugin>/`` environments."""

    def __init__(self, base_dir: Path | None = None) -> None:
        if base_dir is not None:
            self._base = Path(base_dir)
        else:
            from app.core.config import plugin_venvs_dir

            self._base = plugin_venvs_dir()
        self._base.mkdir(parents=True, exist_ok=True)

    def venv_dir(self, plugin_name: str) -> Path:
        return self._base / plugin_name

    def python_bin(self, plugin_name: str) -> Path:
        root = self.venv_dir(plugin_name)
        if os.name == "nt":
            return root / "Scripts" / "python.exe"
        return root / "bin" / "python"

    def lockfile_path(self, plugin_name: str) -> Path:
        return self.venv_dir(plugin_name) / "requirements.lock"

    def ensure(
        self,
        plugin_name: str,
        requirements: list[str],
        *,
        system_site_packages: bool = False,
    ) -> Path:
        """Create venv if needed, install *requirements*, write lockfile.

        Returns path to the venv's Python executable.
        """
        py = self.python_bin(plugin_name)
        root = self.venv_dir(plugin_name)
        if not py.exists():
            log.info(
                "Creating isolated venv for plugin '%s' at %s",
                plugin_name,
                root,
            )
            try:
                builder = venv.EnvBuilder(
                    with_pip=True,
                    system_site_packages=system_site_packages,
                    clear=False,
                )
                builder.create(root)
            except Exception as exc:
                raise PluginInstallError(
                    f"Failed to create venv for plugin '{plugin_name}': {exc}"
                ) from exc

        if not py.exists():
            raise PluginInstallError(
                f"Venv for plugin '{plugin_name}' has no python at {py}"
            )

        # Isolated venvs must not inherit host site-packages (would share
        # TF/Torch). Worker imports ``app`` via PYTHONPATH to the repo.
        # Install a small bootstrap set so ``import app`` works without
        # system_site_packages.
        from app.core.plugins.dependencies import WORKER_BOOTSTRAP_REQUIREMENTS

        install_list = list(WORKER_BOOTSTRAP_REQUIREMENTS) + list(requirements)
        if install_list:
            checker = DependencyChecker()
            # Skip shared-env platform conflict hard-fail for plugin pins
            # (isolation is the point). Bootstrap still uses platform ranges.
            try:
                unsatisfied = []
                parsed = checker._parse_requirements(install_list)
                unsatisfied = checker._find_unsatisfied(parsed, python=str(py))
                if unsatisfied:
                    checker.install(
                        unsatisfied,
                        python=str(py),
                        check_platform=False,
                    )
            except PluginDependencyError:
                raise
            except Exception as exc:
                raise PluginDependencyError(
                    f"Failed installing deps for isolated plugin "
                    f"'{plugin_name}': {exc}"
                ) from exc

        self.write_lockfile(plugin_name)
        return py

    def write_lockfile(self, plugin_name: str) -> Path:
        """Freeze installed packages in the plugin venv to requirements.lock."""
        py = self.python_bin(plugin_name)
        if not py.exists():
            raise PluginInstallError(
                f"Cannot write lockfile: venv missing for '{plugin_name}'"
            )
        result = subprocess.run(
            [str(py), "-m", "pip", "freeze"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise PluginDependencyError(
                f"pip freeze failed for '{plugin_name}': {result.stderr}"
            )
        path = self.lockfile_path(plugin_name)
        path.write_text(result.stdout or "", encoding="utf-8")
        return path

    def remove(self, plugin_name: str) -> None:
        root = self.venv_dir(plugin_name)
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
            log.info("Removed isolated venv for plugin '%s'", plugin_name)

    def gc_unused(self, installed_plugin_names: set[str]) -> list[str]:
        """Delete venvs whose plugin is not in *installed_plugin_names*."""
        removed: list[str] = []
        if not self._base.exists():
            return removed
        for child in self._base.iterdir():
            if not child.is_dir():
                continue
            name = child.name
            if name not in installed_plugin_names:
                shutil.rmtree(child, ignore_errors=True)
                removed.append(name)
                log.info("GC removed unused plugin venv '%s'", name)
        return removed
