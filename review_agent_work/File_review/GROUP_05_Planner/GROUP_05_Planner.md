# Group Review Index — 5: Planner

**Files reviewed:** 1
**Total findings:** 9 (CRITICAL: 1 | HIGH: 4 | MEDIUM: 3 | LOW: 1)
**Date:** 2026-05-26

---

## File Summaries

| File | Overall Risk | Silent Failures | Top Risk |
|---|---|---|---|
| planner.md | HIGH | 2 | `_build` silently overwrites the first node when two NodeSpecs share the same `node_id`, producing a structurally corrupt DAG with no error or warning. |

---

## Priority Findings (CRITICAL and HIGH only)

`[CRITICAL]` planner.md — `_build` — Duplicate node IDs silently overwrite the first node instance, corrupting the DAG without any error or log warning.

`[HIGH]` planner.md — `_build` — `node_registry.get_class()` returning `None` for an unknown node type raises a cryptic `TypeError` instead of a `PipelineGraphError`, breaking the error contract for callers.

`[HIGH]` planner.md — `_build` — `json.dumps(spec.config)` raises a bare `TypeError` on non-JSON-serializable config values with no context identifying the offending node or field.

`[HIGH]` planner.md — `_parse_pipeline_config` — Missing `"type"` key in a node dict raises a raw `KeyError` with no diagnostic context about which node or pipeline is malformed.

`[HIGH]` planner.md — `_parse_pipeline_config` — A string value for `"from"` or `"to"` in an edge dict is silently character-sliced, producing garbage `src_id`/`src_port` values with no error raised.

---

## Most Dangerous File

planner.md — `_build` accepts duplicate node IDs without detection, silently discarding the first node and wiring the wrong instance into the DAG, making this a source of hard-to-diagnose silent data corruption at pipeline construction time.
