#!/usr/bin/env python3
"""Materialize + validate all marketplace templates against a plugin-loaded registry."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def main() -> int:
    from app.core.ir.loader import load_ir
    from app.core.nodes.registry import NodeRegistry
    from app.core.pipeline_template_materializer import (
        load_marketplace_catalog,
        materialize_template_entry,
    )
    from app.core.plugins.manager import PluginManager
    from app.core.plugins.venv_manager import PluginVenvManager
    from app.core.validation import validate_graph_ir

    plugins_root = Path(os.environ.get("GRAPHYN_PLUGINS_DIR") or (REPO / "PluginPackage"))
    reg = NodeRegistry()
    tmp = Path(tempfile.mkdtemp(prefix="graphyn_validate_plugins_"))
    mgr = PluginManager(registry=reg, base_dir=str(tmp))
    mgr._plugins_dir = str(tmp)

    installed = 0
    install_errors = []
    with patch.object(PluginVenvManager, "ensure", return_value=Path("/tmp/fake-venv/bin/python")):
        for toml in sorted(plugins_root.rglob("plugin.toml")):
            src = str(toml.parent) + "/"
            try:
                mgr.install(src)
                installed += 1
            except Exception as exc:
                install_errors.append((src, str(exc)[:200]))

    catalog = load_marketplace_catalog()
    templates = catalog.get("templates") or []
    ok = 0
    fail = 0
    failures = []
    unk_types = Counter()
    mat_fail = 0

    for entry in templates:
        tid = entry.get("id")
        try:
            graph_dict = materialize_template_entry(entry)
            graph = load_ir(graph_dict)
            errors = validate_graph_ir(graph, reg)
            if errors:
                fail += 1
                for e in errors:
                    if "Unknown node type" in e:
                        # e like "[n0] Unknown node type 'foo'. Available: ..."
                        try:
                            nt = e.split("Unknown node type '")[1].split("'")[0]
                            unk_types[nt] += 1
                        except Exception:
                            pass
                failures.append({"id": tid, "errors": errors[:5]})
            else:
                ok += 1
        except Exception as exc:
            mat_fail += 1
            fail += 1
            failures.append({"id": tid, "errors": [f"EXCEPTION: {exc}"]})

    total = len(templates)
    pct = (100.0 * ok / total) if total else 0.0
    try:
        reg_count = len(list(reg))
    except Exception:
        reg_count = len(getattr(reg, "_nodes", {}))
    summary = {
        "plugins_installed": installed,
        "plugin_install_errors": install_errors[:20],
        "plugin_install_error_count": len(install_errors),
        "templates_total": total,
        "validate_ok": ok,
        "validate_fail": fail,
        "materialize_or_load_fail": mat_fail,
        "ok_pct": round(pct, 2),
        "unknown_node_types": dict(unk_types.most_common(40)),
        "sample_failures": failures[:30],
        "registry_node_types": reg_count,
    }
    out = REPO / "docs" / "_gen" / "marketplace_validate_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in summary if k not in ("sample_failures", "plugin_install_errors")}, indent=2))
    print(f"wrote {out}")
    return 0 if pct >= 95.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
