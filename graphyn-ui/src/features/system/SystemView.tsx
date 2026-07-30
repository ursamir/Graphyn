import React from 'react'
import { RefreshCw } from 'lucide-react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import {
  ConfirmButton,
  EmptyState,
  ErrorBanner,
  LoadingBlock,
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

export default function SystemView() {
  const pushToast = useAppStore((s) => s.pushToast)
  const [health, setHealth] = React.useState<unknown>(null)
  const [ready, setReady] = React.useState<unknown>(null)
  const [metrics, setMetrics] = React.useState<unknown>(null)
  const [webhookUrl, setWebhookUrl] = React.useState('')
  const [webhookEvents, setWebhookEvents] = React.useState<string[]>([])
  const [cleanupDays, setCleanupDays] = React.useState(7)
  const [deleteCache, setDeleteCache] = React.useState(true)
  const [deleteArtifacts, setDeleteArtifacts] = React.useState(false)
  const [registryQ, setRegistryQ] = React.useState('')
  const [registryStatus, setRegistryStatus] = React.useState('')
  const [registry, setRegistry] = React.useState<Array<Record<string, unknown>>>([])
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)

  const refresh = React.useCallback(async () => {
    setError(null)
    setLoading(true)
    try {
      const [h, r, m, w] = await Promise.all([
        apiJson('/system/health'),
        apiJson('/system/readiness'),
        apiJson('/system/metrics'),
        apiJson<{ url?: string; events?: string[] }>('/system/webhooks'),
      ])
      setHealth(h)
      setReady(r)
      setMetrics(m)
      setWebhookUrl(w.url ?? '')
      setWebhookEvents(w.events ?? [])
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    void refresh()
  }, [refresh])

  const searchRegistry = async () => {
    try {
      const rows = await apiJson<Array<Record<string, unknown>>>('/system/projects-registry', {
        query: {
          q: registryQ || undefined,
          status: registryStatus || undefined,
        },
      })
      setRegistry(rows)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-lg font-bold">System</h2>
        <button type="button" className="btn-secondary" onClick={() => void refresh()}>
          <RefreshCw className="h-3.5 w-3.5" /> Refresh
        </button>
      </div>
      {error && <ErrorBanner message={error} onRetry={() => void refresh()} />}
      {loading && <LoadingBlock label="Loading system status…" />}

      <div className="grid gap-4 md:grid-cols-3">
        {[
          ['Health', health, badgeFromPayload(health, ['ok'])],
          ['Readiness', ready, badgeFromPayload(ready, ['ready'])],
          ['Metrics', metrics, 'live'],
        ].map(([title, data, badge]) => (
          <section key={String(title)} className="rounded-2xl border border-ink-200 bg-white p-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-semibold">{title as string}</h3>
              <StatusBadge status={String(badge)} />
            </div>
            <pre className="max-h-48 overflow-auto font-mono text-[11px] text-ink-700">
              {JSON.stringify(data, null, 2)}
            </pre>
          </section>
        ))}
      </div>

      <section className="rounded-2xl border border-ink-200 bg-white p-4 space-y-3">
        <h3 className="text-sm font-semibold">Webhooks</h3>
        <input
          value={webhookUrl}
          onChange={(e) => setWebhookUrl(e.target.value)}
          placeholder="https://hooks.example.com/…"
          className="w-full rounded-lg border border-ink-200 px-3 py-2 text-sm"
        />
        <div className="flex flex-wrap gap-4 text-sm">
          {['pipeline_complete', 'pipeline_failed'].map((ev) => (
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
              {ev}
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
        <label className="block text-sm text-ink-600">
          Older than days
          <input
            type="number"
            min={1}
            value={cleanupDays}
            onChange={(e) => setCleanupDays(Number(e.target.value) || 7)}
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
          Delete artifacts
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
              }),
            })
              .then((res) => pushToast(`Cleanup done: ${JSON.stringify(res)}`, 'success'))
              .catch((err) => pushToast(err instanceof Error ? err.message : String(err), 'error'))
          }}
        />
      </section>

      <section className="rounded-2xl border border-ink-200 bg-white p-4 space-y-3">
        <h3 className="text-sm font-semibold">Projects registry</h3>
        <div className="flex flex-wrap gap-2">
          <input
            value={registryQ}
            onChange={(e) => setRegistryQ(e.target.value)}
            placeholder="Search name…"
            className="rounded-lg border border-ink-200 px-2 py-1.5 text-sm"
          />
          <input
            value={registryStatus}
            onChange={(e) => setRegistryStatus(e.target.value)}
            placeholder="status filter"
            className="rounded-lg border border-ink-200 px-2 py-1.5 text-sm"
          />
          <button type="button" className="btn-primary" onClick={() => void searchRegistry()}>
            Search
          </button>
        </div>
        {registry.length === 0 ? (
          <EmptyState title="No registry results" description="Run a search against /system/projects-registry." />
        ) : (
          <div className="overflow-auto rounded-xl border border-ink-100">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-ink-100 text-[11px] uppercase text-ink-500">
                <tr>
                  <th className="px-3 py-2">Name</th>
                  <th className="px-3 py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {registry.map((row) => (
                  <tr key={String(row.name)} className="border-b border-ink-50">
                    <td className="px-3 py-2 font-medium">{String(row.name ?? '')}</td>
                    <td className="px-3 py-2">
                      {row.status ? <StatusBadge status={String(row.status)} /> : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
