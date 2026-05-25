# Known Issues

> **Single source of truth:** `docs/MASTER_ISSUE_REGISTRY.md`
> This file lists only currently open issues for quick reference.
> For full history, fix details, and resolved issues see the registry.

---

## Open — Fix Immediately (before next deployment)

All previously listed issues in this tier have been resolved. See `docs/MASTER_ISSUE_REGISTRY.md` Resolved table.

---

## Open — Fix This Sprint

All previously listed issues in this tier have been resolved. See `docs/MASTER_ISSUE_REGISTRY.md` Resolved table.

---

## Open — Fix When Touching the File

All previously listed issues in this tier have been resolved. See `docs/MASTER_ISSUE_REGISTRY.md` Resolved table.

---

## Open — Deferred (Architectural Work Required)

| ID | Severity | File | Summary |
|---|---|---|---|
| ARCH-1 | High | `core/pipeline_cache.py` | Domain leak — imports `AudioSample` |
| ARCH-2 | High | `core/artifact_store.py` | Domain leak — WAV serialization in platform infrastructure |
| ARCH-3 | High | `core/checkpoint.py` | Domain leak — entirely audio-specific |
| SEC-6 | High | `api/routers/plugins.py` | Plugin install accepts arbitrary remote code execution |
| SCALE-1 | Medium | `core/run_control.py` | Active run registry is process-local |
| SCALE-2 | Medium | `domain/ingestion.py` | Ingest job store is process-local |
| NEW-19 | Medium | `plugins/text-stats/` | Orphaned installed plugin — no `PluginPackage/` source |
