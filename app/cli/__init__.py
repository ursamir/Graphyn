# app/cli/__init__.py
"""
Bounded Context:  CLI Interface
Responsibility:   CLI package marker. Parsing and startup stay in main.py.
Owns:             Nothing at import time.
Public Surface:   app.cli.main:main (graphyn / python -m app.cli.main).
                  Command bodies: app.cli.cmd_*. Shared helpers: app.cli.support.
Must NOT:         Import app.cli.main here — that initializes the node registry.
Dependencies:     None.
Reason To Change: The CLI entry point moves.
"""
