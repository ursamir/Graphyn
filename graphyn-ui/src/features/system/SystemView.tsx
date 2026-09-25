import React from 'react'
import { RefreshCw, Trash2 } from 'lucide-react'
import { apiJson } from '../../api/client'
import {
  formatCleanupToast,
  formatLocaleDateTime,
  formatRelativeTime,
  formatUptime,
  prettyScalar,
} from '../../lib/format'
import { useAppStore } from '../../store/appStore'
import { goView } from '../../routes/nav'
import {
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

function FactRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3 text-sm">
      <dt className="text-ink-500">{label}</dt>
      <dd className="text-right font-medium text-ink-900">{value}</dd>
    </div>
  )
}

function projectName(p: unknown): string {
  if (typeof p === 'string') return p
  if (p && typeof p === 'object' && typeof (p as { name?: unknown }).name === 'string') {
    return (p as { name: string }).name
  }
  return ''
}

function pipelineName(p: unknown): string {
  if (typeof p === 'string') return p
  if (p && typeof p === 'object' && typeof (p as { name?: unknown }).name === 'string') {
    return (p as { name: string }).name
  }
  return ''
}

export default function SystemView() {
  const pushToast = useAppStore((s) => s.pushToast)
  const [health, setHealth] = React.useState<unknown>(null)
  const [ready, setReady] = React.useState<unknown>(null)
  const [metrics, setMetrics] = React.useState<unknown>(null)
  const [webhookUrl, setWebhookUrl] = React.useState('')
  const [webhookEvents, setWebhookEvents] = React.useState<string[]>([])
  const [cleanupDays, setCleanupDays] = React.useState(7)
  const [deleteCache, setDeleteCache] = React.useState(false)
  const [deleteArtifacts, setDeleteArtifacts] = React.useState(false)
  const [cleanupArmed, setCleanupArmed] = React.useState(false)
  const [cleanupConfirmText, setCleanupConfirmText] = React.useState('')
  const [reconcileAbandoned, setReconcileAbandoned] = React.useState(true)
  const [reconciling, setReconciling] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [panelErrors, setPanelErrors] = React.useState<Record<string, string>>({})
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
  const [auditActorFilter, setAuditActorFilter] = React.useState('')
  const [auditResourceFilter, setAuditResourceFilter] = React.useState('')
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
  const [projectOptions, setProjectOptions] = React.useState<string[]>([])
  const [pipelineOptions, setPipelineOptions] = React.useState<string[]>([])
  const [projectsApiOk, setProjectsApiOk] = React.useState(true)
  const [pipelinesApiOk, setPipelinesApiOk] = React.useState(true)
  const [pipelinesLoading, setPipelinesLoading] = React.useState(false)
  const [venvGcBusy, setVenvGcBusy] = React.useState(false)

  const metricsObj = metrics && typeof metrics === 'object' && !Array.isArray(metrics)
    ? (metrics as Record<string, unknown>)
    : null
  const latency =
    metricsObj?.latency_s && typeof metricsObj.latency_s === 'object'
      ? (metricsObj.latency_s as Record<string, unknown>)
      : null

  const runPluginVenvGc = () => {
    setVenvGcBusy(true)
    void apiJson<{ removed?: string[] }>('/plugins/venvs/gc', { method: 'POST' })
      .then((res) => {
        const n = Array.isArray(res?.removed) ? res.removed.length : 0
        pushToast(
          n
            ? `Removed ${n} unused plugin venv${n === 1 ? '' : 's'}`
            : 'No unused plugin venvs to remove',
          'success',
        )
      })
      .catch((err) => pushToast(err instanceof Error ? err.message : String(err), 'error'))
      .finally(() => setVenvGcBusy(false))
  }

  const refresh = React.useCallback(async () => {
    setAuditError(null)
    setLoading(true)
    const errs: Record<string, string> = {}
    const settled = await Promise.allSettled([
      apiJson('/system/health'),
      apiJson('/system/readiness'),
      apiJson('/system/metrics'),
      apiJson<{ url?: string; events?: string[] }>('/system/webhooks'),
      apiJson<{ events?: unknown[] }>('/audit', { query: { limit: 100 } }),
      apiJson<{
        auth_required?: boolean
        token_configured?: boolean
        env?: string
        ok?: boolean
      }>('/system/auth-status'),
      apiJson<{ schedules?: unknown[] }>('/system/schedules'),
    ])
    const label = ['health', 'readiness', 'metrics', 'webhooks', 'audit', 'auth', 'schedules'] as const
    settled.forEach((res, i) => {
      const key = label[i]
      if (res.status === 'rejected') {
        errs[key] = res.reason instanceof Error ? res.reason.message : String(res.reason)
      }
    })
    setPanelErrors(errs)
    setError(
      errs.health && errs.readiness
        ? 'Health and readiness probes failed — see panel messages below.'
        : null,
    )

    if (settled[0].status === 'fulfilled') setHealth(settled[0].value)
    if (settled[1].status === 'fulfilled') setReady(settled[1].value)
    if (settled[2].status === 'fulfilled') setMetrics(settled[2].value)
    if (settled[3].status === 'fulfilled') {
      const w = settled[3].value
      setWebhookUrl(w.url ?? '')
      setWebhookEvents(w.events ?? [])
    }
    if (settled[4].status === 'fulfilled') {
      const audit = settled[4].value
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
    } else {
      setAuditError(errs.audit ?? 'Audit feed unavailable')
      setAuditEvents([])
    }
    if (settled[5].status === 'fulfilled') setAuthStatus(settled[5].value)
    if (settled[6].status === 'fulfilled') {
      const sched = settled[6].value
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
    } else {
      setSchedules([])
    }
    setLoading(false)
  }, [])

  const loadProjects = React.useCallback(async () => {
    try {
      const list = await apiJson<unknown[]>('/projects')
      const names = (Array.isArray(list) ? list : []).map(projectName).filter(Boolean)
      setProjectOptions(names)
      setProjectsApiOk(true)
    } catch {
      setProjectOptions([])
      setProjectsApiOk(false)
    }
  }, [])

  React.useEffect(() => {
    void refresh()
  }, [refresh])

  React.useEffect(() => {
    void loadProjects()
  }, [loadProjects])

  React.useEffect(() => {
    if (!schedProject.trim() || !projectsApiOk) {
      setPipelineOptions([])
      setPipelinesApiOk(true)
      return
    }
    let cancelled = false
    setPipelinesLoading(true)
    void apiJson<unknown[]>(`/projects/${encodeURIComponent(schedProject.trim())}/pipelines`)
      .then((list) => {
        if (cancelled) return
        const names = (Array.isArray(list) ? list : []).map(pipelineName).filter(Boolean)
        setPipelineOptions(names)
        setPipelinesApiOk(true)
        setSchedPipeline((cur) => (cur && names.includes(cur) ? cur : names[0] ?? ''))
      })
      .catch(() => {
        if (cancelled) return
        setPipelineOptions([])
        setPipelinesApiOk(false)
      })
      .finally(() => {
        if (!cancelled) setPipelinesLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [schedProject, projectsApiOk])

  const [systemTab, setSystemTab] = React.useState<
    'status' | 'schedules' | 'webhooks' | 'cleanup' | 'audit'
  >('status')

  const readyObj = ready && typeof ready === 'object' ? (ready as Record<string, unknown>) : null
  const healthObj = health && typeof health === 'object' ? (health as Record<string, unknown>) : null
  const backendMode = String(readyObj?.backend_mode ?? '').trim()
  const backendId = String(readyObj?.backend ?? '').trim()
  const workerCount = Number(readyObj?.worker_count ?? NaN)
  const nodeTypeCount = Number(readyObj?.node_type_count ?? NaN)
  const registryReady = readyObj?.registry_ready === true || readyObj?.status === 'ready'
  // Distinguish "still starting" (transient, will resolve) from "hard-failed"
  // (permanent until the plugin/manifest issue is fixed and the API restarted) —
  // status:"failed" + registry_init_error come from a real AutoDiscovery
  // exception, not from still-loading isolated venvs.
  const registryInitError =
    typeof readyObj?.registry_init_error === 'string' && readyObj.registry_init_error.trim()
      ? readyObj.registry_init_error.trim()
      : null
  const registryFailed = readyObj?.status === 'failed' && !!registryInitError
  const isDistributed = backendMode === 'distributed'
  const backendLabel =
    backendMode === 'distributed'
      ? 'Distributed'
      : backendMode === 'local'
        ? 'Local'
        : backendId
          ? backendId
          : ''

  const goNav = (view: 'workers' | 'proposals' | 'plugins') => goView(view)

  const canAddSchedule =
    Boolean(schedName.trim()) && Boolean(schedProject.trim()) && Boolean(schedPipeline.trim())

  const filteredAuditEvents = React.useMemo(() => {
    const actorQ = auditActorFilter.trim().toLowerCase()
    const resourceQ = auditResourceFilter.trim().toLowerCase()
    return auditEvents.filter((ev) => {
      if (actorQ && !String(ev.actor || '').toLowerCase().includes(actorQ)) return false
      if (resourceQ) {
        const blob = `${ev.resource_type || ''} ${ev.resource_id || ''} ${ev.action || ''}`.toLowerCase()
        if (!blob.includes(resourceQ)) return false
      }
      return true
    })
  }, [auditEvents, auditActorFilter, auditResourceFilter])

  const exportAuditJson = () => {
    const blob = new Blob([JSON.stringify(filteredAuditEvents, null, 2)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `audit-events-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const tabs: Array<{ id: typeof systemTab; label: string }> = [
    { id: 'status', label: 'Status' },
    { id: 'schedules', label: 'Schedules' },
    { id: 'webhooks', label: 'Webhooks' },
    { id: 'cleanup', label: 'Cleanup' },
    { id: 'audit', label: 'Audit' },
  ]

  const useProjectSelect = projectsApiOk && projectOptions.length > 0
  const usePipelineSelect = useProjectSelect && pipelinesApiOk && !!schedProject.trim()

  return (
    <div className="h-full min-h-0 overflow-y-auto p-6 space-y-5">
      <PageHeader
        title="Ops"
        description="Health, schedules, webhooks, cleanup, audit. Shared-bearer single-tenant — see trust note on Status."
        actions={
          <button type="button" className="btn-secondary" onClick={() => void refresh()}>
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </button>
        }
      />
      {error && <ErrorBanner message={error} onRetry={() => void refresh()} />}
      {loading && health == null && ready == null ? <LoadingBlock label="Loading system status…" /> : null}

      <div className="flex flex-wrap gap-1 border-b border-ink-200/80 pb-0">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setSystemTab(t.id)}
            className={
              systemTab === t.id
                ? 'border-b-2 border-accent-600 px-3 py-2 text-[13px] font-semibold text-ink-950'
                : 'px-3 py-2 text-[13px] text-ink-500 hover:text-ink-800'
            }
          >
            {t.label}
          </button>
        ))}
      </div>

      {authStatus && authStatus.auth_required && !authStatus.token_configured ? (
        <div className="rounded-2xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950">
          Auth is required ({authStatus.env || 'production'}) but{' '}
          <code className="font-mono text-xs">GRAPHYN_API_TOKEN</code> is not configured on the
          server. Set the token and paste the same value in Settings.
        </div>
      ) : null}

      {systemTab === 'status' && (
        <div className="space-y-4">
          <div
            className="rounded-2xl border border-ink-200 bg-ink-50/80 px-4 py-3 text-xs text-ink-700 shadow-sm"
            role="note"
            data-testid="ops-trust-honesty"
          >
            <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-500">
              Auth &amp; token honesty
            </div>
            <ul className="mt-1.5 list-disc space-y-1 pl-4 leading-relaxed">
              <li>
                Single-tenant <strong>shared Bearer</strong> (SEC-001 / DIST-AUTH): API operators and
                Mode B workers use the same token — no fake RBAC.
              </li>
              <li>
                Console stores the token in <code className="font-mono text-[11px]">localStorage</code>{' '}
                (interim). XSS can exfiltrate it (THREAT-001/002); CSP is baseline-only.
              </li>
              <li>
                Backup / restore of <code className="font-mono text-[11px]">GRAPHYN_HOME</code> + project
                dir: see <code className="font-mono text-[11px]">docs/OPS_BACKUP_RESTORE.md</code>.
              </li>
            </ul>
          </div>
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
            ) : (
              <span className="text-[12px] text-ink-400">Unknown</span>
            )}
            {isDistributed ? (
              <button
                type="button"
                className="rounded-full border border-ink-200 bg-white px-2.5 py-0.5 text-[12px] text-ink-700 hover:border-accent-300 hover:text-accent-800"
                onClick={() => goNav('workers')}
                title="Open Workers"
              >
                {Number.isFinite(workerCount)
                  ? `${workerCount} ${workerCount === 1 ? 'worker' : 'workers'}`
                  : 'Workers'}
              </button>
            ) : null}
            <span
              className="rounded-full border border-ink-200 bg-ink-50 px-2.5 py-0.5 text-[11px] text-ink-600"
              title="MCP runs as a separate stdio process — not an HTTP health check"
            >
              MCP: <code className="font-mono text-[10px]">graphyn mcp</code> · 29 tools
            </span>
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

          {panelErrors.metrics ? (
            <p className="text-xs text-rose-700">{panelErrors.metrics}</p>
          ) : null}
          {metricsObj ? (
            <div className="flex flex-wrap items-stretch gap-2 rounded-2xl border border-ink-200 bg-white px-3 py-2.5 shadow-sm">
              <span className="self-center text-[11px] font-semibold uppercase tracking-wide text-ink-400 px-1">
                Metrics
              </span>
              {(
                [
                  [
                    'Requests',
                    typeof metricsObj.requests_total === 'number'
                      ? String(metricsObj.requests_total)
                      : '—',
                  ],
                  [
                    'Uptime',
                    typeof metricsObj.uptime_s === 'number'
                      ? formatUptime(metricsObj.uptime_s) || '—'
                      : '—',
                  ],
                  [
                    'RPS',
                    typeof metricsObj.requests_per_second === 'number'
                      ? metricsObj.requests_per_second.toFixed(2)
                      : '—',
                  ],
                  [
                    '5xx',
                    typeof metricsObj.errors_5xx_total === 'number'
                      ? String(metricsObj.errors_5xx_total)
                      : '0',
                  ],
                  [
                    'p95',
                    typeof latency?.p95 === 'number'
                      ? `${Math.round(Number(latency.p95) * 1000)}ms`
                      : '—',
                  ],
                ] as const
              ).map(([label, value]) => (
                <div
                  key={label}
                  className="min-w-[4.5rem] rounded-xl border border-ink-100 bg-ink-50/80 px-3 py-1.5"
                >
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">
                    {label}
                  </div>
                  <div className="font-mono text-sm font-semibold text-ink-900">{value}</div>
                </div>
              ))}
            </div>
          ) : null}

          <div className="grid gap-4 md:grid-cols-2">
            <section className="rounded-2xl border border-ink-200 bg-white p-4">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-sm font-semibold">Health</h3>
                <StatusBadge status={badgeFromPayload(health, ['ok'])} />
              </div>
              {panelErrors.health ? (
                <p className="mb-2 text-xs text-rose-700">{panelErrors.health}</p>
              ) : null}
              <dl className="space-y-1.5">
                <FactRow
                  label="Process"
                  value={healthObj?.status === 'ok' ? 'Responding' : prettyScalar(healthObj?.status) || '—'}
                />
                <FactRow
                  label="Checked"
                  value={
                    typeof healthObj?.timestamp === 'string'
                      ? formatLocaleDateTime(healthObj.timestamp)
                      : '—'
                  }
                />
              </dl>
              <p className="mt-3 text-[11px] text-ink-400">
                Liveness only — the API process answered. Catalog readiness is below.
              </p>
            </section>

            <section className="rounded-2xl border border-ink-200 bg-white p-4">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-sm font-semibold">Readiness</h3>
                <StatusBadge status={badgeFromPayload(ready, ['ready'])} />
              </div>
              {panelErrors.readiness ? (
                <p className="mb-2 text-xs text-rose-700">{panelErrors.readiness}</p>
              ) : null}
              <dl className="space-y-1.5">
                <FactRow
                  label="Catalog"
                  value={
                    registryReady
                      ? Number.isFinite(nodeTypeCount)
                        ? `Ready · ${nodeTypeCount} node types`
                        : 'Ready'
                      : registryFailed
                        ? 'Failed to load'
                        : 'Still loading plugins…'
                  }
                />
                <FactRow
                  label="Backend"
                  value={
                    backendLabel
                      ? `${backendLabel}${backendId && backendId !== backendMode ? ` (${backendId})` : ''}`
                      : '—'
                  }
                />
                {isDistributed ? (
                  <FactRow
                    label="Workers"
                    value={Number.isFinite(workerCount) ? String(workerCount) : '—'}
                  />
                ) : null}
                <FactRow
                  label="Runs folder"
                  value={
                    (readyObj?.checks as Record<string, unknown> | undefined)?.runs_dir_exists === true
                      ? 'Yes'
                      : 'Missing'
                  }
                />
                <FactRow
                  label="Cache folder"
                  value={
                    (readyObj?.checks as Record<string, unknown> | undefined)?.cache_dir_exists === true
                      ? 'Yes'
                      : 'Missing'
                  }
                />
                <FactRow
                  label="Checked"
                  value={
                    typeof readyObj?.timestamp === 'string'
                      ? formatLocaleDateTime(String(readyObj.timestamp))
                      : '—'
                  }
                />
              </dl>
              {registryFailed ? (
                <p className="mt-3 rounded-lg bg-rose-50 p-2 text-[11px] text-rose-800">
                  Node registry failed to load and will not recover on its own — this is a
                  hard AutoDiscovery error (e.g. a duplicate node_type or a broken plugin
                  import), not a slow install. Fix the plugin, then restart the API.
                  <br />
                  <code className="mt-1 block whitespace-pre-wrap break-all font-mono">
                    {registryInitError}
                  </code>
                </p>
              ) : !registryReady ? (
                <p className="mt-3 text-[11px] text-amber-800">
                  Health can be OK while plugins finish installing. Refresh in a moment, or open{' '}
                  <button type="button" className="font-medium text-accent-700 hover:underline" onClick={() => goNav('plugins')}>
                    Plugins
                  </button>
                  .
                </p>
              ) : null}
            </section>
          </div>

          <section className="rounded-2xl border border-ink-200 bg-white px-4 py-3">
            <div className="flex flex-wrap items-center gap-3">
              <div className="min-w-0 flex-1">
                <h3 className="text-sm font-semibold text-ink-900">Maintenance</h3>
                <p className="text-[12px] text-ink-500">
                  Remove unused isolated plugin environments left behind after uninstalls.
                </p>
              </div>
              <button
                type="button"
                className="btn-secondary"
                disabled={venvGcBusy}
                onClick={runPluginVenvGc}
              >
                <Trash2 className="h-3.5 w-3.5" />
                {venvGcBusy ? 'Cleaning…' : 'Clean unused plugin venvs'}
              </button>
            </div>
          </section>
        </div>
      )}

      {systemTab === 'audit' && (
        <section className="rounded-2xl border border-ink-200 bg-white p-4 space-y-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold">Recent audit events</h3>
              <p className="text-xs text-ink-500">
                Who did what on this API (last 100 events). Filters apply in the browser.
                {auditEvents.length > 0
                  ? ` Showing ${filteredAuditEvents.length} of ${auditEvents.length}.`
                  : ''}
              </p>
            </div>
            <button
              type="button"
              className="btn-secondary"
              disabled={filteredAuditEvents.length === 0}
              onClick={exportAuditJson}
            >
              Export JSON
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            <input
              value={auditActorFilter}
              onChange={(e) => setAuditActorFilter(e.target.value)}
              placeholder="Filter actor"
              className="rounded-lg border border-ink-200 px-3 py-1.5 text-sm"
              aria-label="Filter audit by actor"
            />
            <input
              value={auditResourceFilter}
              onChange={(e) => setAuditResourceFilter(e.target.value)}
              placeholder="Filter resource / action"
              className="rounded-lg border border-ink-200 px-3 py-1.5 text-sm"
              aria-label="Filter audit by resource"
            />
            {(auditActorFilter || auditResourceFilter) && (
              <button
                type="button"
                className="btn-quiet"
                onClick={() => {
                  setAuditActorFilter('')
                  setAuditResourceFilter('')
                }}
              >
                Clear filters
              </button>
            )}
          </div>
          {auditError && <p className="text-sm text-amber-800">{auditError}</p>}
          {!auditError && auditEvents.length === 0 ? (
            <EmptyState
              title="No audit events yet"
              description="Accept/reject proposals or other audited mutations will appear here."
              action={
                <button type="button" className="btn-secondary" onClick={() => goNav('proposals')}>
                  Open Proposals
                </button>
              }
            />
          ) : filteredAuditEvents.length === 0 ? (
            <p className="py-4 text-center text-sm text-ink-500">No events match these filters.</p>
          ) : (
            <div className="overflow-hidden rounded-xl border border-ink-100">
              <table className="w-full text-left text-[12px]">
                <thead className="border-b border-ink-100 bg-ink-50/80 text-[10px] uppercase tracking-wide text-ink-500">
                  <tr>
                    <th className="px-2 py-1.5 font-semibold">When</th>
                    <th className="px-2 py-1.5 font-semibold">Actor</th>
                    <th className="px-2 py-1.5 font-semibold">Action</th>
                    <th className="px-2 py-1.5 font-semibold">Resource</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredAuditEvents.map((ev, i) => (
                    <tr key={ev.event_id || `${ev.ts}-${i}`} className="border-b border-ink-50 last:border-0">
                      <td className="px-2 py-1 text-ink-600 whitespace-nowrap" title={formatLocaleDateTime(ev.ts)}>
                        {ev.ts ? formatRelativeTime(ev.ts) : '—'}
                      </td>
                      <td className="px-2 py-1 text-ink-800 truncate max-w-[8rem]">{ev.actor || '—'}</td>
                      <td className="px-2 py-1">
                        <StatusBadge status={String(ev.action || 'unknown')} />
                      </td>
                      <td className="px-2 py-1 font-mono text-[10px] text-ink-600 truncate max-w-[12rem]" title={`${ev.resource_type}:${ev.resource_id}`}>
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
      )}

      {systemTab === 'schedules' && (
      <section className="rounded-2xl border border-ink-200 bg-white p-4 space-y-3">
        {panelErrors.schedules ? (
          <p className="text-xs text-rose-700">{panelErrors.schedules}</p>
        ) : null}
        <div>
          <h3 className="text-sm font-semibold">Schedules</h3>
          <p className="text-xs text-ink-500">
            Run a project pipeline on a fixed interval while this API is up. Choose an interval in
            minutes (not cron expressions).
          </p>
        </div>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <input
            className="rounded-lg border border-ink-200 px-3 py-2 text-sm"
            placeholder="Name"
            value={schedName}
            onChange={(e) => setSchedName(e.target.value)}
          />
          {useProjectSelect ? (
            <select
              className="rounded-lg border border-ink-200 px-3 py-2 text-sm"
              value={schedProject}
              onChange={(e) => {
                setSchedProject(e.target.value)
                setSchedPipeline('')
              }}
            >
              <option value="">Select project…</option>
              {projectOptions.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          ) : (
            <input
              className="rounded-lg border border-ink-200 px-3 py-2 text-sm"
              placeholder="Project"
              value={schedProject}
              onChange={(e) => setSchedProject(e.target.value)}
            />
          )}
          {usePipelineSelect ? (
            <select
              className="rounded-lg border border-ink-200 px-3 py-2 text-sm"
              value={schedPipeline}
              disabled={pipelinesLoading || !schedProject}
              onChange={(e) => setSchedPipeline(e.target.value)}
            >
              <option value="">{pipelinesLoading ? 'Loading pipelines…' : 'Select pipeline…'}</option>
              {pipelineOptions.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          ) : (
            <input
              className="rounded-lg border border-ink-200 px-3 py-2 text-sm"
              placeholder="Pipeline"
              value={schedPipeline}
              onChange={(e) => setSchedPipeline(e.target.value)}
            />
          )}
          <label className="block text-sm text-ink-600">
            <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-ink-400">
              Interval (minutes)
            </span>
            <input
              type="number"
              min={1}
              className="w-full rounded-lg border border-ink-200 px-3 py-2 text-sm"
              placeholder="e.g. 60"
              value={schedInterval}
              onChange={(e) => setSchedInterval(Number(e.target.value) || 60)}
              aria-label="Interval in minutes"
            />
          </label>
        </div>
        {!projectsApiOk && (
          <p className="text-xs text-ink-500">Projects API unavailable — enter project and pipeline as text.</p>
        )}
        {projectsApiOk && schedProject && !pipelinesApiOk && (
          <p className="text-xs text-ink-500">Pipelines API unavailable — enter pipeline name as text.</p>
        )}
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-primary"
            disabled={!canAddSchedule}
            onClick={() => {
              void apiJson('/system/schedules', {
                method: 'POST',
                body: JSON.stringify({
                  name: schedName.trim(),
                  project: schedProject.trim(),
                  pipeline: schedPipeline.trim(),
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
            Run due now
          </button>
        </div>
        {loading ? (
          <LoadingBlock label="Loading schedules…" />
        ) : schedules.length === 0 ? (
          <EmptyState
            title="No schedules yet"
            description="Pick a project pipeline and interval, then Add schedule. Jobs only fire while this API process is running."
          />
        ) : (
          <ul className="space-y-2">
            {schedules.map((s) => {
              const hasError = Boolean(s.last_error)
              return (
              <li
                key={s.id}
                className={
                  hasError
                    ? 'flex flex-wrap items-center justify-between gap-2 rounded-xl border border-rose-300 bg-rose-50/70 px-3 py-2 text-sm'
                    : 'flex flex-wrap items-center justify-between gap-2 rounded-xl border border-ink-100 px-3 py-2 text-sm'
                }
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2 font-medium text-ink-900">
                    <span>{s.name}</span>
                    <span className="font-mono text-[11px] text-ink-500">
                      {s.project}/{s.pipeline}
                    </span>
                    <StatusBadge status={s.enabled ? 'enabled' : 'disabled'} />
                  </div>
                  <div className="text-[11px] text-ink-500">
                    every {s.interval_minutes ?? '—'} min
                    {s.enabled && s.next_run_at ? ` · next ${formatRelativeTime(s.next_run_at)}` : ''}
                    {!s.enabled ? ' · paused' : ''}
                    {s.last_run_id ? ` · last run ${String(s.last_run_id).slice(0, 8)}…` : ''}
                  </div>
                  {hasError ? (
                    <div className="mt-1 text-[12px] font-medium text-rose-900" title={s.last_error}>
                      Last error: {s.last_error}
                    </div>
                  ) : null}
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
              )
            })}
          </ul>
        )}
      </section>
      )}

      {systemTab === 'webhooks' && (
      <section className="rounded-2xl border border-ink-200 bg-white p-4 space-y-3">
        {panelErrors.webhooks ? (
          <p className="text-xs text-rose-700">{panelErrors.webhooks}</p>
        ) : null}
        <div>
          <h3 className="text-sm font-semibold">Webhooks</h3>
          <p className="text-xs text-ink-500">
            Send a POST when pipelines finish or fail. Leave events unchecked to receive all event
            types.
          </p>
        </div>
        {!webhookUrl.trim() ? (
          <p className="rounded-lg border border-ink-100 bg-ink-50/80 px-3 py-2 text-[12px] text-ink-600">
            No webhook URL saved yet.
          </p>
        ) : null}
        <label className="block text-sm text-ink-600">
          <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-ink-400">
            Endpoint URL
          </span>
          <input
            value={webhookUrl}
            onChange={(e) => setWebhookUrl(e.target.value)}
            placeholder="https://hooks.example.com/…"
            className="w-full rounded-lg border border-ink-200 px-3 py-2 text-sm"
          />
        </label>
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
                body: JSON.stringify({ url: webhookUrl.trim(), events: webhookEvents }),
              })
                .then(() =>
                  pushToast(webhookUrl.trim() ? 'Webhook saved' : 'Webhook cleared', 'success'),
                )
                .catch((err) => pushToast(err instanceof Error ? err.message : String(err), 'error'))
            }
          >
            Save
          </button>
          <button
            type="button"
            className="btn-secondary"
            disabled={!webhookUrl.trim()}
            onClick={() =>
              void apiJson<{ ok?: boolean; reason?: string }>('/system/webhooks/test', {
                method: 'POST',
              })
                .then((res) => {
                  if (res?.ok === false) {
                    pushToast(res.reason || 'Webhook test failed', 'error')
                    return
                  }
                  pushToast('Test webhook sent', 'success')
                })
                .catch((err) => pushToast(err instanceof Error ? err.message : String(err), 'error'))
            }
          >
            Send test
          </button>
        </div>
      </section>
      )}

      {systemTab === 'cleanup' && (
      <section className="rounded-2xl border border-ink-200 bg-white p-4 space-y-3">
        <h3 className="text-sm font-semibold">Cleanup</h3>
        <p className="text-sm text-ink-500">
          Free disk by deleting finished run records older than N days (always keeps the latest run
          per pipeline). Optionally clear the pipeline cache and matching workspace artifacts.
          Running runs, examples, and dataset inputs are never deleted.
        </p>
        <p className="text-xs text-amber-800 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
          Destructive options stay unchecked by default. Type{' '}
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
      )}
    </div>
  )
}
