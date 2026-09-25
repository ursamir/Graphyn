# app/cli/exit_codes.py
"""CLI exit codes per SRS CLI-000."""
from __future__ import annotations

EXIT_OK = 0
EXIT_GENERAL = 1
EXIT_VALIDATION = 2
EXIT_AUTH = 3
EXIT_NOT_FOUND = 4
EXIT_CONFLICT = 5
EXIT_CANCELLED = 130


class CliError(Exception):
    """Carry a normative CLI exit code + message."""

    def __init__(self, message: str, code: int = EXIT_GENERAL):
        super().__init__(message)
        self.code = int(code)
        self.message = message
