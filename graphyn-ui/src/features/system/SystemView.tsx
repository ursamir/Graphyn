import React from 'react'
import { RefreshCw } from 'lucide-react'
import { apiJson } from '../../api/client'
import {
  formatCleanupToast,
  formatLocaleDateTime,
  formatMetricsSummary,
  formatRelativeTime,
  pickStatusFacts,
  prettyScalar,
  startCase,
} from '../../lib/format'
import { useAppStore } from '../../store/appStore'
import {
  CollapsibleJson,
  EmptyState,
  ErrorBanner,
  LoadingBlock,
  PageHeader,
  StatusBadge,
} from '../../components/ui'

function badgeFromPayload(data: unknown, okKeys: string[]): string {
  if (!data || typeof data !== 'object') return 'unknown'
  const o = data as Record<string, unknown>
  if (typeof o.status === 'string') return o.status
  if (o.ready === true || o.ok === true) return 'ready'
  for (const k of okKeys) {
    if (o[k] === true) return 'ok'
    if (o[k] === false) return 'degraded'
  }
  return 'ok'
}

function Facts({ data }: { data: unknown }) {
  const facts = pickStatusFacts(data, 6)
  if (facts.length === 0) return <p className="text-sm text-ink-500">No status yet.</p>
  return (
    <dl className="space-y-1.5 text-sm">
      {facts.map((f) => {
        const value =
          f.key === 'timestamp' && typeof f.value === 'string'
            ? formatLocaleDateTime(f.value)
            : prettyScalar(f.value) || String(f.value)
        return (
          <div key={f.key} className="flex justify-between gap-3">
            <dt className="text-ink-500">{startCase(f.key)}</dt>
            <dd className="font-medium text-ink-900">{value}</dd>
          </div>
        )
      })}
    </dl>
  )
}

