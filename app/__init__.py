"""Graphyn platform package.

``__version__`` is read by PluginLoader to enforce each plugin's
``platform_version`` specifier in ``plugin.toml``. Keep in sync with
``setup.py`` / package metadata.
"""

__version__ = "0.1.0"

# Apply TF env defaults as early as possible (before plugins import TensorFlow).
try:
    from app.core.tf_runtime import configure_tf_stable_defaults as _configure_tf

    _configure_tf()
except Exception:
    pass
