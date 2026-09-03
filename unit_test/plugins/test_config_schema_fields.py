"""plugin.toml config_schema must be typed; known finite keys need enum lists."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = ROOT / "PluginPackage"

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-redef]

KNOWN_ENUM_KEYS = {
    "backend",
    "device",
    "architecture",
    "quantization",
    "feature_type",
    "source_type",
    "mode",
    "rejection_policy",
    "normalize_method",
    "on_error",
}


def _plugin_tomls() -> list[Path]:
    return sorted(PLUGIN_ROOT.rglob("plugin.toml"))


def _config_schema_entries(data: dict) -> list[tuple[str, str, dict]]:
    schema = data.get("config_schema") or {}
    if not isinstance(schema, dict):
        return []
    out: list[tuple[str, str, dict]] = []
    for node_type, fields in schema.items():
        if not isinstance(fields, dict):
            continue
        for key, spec in fields.items():
            if isinstance(spec, dict):
                out.append((str(node_type), str(key), spec))
    return out


@pytest.mark.parametrize("toml_path", _plugin_tomls(), ids=lambda p: str(p.relative_to(PLUGIN_ROOT)))
def test_config_schema_entries_have_type(toml_path: Path) -> None:
    data = tomllib.loads(toml_path.read_text())
    entries = _config_schema_entries(data)
    assert entries, f"{toml_path} has no [config_schema.*] fields"
    missing = [f"{node}.{key}" for node, key, spec in entries if "type" not in spec]
    assert not missing, f"{toml_path.name} missing type: {missing}"


@pytest.mark.parametrize("toml_path", _plugin_tomls(), ids=lambda p: str(p.relative_to(PLUGIN_ROOT)))
def test_known_enum_keys_have_enum_lists(toml_path: Path) -> None:
    data = tomllib.loads(toml_path.read_text())
    bad: list[str] = []
    for node, key, spec in _config_schema_entries(data):
        if key not in KNOWN_ENUM_KEYS:
            continue
        enum = spec.get("enum")
        if not isinstance(enum, list) or len(enum) < 2:
            bad.append(f"{node}.{key}")
    assert not bad, f"{toml_path.name} known enum keys without enum lists: {bad}"


def test_nodes_py_literal_for_known_enum_keys() -> None:
    """Pydantic Literal keeps runtime validation aligned with plugin.toml enums."""
    missing: list[str] = []
    for path in sorted(PLUGIN_ROOT.rglob("nodes.py")):
        tree = ast.parse(path.read_text())
        for class_node in tree.body:
            if not isinstance(class_node, ast.ClassDef):
                continue
            for inner in class_node.body:
                if not (isinstance(inner, ast.ClassDef) and inner.name == "Config"):
                    continue
                for stmt in inner.body:
                    if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
                        continue
                    name = stmt.target.id
                    if name not in KNOWN_ENUM_KEYS:
                        continue
                    ann = stmt.annotation
                    ok = isinstance(ann, ast.Subscript) and (
                        (isinstance(ann.value, ast.Name) and ann.value.id == "Literal")
                        or (isinstance(ann.value, ast.Attribute) and ann.value.attr == "Literal")
                    )
                    if not ok:
                        missing.append(f"{path.relative_to(ROOT)}:{class_node.name}.{name}")
    assert not missing, f"Config fields need Literal for canvas dropdowns: {missing}"


def test_trainer_model_json_schema_exposes_enums() -> None:
    import importlib.util

    path = ROOT / "PluginPackage/Common/trainer/nodes.py"
    spec = importlib.util.spec_from_file_location("graphyn_trainer_schema_under_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    trainer = mod.TrainerNode.Config.model_json_schema()["properties"]
    builder = mod.ModelBuilderNode.Config.model_json_schema()["properties"]
    assert trainer["backend"]["enum"] == ["keras", "pytorch", "auto"]
    assert trainer["device"]["enum"] == ["auto", "cpu", "gpu"]
    assert builder["architecture"]["enum"] == ["ds_cnn", "mobilenet", "simple_cnn"]
    assert builder["backend"]["enum"] == ["keras", "auto"]
    assert trainer["epochs"]["type"] == "integer"
    assert trainer["mixed_precision"]["type"] == "boolean"


def test_nodes_py_field_is_imported() -> None:
    """c466516 used Field() in Config; the name must be imported (not only inside string templates)."""
    missing: list[str] = []
    for path in sorted(PLUGIN_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text())
        uses = False
        imported = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("pydantic"):
                if any(a.name in {"Field", "*"} for a in node.names):
                    imported = True
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Field":
                uses = True
        if uses and not imported:
            missing.append(str(path.relative_to(ROOT)))
    assert not missing, f"Field() used without pydantic import: {missing}"
