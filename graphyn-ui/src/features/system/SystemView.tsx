import React from 'react'
import { CalendarClock as EmptyCalendarClock, ScrollText as EmptyScrollText } from 'lucide-react'
import { RefreshCw, Trash2 } from 'lucide-react'
import { workspaceErrorMessage } from '../../lib/workspaceName'
import { apiJson } from '../../api/client'
import { CRON_PRESETS, describeCron, intervalText, scheduleCadence } from '../../lib/cron'
import { ActorName } from '../../components/ActorName'
import { unwrapList } from '../../api/unwrapList'
import {
  formatCleanupToast,
  formatLocaleDateTime,
  formatRelativeTime,
  formatUptime,
  prettyScalar,
} from '../../lib/format'
import { useAppStore } from '../../store/appStore'
import { goView, guardedNavigatePath } from '../../routes/nav'
import { paths } from '../../routes/paths'
import {
  AUDIT_CATEGORIES,
  AUDIT_CATEGORY_LABEL,
  DEFAULT_AUDIT_CATEGORIES,
  auditActionTone,
  auditActorDisplay,
  auditCategory,
  auditCategoryQuery,
  auditEventLabel,
  auditMatchesQuery,
  auditResourceLabel,
  auditTarget,
  nextAuditLimit,
  type AuditCategory,
  relatedRunId,
  type AuditEvent,
  type AuditTarget,
} from './auditEvents'
import {
  EmptyState,
  ErrorBanner,
  IdeTabs,
  LoadingBlock,
  StatusBadge,
} from '../../components/ui'
import { WorkbenchPage } from '../../layout'

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

/** GET /system/schedules row. `orphaned` = owning workspace was deleted. */
type ScheduleRow = {
  id?: string
  name?: string
  project?: string
  pipeline?: string
  interval_minutes?: number
  /** 5-field UTC cron (overrides interval_minutes) — newer APIs only. */
  cron?: string | null
  enabled?: boolean
  next_run_at?: string
  last_run_id?: string
  last_error?: string
  env?: string
  orphaned?: boolean
  orphaned_at?: string
  disabled_reason?: string
}

/** Plain-language action, technical name in the tooltip. */
const STUCK_RUNS_TIP =
  'Reconcile abandoned runs — POST /system/cleanup with reconcile_abandoned: RUNNING/QUEUED runs with no heartbeat for 1h are marked FAILED. Nothing is deleted.'

/** Shared label + control styling so every Add-schedule field lines up. */
const SCHED_LABEL = 'mb-1 block text-[12px] font-semibold text-ink-600'
const SCHED_FIELD = 'h-9 w-full rounded-lg border border-ink-200 bg-white px-3 text-sm disabled:bg-ink-50 disabled:text-ink-400'

