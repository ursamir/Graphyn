# unit_test/plugins/common/test_dataset_versioner.py
"""dataset_versioner was never shipped under PluginPackage/Common/.

On-disk versioning is ``audio_exporter`` + ``app.core.mlops.dataset_versions``.
Keep this module so older imports/discovery don't 404; skip at collection.
"""
from __future__ import annotations

import pytest

pytest.skip(
    "dataset_versioner plugin was never shipped; use audio_exporter for "
    "datasets/output/<project>/vN manifests",
    allow_module_level=True,
)
