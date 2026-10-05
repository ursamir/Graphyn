/**
 * Editor → Triggers dock (bottom-left of the canvas). Per saved pipeline:
 *
 *  - **Webhook** — `GET/PUT/DELETE /projects/{ws}/pipelines/{p}/hook`:
 *    enable / env, full delivery URL, Rotate secret (`…/hook/rotate`, the
 *    `whsec_…` secret shown ONCE in a copy dialog), header allowlist, a
 *    copyable curl + openssl signing example and the last deliveries (runs with
 *    trigger `webhook` of this hook). Hidden with a note on APIs without the
 *    hook routes (404 from the route itself).
 *  - **Schedules** — `GET/POST /system/schedules` with interval or 5-field UTC
 *    cron and a plain-English preview (`lib/cron.ts`).
 */
import React from 'react'
import clsx from 'clsx'
import { AlertTriangle, CheckCircle2, Clock, Copy, ExternalLink, KeyRound, RefreshCw, Webhook, X } from 'lucide-react'
import { createPortal } from 'react-dom'
import { API_BASE_URL, ApiError, apiJson } from '../../api/client'
import { apiErrorCode } from '../../api/errorCode'
import { formatRelativeTime } from '../../lib/format'
import { describeCron, scheduleCadence } from '../../lib/cron'
import { CronField } from '../../components/CronField'
import { useAppStore } from '../../store/appStore'
import { goView } from '../../routes/nav'
import { navigatePath } from '../../routes/parsePath'
import { paths } from '../../routes/paths'
import { ConfirmButton, StatusBadge } from '../../components/ui'
import {
  HOOK_ENVS,
  apiOrigin,
  bearerExample,
  hookDeliveries,
  hookFullUrl,
  parseHeaderAllowlist,
  parseHookView,
  signingExample,
  type HookDelivery,
  type HookView,
} from './webhookHook'

type ScheduleRow = {
  id: string
  name: string
  project: string
  pipeline: string
  interval_minutes: number
  cron?: string | null
  enabled: boolean
  next_run_at?: string | null
  last_error?: string | null
}

type TriggersDockProps = {
  open: boolean
  onClose: () => void
  project: string
  pipelines: string[]
  defaultPipeline?: string
  /** Canvas pipeline name + whether it has a webhook_trigger step (hint only). */
  canvasPipeline?: string
  canvasHasWebhookTrigger?: boolean
}

/** 404 from FastAPI's router (route unknown → older API), not a domain 404. */
function isRouteMissing(err: unknown): boolean {
  if (!(err instanceof ApiError) || err.status !== 404) return false
  const body = err.body as { detail?: unknown } | undefined
  return !apiErrorCode(err) && (body?.detail === 'Not Found' || body == null)
}

function CopyButton({ text, label, className }: { text: string; label: string; className?: string }) {
  const [done, setDone] = React.useState(false)
  return (
    <button
      type="button"
      className={clsx('btn-quiet !px-1.5 !py-0.5 text-[11px]', className)}
      title={label}
      aria-label={label}
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => {
          setDone(true)
          window.setTimeout(() => setDone(false), 1200)
        })
      }}
    >
      {done ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  )
}

