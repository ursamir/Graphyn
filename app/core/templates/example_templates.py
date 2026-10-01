# app/core/templates/example_templates.py
"""
Bounded Context:  Graph Language / Templates
Responsibility:   Discover example Graph IR files under examples/ and sync them
                  into the project templates directory for the console UI.
Owns:             Example discovery, path rewriting, template sync helpers.
Public Surface:   discover_example_graphs, rewrite_graph_paths, sync_example_templates,
                  seed_example_input_datasets, template_display_title,
                  source_template_metadata, resolve_template_title
Must NOT:         Execute pipelines or mutate example sources.
Dependencies:     pathlib, json, app.core.config.project_dir, app.core.paths.workspace_paths
Reason To Change: Example layout changes or template naming conventions change.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_PREFIX = "ex-"

_EX_ID_RE = re.compile(r"^ex-(\d+)-(.+)$")
_TITLE_ACRONYMS = frozenset(
    {"asr", "llm", "crm", "rag", "pii", "kws", "tflite", "onnx", "vad", "e2e", "mlops", "gpu", "ml", "ai"}
)


def _humanize_template_id(name: str) -> str:
    words = [w for w in re.split(r"[-_]+", name) if w]
    out: list[str] = []
    for i, w in enumerate(words):
        low = w.lower()
        if low in _TITLE_ACRONYMS:
            out.append(low.upper())
        elif i == 0:
            out.append(low[:1].upper() + low[1:])
        else:
            out.append(low)
    return " ".join(out) or name


def template_display_title(name: str, metadata: dict[str, Any] | None = None) -> str:
    """Human display title for a template card.

    ``metadata.title`` wins (ignored by the IR loader, so it is safe to add to
    any graph). Otherwise the id is humanized; synced numbered examples
    (``ex-NN-<slug>``) get an ``(example NN)`` suffix so they never collide
    with a same-named starter under ``examples/templates/``.
    """
    meta = metadata if isinstance(metadata, dict) else {}
    title = meta.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()[:120]
    m = _EX_ID_RE.match(name or "")
    if m:
        return f"{_humanize_template_id(m.group(2))} (example {int(m.group(1)):02d})"
    return _humanize_template_id(name or "")


def source_template_metadata(
    name: str, synced_metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Return ``metadata`` of the repo source graph a synced template came from.

    Workspace copies under ``configs/templates/`` can predate metadata added to
    the repo sources (e.g. ``metadata.title``). Resolution order: the synced
    copy's ``metadata.source_example`` (relative to ``examples/``), then
    ``examples/templates/<name>.graph.json``. Returns ``{}`` when not found.
    """
    if not name or not _SAFE_NAME_RE.match(name):
        return {}
    root = examples_dir()
    candidates: list[Path] = []
    meta = synced_metadata if isinstance(synced_metadata, dict) else {}
    src_rel = meta.get("source_example")
    if isinstance(src_rel, str) and src_rel and ".." not in Path(src_rel).parts:
        candidates.append(root / src_rel)
    candidates.append(root / "templates" / f"{name}.graph.json")
    for path in candidates:
        try:
            resolved = path.resolve()
            resolved.relative_to(root.resolve())
        except (OSError, ValueError):
            continue
        if not resolved.is_file():
            continue
        try:
            data = json.loads(resolved.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict) and isinstance(data.get("metadata"), dict):
            return data["metadata"]
    return {}


def resolve_template_title(name: str, synced_metadata: dict[str, Any] | None = None) -> str:
    """Display title for a workspace template, falling back to the repo source.

    Uses the synced copy's ``metadata.title`` when present, else the repo
    source graph's ``metadata.title``, else :func:`template_display_title`.
    """
    meta = synced_metadata if isinstance(synced_metadata, dict) else {}
    title = meta.get("title")
    if isinstance(title, str) and title.strip():
        return template_display_title(name, meta)
    src_meta = source_template_metadata(name, meta)
    src_title = src_meta.get("title")
    if isinstance(src_title, str) and src_title.strip():
        return template_display_title(name, {"title": src_title})
    return template_display_title(name, meta)


# Preference order for "one example → one Builder template".
# Per-label / per-phase shards (pipeline_go, pipeline_preprocess_up, …) are
# intentionally excluded — those exist for CLI batch scripts, not the console.
_CANONICAL_NAMES: tuple[str, ...] = (
    "pipeline.graph.json",
    "composed.graph.json",
    "edge_inference.graph.json",
    "pipeline_train_ml.graph.json",
    "pipeline_preprocess.graph.json",
)


def repo_root() -> Path:
    """Repository root (contains app/ and examples/)."""
    return Path(__file__).resolve().parents[3]


def examples_dir() -> Path:
    return repo_root() / "examples"


