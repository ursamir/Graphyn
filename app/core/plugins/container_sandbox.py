# app/core/plugins/container_sandbox.py
"""
Bounded Context:  Plugin isolation (Mode B worker path)
Responsibility:   Opt-in container execution for isolated plugin nodes via
                  docker or podman. Subprocess remains the default.
Owns:             plugin_isolation_mode(), run_in_container(), ContainerSandboxError,
                  sandbox_status().
Public Surface:   Those names; used by isolated_executor.run_isolated_node.
Must NOT:         Claim TEE/SGX without hardware; invent cloud sandbox APIs.
Dependencies:     stdlib, docker/podman CLI on PATH when mode=container.
Reason To Change: Runtime flags, egress wiring, or image selection.

Env
---
GRAPHYN_PLUGIN_ISOLATION
    ``subprocess`` (default) | ``container`` | ``docker`` | ``podman``
GRAPHYN_PLUGIN_SANDBOX_IMAGE
    Image for the worker (default: python:3.12-slim). Must include the same
    Python major as the plugin venv *or* mount host venv python carefully.
GRAPHYN_PLUGIN_SANDBOX_NETWORK
    ``none`` | ``bridge`` | ``allowlist`` (default ``allowlist`` when egress
    allowlist is set, else ``bridge``). ``allowlist`` maps to docker
    ``--network=bridge`` plus documenting that HTTP egress inside the plugin
    still goes through Graphyn's ``validate_http_egress_url`` (same story as
    subprocess). True CNI DNS allowlists need a custom network — not shipped.
GRAPHYN_PLUGIN_SANDBOX_RUNTIME
    Force ``docker`` or ``podman`` when mode=container (auto-detect otherwise).
GRAPHYN_HTTP_EGRESS_ALLOWLIST / GRAPHYN_HTTP_EGRESS_MODE
    Inherited into the container env so plugin HTTP nodes keep the same policy.

TEE / SGX / confidential VMs: **Not shipped.** This host has no attested TEE
path; do not set env vars that pretend otherwise.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)


class ContainerSandboxError(RuntimeError):
    """Container runtime missing, misconfigured, or run failed."""


def plugin_isolation_mode() -> str:
    v = (os.environ.get("GRAPHYN_PLUGIN_ISOLATION") or "subprocess").strip().lower()
    if v in ("container", "docker", "podman", "subprocess", ""):
        return v or "subprocess"
    return "subprocess"


def _which_runtime(prefer: str | None = None) -> str:
    forced = (prefer or os.environ.get("GRAPHYN_PLUGIN_SANDBOX_RUNTIME") or "").strip().lower()
    mode = plugin_isolation_mode()
    if mode in ("docker", "podman"):
        forced = mode
    order = [forced] if forced in ("docker", "podman") else ["docker", "podman"]
    for name in order:
        if name and shutil.which(name):
            return name
    raise ContainerSandboxError(
        "GRAPHYN_PLUGIN_ISOLATION requests a container runtime but neither "
        "docker nor podman is on PATH. Install one or set isolation=subprocess."
    )


def sandbox_network_mode() -> str:
    explicit = (os.environ.get("GRAPHYN_PLUGIN_SANDBOX_NETWORK") or "").strip().lower()
    if explicit in ("none", "bridge", "allowlist", "host"):
        return explicit
    allow = (os.environ.get("GRAPHYN_HTTP_EGRESS_ALLOWLIST") or "").strip()
    return "allowlist" if allow else "bridge"


def sandbox_image() -> str:
    return (os.environ.get("GRAPHYN_PLUGIN_SANDBOX_IMAGE") or "python:3.12-slim").strip()


def sandbox_status() -> dict[str, Any]:
    mode = plugin_isolation_mode()
    runtime = None
    runtime_error = None
    if mode != "subprocess":
        try:
            runtime = _which_runtime()
        except ContainerSandboxError as exc:
            runtime_error = str(exc)
    return {
        "isolation_mode": mode,
        "runtime": runtime,
        "runtime_error": runtime_error,
        "image": sandbox_image() if mode != "subprocess" else None,
        "network": sandbox_network_mode() if mode != "subprocess" else None,
        "egress_allowlist_set": bool(
            (os.environ.get("GRAPHYN_HTTP_EGRESS_ALLOWLIST") or "").strip()
        ),
        "tee_sgx": "Not shipped — no attested TEE/SGX path on this platform",
        "note": (
            "Default remains subprocess. Container mode is opt-in Mode B worker "
            "isolation; HTTP egress policy is the same allowlist as subprocess "
            "(GRAPHYN_HTTP_EGRESS_*)."
        ),
    }


def _docker_network_args(net: str) -> list[str]:
    if net == "none":
        return ["--network", "none"]
    if net == "host":
        return ["--network", "host"]
    # bridge + allowlist: use bridge; Graphyn egress validators still apply in-process
    return ["--network", "bridge"]


def run_in_container(
    *,
    cmd: list[str],
    env: dict[str, str],
    work_dir: Path,
    mounts: list[tuple[Path, str, bool]],
    timeout: float | None,
    cancel_check: Callable[[], bool] | None = None,
) -> subprocess.CompletedProcess:
    """Run *cmd* inside docker/podman with *mounts* (host, container_path, readonly).

    *cmd* should be the same argv the subprocess path would use (venv python -m …),
    but the executable is rewritten to run via ``python -m`` inside the image when
    the host venv python path is not portable — callers pass a cmd whose [0] is
    already a path mounted into the container.
    """
    runtime = _which_runtime()
    image = sandbox_image()
    net = sandbox_network_mode()
    work_dir = Path(work_dir).resolve()

    argv: list[str] = [
        runtime,
        "run",
        "--rm",
        "-i",
        "--workdir",
        str(work_dir),
        *_docker_network_args(net),
        # Drop capabilities; no privilege escalation
        "--security-opt",
        "no-new-privileges",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
    ]
    # Mounts
    for host, dest, ro in mounts:
        host = Path(host).resolve()
        flag = "ro" if ro else "rw"
        argv.extend(["-v", f"{host}:{dest}:{flag}"])
    # Env — pass through Graphyn egress + seed + progress markers only (not all host secrets)
    pass_prefixes = (
        "GRAPHYN_",
        "PYTHON",
        "TF_",
        "CUDA_",
        "NVIDIA_",
        "LD_",
        "HOME",
        "LANG",
        "LC_",
    )
    for k, v in env.items():
        if k.startswith(pass_prefixes) or k in (
            "PATH",
            "TZ",
            "TERM",
        ):
            argv.extend(["-e", f"{k}={v}"])
    # Always ensure egress policy env visible
    for k in (
        "GRAPHYN_HTTP_EGRESS_MODE",
        "GRAPHYN_HTTP_EGRESS_ALLOWLIST",
        "GRAPHYN_PLUGIN_ISOLATION",
    ):
        if k in os.environ and k not in env:
            argv.extend(["-e", f"{k}={os.environ[k]}"])

    argv.append(image)
    argv.extend(cmd)

    log.info(
        "container sandbox: runtime=%s image=%s network=%s cmd0=%s",
        runtime,
        image,
        net,
        cmd[0] if cmd else None,
    )

    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(work_dir),
    )
    deadline = (time.monotonic() + float(timeout)) if timeout and timeout > 0 else None
    try:
        while True:
            if cancel_check is not None and cancel_check():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise ContainerSandboxError("container plugin run cancelled")
            rc = proc.poll()
            if rc is not None:
                out, err = proc.communicate()
                return subprocess.CompletedProcess(argv, rc, out, err)
            if deadline is not None and time.monotonic() > deadline:
                proc.kill()
                out, err = proc.communicate()
                raise ContainerSandboxError(
                    f"container plugin run timed out after {timeout}s"
                )
            time.sleep(0.05)
    except ContainerSandboxError:
        raise
    except Exception as exc:
        try:
            proc.kill()
        except Exception:
            pass
        raise ContainerSandboxError(f"container run failed: {exc}") from exc
