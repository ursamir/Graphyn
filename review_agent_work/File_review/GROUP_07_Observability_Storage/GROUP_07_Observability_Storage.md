# Group Review Index — 7: Observability & Storage

**Files reviewed:** 8  
**Total findings:** 27 (CRITICAL: 0 | HIGH: 10 | MEDIUM: 13 | LOW: 4)  
**Date:** 2026-05-26

---

## File Summaries

| File | Overall Risk | Silent Failures | Top Risk |
|---|---|---|---|
| checkpoint.md | HIGH | 2 | `_write_checkpoint` silently skips all non-AudioSample outputs — expensive nodes never get checkpointed and always re-execute on resume |
| pipeline_cache.md | HIGH | 3 | `save()` for audio ports is non-atomic — a partial write leaves orphaned port dirs that load as an incomplete (wrong) cache hit |
| artifact_store.md | HIGH | 2 | `cleanup()` deletes dirs for corrupt records without removing their index entries, leaving stale content-hash pointers that cause duplicate registration |
| artifact_serializer.md | LOW | 0 | Duplicate handler objects in `_ordered` when same instance registered for multiple types causes redundant `infer_type()` calls on every node execution |
| run_journal.md | HIGH | 1 | `update_resume_state` writes non-atomically — a crash mid-write permanently destroys resume capability for the affected run |
| run_control.md | HIGH | 0 | `_get_redis_client()` creates a new connection pool on every call — exhausts Redis connections under load and silently degrades multi-worker run control |
| provenance.md | HIGH | 0 | `record()` writes three files non-atomically — a crash between writes leaves the `by_run` index truncated, making all provenance for that run unreachable |
| logger.md | MEDIUM | 0 | `_emit` and `_emit_structured` call `queue.put()` without timeout — a bounded queue with a dead consumer blocks the pipeline execution thread indefinitely |

---

## Priority Findings (CRITICAL and HIGH only)

**[HIGH] checkpoint.md — `_write_checkpoint` — Silent Failure Risk**  
Silently skips checkpointing for all non-AudioSample node outputs. Expensive non-audio nodes (trainers, feature extractors) always re-execute on resume with no error surfaced to the caller.

**[HIGH] checkpoint.md — `_write_checkpoint` — Resource Leak**  
Manifest write is not atomic. A crash between the last `handler.serialize()` and the `manifest.json` write leaves orphaned port directories. The directory-scan fallback in `load()` then loads the partial data as a valid (but incomplete) cache hit — silent wrong result.

**[HIGH] pipeline_cache.md — `PipelineCache.save` (audio path) — Resource Leak / Silent Failure**  
`manifest.json` write is not atomic. A partial write leaves orphaned `port_*/` directories. The directory-scan fallback in `load()` loads the partial data as a valid cache hit with missing ports — silent wrong result delivered to downstream nodes.

**[HIGH] pipeline_cache.md — `PipelineCache.input_hash` — Silent Failure Risk**  
`sample.data.shape` is accessed without checking that `data` has a `.shape` attribute. An AudioSample where `data` is `bytes` or a list raises `AttributeError` that propagates uncaught through `compute_key()` to the orchestrator, crashing the pipeline.

**[HIGH] artifact_store.md — `ArtifactStore.cleanup` — Silent Failure Risk**  
Entries with corrupt `record.json` are deleted by `shutil.rmtree` (the `except: pass` falls through to the delete) but are NOT added to `hashes_to_remove` or `deleted_ids`. Their content-hash index entries are never cleaned up. The index points to non-existent directories, causing duplicate registration on the next run.

**[HIGH] artifact_store.md — `ArtifactStore.register` — State Bug**  
When `_serialize_data` raises `ArtifactSerializationError`, the temp directory `_tmp_{uuid}/` is not cleaned up before re-raising. Every failed serialization leaks a temp directory on disk.

**[HIGH] run_journal.md — `RunManager.__init__` — Edge Case**  
`run_id` is truncated to 16 hex characters (64 bits). Birthday collision expected after ~4 billion runs. Two runs with the same `run_id` write to the same directory, silently corrupting each other's metadata, logs, and resume state.

**[HIGH] run_journal.md — `RunManager.update_resume_state` — State Bug**  
`resume_state.json` is written non-atomically (no `os.replace`). A crash mid-write truncates the file. The next resume attempt raises `ResumeError` — resume capability is permanently lost for the affected run.

**[HIGH] run_control.md — `_get_redis_client` — Resource Leak**  
Creates a new Redis connection pool on every call. Three calls per run lifecycle (`register`, `get`, `deregister`). Under concurrent load, exhausts Redis connection limits and silently falls back to in-process-only mode, breaking multi-worker run control.

**[HIGH] provenance.md — `ProvenanceStore.record` — State Bug**  
Three file writes (`{artifact_id}.json`, `by_run/{run_id}.json`, `by_graph_hash/{hash}.json`) are non-atomic. A crash between writes leaves the `by_run` index truncated. `find_by_run()` returns `[]` for the affected run — all provenance for that run is unreachable via the run index.

---

## Most Dangerous File

**run_journal.md** — `RunManager.update_resume_state` writes `resume_state.json` non-atomically, and `RunManager.__init__` truncates `run_id` to 64 bits. Together these two bugs mean that (a) any crash during a node completion permanently destroys resume capability, and (b) in high-throughput systems, two runs can silently corrupt each other's entire run directory including metadata, logs, artifacts, and resume state.
