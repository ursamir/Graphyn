# WakeWord — experimental CLI / library (not a Graphyn plugin)

This tree is a **standalone wake-word training and inference toolkit** (Typer CLI, data generation, ONNX export). It is **not** a first-class Graphyn plugin pack.

- **No `plugin.toml`** — there is no manifest and no registered `node_type`.
- **Not auto-installed** — `PluginManager` / `graphyn plugin install` do not discover or install this folder.
- **Not in the node catalogue** — use it as a library or run `python -m PluginPackage.WakeWord` (see `cli.py`) outside pipeline graphs.

For installable workflow nodes, use the **Audio** and **Common** plugins documented in `PluginPackage/NODES.md`.
