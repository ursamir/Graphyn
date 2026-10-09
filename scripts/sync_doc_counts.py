#!/usr/bin/env python3
"""Keep the counts in the docs equal to what actually ships (F19 / F-21).

Counts come from the source of truth, not from memory:

* plugins / node types / packs — every ``PluginPackage/<Pack>/<plugin>/plugin.toml``
  (``node_types`` list; this is exactly what auto-install registers, see
  ``unit_test/f19/test_f19_doc_counts.py`` which cross-checks a real registry);
* MCP tools — the names ``app.mcp.tool_registry.register_all_tools`` registers,
  with and without ``GRAPHYN_MCP_HUMAN_APPROVAL=1``.

Docs carry markers that this script rewrites:

* inline  ``<!-- count:KEY -->123<!-- /count -->``
* block   ``<!-- count-block:KEY -->`` … ``<!-- /count-block -->``

Usage::

    python scripts/sync_doc_counts.py          # rewrite docs in place
    python scripts/sync_doc_counts.py --check  # exit 1 when a doc has drifted
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCS = [
    "README.md",
    "AGENTS.md",
    "docs/PLUGIN_GUIDE.md",
    "PluginPackage/NODES.md",
    "PluginPackage/ARCHITECTURE.md",
]
_INLINE = re.compile(r"<!-- count:([\w:.-]+) -->(.*?)<!-- /count -->", re.S)
_BLOCK = re.compile(r"(<!-- count-block:([\w:.-]+) -->\n)(.*?)(<!-- /count-block -->)", re.S)


def plugin_inventory(root: Path = REPO) -> dict[str, list[dict]]:
    """``{pack: [{"plugin": dir, "name": manifest name, "node_types": [...]}, ...]}``."""
    packs: dict[str, list[dict]] = {}
    for toml in sorted((root / "PluginPackage").glob("*/*/plugin.toml")):
        data = tomllib.loads(toml.read_text(encoding="utf-8"))
        node_types = data.get("node_types") or (data.get("plugin") or {}).get("node_types") or []
        packs.setdefault(toml.parent.parent.name, []).append(
            {
                "plugin": toml.parent.name,
                "name": (data.get("plugin") or {}).get("name", toml.parent.name),
                "node_types": list(node_types),
            }
        )
    return packs


def mcp_tool_names(human_approval: bool = False) -> list[str]:
    sys.path.insert(0, str(REPO))
    from app.mcp.tool_registry import register_all_tools

    saved = os.environ.get("GRAPHYN_MCP_HUMAN_APPROVAL")
    os.environ["GRAPHYN_MCP_HUMAN_APPROVAL"] = "1" if human_approval else "0"
    try:
        names: list[str] = []
        register_all_tools(lambda name, *_a, **_k: names.append(name))
    finally:
        if saved is None:
            os.environ.pop("GRAPHYN_MCP_HUMAN_APPROVAL", None)
        else:
            os.environ["GRAPHYN_MCP_HUMAN_APPROVAL"] = saved
    return sorted(set(names))


def compute_values(root: Path = REPO, *, with_mcp: bool = True) -> dict[str, str]:
    inv = plugin_inventory(root)
    all_types = sorted({t for plugins in inv.values() for p in plugins for t in p["node_types"]})
    v: dict[str, str] = {
        "packs": str(len(inv)),
        "pack_names": ", ".join(inv),
        "plugins": str(sum(len(p) for p in inv.values())),
        "node_types": str(len(all_types)),
    }
    for pack, plugins in inv.items():
        types = [t for p in plugins for t in p["node_types"]]
        v[f"pack:{pack}:plugins"] = str(len(plugins))
        v[f"pack:{pack}:node_types"] = str(len(types))
        v[f"pack:{pack}:node_list"] = ", ".join(f"`{t}`" for t in types)
    rows = ["| Pack | Plugins | Node types |", "|---|---:|---|"]
    for pack, plugins in inv.items():
        types = [t for p in plugins for t in p["node_types"]]
        rows.append(f"| {pack} | {len(plugins)} | {', '.join(f'`{t}`' for t in types)} |")
    rows.append(f"| **Total** | **{v['plugins']}** | **{v['node_types']}** |")
    v["pack_table"] = "\n".join(rows) + "\n"
    if with_mcp:
        base = mcp_tool_names(False)
        full = mcp_tool_names(True)
        v["mcp_tools"] = str(len(base))
        v["mcp_tools_with_approval"] = str(len(full))
    return v


def render(text: str, values: dict[str, str]) -> tuple[str, list[str]]:
    """Return (new_text, unknown_keys)."""
    unknown: list[str] = []

    def _inline(m: re.Match) -> str:
        key = m.group(1)
        if key not in values:
            unknown.append(key)
            return m.group(0)
        return f"<!-- count:{key} -->{values[key]}<!-- /count -->"

    def _block(m: re.Match) -> str:
        key = m.group(2)
        if key not in values:
            unknown.append(key)
            return m.group(0)
        body = values[key] if values[key].endswith("\n") else values[key] + "\n"
        return f"{m.group(1)}{body}{m.group(4)}"

    return _BLOCK.sub(_block, _INLINE.sub(_inline, text)), unknown


def sync(root: Path = REPO, *, check: bool = False, values: dict[str, str] | None = None) -> list[str]:
    """Rewrite (or, with *check*, compare) every doc. Returns drifted/unknown messages."""
    values = values if values is not None else compute_values(root)
    problems: list[str] = []
    for rel in DOCS:
        path = root / rel
        if not path.is_file():
            problems.append(f"{rel}: missing")
            continue
        old = path.read_text(encoding="utf-8")
        new, unknown = render(old, values)
        problems += [f"{rel}: unknown count key {k!r}" for k in unknown]
        if "<!-- count" not in old:
            problems.append(f"{rel}: has no count markers")
        if new != old:
            if check:
                problems.append(f"{rel}: counts are stale (run scripts/sync_doc_counts.py)")
            else:
                path.write_text(new, encoding="utf-8")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="fail instead of rewriting")
    args = ap.parse_args(argv)
    values = compute_values()
    problems = sync(check=args.check, values=values)
    print(
        f"packs={values['packs']} plugins={values['plugins']} node_types={values['node_types']} "
        f"mcp_tools={values.get('mcp_tools')} (+approval {values.get('mcp_tools_with_approval')})"
    )
    for p in problems:
        print("  " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
