#!/usr/bin/env python3
"""Regenerate docs/PLUGIN_NODE_PLATFORM_CATALOG.json from the shipped plugins.

The node contract (ports with real port types, config fields with defaults,
dependencies, runtime) is read from the plugins themselves via the plugin
manager, so the catalog cannot advertise nodes or ports that do not exist.
``purpose`` comes from the node's own metadata description (falling back to
the previous catalog entry). Removed packs (RAG, Vision, TinyML, MLOps) are
listed under ``removed_packs`` only.

Also prunes docs/PLUGIN_NODE_REFINEMENTS.json ``added_nodes`` to shipped nodes.
"""
from __future__ import annotations

import json
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
OUT = REPO / "docs" / "PLUGIN_NODE_PLATFORM_CATALOG.json"
REFINEMENTS = REPO / "docs" / "PLUGIN_NODE_REFINEMENTS.json"

from generate_pipeline_template_catalog import REMOVED_PACKS, SHIPPED_PACKS, _full_registry  # noqa: E402


def _type_name(t) -> str:
    if t is None:
        return "None"
    s = str(t) if not isinstance(t, type) else t.__name__
    for prefix in ("app.models.", "typing."):
        s = s.replace(prefix, "")
    # strip module paths like audio_sample.AudioSample -> AudioSample
    import re
    return re.sub(r"\b[a-z_]+\.(?=[A-Z])", "", s)


def main() -> int:
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.is_file() else {}
    prose = {n.get("node_type"): n for n in (old.get("nodes") or []) + (old.get("refinement_added_nodes") or [])}
    reg = _full_registry()
    # node_type -> plugin dir
    where: dict[str, Path] = {}
    for toml in sorted((REPO / "PluginPackage").rglob("plugin.toml")):
        if toml.parent.parent.name not in SHIPPED_PACKS:
            continue
        d = tomllib.loads(toml.read_text(encoding="utf-8"))
        p = d.get("plugin", d)
        for nt in p.get("node_types") or []:
            where[nt] = toml.parent
    nodes = []
    for i, nt in enumerate(sorted(reg._classes), start=1):
        cls = reg.get_class(nt)
        meta = getattr(cls, "metadata", None)
        pdir = where.get(nt)
        manifest = {}
        if pdir is not None:
            d = tomllib.loads((pdir / "plugin.toml").read_text(encoding="utf-8"))
            manifest = d.get("plugin", d)
        cfg = []
        for name, f in (getattr(cls.Config, "model_fields", {}) or {}).items():
            ann = _type_name(f.annotation)
            if f.is_required():
                cfg.append(f"{name}:{ann}")
            else:
                dv = f.default if f.default_factory is None else f.default_factory()
                cfg.append(f"{name}:{ann}={json.dumps(dv, default=str)[:60]}")
        prev = prose.get(nt) or {}
        nodes.append({
            "id": f"N{i:03d}",
            "node_type": nt,
            "pack": f"PluginPackage/{pdir.parent.name}/{pdir.name}/" if pdir else "",
            "category": getattr(meta, "category", None) or prev.get("category") or "",
            "purpose": (getattr(meta, "description", "") or "").split(". ")[0].strip() or prev.get("purpose", ""),
            "status": "Shipped",
            "runtime": manifest.get("runtime", "inprocess"),
            "inputs": [{"name": n, "type": _type_name(getattr(p, "data_type", None)), "required": bool(getattr(p, "required", True))}
                       for n, p in (getattr(cls, "input_ports", None) or {}).items()],
            "outputs": [{"name": n, "type": _type_name(getattr(p, "data_type", None))}
                        for n, p in (getattr(cls, "output_ports", None) or {}).items()],
            "config": cfg,
            "dependencies": list(manifest.get("dependencies") or []),
            "optional_dependencies": list(manifest.get("optional_dependencies") or []),
            "capabilities": prev.get("capabilities", {}),
        })
    by_pack: dict[str, int] = {}
    for n in nodes:
        pk = n["pack"].split("/")[1] if n["pack"] else "core"
        by_pack[pk] = by_pack.get(pk, 0) + 1
    doc = {
        "title": "Graphyn Plugin/Node Platform Catalog",
        "status": "generated-from-shipped-plugins",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/generate_plugin_node_platform_catalog.py",
        "shipped_packs": list(SHIPPED_PACKS),
        "removed_packs": list(REMOVED_PACKS),
        "total_node_types": len(nodes),
        "counts_by_pack": dict(sorted(by_pack.items())),
        "nodes": nodes,
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(nodes)} shipped node types -> {OUT.relative_to(REPO)}: {doc['counts_by_pack']}")
    if REFINEMENTS.is_file():
        ref = json.loads(REFINEMENTS.read_text(encoding="utf-8"))
        before = [n.get("node_type") for n in ref.get("added_nodes") or []]
        ref["added_nodes"] = [n for n in ref.get("added_nodes") or [] if n.get("node_type") in reg._classes]
        dropped = [nt for nt in before if nt not in reg._classes]
        if dropped:
            ref["pruned_removed_pack_nodes"] = sorted(set(ref.get("pruned_removed_pack_nodes", [])) | set(dropped))
            ref["resulting_total_node_types"] = len(nodes)
            REFINEMENTS.write_text(json.dumps(ref, indent=2) + "\n", encoding="utf-8")
            print(f"Pruned refinements added_nodes not shipped: {dropped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
