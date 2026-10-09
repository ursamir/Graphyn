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

import contextlib
import json
import logging
import os
import socket
import time
import shutil
import subprocess
import sys
import venv
from pathlib import Path

from app.core.plugins.dependencies import DependencyChecker
from app.core.plugins.errors import PluginDependencyError, PluginInstallError

log = logging.getLogger(__name__)

# Boot time of this process; a venv rebuilt by *another* container after this
# moment is already current and must not be wiped again (see ``remove``).
_PROCESS_START = time.time()
_BUILD_STAMP = ".graphyn-built.json"


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

    @contextlib.contextmanager
    def _venv_lock(self, plugin_name: str):
        """Exclusive cross-process lock for one plugin venv.

        Mode B shares the venvs directory between the control plane and the
        worker containers (same host kernel, same inode), so both used to
        rebuild a drifted venv at the same time and one side failed half-way
        (``ensurepip`` on a venv the other was deleting). ``flock`` serialises
        create / install / remove; the loser then finds the venv ready.
        """
        lock_dir = self._base / ".locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        with open(lock_dir / f"{plugin_name}.lock", "a+") as fh:
            try:
                import fcntl
            except ImportError:  # pragma: no cover — non-POSIX dev hosts
                yield
                return
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def ensure(
        self,
        plugin_name: str,
        requirements: list[str],
        *,
        system_site_packages: bool = False,
        one_by_one: bool = False,
    ) -> Path:
        """Create venv if needed, install *requirements*, write lockfile.

        Serialised per plugin across processes/containers (see ``_venv_lock``).
        """
        with self._venv_lock(plugin_name):
            return self._ensure_locked(
                plugin_name,
                requirements,
                system_site_packages=system_site_packages,
                one_by_one=one_by_one,
            )

    def _ensure_locked(
        self,
        plugin_name: str,
        requirements: list[str],
        *,
        system_site_packages: bool = False,
        one_by_one: bool = False,
    ) -> Path:
        """Create venv if needed, install *requirements*, write lockfile.

        Returns path to the venv's Python executable.

        *one_by_one* — install each missing requirement separately (used for
        optional extras so one bad wheel does not abort the rest).
        """
        py = self.python_bin(plugin_name)
        root = self.venv_dir(plugin_name)
        changed = False
        if py.exists() and not self._has_pip(root):
            # Half-built (creator crashed / was killed mid-ensurepip): rebuild.
            log.warning("Venv for plugin '%s' is incomplete (no pip) — rebuilding", plugin_name)
            shutil.rmtree(root, ignore_errors=True)
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
                changed = True
            except Exception as exc:
                # Never leave a half-built venv behind for the next boot/process.
                shutil.rmtree(root, ignore_errors=True)
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
                parsed = checker._parse_requirements(install_list)
                unsatisfied = checker._find_unsatisfied(parsed, python=str(py))
                if unsatisfied:
                    # pip stdout/stderr are captured — emit progress so Docker
                    # logs are not empty for 10–30 minutes of silent installs.
                    print(
                        f"graphyn: plugin '{plugin_name}' installing "
                        f"{len(unsatisfied)} package(s): "
                        f"{', '.join(unsatisfied[:6])}"
                        f"{'…' if len(unsatisfied) > 6 else ''}",
                        flush=True,
                        file=sys.stderr,
                    )
                    changed = True
                    checker.install(
                        unsatisfied,
                        python=str(py),
                        check_platform=False,
                        one_by_one=one_by_one,
                    )
                    # Re-verify rather than trusting pip's exit code alone —
                    # a package can appear to install yet still not be
                    # importable in the venv (interrupted extraction, a
                    # transient resolver failure pip itself papered over).
                    still = checker._find_unsatisfied(parsed, python=str(py))
                    if still:
                        joined = ", ".join(still)
                        raise PluginDependencyError(
                            f"Install reported success for plugin '{plugin_name}' "
                            f"but still not importable in its venv: {joined}"
                        )
                    print(
                        f"graphyn: plugin '{plugin_name}' venv packages ready",
                        flush=True,
                        file=sys.stderr,
                    )
            except PluginDependencyError:
                raise
            except Exception as exc:
                raise PluginDependencyError(
                    f"Failed installing deps for isolated plugin "
                    f"'{plugin_name}': {exc}"
                ) from exc

        self.write_lockfile(plugin_name)
        if changed:
            self._write_build_stamp(plugin_name)
        return py

    @staticmethod
    def _has_pip(root: Path) -> bool:
        return any(root.glob("lib/python*/site-packages/pip")) or (root / "Lib" / "site-packages" / "pip").exists()

    def _write_build_stamp(self, plugin_name: str) -> None:
        try:
            (self.venv_dir(plugin_name) / _BUILD_STAMP).write_text(
                json.dumps({"host": socket.gethostname(), "pid": os.getpid(), "built_at": time.time()}),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _built_elsewhere_since_boot(self, plugin_name: str) -> bool:
        """True when another host/container (re)built this venv after we booted."""
        try:
            stamp = json.loads((self.venv_dir(plugin_name) / _BUILD_STAMP).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return stamp.get("host") != socket.gethostname() and float(stamp.get("built_at") or 0) > _PROCESS_START

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
        with self._venv_lock(plugin_name):
            if self._built_elsewhere_since_boot(plugin_name):
                # Shared venvs dir (Mode B): the other container already rebuilt
                # it for the new requirements while we waited on the lock —
                # wiping it again would break that container's live runtime.
                log.info("Kept venv for plugin '%s' (rebuilt by another host since boot)", plugin_name)
                return
            if root.exists():
                shutil.rmtree(root, ignore_errors=True)
                log.info("Removed isolated venv for plugin '%s'", plugin_name)

    def gc_unused(self, installed_plugin_names: set[str]) -> list[str]:
        """Delete venvs whose plugin is not in *installed_plugin_names*."""
        removed: list[str] = []
        if not self._base.exists():
            return removed
        for child in self._base.iterdir():
            if not child.is_dir() or child.name.startswith("."):
                continue  # ".locks" and other bookkeeping dirs are not venvs
            name = child.name
            if name not in installed_plugin_names:
                shutil.rmtree(child, ignore_errors=True)
                removed.append(name)
                log.info("GC removed unused plugin venv '%s'", name)
        return removed
