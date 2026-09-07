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
  ConfirmButton,
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
  const [deleteCache, setDeleteCache] = React.useState(true)
  const [deleteArtifacts, setDeleteArtifacts] = React.useState(false)
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

  const refresh = React.useCallback(async () => {
    setError(null)
    setAuditError(null)
    setLoading(true)
    try {
      const [h, r, m, w, audit] = await Promise.all([
        apiJson('/system/health'),
        apiJson('/system/readiness'),
        apiJson('/system/metrics'),
        apiJson<{ url?: string; events?: string[] }>('/system/webhooks'),
        apiJson<{ events?: unknown[] }>('/audit', { query: { limit: 25 } }).catch((err) => {
          setAuditError(err instanceof Error ? err.message : String(err))
          return { events: [] }
        }),
      ])
      setHealth(h)
      setReady(r)
      setMetrics(m)
      setWebhookUrl(w.url ?? '')
      setWebhookEvents(w.events ?? [])
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
        <label className="block text-sm text-ink-600">
          Older than days
          <input
            type="number"
            min={0}
            value={cleanupDays}
            onChange={(e) => {
              const n = parseInt(e.target.value, 10)
              setCleanupDays(Number.isFinite(n) && n >= 0 ? n : 0)
            }}
            className="ml-2 w-20 rounded border border-ink-200 px-2 py-1"
          />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={deleteCache} onChange={(e) => setDeleteCache(e.target.checked)} />
          Delete cache
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={deleteArtifacts}
            onChange={(e) => setDeleteArtifacts(e.target.checked)}
          />
          Delete workspace artifacts
        </label>
        <ConfirmButton
          label="Run cleanup"
          confirmLabel="Confirm cleanup"
          danger
          onConfirm={() => {
            void apiJson('/system/cleanup', {
              method: 'POST',
              body: JSON.stringify({
                older_than_days: cleanupDays,
                delete_cache: deleteCache,
                delete_artifacts: deleteArtifacts,
                keep_latest: true,
              }),
            })
              .then((res) => pushToast(formatCleanupToast(res), 'success'))
              .catch((err) => pushToast(err instanceof Error ? err.message : String(err), 'error'))
          }}
        />
      </section>
    </div>
  )
}
