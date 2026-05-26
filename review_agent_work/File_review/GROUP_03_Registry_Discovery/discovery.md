# Functional Review — app/core/nodes/discovery.py

**Group:** 3 — Registry & Discovery  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/nodes/discovery.py
FUNCTION:    AutoDiscovery._import_file
CATEGORY:    State Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Import a Python file as a module; for plugin files (package_prefix=None),
loads via `spec_from_file_location` using `"{parent}.{stem}"` as the module
name.

WHAT IT ACTUALLY DOES:
Unconditionally writes the module into `sys.modules[module_name]` before
`spec.loader.exec_module(module)` completes. If `exec_module` raises (syntax
error, import error, runtime error at module level), the partially-initialised
module object remains in `sys.modules` under that name. Any subsequent import
of the same module name (e.g. a retry after fixing the plugin) will find the
broken stub in `sys.modules` and return it without re-executing the file.

EVIDENCE:
```python
sys.modules[module_name] = module          # written before exec
spec.loader.exec_module(module)            # may raise — stub stays in sys.modules
return module
```

REPRODUCTION SCENARIO:
1. Plugin file `myplugin/nodes.py` has a syntax error.
2. `_import_file` writes stub to `sys.modules["myplugin.nodes"]`, then
   `exec_module` raises `SyntaxError`.
3. `_scan_directory` catches the exception and logs a warning.
4. The broken stub remains in `sys.modules`.
5. Any later `importlib.import_module("myplugin.nodes")` returns the stub
   (an empty module object) instead of re-importing the fixed file.

IMPACT:
Silent wrong result — a fixed plugin is never actually loaded in the same
process lifetime; the broken stub is returned silently.

FIX DIRECTION:
Remove from `sys.modules` on failure:
```python
sys.modules[module_name] = module
try:
    spec.loader.exec_module(module)
except Exception:
    sys.modules.pop(module_name, None)
    raise
```

--------------------------------------------------------------------
FILE:        app/core/nodes/discovery.py
FUNCTION:    AutoDiscovery._import_file
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
For plugin files, derive a module name as `"{parent}.{stem}"` where `parent`
is `path.parent.name`.

WHAT IT ACTUALLY DOES:
`path.parent.name` is the immediate parent directory name (e.g. `"audio_classifier"`).
If two different plugins in different top-level directories both have a
subdirectory with the same name (e.g. `plugins_v1/audio_classifier/nodes.py`
and `plugins_v2/audio_classifier/nodes.py`), both produce the module name
`"audio_classifier.nodes"`. The second import finds the first module in
`sys.modules` and returns it without loading the second file.

EVIDENCE:
```python
parent = path.parent.name
module_name = f"{parent}.{path.stem}" if parent else path.stem
```
No uniqueness guarantee — two plugins with the same directory name collide.

REPRODUCTION SCENARIO:
Install two plugins both named `audio_classifier` in different plugin
directories. The second plugin's `nodes.py` is silently skipped; the first
plugin's classes are returned for both.

IMPACT:
Silent wrong result — wrong node class registered under the second plugin's
node_type; behaviour is undefined.

FIX DIRECTION:
Use the full path to generate a unique module name:
```python
import hashlib
path_hash = hashlib.md5(str(path).encode()).hexdigest()[:8]
module_name = f"_graphyn_plugin_{path.parent.name}_{path_hash}.{path.stem}"
```

--------------------------------------------------------------------
FILE:        app/core/nodes/discovery.py
FUNCTION:    AutoDiscovery._process_module
CATEGORY:    Silent Failure Risk
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Inspect module and register any PortDataType / Node subclasses found.

WHAT IT ACTUALLY DOES:
Filters Node subclasses by `obj.__module__ == module.__name__`. For plugin
files loaded via `spec_from_file_location`, `module.__name__` is set to
`"{parent}.{stem}"` (e.g. `"audio_classifier.nodes"`). However, classes
defined in that module have `cls.__module__` set to whatever Python assigned
during `exec_module`, which is also `"{parent}.{stem}"` — so the filter
works. BUT: if the plugin file uses `from .utils import SomeNode` (a relative
import that re-exports a class defined in a sibling module), that class has
`__module__ == "audio_classifier.utils"`, not `"audio_classifier.nodes"`, so
it is silently skipped even though the plugin author intended it to be
registered.

EVIDENCE:
```python
if (
    issubclass(obj, Node)
    and obj is not Node
    and obj.__module__ == module.__name__   # ← filters out re-exported classes
):
    self._register_node(obj)
```

REPRODUCTION SCENARIO:
Plugin `audio_classifier/nodes.py` does:
```python
from .base_classifier import AudioClassifierNode  # defined in base_classifier.py
```
`AudioClassifierNode.__module__` is `"audio_classifier.base_classifier"`, not
`"audio_classifier.nodes"`. The class is silently not registered.

IMPACT:
Silent wrong result — plugin node not registered; pipeline execution fails
later with `NodeNotFoundError` rather than at discovery time.

FIX DIRECTION:
Document the limitation clearly, or additionally check for an explicit
`__all__` list on the module and register classes listed there regardless
of `__module__`.