export default function SystemView() {
  const pushToast = useAppStore((s) => s.pushToast)
  const [health, setHealth] = React.useState<unknown>(null)
  const [ready, setReady] = React.useState<unknown>(null)
  const [metrics, setMetrics] = React.useState<unknown>(null)
  const [webhookUrl, setWebhookUrl] = React.useState('')
  const [webhookDraft, setWebhookDraft] = React.useState('')
  const [webhookConfigured, setWebhookConfigured] = React.useState(false)
  const [webhookVersion, setWebhookVersion] = React.useState<string | null>(null)
  const [webhookEvents, setWebhookEvents] = React.useState<string[]>([])
  const [cleanupDays, setCleanupDays] = React.useState(7)
  const [deleteCache, setDeleteCache] = React.useState(false)
  const [deleteArtifacts, setDeleteArtifacts] = React.useState(false)
  const [cleanupArmed, setCleanupArmed] = React.useState(false)
  const [cleanupConfirmText, setCleanupConfirmText] = React.useState('')
  const [cleanupBusy, setCleanupBusy] = React.useState(false)
  const cleanupInFlight = React.useRef(false)
  const [reconcileAbandoned, setReconcileAbandoned] = React.useState(true)
  const [reconciling, setReconciling] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [panelErrors, setPanelErrors] = React.useState<Record<string, string>>({})
  const [loading, setLoading] = React.useState(true)
  const [auditEvents, setAuditEvents] = React.useState<AuditEvent[]>([])
  /** Events requested from GET /audit (API caps limit at 1000). */
  const [auditLimit, setAuditLimit] = React.useState(100)
  /** Server says older events exist (GET /audit has_more); null = old API without paging info. */
  const [auditHasMore, setAuditHasMore] = React.useState<boolean | null>(null)
  const auditLimitRef = React.useRef(100)
  auditLimitRef.current = auditLimit
  const [auditLoadingMore, setAuditLoadingMore] = React.useState(false)
  /** Run id / resource search (client-side over the loaded events). */
  const [auditQuery, setAuditQuery] = React.useState('')
  const openRunInStore = useAppStore((s) => s.openRun)
  const openProposalsInStore = useAppStore((s) => s.openProposals)
  const activeProjectForAudit = useAppStore((s) => s.activeProject)
  const [auditError, setAuditError] = React.useState<string | null>(null)
  const [auditActorFilter, setAuditActorFilter] = React.useState('')
  const [auditResourceFilter, setAuditResourceFilter] = React.useState('')
  /** Housekeeping events (notifications.*) are hidden unless this is on. */
  /** Category chips (Runs · Models · Data · Admin · System · UI); UI + System hidden by default (server `exclude_category`). */
  const [auditCategories, setAuditCategories] = React.useState<ReadonlySet<AuditCategory>>(DEFAULT_AUDIT_CATEGORIES)
  const auditCatQueryRef = React.useRef(auditCategoryQuery(DEFAULT_AUDIT_CATEGORIES))
  auditCatQueryRef.current = auditCategoryQuery(auditCategories)
  const [authStatus, setAuthStatus] = React.useState<{
    auth_required?: boolean
    token_configured?: boolean
    env?: string
    ok?: boolean
  } | null>(null)
  const [schedules, setSchedules] = React.useState<
    ScheduleRow[]
  >([])
  const [schedName, setSchedName] = React.useState('hourly')
  const [schedProject, setSchedProject] = React.useState('')
  const [schedPipeline, setSchedPipeline] = React.useState('')
  const [schedInterval, setSchedInterval] = React.useState(60)
  const [schedCadence, setSchedCadence] = React.useState<'interval' | 'cron'>('interval')
  const [schedCron, setSchedCron] = React.useState('0 9 * * 1-5')
  const schedCronPreview = describeCron(schedCron)
  const [schedEnv, setSchedEnv] = React.useState<'draft' | 'staging' | 'prod'>('draft')
  const [projectOptions, setProjectOptions] = React.useState<string[]>([])
  const [pipelineOptions, setPipelineOptions] = React.useState<string[]>([])
  const [projectsApiOk, setProjectsApiOk] = React.useState(true)
  const [pipelinesApiOk, setPipelinesApiOk] = React.useState(true)
  const [pipelinesLoading, setPipelinesLoading] = React.useState(false)
  const [schedSaving, setSchedSaving] = React.useState(false)
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
            ? `Removed ${n} unused plugin environment${n === 1 ? '' : 's'}`
            : 'No unused plugin environments to remove',
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
      apiJson<{
        url?: string
        events?: string[]
        url_configured?: boolean
        resource_version?: string
      }>('/system/webhooks'),
      apiJson<{ events?: unknown[]; has_more?: boolean }>('/audit', {
        query: { limit: auditLimitRef.current, ...auditCatQueryRef.current },
      }),
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
      setWebhookConfigured(Boolean(w.url_configured ?? (w.url ?? '').trim()))
      setWebhookVersion(w.resource_version != null ? String(w.resource_version) : null)
      setWebhookDraft('')
      setWebhookEvents(w.events ?? [])
    }
    if (settled[4].status === 'fulfilled') {
      const audit = settled[4].value
      const events = Array.isArray(audit?.events) ? audit.events : []
      setAuditEvents(
        events.filter((e): e is Record<string, unknown> => !!e && typeof e === 'object') as AuditEvent[],
      )
      setAuditHasMore(typeof audit?.has_more === 'boolean' ? audit.has_more : null)
    } else {
      setAuditError(errs.audit ?? 'Audit feed unavailable')
      setAuditEvents([])
    }
    if (settled[5].status === 'fulfilled') setAuthStatus(settled[5].value)
    if (settled[6].status === 'fulfilled') {
      const sched = settled[6].value
      const schedList = Array.isArray(sched?.schedules) ? sched.schedules : []
      setSchedules(
        schedList.filter((e): e is Record<string, unknown> => !!e && typeof e === 'object') as ScheduleRow[],
      )
    } else {
      setSchedules([])
    }
    setLoading(false)
  }, [])

  const loadProjects = React.useCallback(async () => {
    try {
      const list = unwrapList(await apiJson('/projects'))
      const names = list.map(projectName).filter(Boolean)
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
      // Client-side too: older APIs ignore `exclude_category`.
      if (!auditCategories.has(auditCategory(ev))) return false
      if (actorQ) {
        const who = `${ev.actor || ''} ${auditActorDisplay(ev).label}`.toLowerCase()
        if (!who.includes(actorQ)) return false
      }
      if (resourceQ) {
        const blob = `${ev.resource_type || ''} ${ev.resource_id || ''} ${ev.action || ''} ${auditEventLabel(ev)}`.toLowerCase()
        if (!blob.includes(resourceQ)) return false
      }
      return auditMatchesQuery(ev, auditQuery)
    })
  }, [auditEvents, auditActorFilter, auditResourceFilter, auditQuery, auditCategories])

  /** Category change → refetch the first page with the server-side filter. */
  const auditCatKey = [...auditCategories].sort().join(',')
  const firstAuditCatKey = React.useRef(auditCatKey)
  React.useEffect(() => {
    if (firstAuditCatKey.current === auditCatKey) return
    firstAuditCatKey.current = auditCatKey
    let cancelled = false
    setAuditLimit(100)
    apiJson<{ events?: unknown[]; has_more?: boolean }>('/audit', {
      query: { limit: 100, ...auditCategoryQuery(new Set(auditCatKey.split(',').filter(Boolean))) },
    })
      .then((res) => {
        if (cancelled) return
        const events = Array.isArray(res?.events) ? res.events : []
        setAuditEvents(events.filter((e): e is Record<string, unknown> => !!e && typeof e === 'object') as AuditEvent[])
        setAuditHasMore(typeof res?.has_more === 'boolean' ? res.has_more : null)
        setAuditError(null)
      })
      .catch((err: unknown) => {
        if (!cancelled) setAuditError(err instanceof Error ? err.message : String(err))
      })
    return () => {
      cancelled = true
    }
  }, [auditCatKey])

  const toggleAuditCategory = (c: AuditCategory) =>
    setAuditCategories((prev) => {
      const next = new Set(prev)
      if (next.has(c)) next.delete(c)
      else next.add(c)
      return next.size === 0 ? prev : next
    })

  /**
   * "Load more": with offset paging (new API, `has_more` present) append the next 100 older
   * events; on an old API fall back to re-requesting a bigger limit (newest-first, capped at 1000).
   */
  const loadMoreAudit = async () => {
    setAuditLoadingMore(true)
    try {
      if (auditHasMore !== null) {
        const res = await apiJson<{ events?: unknown[]; has_more?: boolean }>('/audit', {
          query: { limit: 100, offset: auditEvents.length, ...auditCatQueryRef.current },
        })
        const more = (Array.isArray(res?.events) ? res.events : []).filter(
          (e): e is Record<string, unknown> => !!e && typeof e === 'object',
        ) as AuditEvent[]
        setAuditEvents((prev) => [...prev, ...more])
        setAuditLimit((n) => n + more.length)
        setAuditHasMore(typeof res?.has_more === 'boolean' ? res.has_more : more.length >= 100)
        return
      }
      const next = nextAuditLimit(auditLimit)
      const res = await apiJson<{ events?: unknown[] }>('/audit', { query: { limit: next, ...auditCatQueryRef.current } })
      const events = Array.isArray(res?.events) ? res.events : []
      setAuditEvents(events.filter((e): e is Record<string, unknown> => !!e && typeof e === 'object') as AuditEvent[])
      setAuditLimit(next)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setAuditLoadingMore(false)
    }
  }

  const openAuditTarget = (target: AuditTarget) => {
    if (target.kind === 'run') {
      const project = target.project || activeProjectForAudit || ''
      if (!project) {
        pushToast('Open a workspace first — runs open inside a workspace', 'info')
        return
      }
      openRunInStore(target.runId, { project, panel: 'lineage' })
      return
    }
    if (target.kind === 'proposal') {
      openProposalsInStore({ id: target.id })
      return
    }
    if (target.kind === 'model') {
      const ws = target.project || activeProjectForAudit
      if (!ws) {
        pushToast('Open a workspace first to view models', 'info')
        return
      }
      guardedNavigatePath(paths.model(ws, target.name))
      return
    }
    guardedNavigatePath(paths.editor(target.project, target.name))
  }

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

  return (
    <WorkbenchPage
      title="Ops"
      description="Health, schedules, webhooks, cleanup, and audit."
      actions={
        <button type="button" className="btn-secondary" onClick={() => void refresh()}>
          <RefreshCw className="h-3.5 w-3.5" /> Refresh
        </button>
      }
      toolbar={
        <IdeTabs
          aria-label="Ops sections"
          value={systemTab}
          options={tabs}
          onChange={setSystemTab}
        />
      }
    >
      <div className="space-y-4">
      {error && <ErrorBanner message={error} onRetry={() => void refresh()} />}
      {loading && health == null && ready == null ? <LoadingBlock label="Loading system status…" /> : null}

      {authStatus && authStatus.auth_required && !authStatus.token_configured ? (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950">
          Auth is required ({authStatus.env || 'production'}) but{' '}
          <code className="font-mono text-xs">GRAPHYN_API_TOKEN</code> is not configured on the
          server. Set the token and paste the same value in Settings.
        </div>
      ) : null}

      {systemTab === 'status' && (
        <div className="space-y-4">
          <div className="ui-card flex flex-wrap items-center gap-2 text-sm">
            <span className="text-[12px] font-semibold text-ink-600">Backend</span>
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
              title="MCP is a separate process, not part of this health check"
            >
              MCP: <code className="font-mono text-[10px]">graphyn mcp</code>
            </span>
          </div>

          {panelErrors.metrics ? (
            <p className="text-xs text-rose-700">{panelErrors.metrics}</p>
          ) : null}
          {metricsObj ? (
            <div className="flex flex-wrap items-stretch gap-2 ui-card ui-card-sm">
              <span className="self-center px-1 text-[12px] font-semibold text-ink-600">
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
                  <div className="text-[11px] font-medium text-ink-500">
                    {label}
                  </div>
                  <div className="font-mono text-sm font-semibold text-ink-900">{value}</div>
                </div>
              ))}
            </div>
          ) : null}

          <div className="grid gap-4 md:grid-cols-2">
            <section className="ui-card">
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

            <section className="ui-card">
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
                  The node catalog failed to load. It stays failed until the plugin problem is
                  fixed and the API is restarted.
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

          <section className="ui-card space-y-3" aria-labelledby="ops-maintenance-title">
            <h3 id="ops-maintenance-title" className="text-sm font-semibold text-ink-900">
              Maintenance
            </h3>
            <div className="flex flex-wrap items-center gap-3">
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-medium text-ink-800">Stuck runs</div>
                <p className="text-[12px] text-ink-500">
                  Runs still marked running or queued with no progress for over an hour (for example
                  after an API restart) are marked as failed.
                </p>
              </div>
              <button
                type="button"
                className="btn-secondary"
                title={STUCK_RUNS_TIP}
                disabled={reconciling || cleanupBusy}
                onClick={() => {
                  if (cleanupInFlight.current) return
                  cleanupInFlight.current = true
                  setReconciling(true)
                  void apiJson('/system/cleanup', {
                    method: 'POST',
                    timeoutMs: 600000,
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
                    .finally(() => {
                      cleanupInFlight.current = false
                      setReconciling(false)
                    })
                }}
              >
                {reconciling ? 'Marking…' : 'Mark stuck runs as failed'}
              </button>
            </div>
            <div className="flex flex-wrap items-center gap-3 border-t border-ink-100 pt-3">
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-medium text-ink-800">Plugin environments</div>
                <p className="text-[12px] text-ink-500">
                  Remove own-environment folders left behind after plugins are uninstalled.
                </p>
              </div>
              <button
                type="button"
                className="btn-secondary"
                disabled={venvGcBusy}
                onClick={runPluginVenvGc}
                title="Delete unused per-plugin virtualenvs under ~/.graphyn/plugins/venvs (POST /plugins/venvs/gc)"
              >
                <Trash2 className="h-3.5 w-3.5" />
                {venvGcBusy ? 'Cleaning…' : 'Clean unused environments'}
              </button>
            </div>
          </section>
        </div>
      )}

      {systemTab === 'audit' && (
        <section className="ui-card space-y-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold">Audit events</h3>
              <p className="text-xs text-ink-500">
                Who did what on this API, newest first (last {auditLimit.toLocaleString()} requested). Filters and
                search apply to the loaded events.
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
              value={auditQuery}
              onChange={(e) => setAuditQuery(e.target.value)}
              placeholder="Search run id / resource"
              className="min-w-0 flex-1 basis-56 rounded-lg border border-ink-200 px-3 py-1.5 font-mono text-sm"
              aria-label="Search audit by run id or resource"
            />
            <input
              value={auditActorFilter}
              onChange={(e) => setAuditActorFilter(e.target.value)}
              placeholder="Filter actor"
              className="min-w-0 flex-1 basis-32 rounded-lg border border-ink-200 px-3 py-1.5 text-sm"
              aria-label="Filter audit by actor"
            />
            <input
              value={auditResourceFilter}
              onChange={(e) => setAuditResourceFilter(e.target.value)}
              placeholder="Filter type / action"
              className="min-w-0 flex-1 basis-32 rounded-lg border border-ink-200 px-3 py-1.5 text-sm"
              aria-label="Filter audit by resource type or action"
            />
            <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Audit categories">
              {AUDIT_CATEGORIES.map((c) => {
                const on = auditCategories.has(c)
                return (
                  <button
                    key={c}
                    type="button"
                    className={on ? 'catalog-pill catalog-pill-on' : 'catalog-pill'}
                    aria-pressed={on}
                    title={
                      c === 'ui'
                        ? 'Console housekeeping (notifications read …) — hidden by default'
                        : c === 'system'
                          ? 'Automatic events (schedule checks, workers, server) — hidden by default'
                          : `${on ? 'Hide' : 'Show'} ${AUDIT_CATEGORY_LABEL[c].toLowerCase()} events`
                    }
                    onClick={() => toggleAuditCategory(c)}
                  >
                    {AUDIT_CATEGORY_LABEL[c]}
                  </button>
                )
              })}
            </div>
            {(auditActorFilter || auditResourceFilter || auditQuery) && (
              <button
                type="button"
                className="btn-quiet"
                onClick={() => {
                  setAuditActorFilter('')
                  setAuditResourceFilter('')
                  setAuditQuery('')
                }}
              >
                Clear filters
              </button>
            )}
          </div>
          {auditError && <p className="text-sm text-amber-800">{auditError}</p>}
          {!auditError && auditEvents.length === 0 ? (
            <EmptyState icon={EmptyScrollText}
              title="No audit events yet"
              description="Runs, proposals, model registrations and other audited actions appear here."
              action={
                <button type="button" className="btn-secondary" onClick={() => goNav('proposals')}>
                  Open Proposals
                </button>
              }
            />
          ) : filteredAuditEvents.length === 0 ? (
            <p className="py-4 text-center text-sm text-ink-500">
              {auditEvents.every((ev) => !auditCategories.has(auditCategory(ev)))
                ? 'Only events of hidden categories so far — turn on System or UI above to see them.'
                : `No events match these filters${
                    auditLimit < 1000 && auditEvents.length >= auditLimit ? ' in the loaded events — try Load more.' : '.'
                  }`}
            </p>
          ) : (
            <div className="overflow-x-auto rounded-xl border border-ink-100">
              <table className="w-full min-w-[34rem] text-left text-[12px]">
                <thead className="border-b border-ink-100 bg-ink-50/80 text-[11px] text-ink-500">
                  <tr>
                    <th className="px-2 py-1.5 font-semibold">When</th>
                    <th className="px-2 py-1.5 font-semibold">Actor</th>
                    <th className="px-2 py-1.5 font-semibold">Action</th>
                    <th className="px-2 py-1.5 font-semibold">Resource</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredAuditEvents.map((ev, i) => {
                    const when = ev.timestamp || ev.ts
                    const target = auditTarget(ev)
                    const related = relatedRunId(ev)
                    const tone = auditActionTone(ev.action, ev.result)
                    const who = auditActorDisplay(ev)
                    const resourceText = auditResourceLabel(ev)
                    return (
                      <tr key={ev.event_id || `${when}-${i}`} className="border-b border-ink-50 align-top last:border-0">
                        <td className="whitespace-nowrap px-2 py-1 text-ink-600" title={formatLocaleDateTime(when)}>
                          {when ? formatRelativeTime(when) : '—'}
                        </td>
                        <td className="max-w-[10rem] px-2 py-1 text-ink-800">
                          {who.muted ? (
                            <span
                              className="block truncate text-ink-400"
                              title={`No name recorded (${who.detail}${ev.claimed_actor ? ` · claimed "${ev.claimed_actor}"` : ''}). Set your name under Access.`}
                            >
                              Local operator
                            </span>
                          ) : (
                            <ActorName
                              actor={ev.actor}
                              verified={typeof ev.actor_verified === 'boolean' ? ev.actor_verified : undefined}
                              claimed={ev.claimed_actor}
                              className="max-w-full"
                            />
                          )}
                          {who.detail && !who.muted ? <span className="block text-[10px] text-ink-400">{who.detail}</span> : null}
                        </td>
                        <td className="whitespace-nowrap px-2 py-1">
                          <span
                            className={
                              tone === 'danger'
                                ? 'rounded-full bg-rose-50 px-1.5 py-0.5 text-[11px] font-medium text-rose-800'
                                : tone === 'warning'
                                  ? 'rounded-full bg-amber-50 px-1.5 py-0.5 text-[11px] font-medium text-amber-900'
                                  : tone === 'success'
                                    ? 'rounded-full bg-emerald-50 px-1.5 py-0.5 text-[11px] font-medium text-emerald-800'
                                    : tone === 'info'
                                      ? 'rounded-full bg-sky-50 px-1.5 py-0.5 text-[11px] font-medium text-sky-800'
                                      : 'rounded-full bg-ink-100 px-1.5 py-0.5 text-[11px] font-medium text-ink-700'
                            }
                            title={`${ev.action || ''}${ev.result && ev.result !== 'success' ? ` · ${ev.result}` : ''}`}
                          >
                            {auditEventLabel(ev)}
                          </span>
                        </td>
                        <td className="min-w-0 px-2 py-1 text-[11px] text-ink-600">
                          <span className="mr-1 text-ink-400">{ev.resource_type || '—'}</span>
                          {ev.resource_id ? (
                            target ? (
                              <button
                                type="button"
                                className="break-all text-left font-mono text-accent-800 underline-offset-2 hover:underline"
                                title={`Open ${ev.resource_type} ${ev.resource_id}`}
                                onClick={() => openAuditTarget(target)}
                              >
                                {resourceText}
                              </button>
                            ) : (
                              <span className="break-all font-mono" title={ev.resource_id}>
                                {resourceText}
                              </span>
                            )
                          ) : null}
                          {related ? (
                            <span className="block text-ink-400">
                              run{' '}
                              <button
                                type="button"
                                className="font-mono text-accent-800 underline-offset-2 hover:underline"
                                title={`Open run ${related}`}
                                onClick={() => openAuditTarget({ kind: 'run', runId: related, project: '' })}
                              >
                                {related.length > 12 ? related.slice(0, 8) : related}
                              </button>
                            </span>
                          ) : null}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          {auditHasMore === true ? (
            <div className="flex justify-center">
              <button type="button" className="btn-secondary" disabled={auditLoadingMore} onClick={() => void loadMoreAudit()}>
                {auditLoadingMore ? 'Loading…' : 'Load 100 older events'}
              </button>
            </div>
          ) : auditHasMore === false ? null : auditEvents.length >= auditLimit && auditLimit < 1000 ? (
            <div className="flex justify-center">
              <button type="button" className="btn-secondary" disabled={auditLoadingMore} onClick={() => void loadMoreAudit()}>
                {auditLoadingMore ? 'Loading…' : `Load more (next ${Math.min(100, 1000 - auditLimit)})`}
              </button>
            </div>
          ) : auditLimit >= 1000 && auditEvents.length >= 1000 ? (
            <p className="text-center text-[11px] text-ink-400">
              Showing the newest 1,000 events (server limit). Use Export JSON or the CLI for older history.
            </p>
          ) : null}
        </section>
      )}

      {systemTab === 'schedules' && (
      <section className="ui-card space-y-3">
        {panelErrors.schedules ? (
          <p className="text-xs text-rose-700">{panelErrors.schedules}</p>
        ) : null}
        <div>
          <h3 className="text-sm font-semibold">Schedules</h3>
          <p className="text-xs text-ink-500">
            Run a saved pipeline every N minutes or on a cron (UTC) while this API is up. Draft runs the pipeline
            as saved. Staging and prod run a published version.
          </p>
        </div>
        <div className="grid items-end gap-2 sm:grid-cols-2 lg:grid-cols-5">
          <label className="block text-sm text-ink-600">
            <span className={SCHED_LABEL}>Name</span>
            <input
              className={SCHED_FIELD}
              placeholder="e.g. hourly"
              value={schedName}
              onChange={(e) => setSchedName(e.target.value)}
            />
          </label>
          <label className="block text-sm text-ink-600">
            <span className={SCHED_LABEL}>Workspace</span>
            {useProjectSelect ? (
              <select
                className={SCHED_FIELD}
                value={schedProject}
                onChange={(e) => {
                  setSchedProject(e.target.value)
                  setSchedPipeline('')
                }}
              >
                <option value="">Select workspace…</option>
                {projectOptions.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            ) : (
              <input
                className={SCHED_FIELD}
                placeholder="workspace name"
                value={schedProject}
                onChange={(e) => setSchedProject(e.target.value)}
              />
            )}
          </label>
          <label className="block text-sm text-ink-600">
            <span className={SCHED_LABEL}>Pipeline</span>
            {useProjectSelect && (!schedProject.trim() || pipelinesApiOk) ? (
              <select
                className={SCHED_FIELD}
                value={schedPipeline}
                disabled={pipelinesLoading || !schedProject || pipelineOptions.length === 0}
                onChange={(e) => setSchedPipeline(e.target.value)}
                title={
                  !schedProject
                    ? 'Select a workspace first'
                    : pipelineOptions.length === 0 && !pipelinesLoading
                      ? `${schedProject} has no saved pipelines — save one from the Editor`
                      : undefined
                }
              >
                <option value="">
                  {!schedProject
                    ? 'Select a workspace first'
                    : pipelinesLoading
                      ? 'Loading pipelines…'
                      : pipelineOptions.length === 0
                        ? 'No saved pipelines'
                        : 'Select pipeline…'}
                </option>
                {pipelineOptions.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            ) : (
              <input
                className={SCHED_FIELD}
                placeholder="pipeline name"
                value={schedPipeline}
                onChange={(e) => setSchedPipeline(e.target.value)}
              />
            )}
          </label>
          <div className="block text-sm text-ink-600">
            <span className={SCHED_LABEL}>Repeat</span>
            <div className="flex gap-1">
              <select
                className={`${SCHED_FIELD} !w-auto shrink-0 !px-2`}
                value={schedCadence}
                onChange={(e) => setSchedCadence(e.target.value as 'interval' | 'cron')}
                aria-label="Repeat by"
              >
                <option value="interval">Minutes</option>
                <option value="cron">Cron</option>
              </select>
              {schedCadence === 'interval' ? (
                <input
                  type="number"
                  min={1}
                  className={`${SCHED_FIELD} min-w-0`}
                  placeholder="e.g. 60"
                  value={schedInterval}
                  onChange={(e) => setSchedInterval(Number(e.target.value) || 60)}
                  aria-label="Interval in minutes"
                />
              ) : (
                <input
                  className={`${SCHED_FIELD} min-w-0 font-mono`}
                  placeholder="0 9 * * 1-5"
                  value={schedCron}
                  spellCheck={false}
                  onChange={(e) => setSchedCron(e.target.value)}
                  aria-label="Cron expression (minute hour day month weekday, UTC)"
                  aria-invalid={!schedCronPreview.ok}
                />
              )}
            </div>
          </div>
          <label className="block text-sm text-ink-600">
            <span className={SCHED_LABEL}>Environment</span>
            <select
              className={SCHED_FIELD}
              value={schedEnv}
              onChange={(e) => setSchedEnv(e.target.value as 'draft' | 'staging' | 'prod')}
              aria-label="Schedule environment"
            >
              <option value="draft">Draft</option>
              <option value="staging">Staging</option>
              <option value="prod">Prod</option>
            </select>
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px]" aria-live="polite">
          {schedCadence === 'cron' ? (
            <>
              <span className={schedCronPreview.ok ? 'text-ink-700' : 'font-medium text-rose-700'}>
                {schedCronPreview.ok ? `Runs ${schedCronPreview.text}` : schedCronPreview.error}
              </span>
              <span className="flex flex-wrap gap-1">
                {CRON_PRESETS.map((p) => (
                  <button
                    key={p.cron}
                    type="button"
                    className={`rounded border px-1.5 py-px text-[11px] ${schedCron.trim() === p.cron ? 'border-ink-700 text-ink-900' : 'border-ink-200 text-ink-500 hover:text-ink-800'}`}
                    title={p.cron}
                    onClick={() => setSchedCron(p.cron)}
                  >
                    {p.label}
                  </button>
                ))}
              </span>
            </>
          ) : (
            <span className="text-ink-500">Runs {intervalText(schedInterval)}</span>
          )}
        </div>
        {useProjectSelect && schedProject && pipelinesApiOk && !pipelinesLoading && pipelineOptions.length === 0 ? (
          <p className="text-xs text-ink-500">
            {schedProject} has no saved pipelines yet — save one from its Editor, then schedule it here.
          </p>
        ) : null}
        <p className="text-[11px] text-ink-400">
          Name, workspace, and pipeline use letters, numbers, underscores, and hyphens.
        </p>
        {!projectsApiOk && (
          <p className="text-xs text-ink-500">Workspaces API unavailable — enter workspace and pipeline as text.</p>
        )}
        {projectsApiOk && schedProject && !pipelinesApiOk && (
          <p className="text-xs text-ink-500">Pipelines API unavailable — enter pipeline name as text.</p>
        )}
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-primary"
            disabled={!canAddSchedule || schedSaving || (schedCadence === 'cron' && !schedCronPreview.ok)}
            onClick={() => {
              if (schedSaving) return
              setSchedSaving(true)
              void apiJson('/system/schedules', {
                method: 'POST',
                body: JSON.stringify({
                  name: schedName.trim(),
                  project: schedProject.trim(),
                  pipeline: schedPipeline.trim(),
                  interval_minutes: schedInterval,
                  ...(schedCadence === 'cron' ? { cron: schedCron.trim() } : {}),
                  env: schedEnv,
                  enabled: true,
                }),
              })
                .then((res) => {
                  const ignoredCron =
                    schedCadence === 'cron' && !(res && typeof res === 'object' && 'cron' in (res as object))
                  pushToast(
                    ignoredCron
                      ? `This API does not support cron yet — created as ${intervalText(schedInterval)}`
                      : 'Schedule created',
                    ignoredCron ? 'info' : 'success',
                  )
                  void refresh()
                })
                .catch((err) =>
                  pushToast(workspaceErrorMessage(err instanceof Error ? err.message : String(err)), 'error'),
                )
                .finally(() => setSchedSaving(false))
            }}
          >
            {schedSaving ? 'Adding…' : 'Add schedule'}
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
          <EmptyState icon={EmptyCalendarClock}
            title="No schedules yet"
            description="Pick a workspace, one of its pipelines and an interval or cron, then Add schedule. Jobs only fire while this API process is running."
          />
        ) : (
          <ul className="space-y-2">
            {schedules.map((s) => {
              const hasError = Boolean(s.last_error)
              const orphaned = Boolean(s.orphaned)
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
                    {orphaned ? (
                      <span
                        className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-900"
                        title={s.orphaned_at ? `Orphaned ${formatRelativeTime(s.orphaned_at)}` : undefined}
                      >
                        Orphaned — workspace deleted
                      </span>
                    ) : (
                      <StatusBadge status={s.enabled ? 'enabled' : 'disabled'} />
                    )}
                  </div>
                  <div className="text-[11px] text-ink-500">
                    <span title={s.cron ? `cron ${s.cron} (UTC)` : undefined}>{scheduleCadence(s).text}</span> · {s.env || 'prod'}
                    {s.enabled && !orphaned && s.next_run_at ? ` · next ${formatRelativeTime(s.next_run_at)}` : ''}
                    {!s.enabled && !orphaned ? ' · paused' : ''}
                    {s.last_run_id ? ` · last run ${String(s.last_run_id).slice(0, 8)}…` : ''}
                  </div>
                  {s.disabled_reason && (!s.enabled || orphaned) ? (
                    <div className="mt-1 text-[12px] text-amber-900">
                      Disabled: {s.disabled_reason}
                    </div>
                  ) : null}
                  {hasError ? (
                    <div className="mt-1 text-[12px] font-medium text-rose-900" title={s.last_error}>
                      Last error: {s.last_error}
                    </div>
                  ) : null}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {!orphaned ? (
                  <>
                  <select
                    className="rounded-lg border border-ink-200 bg-white px-2 py-1 text-xs"
                    value={s.env || 'prod'}
                    aria-label={`Environment for ${s.name || 'schedule'}`}
                    onChange={(e) =>
                      void apiJson(`/system/schedules/${s.id}/env`, {
                        method: 'POST',
                        body: JSON.stringify({ env: e.target.value }),
                      })
                        .then(() => {
                          pushToast(`Schedule environment set to ${e.target.value}`, 'success')
                          void refresh()
                        })
                        .catch((err) =>
                          pushToast(err instanceof Error ? err.message : String(err), 'error'),
                        )
                    }
                  >
                    <option value="draft">Draft</option>
                    <option value="staging">Staging</option>
                    <option value="prod">Prod</option>
                  </select>
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
                  </>
                  ) : null}
                  <button
                    title={orphaned ? 'Workspace deleted — this schedule can only be removed' : undefined}
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
      <section className="ui-card space-y-3">
        {panelErrors.webhooks ? (
          <p className="text-xs text-rose-700">{panelErrors.webhooks}</p>
        ) : null}
        <div>
          <h3 className="text-sm font-semibold">Webhooks</h3>
          <p className="text-xs text-ink-500">
            Send a POST when pipelines finish or fail. Leave events unchecked to receive every
            event. The saved address is shown without its secret path.
          </p>
        </div>
        {webhookConfigured ? (
          <p className="rounded-lg border border-ink-100 bg-ink-50/80 px-3 py-2 text-[12px] text-ink-700">
            Current endpoint:{' '}
            <code className="font-mono text-[11px]">{webhookUrl || 'configured'}</code>
          </p>
        ) : (
          <p className="rounded-lg border border-ink-100 bg-ink-50/80 px-3 py-2 text-[12px] text-ink-600">
            No webhook URL saved yet.
          </p>
        )}
        <label className="block text-sm text-ink-600">
          <span className="mb-1 block text-[12px] font-semibold text-ink-600">
            {webhookConfigured ? 'Replace endpoint URL' : 'Endpoint URL'}
          </span>
          <input
            value={webhookDraft}
            onChange={(e) => setWebhookDraft(e.target.value)}
            placeholder={
              webhookConfigured
                ? 'Leave blank to keep the current endpoint'
                : 'https://hooks.example.com/…'
            }
            className="w-full rounded-lg border border-ink-200 px-3 py-2 text-sm"
          />
        </label>
        <div className="flex flex-wrap gap-4 text-sm">
          {(
            [
              ['pipeline_complete', 'Pipeline complete'],
              ['pipeline_failed', 'Pipeline failed'],
              ['pipeline_cancelled', 'Pipeline cancelled'],
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
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-primary"
            disabled={!webhookDraft.trim() && !webhookConfigured}
            onClick={() => {
              const replacing = webhookDraft.trim().length > 0
              void apiJson('/system/webhooks', {
                method: 'PUT',
                body: JSON.stringify({
                  url: replacing ? webhookDraft.trim() : '',
                  events: webhookEvents,
                  keep_url: !replacing && webhookConfigured,
                  resource_version: webhookVersion,
                }),
              })
                .then(() => {
                  pushToast(replacing || webhookConfigured ? 'Webhook saved' : 'Webhook cleared', 'success')
                  void refresh()
                })
                .catch((err) => pushToast(err instanceof Error ? err.message : String(err), 'error'))
            }}
          >
            Save
          </button>
          <button
            type="button"
            className="btn-secondary"
            disabled={!webhookConfigured}
            onClick={() =>
              void apiJson<{ ok?: boolean; reason?: string }>('/system/webhooks/test', {
                method: 'POST',
                timeoutMs: 20000,
              })
                .then((res) => {
                  if (res?.ok === false) {
                    pushToast(res.reason || 'Webhook test failed', 'error')
                    return
                  }
                  pushToast('Test webhook delivered', 'success')
                })
                .catch((err) => pushToast(err instanceof Error ? err.message : String(err), 'error'))
            }
          >
            Send test
          </button>
          {webhookConfigured ? (
            <button
              type="button"
              className="btn-secondary"
              onClick={() =>
                void apiJson('/system/webhooks', {
                  method: 'PUT',
                  body: JSON.stringify({
                    url: '',
                    events: [],
                    keep_url: false,
                    resource_version: webhookVersion,
                  }),
                })
                  .then(() => {
                    pushToast('Webhook cleared', 'success')
                    void refresh()
                  })
                  .catch((err) =>
                    pushToast(err instanceof Error ? err.message : String(err), 'error'),
                  )
              }
            >
              Clear
            </button>
          ) : null}
        </div>
      </section>
      )}

      {systemTab === 'cleanup' && (
      <section className="ui-card space-y-3">
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
          <span title={STUCK_RUNS_TIP}>Mark stuck (running or queued) runs as failed first</span>
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
                <li>
                  {reconcileAbandoned
                    ? 'Mark stuck running or queued runs as failed first'
                    : 'Leave running and queued runs unchanged'}
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
            {cleanupBusy && (
              <p className="text-xs text-rose-900/90">
                Cleaning up… a large workspace can take a few minutes. Leave this open.
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="btn-danger"
                disabled={cleanupBusy || cleanupConfirmText.trim() !== 'CLEANUP'}
                onClick={() => {
                  if (cleanupInFlight.current) return
                  cleanupInFlight.current = true
                  setCleanupBusy(true)
                  void apiJson('/system/cleanup', {
                    method: 'POST',
                    timeoutMs: 600000,
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
                    .finally(() => {
                      cleanupInFlight.current = false
                      setCleanupBusy(false)
                    })
                }}
              >
                {cleanupBusy ? 'Cleaning up…' : 'Confirm cleanup'}
              </button>
              <button
                type="button"
                className="btn-secondary"
                disabled={cleanupBusy}
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
    </WorkbenchPage>
  )
}