export default function SystemView() {
  const pushToast = useAppStore((s) => s.pushToast)
  const setView = useAppStore((s) => s.setView)
  const [health, setHealth] = React.useState<unknown>(null)
  const [ready, setReady] = React.useState<unknown>(null)
  const [metrics, setMetrics] = React.useState<unknown>(null)
  const [webhookUrl, setWebhookUrl] = React.useState('')
  const [webhookEvents, setWebhookEvents] = React.useState<string[]>([])
  const [cleanupDays, setCleanupDays] = React.useState(7)
  const [deleteCache, setDeleteCache] = React.useState(false)
  const [deleteArtifacts, setDeleteArtifacts] = React.useState(false)
  const [cleanupArmed, setCleanupArmed] = React.useState(false)
  const [cleanupConfirmText, setCleanupConfirmText] = React.useState("")
  const [reconcileAbandoned, setReconcileAbandoned] = React.useState(true)
  const [reconciling, setReconciling] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [auditEvents, setAuditEvents] = React.useState<
    Array<{
      event_id?: string
      ts?: string
      actor?: string
      action?: string
      resource_type?: string
      resource_id?: string
    }>
  >([])
  const [auditError, setAuditError] = React.useState<string | null>(null)
  const [authStatus, setAuthStatus] = React.useState<{
    auth_required?: boolean
    token_configured?: boolean
    env?: string
    ok?: boolean
  } | null>(null)
  const [schedules, setSchedules] = React.useState<
    Array<{
      id?: string
      name?: string
      project?: string
      pipeline?: string
      interval_minutes?: number
      enabled?: boolean
      next_run_at?: string
      last_run_id?: string
      last_error?: string
    }>
  >([])
  const [schedName, setSchedName] = React.useState('hourly')
  const [schedProject, setSchedProject] = React.useState('')
  const [schedPipeline, setSchedPipeline] = React.useState('')
  const [schedInterval, setSchedInterval] = React.useState(60)

  const refresh = React.useCallback(async () => {
    setError(null)
    setAuditError(null)
    setLoading(true)
    try {
      const [h, r, m, w, audit, auth, sched] = await Promise.all([
        apiJson('/system/health'),
        apiJson('/system/readiness'),
        apiJson('/system/metrics'),
        apiJson<{ url?: string; events?: string[] }>('/system/webhooks'),
        apiJson<{ events?: unknown[] }>('/audit', { query: { limit: 25 } }).catch((err) => {
          setAuditError(err instanceof Error ? err.message : String(err))
          return { events: [] }
        }),
        apiJson<{
          auth_required?: boolean
          token_configured?: boolean
          env?: string
          ok?: boolean
        }>('/system/auth-status').catch(() => null),
        apiJson<{ schedules?: unknown[] }>('/system/schedules').catch(() => ({ schedules: [] })),
      ])
      setHealth(h)
      setReady(r)
      setMetrics(m)
      setWebhookUrl(w.url ?? '')
      setWebhookEvents(w.events ?? [])
      setAuthStatus(auth)
      const schedList = Array.isArray(sched?.schedules) ? sched.schedules : []
      setSchedules(
        schedList.filter((e): e is Record<string, unknown> => !!e && typeof e === 'object') as Array<{
          id?: string
          name?: string
          project?: string
          pipeline?: string
          interval_minutes?: number
          enabled?: boolean
          next_run_at?: string
          last_run_id?: string
          last_error?: string
        }>,
      )
      const events = Array.isArray(audit?.events) ? audit.events : []
      setAuditEvents(
        events.filter((e): e is Record<string, unknown> => !!e && typeof e === 'object') as Array<{
          event_id?: string
          ts?: string
          actor?: string
          action?: string
          resource_type?: string
          resource_id?: string
        }>,
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    void refresh()
  }, [refresh])

  const metricsLine = formatMetricsSummary(metrics)
  const readyObj = ready && typeof ready === 'object' ? (ready as Record<string, unknown>) : null
  const backendMode = String(readyObj?.backend_mode ?? '').trim()
  const backendId = String(readyObj?.backend ?? '').trim()
  const workerCount = Number(readyObj?.worker_count ?? NaN)
  const backendLabel =
    backendMode === 'distributed'
      ? 'Distributed'
      : backendMode === 'local'
        ? 'Local'
        : backendId
          ? backendId
          : ''

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      <PageHeader
        title="System"
        description="Ops health, webhooks, cleanup, and recent audit events — accountability surface for mutations."
        actions={
          <button type="button" className="btn-secondary" onClick={() => void refresh()}>
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </button>
        }
      />
      {error && <ErrorBanner message={error} onRetry={() => void refresh()} />}
      {loading && <LoadingBlock label="Loading system status…" />}

      {authStatus && authStatus.auth_required && !authStatus.token_configured ? (
        <div className="rounded-2xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950">
          Auth is required ({authStatus.env || 'production'}) but{' '}
          <code className="font-mono text-xs">GRAPHYN_API_TOKEN</code> is not configured on the
          server. Set the token and paste the same value in Settings.
        </div>
      ) : null}
      {authStatus && authStatus.auth_required && authStatus.token_configured ? (
        <div className="rounded-2xl border border-ink-200 bg-ink-50/80 px-4 py-2 text-xs text-ink-600">
          Bearer auth required — send the same token as{' '}
          <code className="font-mono">GRAPHYN_API_TOKEN</code> from Settings.
        </div>
      ) : null}

      {(backendLabel || Number.isFinite(workerCount)) && (
        <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-ink-200 bg-white px-4 py-3 text-sm shadow-sm">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">Backend</span>
          {backendLabel ? (
            <span
              className="rounded-full border border-ink-200 bg-ink-50 px-2.5 py-0.5 text-[12px] font-medium text-ink-800"
              title={backendId || undefined}
            >
              {backendLabel}
              {backendId && backendId !== backendMode ? (
                <span className="ml-1 font-mono text-[10px] text-ink-500">{backendId}</span>
              ) : null}
            </span>
          ) : null}
          {Number.isFinite(workerCount) ? (
            <button
              type="button"
              className="rounded-full border border-ink-200 bg-white px-2.5 py-0.5 text-[12px] text-ink-700 hover:border-accent-300 hover:text-accent-800"
              onClick={() => {
                setView('workers')
                window.history.replaceState(null, '', '#/workers')
              }}
              title="Open Workers"
            >
              {workerCount} {workerCount === 1 ? 'worker' : 'workers'}
            </button>
          ) : null}
          <button
            type="button"
            className="btn-secondary ml-auto"
            disabled={reconciling}
            onClick={() => {
              setReconciling(true)
              void apiJson('/system/cleanup', {
                method: 'POST',
                body: JSON.stringify({
                  older_than_days: 36500,
                  delete_cache: false,
                  delete_artifacts: false,
                  keep_latest: true,
                  reconcile_abandoned: true,
                  stale_after_hours: 1,
                }),
              })
                .then((res) => {
                  pushToast(formatCleanupToast(res), 'success')
                  void refresh()
                })
                .catch((err) =>
                  pushToast(err instanceof Error ? err.message : String(err), 'error'),
                )
                .finally(() => setReconciling(false))
            }}
          >
            {reconciling ? 'Reconciling…' : 'Reconcile abandoned runs'}
          </button>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {[
          ['Health', health, badgeFromPayload(health, ['ok'])],
          ['Readiness', ready, badgeFromPayload(ready, ['ready'])],
        ].map(([title, data, badge]) => (
          <section key={String(title)} className="rounded-2xl border border-ink-200 bg-white p-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-semibold">{title as string}</h3>
              <StatusBadge status={String(badge)} />
            </div>
            <Facts data={data} />
            <div className="mt-3">
              <CollapsibleJson value={data} label="Raw JSON" />
            </div>
          </section>
        ))}
      </div>

      {metricsLine ? (
        <section className="rounded-2xl border border-ink-200 bg-white p-4">
          <h3 className="mb-1 text-sm font-semibold">Metrics</h3>
          <p className="text-sm text-ink-700">{metricsLine}</p>
          <div className="mt-3">
            <CollapsibleJson value={metrics} label="Raw JSON" />
          </div>
        </section>
      ) : null}

      <section className="rounded-2xl border border-ink-200 bg-white p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-semibold">Audit — recent events</h3>
            <p className="text-xs text-ink-500">
              Append-only actor trail from GET /api/v1/audit (proposals, and other mutations).
            </p>
          </div>
        </div>
        {auditError && <p className="text-sm text-amber-800">{auditError}</p>}
        {!auditError && auditEvents.length === 0 ? (
          <EmptyState
            title="No audit events yet"
            description="Accept/reject proposals or other audited mutations will appear here."
            action={
              <button
                type="button"
                className="btn-secondary"
                onClick={() => {
                  setView('proposals')
                  window.history.replaceState(null, '', '#/proposals')
                }}
              >
                Open Proposals
              </button>
            }
          />
        ) : (
          <div className="overflow-hidden rounded-xl border border-ink-100">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-ink-100 bg-ink-50/80 text-[11px] uppercase tracking-wide text-ink-500">
                <tr>
                  <th className="px-3 py-2 font-semibold">When</th>
                  <th className="px-3 py-2 font-semibold">Actor</th>
                  <th className="px-3 py-2 font-semibold">Action</th>
                  <th className="px-3 py-2 font-semibold">Resource</th>
                </tr>
              </thead>
              <tbody>
                {auditEvents.map((ev, i) => (
                  <tr key={ev.event_id || `${ev.ts}-${i}`} className="border-b border-ink-50 last:border-0">
                    <td className="px-3 py-2 text-ink-600 whitespace-nowrap" title={formatLocaleDateTime(ev.ts)}>
                      {ev.ts ? formatRelativeTime(ev.ts) : '—'}
                    </td>
                    <td className="px-3 py-2 text-ink-800">{ev.actor || '—'}</td>
                    <td className="px-3 py-2">
                      <StatusBadge status={String(ev.action || 'unknown')} />
                    </td>
                    <td className="px-3 py-2 font-mono text-[11px] text-ink-600 truncate max-w-[14rem]" title={`${ev.resource_type}:${ev.resource_id}`}>
                      {ev.resource_type || '—'}
                      {ev.resource_id ? ` · ${String(ev.resource_id).slice(0, 12)}` : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-ink-200 bg-white p-4 space-y-3">
        <h3 className="text-sm font-semibold">Projects</h3>
        <p className="text-sm text-ink-500">
          Dataset projects, versions, and contracts are managed on the Projects screen — not duplicated here.
        </p>
        <button
          type="button"
          className="btn-primary"
          onClick={() => {
            setView('projects')
            window.history.replaceState(null, '', '#/projects')
          }}
        >
          Open Projects
        </button>
      </section>

      <section className="rounded-2xl border border-ink-200 bg-white p-4 space-y-3">
        <div>
          <h3 className="text-sm font-semibold">Schedules</h3>
          <p className="text-xs text-ink-500">
            Interval jobs that run a project pipeline while the API process is up (always-on lite).
          </p>
        </div>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <input
            className="rounded-lg border border-ink-200 px-3 py-2 text-sm"
            placeholder="Name"
            value={schedName}
            onChange={(e) => setSchedName(e.target.value)}
          />
          <input
            className="rounded-lg border border-ink-200 px-3 py-2 text-sm"
            placeholder="Project"
            value={schedProject}
            onChange={(e) => setSchedProject(e.target.value)}
          />
          <input
            className="rounded-lg border border-ink-200 px-3 py-2 text-sm"
            placeholder="Pipeline"
            value={schedPipeline}
            onChange={(e) => setSchedPipeline(e.target.value)}
          />
          <input
            type="number"
            min={1}
            className="rounded-lg border border-ink-200 px-3 py-2 text-sm"
            placeholder="Interval (min)"
            value={schedInterval}
            onChange={(e) => setSchedInterval(Number(e.target.value) || 60)}
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-primary"
            onClick={() => {
              void apiJson('/system/schedules', {
                method: 'POST',
                body: JSON.stringify({
                  name: schedName,
                  project: schedProject,
                  pipeline: schedPipeline,
                  interval_minutes: schedInterval,
                  enabled: true,
                }),
              })
                .then(() => {
                  pushToast('Schedule created', 'success')
                  void refresh()
                })
                .catch((err) =>
                  pushToast(err instanceof Error ? err.message : String(err), 'error'),
                )
            }}
          >
            Add schedule
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => {
              void apiJson('/system/schedules/tick', { method: 'POST' })
                .then((res) => {
                  const n = Number((res as { count?: number })?.count ?? 0)
                  pushToast(n ? `Fired ${n} schedule(s)` : 'No schedules due', 'success')
                  void refresh()
                })
                .catch((err) =>
                  pushToast(err instanceof Error ? err.message : String(err), 'error'),
                )
            }}
          >
            Tick due now
          </button>
        </div>
        {schedules.length === 0 ? (
          <p className="text-sm text-ink-500">No schedules yet.</p>
        ) : (
          <ul className="space-y-2">
            {schedules.map((s) => (
              <li
                key={s.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-ink-100 px-3 py-2 text-sm"
              >
                <div className="min-w-0">
                  <div className="font-medium text-ink-900">
                    {s.name}{' '}
                    <span className="font-mono text-[11px] text-ink-500">
                      {s.project}/{s.pipeline}
                    </span>
                  </div>
                  <div className="text-[11px] text-ink-500">
                    every {s.interval_minutes}m · {s.enabled ? 'enabled' : 'disabled'}
                    {s.next_run_at ? ` · next ${formatRelativeTime(s.next_run_at)}` : ''}
                    {s.last_error ? ` · err: ${s.last_error}` : ''}
                  </div>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() =>
                      void apiJson(`/system/schedules/${s.id}/run`, { method: 'POST' })
                        .then((res) => {
                          pushToast(
                            `Started ${(res as { last_run_id?: string })?.last_run_id || 'run'}`,
                            'success',
                          )
                          void refresh()
                        })
                        .catch((err) =>
                          pushToast(err instanceof Error ? err.message : String(err), 'error'),
                        )
                    }
                  >
                    Run now
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() =>
                      void apiJson(`/system/schedules/${s.id}/enable`, {
                        method: 'POST',
                        body: JSON.stringify({ enabled: !s.enabled }),
                      })
                        .then(() => void refresh())
                        .catch((err) =>
                          pushToast(err instanceof Error ? err.message : String(err), 'error'),
                        )
                    }
                  >
                    {s.enabled ? 'Disable' : 'Enable'}
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() =>
                      void apiJson(`/system/schedules/${s.id}`, { method: 'DELETE' })
                        .then(() => {
                          pushToast('Schedule deleted', 'success')
                          void refresh()
                        })
                        .catch((err) =>
                          pushToast(err instanceof Error ? err.message : String(err), 'error'),
                        )
                    }
                  >
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="rounded-2xl border border-ink-200 bg-white p-4 space-y-3">
        <h3 className="text-sm font-semibold">Webhooks</h3>
        <input
          value={webhookUrl}
          onChange={(e) => setWebhookUrl(e.target.value)}
          placeholder="https://hooks.example.com/…"
          className="w-full rounded-lg border border-ink-200 px-3 py-2 text-sm"
        />
        <div className="flex flex-wrap gap-4 text-sm">
          {(
            [
              ['pipeline_complete', 'Pipeline complete'],
              ['pipeline_failed', 'Pipeline failed'],
            ] as const
          ).map(([ev, label]) => (
            <label key={ev} className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={webhookEvents.includes(ev)}
                onChange={() =>
                  setWebhookEvents((prev) =>
                    prev.includes(ev) ? prev.filter((x) => x !== ev) : [...prev, ev],
                  )
                }
              />
              {label}
            </label>
          ))}
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            className="btn-primary"
            onClick={() =>
              void apiJson('/system/webhooks', {
                method: 'PUT',
                body: JSON.stringify({ url: webhookUrl, events: webhookEvents }),
              })
                .then(() => pushToast('Webhook saved', 'success'))
                .catch((err) => pushToast(err instanceof Error ? err.message : String(err), 'error'))
            }
          >
            Save
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() =>
              void apiJson('/system/webhooks/test', { method: 'POST' })
                .then(() => pushToast('Test webhook sent', 'success'))
                .catch((err) => pushToast(err instanceof Error ? err.message : String(err), 'error'))
            }
          >
            Test
          </button>
        </div>
      </section>

      <section className="rounded-2xl border border-ink-200 bg-white p-4 space-y-3">
        <h3 className="text-sm font-semibold">Cleanup</h3>
        <p className="text-sm text-ink-500">
          Deletes finished run journals under workspace/runs (completed, failed, or cancelled — never a
          currently running run). Optionally also deletes pipeline cache under workspace/cache and
          workspace/artifacts/&lt;slug&gt;/runs/&lt;run_id&gt; folders for those runs. Set days to 0 to
          clear all finished runs. The run that latest/ still points at is kept by default.
          examples/ and datasets/input are never deleted.
        </p>
        <p className="text-xs text-amber-800 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
          Destructive options stay unchecked by default. Cleanup always requires typing{' '}
          <span className="font-mono font-semibold">CLEANUP</span> to confirm.
        </p>
        <label className="block text-sm text-ink-600">
          Older than days
          <input
            type="number"
            min={0}
            value={cleanupDays}
            onChange={(e) => {
              const n = parseInt(e.target.value, 10)
              setCleanupDays(Number.isFinite(n) && n >= 0 ? n : 0)
              setCleanupArmed(false)
              setCleanupConfirmText('')
            }}
            className="ml-2 w-20 rounded border border-ink-200 px-2 py-1"
          />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={deleteCache}
            onChange={(e) => {
              setDeleteCache(e.target.checked)
              setCleanupArmed(false)
              setCleanupConfirmText('')
            }}
          />
          Delete cache
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={deleteArtifacts}
            onChange={(e) => {
              setDeleteArtifacts(e.target.checked)
              setCleanupArmed(false)
              setCleanupConfirmText('')
            }}
          />
          Delete workspace artifacts
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={reconcileAbandoned}
            onChange={(e) => {
              setReconcileAbandoned(e.target.checked)
              setCleanupArmed(false)
              setCleanupConfirmText('')
            }}
          />
          Reconcile abandoned RUNNING/QUEUED runs first
        </label>
        {!cleanupArmed ? (
          <button
            type="button"
            className="btn-danger"
            onClick={() => {
              setCleanupArmed(true)
              setCleanupConfirmText('')
            }}
          >
            Run cleanup…
          </button>
        ) : (
          <div className="rounded-xl border border-rose-200 bg-rose-50/70 p-3 space-y-3">
            <div className="text-sm text-rose-950">
              <div className="font-semibold">Confirm cleanup</div>
              <ul className="mt-1 list-disc pl-5 text-xs text-rose-900/90 space-y-0.5">
                <li>
                  Delete finished run journals older than{' '}
                  <span className="font-medium">{cleanupDays}</span> day
                  {cleanupDays === 1 ? '' : 's'} (keep latest)
                </li>
                <li>{deleteCache ? 'Also delete pipeline cache' : 'Keep pipeline cache'}</li>
                <li>
                  {deleteArtifacts
                    ? 'Also delete workspace artifacts for those runs'
                    : 'Keep workspace artifacts'}
                </li>
              </ul>
            </div>
            <label className="block text-sm text-rose-950">
              Type <span className="font-mono font-semibold">CLEANUP</span> to proceed
              <input
                value={cleanupConfirmText}
                onChange={(e) => setCleanupConfirmText(e.target.value)}
                placeholder="CLEANUP"
                autoComplete="off"
                spellCheck={false}
                className="mt-1 w-full rounded-lg border border-rose-200 bg-white px-3 py-2 font-mono text-sm"
              />
            </label>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="btn-danger"
                disabled={cleanupConfirmText.trim() !== 'CLEANUP'}
                onClick={() => {
                  void apiJson('/system/cleanup', {
                    method: 'POST',
                    body: JSON.stringify({
                      older_than_days: cleanupDays,
                      delete_cache: deleteCache,
                      delete_artifacts: deleteArtifacts,
                      keep_latest: true,
                      reconcile_abandoned: reconcileAbandoned,
                      stale_after_hours: 1,
                    }),
                  })
                    .then((res) => {
                      pushToast(formatCleanupToast(res), 'success')
                      setCleanupArmed(false)
                      setCleanupConfirmText('')
                    })
                    .catch((err) =>
                      pushToast(err instanceof Error ? err.message : String(err), 'error'),
                    )
                }}
              >
                Confirm cleanup
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => {
                  setCleanupArmed(false)
                  setCleanupConfirmText('')
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