--------------------------------------------------------------------
FILE:        app/core/nodes/discovery.py
FUNCTION:    AutoDiscovery.run
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Scan `nodes_dir` root and then "one level of Category_Folders (subdirectories
that contain an `__init__.py`)".

WHAT IT ACTUALLY DOES:
Step 2 iterates `nodes_path.iterdir()` and scans any subdirectory that has
an `__init__.py`. It does NOT skip the subdirectory if it is also in
`_EXCLUDED_FILES` or matches `_EXCLUDED_PREFIXES`. More importantly, it
constructs `category_prefix = f"app.core.nodes.{subdir.name}"` — this
hardcodes `"app.core.nodes"` as the parent package regardless of what
`nodes_dir` was actually passed in. If `nodes_dir` is not `app/core/nodes`
(e.g. a test fixture or a different install), the constructed module name
will be wrong and `importlib.import_module` will fail or import the wrong
module.

EVIDENCE:
```python
for subdir in sorted(nodes_path.iterdir()):
    if subdir.is_dir() and (subdir / "__init__.py").exists():
        category_prefix = f"app.core.nodes.{subdir.name}"   # hardcoded prefix
        self._scan_directory(subdir, package_prefix=category_prefix)
```

REPRODUCTION SCENARIO:
Call `AutoDiscovery(registry).run(nodes_dir="/tmp/test_nodes")`. The
category_prefix becomes `"app.core.nodes.some_subdir"`, which does not
correspond to any real package. `importlib.import_module` raises
`ModuleNotFoundError` for every file in the subdirectory.

IMPACT:
All category-folder nodes fail to load when `nodes_dir` is not the default
path; silent failure in test environments.

FIX DIRECTION:
Derive the package prefix from the actual `nodes_dir` path rather than
hardcoding it. Accept a `package_prefix` parameter in `run()`, or compute
it from the path relative to the Python path.

--------------------------------------------------------------------
FILE:        app/core/nodes/discovery.py
FUNCTION:    AutoDiscovery.run
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Scan `plugins_dir` for manifest-based plugins; warn about bare `.py` files
and subdirectories without manifests.

WHAT IT ACTUALLY DOES:
When `plugins_dir is _PLUGINS_DIR_DEFAULT`, it imports `app.core.config` to
get the default path. If `app.core.config` is not importable (e.g. missing
env var, circular import during test), the `from app.core.config import
plugins_home as _plugins_home` line raises an exception that propagates
uncaught out of `run()`, aborting the entire discovery scan — including the
already-completed `nodes_dir` scan results that were successfully registered.

EVIDENCE:
```python
if plugins_dir is _PLUGINS_DIR_DEFAULT:
    from app.core.config import plugins_home as _plugins_home
    plugins_dir = str(_plugins_home())   # may raise — no try/except
```

REPRODUCTION SCENARIO:
Run `AutoDiscovery(registry).run("app/core/nodes")` in a test environment
where `GRAPHYN_HOME` is not set and `app.core.config` raises on import.
The exception propagates; the registry is left partially populated.

IMPACT:
Partial registry population with no error surfaced to the caller about which
nodes were successfully registered; subsequent pipeline construction may fail
with confusing `NodeNotFoundError`.

FIX DIRECTION:
```python
try:
    from app.core.config import plugins_home as _plugins_home
    plugins_dir = str(_plugins_home())
except Exception as exc:
    log.warning("AutoDiscovery: could not resolve plugins_dir: %s", exc)
    plugins_dir = "plugins"   # safe fallback
```

--------------------------------------------------------------------
FILE:        app/core/nodes/discovery.py
FUNCTION:    AutoDiscovery._register_node
CATEGORY:    Silent Failure Risk
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validate and register a single Node subclass; derives `node_type` from the
class name if not explicitly declared.

WHAT IT ACTUALLY DOES:
The duplicate-check uses `existing.__name__ == cls.__name__ and
existing.__qualname__ == cls.__qualname__` to decide whether two different
class objects are "the same class loaded under a different import path". This
heuristic can produce false positives: two completely different node classes
in different plugins that happen to share the same class name and qualname
(e.g. both named `AudioClassifierNode` in different plugin packages) will
silently skip registration of the second one instead of raising
`DuplicateNodeTypeError`.

EVIDENCE:
```python
if existing.__name__ == cls.__name__ and existing.__qualname__ == cls.__qualname__:
    return  # same class, different import path — skip silently
```
No check on `__module__` — two classes from different modules with the same
name are treated as identical.

REPRODUCTION SCENARIO:
Plugin A defines `class AudioClassifierNode(Node): node_type = "audio_classifier"`.
Plugin B also defines `class AudioClassifierNode(Node): node_type = "audio_classifier"`.
The second plugin's class is silently dropped; Plugin A's class is used for
both, producing wrong behaviour for Plugin B's pipelines.

IMPACT:
Silent wrong result — wrong node class used for a node_type; no error raised.

