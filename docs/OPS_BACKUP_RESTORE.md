# Ops: Backup, restore, and graceful shutdown

Normative refs: SRS **OPS-001** / **OPS-002** / **OPS-003** / **OPS-005** / **OPS-011**.

This runbook is self-contained. It does not invent product numbers or device OTA procedures.

## What to back up

Graphyn state is filesystem-first. Back up these roots **together** (same quiesce window):

| Path | Env / default | Contents |
|---|---|---|
| Platform home | `GRAPHYN_HOME` (default `~/.graphyn`) | Plugins registry + installed plugins + venvs, secrets (0600), optional caches |
| Project / workspace | `GRAPHYN_PROJECT_DIR` (compose often mounts `./workspace`) | Runs (`runs/`), artifacts, provenance, models registry, pipeline envs, datasets outputs, ship packages, audit log, schedules/webhooks config |
| Compose named volume | `graphyn-home` | Docker persistence for `GRAPHYN_HOME` inside the API container |

**Consistency rule:** Prefer stopping new work (or full API stop) before copying. A hot copy of `runs/` mid-write can leave a single run’s `meta.json` / artifact index inconsistent; Graphyn quarantines corrupt indexes and fails readiness (`store_corrupt`) rather than silently returning empty success.

### Minimal consistent set (P0)

1. Entire `GRAPHYN_HOME` tree.
2. Entire `GRAPHYN_PROJECT_DIR` tree (or the DB, if you later move stores off filesystem — not current default).
3. Record env: `GRAPHYN_BACKEND`, `GRAPHYN_API_TOKEN` (store secrets out-of-band), `GRAPHYN_AUTH_REQUIRED`, IR/plugin pins if any.

Do **not** commit secrets or bearer tokens into git.

## Backup procedure (example)

```bash
# 1) Optional: set API to drain (SIGTERM) or stop accepting traffic at the proxy.
# 2) Snapshot
TS=$(date -u +%Y%m%dT%H%M%SZ)
DEST=/var/backups/graphyn/$TS
mkdir -p "$DEST"
tar -C "${GRAPHYN_HOME:-$HOME/.graphyn}" -czf "$DEST/graphyn-home.tgz" .
tar -C "${GRAPHYN_PROJECT_DIR:-./workspace}" -czf "$DEST/graphyn-project.tgz" .
# 3) Verify archives readable
tar -tzf "$DEST/graphyn-home.tgz" >/dev/null
tar -tzf "$DEST/graphyn-project.tgz" >/dev/null
echo "Backup OK $DEST"
```

Docker Compose: stop or scale API to 0, then archive the `graphyn-home` volume and the bind-mounted project directory with the same timestamp.

## Restore procedure

1. Stop API / workers that would write to the targets.
2. Restore `GRAPHYN_HOME` and `GRAPHYN_PROJECT_DIR` from the **same** backup timestamp.
3. Restore env / secrets out-of-band (`GRAPHYN_API_TOKEN`, etc.).
4. Start API; wait until `GET /api/v1/system/readiness` reports `"ready": true`.
5. Spot-check: list projects, a known `run_id`, artifact lineage, schedules.

If readiness shows `checks.store_corrupt: true`, inspect quarantined `*.corrupt*` siblings under artifacts/plugins, fix or remove bad indexes, and restart. Do not wipe prod pointers without `POST /system/cleanup` dry-run.

## Migration notes (OPS-003)

- Graph IR: use `graphyn migrate` / loader `CURRENT` schema; unsupported major schema versions refuse load.
- Plugin registry: corrupt records are quarantined under `_quarantine` / `*.corrupt*`.
- Forward-compatible minor bumps preferred; breaking REST → `/api/v2` or documented deprecation (OPS-012).

## Graceful shutdown / SIGTERM drain (OPS-005, OPS-011)

On process shutdown (uvicorn SIGTERM → FastAPI lifespan exit):

1. Set process **draining** — new `/pipelines/run` and `/pipelines/run-async` return **503** (`draining`).
2. Wait up to `GRAPHYN_SHUTDOWN_GRACE_S` (default **30s**) for in-flight active runs to finish.
3. Best-effort **cancel** remaining local active runs; brief soft wait; flush an `ops.shutdown_drain` audit event.
4. Stop schedule ticker; exit.

This is **best-effort** within one API worker process. Multi-worker / Redis-routed runs may still be active on other workers — drain each worker and stop claiming new jobs at the proxy.

## Related

- `docs/DEPLOYMENT.md` — compose volumes and `GRAPHYN_HOME`
- `docs/TRUST_MODEL.md` — shared-bearer / secrets layout
- `docs/SRS_ALIGNMENT_GAP_MATRIX.md` — OPS row cites this path
