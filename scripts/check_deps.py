#!/usr/bin/env python3
"""Verify requirements.txt covers setup.py install_requires (DEPS gate).

Exits 0 when every non-marker package named in install_requires appears in
requirements.txt. Use --inventory to list direct app/ third-party imports
vs declared deps.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _req_name(spec: str) -> str:
    base = spec.split(";", 1)[0].strip()
    base = re.split(r"[\[<>=!~]", base, maxsplit=1)[0].strip()
    return base.lower().replace("_", "-")


def _string_list_from_assign(tree: ast.AST, name: str) -> list[str]:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    if isinstance(node.value, ast.List):
                        out = []
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                out.append(elt.value)
                        return out
    raise SystemExit(f"setup.py: could not find list assign {name!r}")


def install_requires_names() -> set[str]:
    tree = ast.parse((ROOT / "setup.py").read_text(encoding="utf-8"))
    return {_req_name(x) for x in _string_list_from_assign(tree, "_INSTALL_REQUIRES")}


def extras_names() -> set[str]:
    tree = ast.parse((ROOT / "setup.py").read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "_EXTRAS":
                    if not isinstance(node.value, ast.Dict):
                        continue
                    for val in node.value.values:
                        if isinstance(val, ast.List):
                            for elt in val.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    names.add(_req_name(elt.value))
    return names


def requirements_txt_names() -> set[str]:
    names: set[str] = set()
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        names.add(_req_name(s))
    return names


_STDLIB = set(getattr(sys, "stdlib_module_names", ())) | {
    "__future__",
    "typing_extensions",
    "tomllib",
}

_IMPORT_TO_DIST = {
    "yaml": "pyyaml",
}


def inventory_app_imports() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in (ROOT / "app").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mods = [node.module.split(".")[0]]
            for m in mods:
                if m in ("app",) or m in _STDLIB:
                    continue
                found.setdefault(m, set()).add(str(path.relative_to(ROOT)))
    return found


def main(argv: list[str]) -> int:
    req = install_requires_names()
    txt = requirements_txt_names()
    extras = extras_names()
    missing = sorted(req - txt)
    extra = sorted(txt - req)

    if "--inventory" in argv:
        inv = inventory_app_imports()
        declared = req | extras
        print("=== Direct third-party imports under app/ ===")
        for name in sorted(inv):
            dist = _IMPORT_TO_DIST.get(name, name).lower().replace("_", "-")
            if dist in req:
                where = "install_requires"
            elif dist in extras:
                where = "extras"
            else:
                where = "UNDECLARED"
            print(f"  {name:20s} -> {dist:20s} [{where}]  ({len(inv[name])} files)")
        print()

    print(f"install_requires packages: {len(req)}")
    print(f"requirements.txt packages: {len(txt)}")
    if missing:
        print("MISSING from requirements.txt:", ", ".join(missing))
    if extra:
        print("EXTRA in requirements.txt (not in install_requires):", ", ".join(extra))
    if missing:
        print("FAIL: requirements.txt out of sync with setup.py")
        return 1
    print("OK: requirements.txt covers setup.py install_requires")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