FIX DIRECTION:
Include `__module__` in the identity check:
```python
if (existing.__name__ == cls.__name__
        and existing.__qualname__ == cls.__qualname__
        and existing.__module__ == cls.__module__):
    return  # genuinely the same class
raise DuplicateNodeTypeError(...)
```

--------------------------------------------------------------------
FILE:        app/core/nodes/discovery.py
FUNCTION:    AutoDiscovery._register_node
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Populate `meta.input_ports` and `meta.output_ports` from the class's port
definitions if not already set.

WHAT IT ACTUALLY DOES:
```python
if not meta.input_ports:
    meta.input_ports = {k: _port_to_dict(v) for k, v in cls.input_ports.items()}
if not meta.output_ports:
    meta.output_ports = {k: _port_to_dict(v) for k, v in cls.output_ports.items()}
```
`cls.input_ports` and `cls.output_ports` are class-level attributes. If a
node class defines them as `{}` (empty dict, e.g. a source node with no
inputs), `not meta.input_ports` is `True` (empty dict is falsy), so the
assignment runs and sets `meta.input_ports = {}` — which is correct. However,
if `cls.input_ports` raises `AttributeError` (node class forgot to define
it), the exception propagates uncaught from `_register_node` as a generic
`AttributeError` rather than a `NodeMetadataError`, bypassing the
`NodeMetadataError` catch in `_scan_directory`.

EVIDENCE:
```python
meta.input_ports = {k: _port_to_dict(v) for k, v in cls.input_ports.items()}
# AttributeError if cls.input_ports not defined — not caught as NodeMetadataError
```

REPRODUCTION SCENARIO:
A node class that inherits from `Node` but does not define `input_ports`.
`_register_node` raises `AttributeError`; `_scan_directory` catches it as a
generic `Exception` and logs a warning — but the warning message says
"error processing module" rather than "missing metadata", making diagnosis
harder.

IMPACT:
Confusing warning message; node silently not registered.

FIX DIRECTION:
Wrap the port population in a try/except and raise `NodeMetadataError`:
```python
try:
    if not meta.input_ports:
        meta.input_ports = {k: _port_to_dict(v) for k, v in cls.input_ports.items()}
    if not meta.output_ports:
        meta.output_ports = {k: _port_to_dict(v) for k, v in cls.output_ports.items()}
except AttributeError as exc:
    raise NodeMetadataError(f"Node '{cls.__name__}' missing port definitions: {exc}") from exc
```

--------------------------------------------------------------------
FILE:        app/core/nodes/discovery.py
FUNCTION:    _pascal_to_snake
CATEGORY:    Contract Mismatch
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Convert PascalCase to snake_case and strip trailing `_node` suffix.
Docstring example: `TFRecordExportNode → tf_record_export`.

WHAT IT ACTUALLY DOES:
Applies two regex passes then lowercases. For `TFRecordExportNode`:
- Pass 1 (`([A-Z]+)([A-Z][a-z])`): matches `TFR` → `TF_Record` → `TF_RecordExportNode`
- Pass 2 (`([a-z\d])([A-Z])`): matches `d_E` → `TF_Record_Export_Node`
- Lower: `tf_record_export_node`
- Strip `_node`: `tf_record_export` ✓

However for `HFExportNode`:
- Pass 1: `HFE` → `HF_Export` → `HF_ExportNode`
- Pass 2: `t_N` → `HF_Export_Node`
- Lower: `hf_export_node`
- Strip `_node`: `hf_export` ✓

For `URLParserNode`:
- Pass 1: `URLP` → `URL_Parser` → `URL_ParserNode`
- Pass 2: `r_N` → `URL_Parser_Node`
- Lower: `url_parser_node`
- Strip `_node`: `url_parser` ✓

The regex logic appears correct for the documented examples. However, a
class named exactly `Node` (the base class) would produce `node_type = ""`
after stripping `_node` from `node`. The guard `obj is not Node` in
`_process_module` prevents this from being registered, but if a subclass
is named `SomeNode` and `_pascal_to_snake("SomeNode")` → `some_node` →
strip `_node` → `some` — this is correct. The edge case is a class named
`XNode` where `X` is a single letter: `_pascal_to_snake("XNode")` →
pass1: no match → pass2: no match → lower: `xnode` → strip `_node`: `x`.
This is a valid (if short) node_type. No bug, but worth documenting.

EVIDENCE:
```python
node_type = getattr(cls, "node_type", "") or _pascal_to_snake(cls.__name__)
```
If `node_type` is explicitly set to `""` on the class, `_pascal_to_snake`
is used as fallback — correct.

REPRODUCTION SCENARIO:
Not a bug — documenting for completeness.

IMPACT:
None — informational only.

FIX DIRECTION:
No fix needed. Consider adding a guard: if derived `node_type` is empty
string, raise `NodeMetadataError`.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 3 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | UNSAFE |
| Resource Safety | SAFE |
| Test Hostile | PARTIAL |
| Top Risk | `_import_file` writes a broken module stub to `sys.modules` before `exec_module` completes — a plugin with a syntax error permanently poisons `sys.modules` for that module name, preventing recovery in the same process. |
