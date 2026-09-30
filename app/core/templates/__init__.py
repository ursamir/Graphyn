# app/core/templates/__init__.py
"""
Bounded Context:  Template catalog
Responsibility:   Example template seeding and marketplace graph materialization.
Owns:             Re-exports of this package's public names.
Public Surface:   lazy __getattr__ exports listed in _EXPORTS.
Must NOT:         Import heavy submodules at package import time.
Dependencies:     Submodules of this package (lazy).
Reason To Change: A public name moves to another package.
"""
from __future__ import annotations

_EXPORTS: dict[str, str] = {
    "build_graph_from_chain": "app.core.templates.pipeline_template_materializer",
    "discover_example_graphs": "app.core.templates.example_templates",
    "examples_dir": "app.core.templates.example_templates",
    "find_template": "app.core.templates.pipeline_template_materializer",
    "load_marketplace_catalog": "app.core.templates.pipeline_template_materializer",
    "materialize_template_entry": "app.core.templates.pipeline_template_materializer",
    "materialize_to_file": "app.core.templates.pipeline_template_materializer",
    "repo_root": "app.core.templates.example_templates",
    "rewrite_graph_paths": "app.core.templates.example_templates",
    "search_marketplace_templates": "app.core.templates.pipeline_template_materializer",
    "seed_example_input_datasets": "app.core.templates.example_templates",
    "sync_example_templates": "app.core.templates.example_templates",
    "templates_dir": "app.core.templates.example_templates",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    module = importlib.import_module(module_name)
    return getattr(module, name)


__all__ = sorted(_EXPORTS)
