"""Wave B CLI-000 global flags + exit codes."""
from __future__ import annotations

import subprocess
import sys


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "app.cli.main", *args],
        capture_output=True,
        text=True,
    )


def test_global_flags_in_help():
    r = _run("--help")
    assert r.returncode == 0
    assert "--api-url" in r.stdout
    assert "--token" in r.stdout
    assert "--actor" in r.stdout
    assert "--json" in r.stdout


def test_validate_missing_args_exit_2():
    r = _run("validate")
    assert r.returncode == 2