def templates_dir() -> Path:
    from app.core.config import project_dir

    return project_dir() / "configs" / "templates"


def _canonical_graph(example_dir: Path) -> Path | None:
    """Pick the single graph that represents this example in the Builder."""
    for name in _CANONICAL_NAMES:
        candidate = example_dir / name
        if candidate.is_file():
            return candidate
    graphs = sorted(p for p in example_dir.glob("*.graph.json") if p.is_file())
    if len(graphs) == 1:
        return graphs[0]
    return None


def _template_name_for(rel: Path) -> str:
    """
    Map examples/01_wake_word/pipeline.graph.json → ex-01-wake-word
    Map examples/templates/basic-wakeword.graph.json → basic-wakeword
    """
    parts = rel.parts
    if parts[0] == "templates" and len(parts) == 2:
        name = parts[1].replace(".graph.json", "").replace(".json", "")
        return name if _SAFE_NAME_RE.match(name) else _PREFIX + re.sub(r"[^A-Za-z0-9_-]+", "-", name)

    folder = parts[0] if parts else "example"
    raw = f"{_PREFIX}{folder}".replace("_", "-")
    raw = re.sub(r"-{2,}", "-", raw).strip("-").lower()
    return re.sub(r"[^a-z0-9_-]", "", raw)


def discover_example_graphs() -> list[dict[str, Any]]:
    """Return metadata for Builder-facing example templates.

    Policy: **one numbered example folder → one template**. Starter graphs under
    ``examples/templates/`` are included as additional named starters.
    """
    root = examples_dir()
    if not root.is_dir():
        return []

    found: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    # 1) Numbered example dirs — canonical graph only
    for example_dir in sorted(p for p in root.iterdir() if p.is_dir() and p.name != "templates"):
        if example_dir.name.startswith("."):
            continue
        path = _canonical_graph(example_dir)
        if path is None:
            continue
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        name = _template_name_for(rel)
        if not _SAFE_NAME_RE.match(name) or name in seen_ids:
            continue
        meta: dict[str, Any] = {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                meta = data.get("metadata") or {}
        except Exception:
            data = None
        # Prefer README purpose line as description when IR description empty
        description = (meta.get("description") if isinstance(meta, dict) else None) or ""
        if not description:
            readme = example_dir / "README.md"
            if readme.is_file():
                try:
                    for line in readme.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if line and not line.startswith("#") and not line.startswith("---"):
                            description = line[:240]
                            break
                except Exception:
                    pass
        found.append(
            {
                "id": name,
                "source": str(rel).replace("\\", "/"),
                "path": str(path),
                "title": template_display_title(name, meta),
                "description": description,
                "tags": (meta.get("tags") if isinstance(meta, dict) else None) or [],
                "example_dir": example_dir.name,
            }
        )
        seen_ids.add(name)

    # 2) Explicit starter templates
    starters = root / "templates"
    if starters.is_dir():
        for path in sorted(starters.glob("*.graph.json")):
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            name = _template_name_for(rel)
            if not _SAFE_NAME_RE.match(name) or name in seen_ids:
                continue
            meta = {}
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    meta = data.get("metadata") or {}
            except Exception:
                pass
            found.append(
                {
                    "id": name,
                    "source": str(rel).replace("\\", "/"),
                    "path": str(path),
                    "title": template_display_title(name, meta),
                    "description": (meta.get("description") if isinstance(meta, dict) else None) or "",
                    "tags": (meta.get("tags") if isinstance(meta, dict) else None) or [],
                    "example_dir": "templates",
                }
            )
            seen_ids.add(name)

    return found


def seed_example_input_datasets() -> list[str]:
    """Copy/symlink examples/<folder>/data into workspace/datasets/input/<slug>.

    Existing destinations are left in place when they resolve. Prefer a
    **relative** directory symlink so Docker bind-mounts of the repo keep
    working (absolute host paths break inside the API container).
    """
    from app.core.config import datasets_input_dir
    from app.core.paths.workspace_paths import artifact_slug

    dest_root = datasets_input_dir()
    dest_root.mkdir(parents=True, exist_ok=True)
    seeded: list[str] = []
    root = examples_dir()
    if not root.is_dir():
        return seeded
    for example_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        data = example_dir / "data"
        if not data.is_dir():
            continue
        slug = artifact_slug(example_dir.name)
        if slug in {"pipeline", "graph", "untitled"}:
            continue
        dest = dest_root / slug
        # Heal dangling / absolute-host symlinks that break in containers.
        if dest.is_symlink() and not dest.exists():
            try:
                dest.unlink()
            except OSError:
                pass
        if dest.exists() or dest.is_symlink():
            if slug not in seeded:
                seeded.append(slug)
            continue
        try:
            rel = os.path.relpath(data.resolve(), start=dest.parent.resolve())
            os.symlink(rel, dest, target_is_directory=True)
        except OSError:
            try:
                shutil.copytree(data, dest)
            except OSError:
                continue
        seeded.append(slug)
    return seeded


def rewrite_graph_paths(
    graph: dict[str, Any],
    *,
    root: Path | None = None,
    slug: str | None = None,
) -> dict[str, Any]:
    """Rewrite repo-absolute paths, then retarget outputs and ingest into workspace.

    Legacy ``examples/**/output`` paths go to ``workspace/artifacts/<slug>/...``.
    ``workspace/datasets/output/...`` Library exports are preserved. Sample ingest
    under ``examples/**/data`` goes to ``workspace/datasets/input/<folder-slug>/...``.
    """
    from app.core.paths.workspace_paths import graph_name, rewire_graph_outputs

    root = (root or repo_root()).resolve()
    root_s = str(root)
    root_s_slash = root_s if root_s.endswith("/") else root_s + "/"

    def rewrite_value(value: Any) -> Any:
        if isinstance(value, str):
            if value.startswith(root_s_slash) or value == root_s:
                return str(Path(value).resolve().relative_to(root)).replace("\\", "/")
            return value
        if isinstance(value, dict):
            return {k: rewrite_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [rewrite_value(v) for v in value]
        return value

    rewritten = rewrite_value(graph)
    name = slug or graph_name(rewritten)
    return rewire_graph_outputs(rewritten, slug=name)


def sync_example_templates(*, force: bool = True, prune_shards: bool = True) -> dict[str, Any]:
    """
    Copy discovered example graphs into {project}/configs/templates/.

    One numbered example → one ``ex-*`` template. Starter graphs from
    ``examples/templates/`` are synced by name. When ``prune_shards`` is True,
    remove obsolete ``ex-*`` shard templates left from the old 1:N import.
    """
    dest_root = templates_dir()
    dest_root.mkdir(parents=True, exist_ok=True)
    root = repo_root()
    written: list[str] = []
    skipped: list[str] = []
    pruned: list[str] = []
    errors: list[dict[str, str]] = []
    seeded = seed_example_input_datasets()
    discovered = discover_example_graphs()
    keep_ids = {item["id"] for item in discovered}

    for item in discovered:
        name = item["id"]
        src = Path(item["path"])
        dest = dest_root / f"{name}.graph.json"
        if dest.exists() and not force:
            skipped.append(name)
            continue
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "schema_version" not in data:
                errors.append({"id": name, "error": "not a Graph IR document"})
                continue
            # Template id (ex-01-wake-word) sanitizes to wake-word; see artifact_slug.
            rewritten = rewrite_graph_paths(data, root=root, slug=name)
            meta = rewritten.setdefault("metadata", {})
            if isinstance(meta, dict):
                tags = list(meta.get("tags") or [])
                if "example" not in tags:
                    tags.append("example")
                meta["tags"] = tags
                if item.get("description"):
                    meta["description"] = item["description"]
                elif not meta.get("description"):
                    meta["description"] = ""
                meta["source_example"] = item["source"]
                meta["example_dir"] = item.get("example_dir") or ""
            for node in rewritten.get("nodes") or []:
                if not isinstance(node, dict):
                    continue
                if node.get("node_type") != "dataset_ingest":
                    continue
                cfg = node.get("config") or {}
                path = cfg.get("path")
                if isinstance(path, str) and path:
                    from app.core.paths.workspace_paths import (
                        dir_has_ingest_files,
                        ingest_dir_candidates,
                        is_produced_dataset_path,
                    )

                    if is_produced_dataset_path(path):
                        # Written by a sibling template (Phase-1 export) at run time.
                        continue

                    ok = False
                    for candidate in ingest_dir_candidates(path):
                        try:
                            if dir_has_ingest_files(candidate) or candidate.is_dir():
                                ok = True
                                break
                        except OSError:
                            continue
                    if not ok:
                        errors.append(
                            {
                                "id": name,
                                "error": f"dataset_ingest path missing: {path}",
                            }
                        )
            dest.write_text(json.dumps(rewritten, indent=2) + "\n", encoding="utf-8")
            written.append(name)
        except Exception as exc:
            errors.append({"id": name, "error": str(exc)})

    if prune_shards:
        for path in sorted(dest_root.glob("ex-*.graph.json")):
            tid = path.name[: -len(".graph.json")] if path.name.endswith(".graph.json") else path.stem
            if tid not in keep_ids:
                path.unlink(missing_ok=True)
                pruned.append(tid)

    return {
        "templates_dir": str(dest_root),
        "written": written,
        "skipped": skipped,
        "pruned": pruned,
        "errors": errors,
        "seeded_input_datasets": seeded,
        "count_written": len(written),
        "count_pruned": len(pruned),
        "count_discovered": len(discovered),
    }
