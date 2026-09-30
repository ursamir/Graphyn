# app/__init__.py
"""
Bounded Context:  Graphyn platform package
Responsibility:   Package version and earliest host defaults (TensorFlow env).
Owns:             __version__
Public Surface:   __version__
Must NOT:         Import plugins, the API, or the CLI.
Dependencies:     app.core.ml.tf_runtime (optional, import failure is ignored)
Reason To Change: The package version or the earliest process default changes.
"""

__version__ = "0.1.0"

# Apply TF env defaults as early as possible (before plugins import TensorFlow).
try:
    from app.core.ml.tf_runtime import configure_tf_stable_defaults as _configure_tf

    _configure_tf()
except Exception:
    pass