/** One-time secret dialog after Rotate: copy, warning, explicit dismissal. */
function SecretOnceDialog({ secret, onClose }: { secret: string; onClose: () => void }) {
  const [copied, setCopied] = React.useState(false)
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/30 p-4">
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="hook-secret-title"
        className="w-full max-w-md overflow-hidden rounded-xl border border-ink-200 bg-white shadow-xl"
      >
        <div className="border-b border-ink-100 px-4 py-2.5">
          <h2 id="hook-secret-title" className="text-[13px] font-semibold text-ink-900">
            Webhook signing secret
          </h2>
        </div>
        <div className="space-y-2 px-4 py-3">
          <p className="flex items-start gap-1.5 rounded-lg bg-amber-50 px-2.5 py-2 text-[12px] text-amber-950">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            Copy it now — it is shown only once and cannot be retrieved later. The previous secret stopped working.
          </p>
          <div className="flex items-center gap-1.5">
            <code className="min-w-0 flex-1 break-all rounded-md bg-ink-50 px-2 py-1.5 font-mono text-[11.5px] text-ink-900">
              {secret}
            </code>
            <button
              type="button"
              className="btn-secondary shrink-0"
              onClick={() => {
                void navigator.clipboard?.writeText(secret).then(() => setCopied(true))
              }}
            >
              {copied ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
          <p className="text-[11px] text-ink-500">Store it in the sender’s secret manager, then use it to sign each delivery.</p>
        </div>
        <div className="flex justify-end gap-2 border-t border-ink-100 px-4 py-2.5">
          <button type="button" className="btn-primary" onClick={onClose}>
            {copied ? 'Done' : 'I stored it'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

export default function TriggersDock({
  open,
  onClose,
  project,
  pipelines,
  defaultPipeline = '',
  canvasPipeline = '',
  canvasHasWebhookTrigger,
}: TriggersDockProps) {
  const pushToast = useAppStore((s) => s.pushToast)
  const openRun = useAppStore((s) => s.openRun)

  const [pipeline, setPipelineState] = React.useState(defaultPipeline)
  // Follow the Editor's open pipeline (the dock mounts before the canvas has
  // loaded, when the name is still the placeholder "pipeline") — unless the
  // user picked another pipeline in the dock; re-sync whenever it opens.
  const pickedRef = React.useRef(false)
  const setPipeline = React.useCallback((name: string) => {
    pickedRef.current = true
    setPipelineState(name)
  }, [])
  React.useEffect(() => {
    if (open) pickedRef.current = false
  }, [open])
  React.useEffect(() => {
    if (defaultPipeline && !pickedRef.current) setPipelineState(defaultPipeline)
  }, [defaultPipeline, open])

  // ── Webhook ────────────────────────────────────────────────────────────
  const [hook, setHook] = React.useState<HookView | null>(null)
  const [hookState, setHookState] = React.useState<'idle' | 'loading' | 'ready' | 'unsupported' | 'unsaved' | 'error'>('idle')
  const [hookError, setHookError] = React.useState('')
  const [hookBusy, setHookBusy] = React.useState(false)
  const [newEnv, setNewEnv] = React.useState<string>('draft')
  const [allowDraft, setAllowDraft] = React.useState('')
  const [secret, setSecret] = React.useState<string | null>(null)
  const [deliveries, setDeliveries] = React.useState<HookDelivery[] | null>(null)
  const [showExample, setShowExample] = React.useState(false)

  const hookPath = pipeline
    ? `/projects/${encodeURIComponent(project)}/pipelines/${encodeURIComponent(pipeline)}/hook`
    : ''

  const loadDeliveries = React.useCallback(
    async (hookId: string) => {
      if (!hookId) {
        setDeliveries([])
        return
      }
      try {
        const runs = await apiJson<unknown>('/runs', { query: { project, limit: 100 } })
        setDeliveries(hookDeliveries(runs, hookId))
      } catch {
        setDeliveries(null)
      }
    },
    [project],
  )

  const loadHook = React.useCallback(async () => {
    if (!hookPath) {
      setHook(null)
      setHookState('idle')
      return
    }
    setHookState('loading')
    setHookError('')
    try {
      const view = parseHookView(await apiJson<unknown>(hookPath))
      setHook(view)
      setAllowDraft(view?.headerAllowlist.join(', ') ?? '')
      setHookState('ready')
      if (view?.exists) void loadDeliveries(view.hookId)
      else setDeliveries(null)
    } catch (err) {
      setHook(null)
      if (isRouteMissing(err)) setHookState('unsupported')
      else if (err instanceof ApiError && err.status === 404) setHookState('unsaved')
      else {
        setHookState('error')
        setHookError(err instanceof Error ? err.message : String(err))
      }
    }
  }, [hookPath, loadDeliveries])

  const putHook = async (patch: Record<string, unknown>, okMsg?: string) => {
    if (!hookPath) return
    setHookBusy(true)
    try {
      const view = parseHookView(await apiJson<unknown>(hookPath, { method: 'PUT', body: JSON.stringify(patch) }))
      setHook(view)
      setAllowDraft(view?.headerAllowlist.join(', ') ?? '')
      if (okMsg) pushToast(okMsg, 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setHookBusy(false)
    }
  }

  const rotate = async () => {
    if (!hookPath) return
    setHookBusy(true)
    try {
      const res = await apiJson<Record<string, unknown>>(`${hookPath}/rotate`, { method: 'POST' })
      setHook(parseHookView(res))
      const s = typeof res?.secret === 'string' ? res.secret : ''
      if (s) setSecret(s)
      else pushToast('Secret rotated', 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setHookBusy(false)
    }
  }

  const deleteHook = async () => {
    if (!hookPath) return
    setHookBusy(true)
    try {
      await apiJson(hookPath, { method: 'DELETE' })
      pushToast('Webhook removed — its secret no longer works', 'success')
      await loadHook()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setHookBusy(false)
    }
  }

  // ── Schedules ──────────────────────────────────────────────────────────
  const [schedules, setSchedules] = React.useState<ScheduleRow[]>([])
  const [loading, setLoading] = React.useState(false)
  const [name, setName] = React.useState('')
  const [cadence, setCadence] = React.useState<'interval' | 'cron'>('interval')
  const [intervalMinutes, setIntervalMinutes] = React.useState(60)
  const [cron, setCron] = React.useState('0 9 * * 1-5')
  const [enabled, setEnabled] = React.useState(true)
  const [busy, setBusy] = React.useState(false)
  const cronPreview = describeCron(cron)

  const refresh = React.useCallback(async () => {
    if (!project) return
    setLoading(true)
    try {
      const schedRes = await apiJson<{ schedules?: ScheduleRow[] }>('/system/schedules').catch(() => ({ schedules: [] }))
      const all = Array.isArray(schedRes.schedules) ? schedRes.schedules : []
      setSchedules(all.filter((s) => !s.project || s.project === project))
    } finally {
      setLoading(false)
    }
  }, [project])

  React.useEffect(() => {
    if (open && project) void refresh()
  }, [open, project, refresh])
  React.useEffect(() => {
    if (open) void loadHook()
  }, [open, loadHook])

  const createSchedule = async () => {
    const n = name.trim()
    const pipe = pipeline.trim()
    if (!n || !pipe) {
      pushToast('Name and pipeline are required', 'error')
      return
    }
    if (cadence === 'cron' && !cronPreview.ok) {
      pushToast(cronPreview.error, 'error')
      return
    }
    setBusy(true)
    try {
      const res = await apiJson<Record<string, unknown> | undefined>('/system/schedules', {
        method: 'POST',
        body: JSON.stringify({
          name: n,
          project,
          pipeline: pipe,
          interval_minutes: Math.max(1, intervalMinutes || 60),
          ...(cadence === 'cron' ? { cron: cron.trim() } : {}),
          enabled,
        }),
      })
      if (cadence === 'cron' && !(res && 'cron' in res)) {
        pushToast('This API does not support cron yet — the schedule uses the interval', 'info')
      } else pushToast('Schedule created', 'success')
      setName('')
      await refresh()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setBusy(false)
    }
  }

  if (!open) return null

  const origin = apiOrigin(API_BASE_URL, typeof window !== 'undefined' ? window.location.origin : '')
  const fullUrl = hook?.urlPath ? hookFullUrl(origin, hook.urlPath) : ''
  const pipeSchedules = schedules.filter((s) => !pipeline || s.pipeline === pipeline)
  const showTriggerHint = Boolean(
    hook?.exists && canvasHasWebhookTrigger === false && canvasPipeline && canvasPipeline === pipeline,
  )

  return (
    <div className="pointer-events-auto absolute bottom-3 left-3 z-20 flex max-h-[min(85%,38rem)] w-[min(100%-1.5rem,24rem)] flex-col overflow-hidden rounded-2xl border border-ink-200 bg-white/95 shadow-soft backdrop-blur">
      <div className="flex items-center gap-2 border-b border-ink-100 px-3 py-2">
        <Clock className="h-3.5 w-3.5 text-ink-500" />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-ink-950">Triggers</div>
          <div className="truncate text-[10px] text-ink-400">What starts {pipeline || 'a pipeline'} in {project}</div>
        </div>
        <button
          type="button"
          className="btn-icon h-7 w-7"
          title="Refresh"
          onClick={() => {
            void refresh()
            void loadHook()
          }}
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading || hookState === 'loading' ? 'animate-spin' : ''}`} />
        </button>
        <button type="button" className="btn-icon h-7 w-7" aria-label="Close triggers" onClick={onClose}>
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto px-3 py-2">
        <label className="block text-[11px] text-ink-600">
          <span className="font-medium">Pipeline</span>
          {pipelines.length > 0 ? (
            <select className="field-control mt-1 text-xs" value={pipeline} onChange={(e) => setPipeline(e.target.value)}>
              {!pipeline ? <option value="">Select a saved pipeline…</option> : null}
              {pipeline && !pipelines.includes(pipeline) ? <option value={pipeline}>{pipeline} (not saved)</option> : null}
              {pipelines.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          ) : (
            <input
              className="field-control mt-1 text-xs"
              placeholder="Saved pipeline name"
              value={pipeline}
              onChange={(e) => setPipeline(e.target.value)}
              onBlur={() => void loadHook()}
            />
          )}
        </label>

        {/* ── Webhook ── */}
        <section className="space-y-1.5" aria-label="Webhook">
          <div className="flex items-center gap-1.5">
            <Webhook className="h-3.5 w-3.5 text-ink-500" aria-hidden />
            <span className="ide-section-title">Webhook</span>
            {hook?.exists ? (
              <span className={clsx('ml-auto text-[11px]', hook.enabled ? 'text-ink-500' : 'font-medium text-amber-800')}>
                {hook.enabled ? 'Enabled' : 'Disabled'}
              </span>
            ) : null}
          </div>
          {!pipeline ? (
            <p className="text-[11px] text-ink-500">Save the pipeline, then give it a webhook URL here.</p>
          ) : hookState === 'loading' && !hook ? (
            <p className="text-[11px] text-ink-400">Loading…</p>
          ) : hookState === 'unsupported' ? (
            <p className="text-[11px] text-ink-500">This API version has no pipeline webhooks — update the API to use them.</p>
          ) : hookState === 'unsaved' ? (
            <p className="text-[11px] text-ink-500">“{pipeline}” is not saved in {project} yet — save it first.</p>
          ) : hookState === 'error' ? (
            <p className="text-[11px] text-rose-700">{hookError}</p>
          ) : hook && !hook.exists ? (
            <div className="space-y-1.5">
              <p className="text-[11px] leading-snug text-ink-500">
                Let another system start this pipeline with an HTTPS POST. The pipeline needs a{' '}
                <span className="font-mono">webhook_trigger</span> step; the request body becomes its output.
              </p>
              <div className="flex items-center gap-1.5">
                <select
                  className="field-control mt-0 w-auto text-xs"
                  value={newEnv}
                  aria-label="Environment the webhook runs"
                  onChange={(e) => setNewEnv(e.target.value)}
                >
                  {HOOK_ENVS.map((e) => (
                    <option key={e} value={e}>
                      {e}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="btn-primary flex-1"
                  disabled={hookBusy}
                  onClick={() => void putHook({ enabled: true, env: newEnv, allowed_envs: [newEnv] }, 'Webhook created — rotate a secret to sign deliveries')}
                >
                  Create webhook
                </button>
              </div>
            </div>
          ) : hook ? (
            <div className="space-y-2">
              {showTriggerHint ? (
                <p className="flex items-start gap-1 rounded-md bg-amber-50 px-2 py-1 text-[11px] text-amber-950">
                  <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                  Add a webhook_trigger step — deliveries are refused without one.
                </p>
              ) : null}
              <div className="flex items-center gap-1">
                <input readOnly className="field-control mt-0 flex-1 font-mono text-[10px]" value={fullUrl} title={fullUrl} aria-label="Webhook URL" />
                <CopyButton text={fullUrl} label="Copy webhook URL" />
              </div>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11px] text-ink-700">
                <label className="inline-flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={hook.enabled}
                    disabled={hookBusy}
                    onChange={(e) => void putHook({ enabled: e.target.checked }, e.target.checked ? 'Webhook enabled' : 'Webhook disabled')}
                  />
                  Enabled
                </label>
                <label className="inline-flex items-center gap-1">
                  Runs
                  <select
                    className="field-control mt-0 w-auto py-0.5 text-[11px]"
                    value={hook.env}
                    disabled={hookBusy}
                    onChange={(e) => {
                      const env = e.target.value
                      const allowed = hook.allowedEnvs.includes(env) ? hook.allowedEnvs : [...hook.allowedEnvs, env]
                      void putHook({ env, allowed_envs: allowed }, `Webhook runs ${env}`)
                    }}
                  >
                    {HOOK_ENVS.map((e) => (
                      <option key={e} value={e}>
                        {e}
                      </option>
                    ))}
                  </select>
                </label>
                <span className="text-ink-400" title="Hook id (the run actor is webhook:<id>)">
                  id <span className="font-mono">{hook.hookId.slice(0, 8)}</span>
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                <KeyRound className="h-3.5 w-3.5 text-ink-400" aria-hidden />
                {hook.hasSecret ? (
                  <span className="text-ink-600" title={hook.rotatedAt || undefined}>
                    Signing secret set{hook.rotatedAt ? ` · rotated ${formatRelativeTime(hook.rotatedAt)}` : ''}
                  </span>
                ) : (
                  <span className="font-medium text-amber-800">No signing secret — bearer tokens only</span>
                )}
                <button type="button" className="btn-secondary ml-auto !py-0.5 text-[11px]" disabled={hookBusy} onClick={() => void rotate()}>
                  {hook.hasSecret ? 'Rotate secret' : 'Create secret'}
                </button>
              </div>
              <label className="block text-[11px] text-ink-600">
                <span className="font-medium">Forward headers</span>
                <input
                  className="field-control mt-1 font-mono text-[11px]"
                  placeholder="x-request-id, x-tenant"
                  value={allowDraft}
                  onChange={(e) => setAllowDraft(e.target.value)}
                  onBlur={() => {
                    const next = parseHeaderAllowlist(allowDraft)
                    if (next.join(',') !== hook.headerAllowlist.join(',')) void putHook({ header_allowlist: next }, 'Header allowlist saved')
                    else setAllowDraft(next.join(', '))
                  }}
                />
                <span className="mt-0.5 block text-[10px] text-ink-400">Lower-case header names passed to the trigger’s headers output. Auth headers never are.</span>
              </label>
              <div>
                <button
                  type="button"
                  className="text-[11px] font-medium text-accent-800 hover:underline"
                  aria-expanded={showExample}
                  onClick={() => setShowExample((v) => !v)}
                >
                  {showExample ? 'Hide signing example' : 'Signing example (curl + openssl)'}
                </button>
                {showExample ? (
                  <div className="mt-1 space-y-1">
                    <div className="relative">
                      <pre className="max-h-48 overflow-auto rounded-md bg-ink-950 px-2 py-1.5 pr-8 font-mono text-[10px] leading-[1.45] text-ink-100">
                        {signingExample({ url: fullUrl, signatureHeader: hook.signatureHeader, timestampHeader: hook.timestampHeader })}
                      </pre>
                      <CopyButton
                        className="absolute right-1 top-1 !text-ink-300 hover:!text-white"
                        text={signingExample({ url: fullUrl, signatureHeader: hook.signatureHeader, timestampHeader: hook.timestampHeader })}
                        label="Copy signing example"
                      />
                    </div>
                    <p className="text-[10px] leading-snug text-ink-500">
                      Signature = <span className="font-mono">sha256=hex(HMAC_SHA256(secret, "&lt;timestamp&gt;." + body))</span>; the
                      timestamp must be within a few minutes. Or send <span className="font-mono">Authorization: Bearer</span> with an API token:
                    </p>
                    <div className="relative">
                      <pre className="max-h-28 overflow-auto rounded-md bg-ink-950 px-2 py-1.5 pr-8 font-mono text-[10px] leading-[1.45] text-ink-100">
                        {bearerExample(fullUrl)}
                      </pre>
                      <CopyButton className="absolute right-1 top-1 !text-ink-300 hover:!text-white" text={bearerExample(fullUrl)} label="Copy bearer example" />
                    </div>
                  </div>
                ) : null}
              </div>
              <div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] font-medium text-ink-600">Last deliveries</span>
                  <button
                    type="button"
                    className="text-[11px] text-accent-800 hover:underline"
                    onClick={() => {
                      navigatePath(`${paths.runs(project)}?q=${encodeURIComponent('trigger:webhook')}`)
                      onClose()
                    }}
                  >
                    All webhook runs
                  </button>
                </div>
                {deliveries == null ? (
                  <p className="text-[10.5px] text-ink-400">Not available.</p>
                ) : deliveries.length === 0 ? (
                  <p className="text-[10.5px] text-ink-400">None yet.</p>
                ) : (
                  <ul className="mt-0.5 divide-y divide-ink-50">
                    {deliveries.map((d) => (
                      <li key={d.runId}>
                        <button
                          type="button"
                          className="flex w-full min-w-0 items-center gap-1.5 py-1 text-left text-[11px] hover:bg-ink-50"
                          title={`Open run ${d.runId}`}
                          onClick={() => openRun(d.runId, { project })}
                        >
                          <StatusBadge kind="run" status={d.status} />
                          <span className="min-w-0 flex-1 truncate text-ink-600" title={d.receivedAt}>
                            {d.receivedAt ? formatRelativeTime(d.receivedAt) : '—'}
                            {d.auth ? ` · ${d.auth}` : ''}
                            {d.bytes != null ? ` · ${d.bytes.toLocaleString()} B` : ''}
                          </span>
                          <span className="font-mono text-[10px] text-ink-400">{d.runId.slice(0, 8)}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="flex justify-end">
                <ConfirmButton label="Remove webhook" confirmLabel="Remove — revokes secret" danger disabled={hookBusy} onConfirm={() => void deleteHook()} />
              </div>
            </div>
          ) : null}
        </section>

        {/* ── Schedules ── */}
        <section className="space-y-2 border-t border-ink-100 pt-2" aria-label="Schedules">
          <div className="flex items-center gap-1.5">
            <Clock className="h-3.5 w-3.5 text-ink-500" aria-hidden />
            <span className="ide-section-title">Schedules</span>
          </div>
          {loading ? (
            <p className="text-[11px] leading-snug text-ink-400">Loading…</p>
          ) : pipeSchedules.length === 0 ? (
            <p className="text-[11px] leading-snug text-ink-500">No schedules for {pipeline || 'this workspace'} yet.</p>
          ) : (
            <ul className="space-y-1.5">
              {pipeSchedules.map((s) => {
                const c = scheduleCadence(s)
                return (
                  <li key={s.id} className="rounded-lg border border-ink-100 bg-ink-50/60 px-2.5 py-1.5 text-[12px] text-ink-800">
                    <div className="font-medium text-ink-900">
                      {s.name} <span className="font-mono text-[10px] text-ink-500">{s.pipeline}</span>
                    </div>
                    <div className="text-[10px] text-ink-500">
                      <span title={c.raw || undefined}>{c.text}</span> · {s.enabled ? 'enabled' : 'paused'}
                      {s.enabled && s.next_run_at ? ` · next ${formatRelativeTime(s.next_run_at)}` : ''}
                    </div>
                    {s.last_error ? <div className="text-[10px] font-medium text-rose-700">Last error: {s.last_error}</div> : null}
                  </li>
                )
              })}
            </ul>
          )}

          <div className="space-y-1.5 rounded-lg border border-ink-100 p-2">
            <input className="field-control mt-0 text-xs" placeholder="Schedule name" value={name} onChange={(e) => setName(e.target.value)} />
            <div className="flex gap-1 text-[11px]" role="radiogroup" aria-label="Schedule type">
              {(['interval', 'cron'] as const).map((k) => (
                <button
                  key={k}
                  type="button"
                  role="radio"
                  aria-checked={cadence === k}
                  className={clsx(
                    'flex-1 rounded-md border px-2 py-0.5',
                    cadence === k ? 'border-ink-800 bg-ink-900 text-white' : 'border-ink-200 text-ink-600 hover:bg-ink-50',
                  )}
                  onClick={() => setCadence(k)}
                >
                  {k === 'interval' ? 'Every N minutes' : 'Cron (UTC)'}
                </button>
              ))}
            </div>
            {cadence === 'interval' ? (
              <label className="block text-[11px] text-ink-600">
                <span className="font-medium">Interval (minutes)</span>
                <input
                  type="number"
                  min={1}
                  className="field-control mt-1 font-mono text-xs"
                  value={intervalMinutes}
                  onChange={(e) => setIntervalMinutes(Number(e.target.value) || 60)}
                />
              </label>
            ) : (
              <CronField value={cron} onChange={setCron} compact />
            )}
            <label className="inline-flex items-center gap-2 text-[11px] text-ink-700">
              <input type="checkbox" className="h-3.5 w-3.5 rounded border-ink-300" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
              Enabled
            </label>
            <button
              type="button"
              className="btn-primary w-full"
              disabled={busy || !pipeline || (cadence === 'cron' && !cronPreview.ok)}
              onClick={() => void createSchedule()}
            >
              Add schedule
            </button>
          </div>
        </section>
      </div>

      <div className="border-t border-ink-100 px-3 py-2">
        <button
          type="button"
          className="btn-quiet w-full justify-start text-[11px]"
          onClick={() => {
            goView('system')
            onClose()
          }}
        >
          <ExternalLink className="h-3.5 w-3.5" /> All schedules and run notifications in Ops
        </button>
      </div>
      {secret ? <SecretOnceDialog secret={secret} onClose={() => setSecret(null)} /> : null}
    </div>
  )
}
