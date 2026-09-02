# app/core/plugins/dependencies.py
"""
Bounded Context:  BC3 — Node Catalog (Plugin Ecosystem)
Responsibility:   Verify PEP 508 plugin dependencies against an environment,
                  report status, guard platform constraints, and optionally
                  install missing packages via pip.
Owns:             DependencyChecker, PLATFORM_CONSTRAINTS, status/conflict APIs
Public Surface:   DependencyChecker
Must NOT:         Import from app.domain, app.api, or app.models.
                  Must not register node types or touch the registry.
Dependencies:     packaging, importlib.metadata, subprocess, stdlib,
                  app.core.plugins.errors, app.core.config (lazy).
Reason To Change: Dependency resolution strategy changes, or auto-install
                  mechanism is replaced (e.g. uv instead of pip).
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version as pkg_version
from typing import Iterable

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from app.core.plugins.errors import PluginDependencyError, PluginManifestError

logger = logging.getLogger(__name__)

# Packages the platform itself relies on — plugin installs into the *shared*
# env must not violate these ranges.
PLATFORM_CONSTRAINTS: tuple[str, ...] = (
    "numpy>=1.24,<3",
    "pydantic>=2.0,<3",
    "packaging>=23.0",
)

# Installed into isolated plugin venvs so ``python -m app.core.plugins.worker``
# can import the platform package without system_site_packages (H3).
WORKER_BOOTSTRAP_REQUIREMENTS: tuple[str, ...] = (
    "pydantic>=2.0,<3",
    "packaging>=23.0",
)


@dataclass(frozen=True)
class DepStatus:
    """Status of one PEP 508 requirement in a target environment."""

    requirement: str
    name: str
    satisfied: bool
    installed_version: str | None
    optional: bool = False


class DependencyChecker:
    """Checks / installs PEP 508 deps against the current or a target Python."""

    def check(self, dependencies: list[str], *, python: str | None = None) -> None:
        """Verify every dependency is satisfied; optionally auto-install."""
        if not dependencies:
            return

        parsed = self._parse_requirements(dependencies)
        unsatisfied = self._find_unsatisfied(parsed, python=python)
        if not unsatisfied:
            return

        if python is None and self._auto_install_enabled():
            self.install(unsatisfied, python=None, check_platform=True)
            still = self._find_unsatisfied(parsed, python=None)
            if still:
                joined = ", ".join(still)
                raise PluginDependencyError(
                    f"Auto-install reported success but packages are still not "
                    f"importable in the current environment: {joined}"
                )
            return

        joined = ", ".join(unsatisfied)
        raise PluginDependencyError(f"Unsatisfied plugin dependencies: {joined}")

    def status(
        self,
        dependencies: list[str],
        *,
        optional_dependencies: list[str] | None = None,
        python: str | None = None,
    ) -> list[DepStatus]:
        """Return satisfaction status for required and optional deps."""
        rows: list[DepStatus] = []
        for dep in dependencies:
            rows.append(self._status_one(dep, optional=False, python=python))
        for dep in optional_dependencies or []:
            rows.append(self._status_one(dep, optional=True, python=python))
        return rows

    def check_conflicts(
        self,
        requirements: list[str],
        *,
        platform_constraints: Iterable[str] | None = None,
    ) -> list[str]:
        """Return human-readable conflict messages (empty = ok).

        Detects:
        - New requirements that contradict PLATFORM_CONSTRAINTS
        - New requirements that contradict already-installed versions in the
          shared env (when the installed version cannot satisfy the new pin)
        """
        constraints = list(platform_constraints or PLATFORM_CONSTRAINTS)
        conflicts: list[str] = []
        parsed_new = self._parse_requirements(requirements)
        parsed_platform = self._parse_requirements(constraints)

        # New req vs platform constraint (same package name)
        by_name: dict[str, list[Requirement]] = {}
        for req in parsed_platform + parsed_new:
            by_name.setdefault(self._normalize_dist_name(req.name), []).append(req)

        for name, reqs in by_name.items():
            if len(reqs) < 2:
                continue
            # Intersect specifiers — empty intersection ⇒ conflict
            combined = SpecifierSet()
            try:
                for req in reqs:
                    combined &= req.specifier
            except Exception:
                conflicts.append(
                    f"{name}: incompatible requirement set {[str(r) for r in reqs]}"
                )
                continue
            # If any platform constraint and any new req share a name and have
            # empty intersection when combined with installed — flag.
            platform_reqs = [r for r in reqs if str(r) in constraints or any(
                self._normalize_dist_name(Requirement(c).name) == name for c in constraints
            )]
            new_reqs = [r for r in parsed_new if self._normalize_dist_name(r.name) == name]
            if platform_reqs and new_reqs:
                inter = SpecifierSet()
                for r in platform_reqs + new_reqs:
                    inter &= r.specifier
                # packaging SpecifierSet empty means "any" when no specs; check pairs
                for pr in platform_reqs:
                    for nr in new_reqs:
                        if pr.specifier and nr.specifier:
                            # Find if there exists any version satisfying both
                            if not self._specifiers_overlap(pr.specifier, nr.specifier):
                                conflicts.append(
                                    f"{name}: platform requires {pr}, plugin requires {nr}"
                                )

        # New req vs currently installed version in shared env
        for req in parsed_new:
            normalized = self._normalize_dist_name(req.name)
            try:
                installed = pkg_version(normalized)
            except PackageNotFoundError:
                try:
                    installed = pkg_version(req.name)
                except PackageNotFoundError:
                    continue
            if req.specifier and Version(installed) not in req.specifier:
                conflicts.append(
                    f"{req}: installed {installed} in shared env does not satisfy "
                    "the new pin (refusing to upgrade platform-critical packages "
                    "silently — use runtime='isolated' or adjust the pin)"
                )

        return conflicts

    def install(
        self,
        requirements: list[str],
        *,
        python: str | None = None,
        check_platform: bool = True,
        timeout: int = 600,
    ) -> None:
        """Install *requirements* with pip into *python* (default: current)."""
        if not requirements:
            return
        self._parse_requirements(requirements)
        self._check_requirement_urls(requirements)

        if check_platform and python is None:
            conflicts = self.check_conflicts(requirements)
            # Only hard-fail on platform-constraint conflicts, not "already
            # installed wrong version" when we're about to pip-install —
            # but platform pin vs plugin pin is fatal.
            hard = [c for c in conflicts if "platform requires" in c]
            if hard:
                raise PluginDependencyError(
                    "Refusing to install into shared env due to platform "
                    "constraint conflicts:\n  - " + "\n  - ".join(hard)
                )

        exe = python or sys.executable
        cmd = [exe, "-m", "pip", "install", *requirements]
        logger.debug("Installing plugin dependencies with %s: %s", exe, requirements)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            joined = ", ".join(requirements)
            raise PluginDependencyError(
                f"pip install timed out after {timeout}s for [{joined}]."
            ) from exc

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            joined = ", ".join(requirements)
            raise PluginDependencyError(
                f"pip install failed for [{joined}].\npip stderr:\n{stderr}"
            )

        logger.info("Installed plugin dependencies: %s", ", ".join(requirements))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _check_requirement_urls(requirements: list[str]) -> None:
        """When GRAPHYN_PLUGIN_ALLOWED_SOURCES is set, reject PEP 508 URLs off-list."""
        from app.core.config import plugin_allowed_sources, plugin_source_is_allowed

        if not plugin_allowed_sources():
            return
        for dep in requirements:
            try:
                req = Requirement(dep)
            except InvalidRequirement:
                continue
            url = req.url
            if not url:
                continue
            if not plugin_source_is_allowed(url):
                raise PluginDependencyError(
                    f"PEP 508 URL requirement {dep!r} is not in "
                    "GRAPHYN_PLUGIN_ALLOWED_SOURCES."
                )

    def _status_one(
        self, dep: str, *, optional: bool, python: str | None
    ) -> DepStatus:
        req = self._parse_requirements([dep])[0]
        installed = self._installed_version(req, python=python)
        satisfied = False
        if installed is not None:
            satisfied = (not req.specifier) or (Version(installed) in req.specifier)
        return DepStatus(
            requirement=str(req),
            name=req.name,
            satisfied=satisfied,
            installed_version=installed,
            optional=optional,
        )

    @staticmethod
    def _parse_requirements(dependencies: list[str]) -> list[Requirement]:
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
        return re.sub(r"[-_.]+", "_", name).lower()

    @classmethod
    def _find_unsatisfied(
        cls, requirements: list[Requirement], *, python: str | None
    ) -> list[str]:
        unsatisfied: list[str] = []
        for req in requirements:
            installed = cls._installed_version(req, python=python)
            if installed is None:
                unsatisfied.append(str(req))
                continue
            if req.specifier and Version(installed) not in req.specifier:
                unsatisfied.append(str(req))
        return unsatisfied

    @classmethod
    def _installed_version(
        cls, req: Requirement, *, python: str | None
    ) -> str | None:
        if python is None:
            normalized = cls._normalize_dist_name(req.name)
            try:
                return pkg_version(normalized)
            except PackageNotFoundError:
                try:
                    return pkg_version(req.name)
                except PackageNotFoundError:
                    return None

        # Query another interpreter via a tiny subprocess
        code = (
            "import sys\n"
            "from importlib.metadata import version, PackageNotFoundError\n"
            f"name={req.name!r}\n"
            "try:\n"
            "    print(version(name))\n"
            "except PackageNotFoundError:\n"
            "    import re\n"
            "    n=re.sub(r'[-_.]+', '_', name).lower()\n"
            "    try:\n"
            "        print(version(n))\n"
            "    except PackageNotFoundError:\n"
            "        sys.exit(2)\n"
        )
        try:
            result = subprocess.run(
                [python, "-c", code],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception:
            return None
        if result.returncode != 0:
            return None
        return (result.stdout or "").strip() or None

    @staticmethod
    def _specifiers_overlap(a: SpecifierSet, b: SpecifierSet) -> bool:
        """Heuristic: true if some plausible version could satisfy both."""
        # Sample candidate versions from clause bounds
        candidates: set[Version] = set()
        for spec in list(a) + list(b):
            raw = getattr(spec, "version", None)
            if raw is None:
                continue
            try:
                v = Version(str(raw))
                candidates.add(v)
                # nearby bumps
                if v.release:
                    major = list(v.release) + [0, 0, 0]
                    candidates.add(Version(f"{major[0]}.{major[1]}.{major[2]}"))
            except Exception:
                continue
        # Also try common releases
        for s in ("1.0", "1.24", "1.26", "2.0", "2.15", "3.0"):
            try:
                candidates.add(Version(s))
            except Exception:
                pass
        if not candidates:
            return True
        return any((v in a and v in b) for v in candidates)

    @staticmethod
    def _auto_install_enabled() -> bool:
        try:
            from app.core.config import plugin_auto_install as _plugin_auto_install

            return _plugin_auto_install()
        except Exception:
            return False

    @classmethod
    def _auto_install(cls, unsatisfied: list[str]) -> None:
        """Backward-compatible wrapper used by older call sites/tests."""
        cls().install(unsatisfied, python=None, check_platform=True)
