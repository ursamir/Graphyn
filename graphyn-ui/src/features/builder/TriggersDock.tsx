import React from 'react'
import { Clock, Copy, ExternalLink, RefreshCw, X } from 'lucide-react'
import { apiJson } from '../../api/client'
import { formatRelativeTime } from '../../lib/format'
import { useAppStore } from '../../store/appStore'
import { goView } from '../../routes/nav'

type ScheduleRow = {
  id: string
  name: string
  project: string
  pipeline: string
  interval_minutes: number
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
}

export default function TriggersDock({
  open,
  onClose,
  project,
  pipelines,
  defaultPipeline = '',
}: TriggersDockProps) {
  const pushToast = useAppStore((s) => s.pushToast)

  const [schedules, setSchedules] = React.useState<ScheduleRow[]>([])
  const [webhookUrl, setWebhookUrl] = React.useState('')
  const [webhookEvents, setWebhookEvents] = React.useState<string[]>([])
  const [loading, setLoading] = React.useState(false)
  const [name, setName] = React.useState('')
  const [pipeline, setPipeline] = React.useState(defaultPipeline)
  const [intervalMinutes, setIntervalMinutes] = React.useState(60)
  const [enabled, setEnabled] = React.useState(true)
  const [busy, setBusy] = React.useState(false)

  React.useEffect(() => {
    if (defaultPipeline) setPipeline((prev) => prev || defaultPipeline)
  }, [defaultPipeline])

  const refresh = React.useCallback(async () => {
    if (!project) return
    setLoading(true)
    try {
      const [schedRes, hookRes] = await Promise.all([
        apiJson<{ schedules?: ScheduleRow[] }>('/system/schedules').catch(() => ({ schedules: [] })),
        apiJson<{ url?: string; events?: string[] }>('/system/webhooks').catch(() => ({
          url: '',
          events: [],
        })),
      ])
      const all = Array.isArray(schedRes.schedules) ? schedRes.schedules : []
      setSchedules(all.filter((s) => !s.project || s.project === project))
      setWebhookUrl(String(hookRes.url ?? ''))
      setWebhookEvents(Array.isArray(hookRes.events) ? hookRes.events.map(String) : [])
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setLoading(false)
    }
  }, [project, pushToast])

  React.useEffect(() => {
    if (open && project) void refresh()
  }, [open, project, refresh])

  const createSchedule = async () => {
    const n = name.trim()
    const pipe = pipeline.trim()
    if (!n || !pipe) {
      pushToast('Name and pipeline are required', 'error')
      return
    }
    setBusy(true)
    try {
      await apiJson('/system/schedules', {
        method: 'POST',
        body: JSON.stringify({
          name: n,
          project,
          pipeline: pipe,
          interval_minutes: Math.max(1, intervalMinutes || 60),
          enabled,
        }),
      })
      pushToast('Schedule created', 'success')
      setName('')
      await refresh()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setBusy(false)
    }
  }

  const copyWebhook = async () => {
    if (!webhookUrl) {
      pushToast('No webhook URL configured — set one in Ops', 'error')
      return
    }
    try {
      await navigator.clipboard.writeText(webhookUrl)
      pushToast('Webhook URL copied', 'success')
    } catch {
      pushToast('Could not copy — select the URL manually', 'error')
    }
  }

  const openOps = () => {
    goView('system')
    onClose()
  }

  if (!open) return null

  return (
    <div className="pointer-events-auto absolute bottom-3 left-3 z-20 flex max-h-[min(70%,28rem)] w-[min(100%-1.5rem,22rem)] flex-col overflow-hidden rounded-2xl border border-ink-200 bg-white/95 shadow-soft backdrop-blur">
      <div className="flex items-center gap-2 border-b border-ink-100 px-3 py-2">
        <Clock className="h-3.5 w-3.5 text-ink-500" />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-ink-950">Triggers</div>
          <div className="truncate text-[10px] text-ink-400">Schedules for {project}</div>
        </div>
        <button type="button" className="btn-icon h-7 w-7" title="Refresh" onClick={() => void refresh()}>
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
        </button>
        <button type="button" className="btn-icon h-7 w-7" aria-label="Close triggers" onClick={onClose}>
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto px-3 py-2">
        <section className="space-y-2">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">Schedules</div>
          {loading ? (
            <p className="text-[11px] leading-snug text-ink-400">Loading…</p>
          ) : schedules.length === 0 ? (
            <p className="text-[11px] leading-snug text-ink-500">
              No schedules yet. Create an interval schedule for a project pipeline.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {schedules.map((s) => (
                <li
                  key={s.id}
                  className="rounded-lg border border-ink-100 bg-ink-50/60 px-2.5 py-1.5 text-[12px] text-ink-800"
                >
                  <div className="font-medium text-ink-900">
                    {s.name}{' '}
                    <span className="font-mono text-[10px] text-ink-500">
                      {s.pipeline}
                    </span>
                  </div>
                  <div className="text-[10px] text-ink-500">
                    every {s.interval_minutes}m · {s.enabled ? 'enabled' : 'disabled'}
                    {s.enabled && s.next_run_at ? ` · next ${formatRelativeTime(s.next_run_at)}` : ''}
                    {s.last_error ? ` · err: ${s.last_error}` : ''}
                  </div>
                </li>
              ))}
            </ul>
          )}

          <div className="space-y-1.5 rounded-lg border border-ink-100 p-2">
            <input
              className="field-control mt-0 text-xs"
              placeholder="Schedule name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            {pipelines.length > 0 ? (
              <select
                className="field-control mt-0 text-xs"
                value={pipeline}
                onChange={(e) => setPipeline(e.target.value)}
                aria-label="Pipeline"
              >
                {pipelines.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            ) : (
              <input
                className="field-control mt-0 text-xs"
                placeholder="Pipeline name"
                value={pipeline}
                onChange={(e) => setPipeline(e.target.value)}
              />
            )}
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
            <p className="text-[10px] leading-snug text-ink-400">
              Cron coming when API supports it.
            </p>
            <label className="inline-flex items-center gap-2 text-[11px] text-ink-700">
              <input
                type="checkbox"
                className="h-3.5 w-3.5 rounded border-ink-300"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
              />
              Enabled
            </label>
            <button
              type="button"
              className="btn-primary w-full"
              disabled={busy}
              onClick={() => void createSchedule()}
            >
              Add schedule
            </button>
          </div>
        </section>

        <section className="space-y-1.5 border-t border-ink-100 pt-2">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">Webhook</div>
          <p className="text-[10px] leading-snug text-ink-500">
            Per-workflow wiring is a global URL + event filter for now. Filter events in Ops.
          </p>
          <div className="flex gap-1.5">
            <input
              readOnly
              className="field-control mt-0 flex-1 font-mono text-[10px]"
              value={webhookUrl || '(not configured)'}
              title={webhookUrl || undefined}
            />
            <button
              type="button"
              className="btn-secondary shrink-0"
              title="Copy webhook URL"
              onClick={() => void copyWebhook()}
            >
              <Copy className="h-3.5 w-3.5" />
            </button>
          </div>
          {webhookEvents.length > 0 ? (
            <div className="text-[10px] text-ink-500">Events: {webhookEvents.join(', ')}</div>
          ) : null}
        </section>
      </div>

      <div className="border-t border-ink-100 px-3 py-2">
        <button type="button" className="btn-quiet w-full justify-start text-[11px]" onClick={openOps}>
          <ExternalLink className="h-3.5 w-3.5" /> Advanced in Ops
        </button>
      </div>
    </div>
  )
}
