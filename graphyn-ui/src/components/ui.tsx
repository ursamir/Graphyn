import React from 'react'
import clsx from 'clsx'
import { AlertTriangle, CheckCircle2, ChevronRight, Copy, Info, X } from 'lucide-react'
import { prettyScalar, startCase } from '../lib/format'

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-ink-200 bg-white/60 px-6 py-16 text-center">
      <div className="text-lg font-semibold text-ink-800">{title}</div>
      {description && <p className="mt-2 max-w-md text-sm text-ink-500">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function LoadingBlock({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 px-4 py-8 text-sm text-ink-500">
      <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-accent-500 border-t-transparent" />
      {label}
    </div>
  )
}

export function ErrorBanner({ message, onRetry, title }: { message: string; onRetry?: () => void; title?: string }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <span title={title}>{message}</span>
      </div>
      {onRetry && (
        <button type="button" className="btn-secondary" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  )
}

export function StatusBadge({
  status,
}: {
  status: string
}) {
  const s = status.toLowerCase()
  const tone =
    s.includes('complete') || s === 'ok' || s === 'ready' || s === 'enabled' || s === 'success'
      ? 'bg-emerald-100 text-emerald-800'
      : s.includes('fail') || s.includes('error') || s === 'cancelled'
        ? 'bg-rose-100 text-rose-800'
        : s.includes('run') || s.includes('install') || s === 'paused'
          ? 'bg-amber-100 text-amber-900'
          : 'bg-ink-100 text-ink-700'
  return (
    <span className={clsx('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide', tone)}>
      <span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" />
      {status}
    </span>
  )
}

export function ConfirmButton({
  label,
  confirmLabel = 'Confirm',
  onConfirm,
  danger,
  disabled,
}: {
  label: string
  confirmLabel?: string
  onConfirm: () => void
  danger?: boolean
  disabled?: boolean
}) {
  const [armed, setArmed] = React.useState(false)
  React.useEffect(() => {
    if (!armed) return
    const t = setTimeout(() => setArmed(false), 4000)
    return () => clearTimeout(t)
  }, [armed])
  return (
    <button
      type="button"
      disabled={disabled}
      className={danger ? 'btn-danger' : 'btn-secondary'}
      onClick={() => {
        if (!armed) {
          setArmed(true)
          return
        }
        setArmed(false)
        onConfirm()
      }}
    >
      {armed ? confirmLabel : label}
    </button>
  )
}

export function ToastHost({
  toasts,
  onDismiss,
}: {
  toasts: Array<{ id: string; message: string; tone: 'info' | 'success' | 'error' }>
  onDismiss: (id: string) => void
}) {
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-full max-w-sm flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={clsx(
            'pointer-events-auto flex items-start gap-2 rounded-xl border px-3 py-2 shadow-lg backdrop-blur',
            t.tone === 'error' && 'border-rose-200 bg-rose-50 text-rose-900',
            t.tone === 'success' && 'border-emerald-200 bg-emerald-50 text-emerald-900',
            t.tone === 'info' && 'border-ink-200 bg-white text-ink-900',
          )}
        >
          {t.tone === 'error' ? (
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          ) : t.tone === 'success' ? (
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
          ) : (
            <Info className="mt-0.5 h-4 w-4 shrink-0" />
          )}
          <div className="min-w-0 flex-1 break-words text-sm">{t.message}</div>
          <button type="button" className="text-ink-400 hover:text-ink-700" onClick={() => onDismiss(t.id)}>
            <X className="h-4 w-4" />
          </button>
        </div>
      ))}
    </div>
  )
}

export class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null }
  static getDerivedStateFromError(error: Error) {
    return { error }
  }
  render() {
    if (this.state.error) {
      return (
        <div className="m-6 rounded-2xl border border-rose-200 bg-rose-50 p-6">
          <h2 className="text-lg font-semibold text-rose-900">Something went wrong</h2>
          <p className="mt-2 text-sm text-rose-800">{this.state.error.message}</p>
          <button type="button" className="btn-secondary mt-4" onClick={() => this.setState({ error: null })}>
            Try again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}


export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string
  description?: string
  actions?: React.ReactNode
}) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h2 className="text-xl font-semibold text-ink-950">{title}</h2>
        {description && <p className="mt-0.5 max-w-2xl text-sm text-ink-500">{description}</p>}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  )
}

export function CollapsibleJson({
  value,
  label = 'JSON',
}: {
  value: unknown
  label?: string
}) {
  return (
    <details className="rounded-lg border border-ink-100 bg-ink-50">
      <summary className="cursor-pointer select-none px-2.5 py-1.5 text-xs font-medium text-ink-500">
        {label}
      </summary>
      <pre className="max-h-64 overflow-auto border-t border-ink-100 p-2.5 font-mono text-[11px] text-ink-800">
        {value == null ? 'null' : JSON.stringify(value, null, 2)}
      </pre>
    </details>
  )
}

function isScalar(value: unknown): boolean {
  return value == null || typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
}

function isFlatRecord(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  return Object.values(value).every(isScalar)
}

export function looksLikePath(value: string): boolean {
  if (!value.includes('/')) return false
  if (value.startsWith('/') || value.startsWith('./') || value.startsWith('../')) return true
  if (/^[A-Za-z]:[\\/]/.test(value)) return true
  if (value.startsWith('workspace/')) return true
  return !/\s/.test(value) && value.length > 6
}

function isIdOrHashKey(key?: string): boolean {
  if (!key) return false
  return /(_id|_hash|^id$|^hash$|artifact_id|run_id|graph_hash|content_hash)$/i.test(key)
}

function middleTruncate(value: string, keep = 18): string {
  if (value.length <= keep * 2 + 1) return value
  return `${value.slice(0, keep)}…${value.slice(-keep)}`
}

export function CopyableMono({
  value,
  title,
}: {
  value: string
  title?: string
}) {
  const [copied, setCopied] = React.useState(false)
  return (
    <span className="inline-flex min-w-0 max-w-full items-center gap-1">
      <code
        className="min-w-0 break-all font-mono text-[11px] text-ink-800"
        title={title ?? value}
      >
        <span className="sm:hidden">{middleTruncate(value)}</span>
        <span className="hidden sm:inline">{value}</span>
      </code>
      <button
        type="button"
        className="btn-icon shrink-0"
        title={copied ? 'Copied' : 'Copy'}
        aria-label="Copy"
        onClick={(e) => {
          e.preventDefault()
          e.stopPropagation()
          void navigator.clipboard.writeText(value).then(() => {
            setCopied(true)
            window.setTimeout(() => setCopied(false), 1200)
          })
        }}
      >
        <Copy className="h-3 w-3" />
      </button>
    </span>
  )
}

export function SlimProgress({ pct }: { pct: number }) {
  const clamped = Math.max(0, Math.min(100, Number.isFinite(pct) ? pct : 0))
  return (
    <span className="inline-flex min-w-[8rem] items-center gap-2">
      <span className="h-1.5 min-w-[5rem] flex-1 overflow-hidden rounded-full bg-ink-100">
        <span className="block h-full rounded-full bg-accent-500" style={{ width: `${clamped}%` }} />
      </span>
      <span className="text-[11px] tabular-nums text-ink-500">{Math.round(clamped)}%</span>
    </span>
  )
}

function valueCell(value: unknown, key?: string): React.ReactNode {
  if (key && key.toLowerCase() === 'status' && typeof value === 'string') {
    return <StatusBadge status={value} />
  }
  if (key && /progress(_pct|pct|percent)?$/i.test(key) && typeof value === 'number') {
    return <SlimProgress pct={value} />
  }
  if (typeof value === 'string' && (looksLikePath(value) || isIdOrHashKey(key))) {
    return <CopyableMono value={value} />
  }
  const scalar = prettyScalar(value)
  if (scalar) return <span className="break-words">{scalar}</span>
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-ink-400">None</span>
    if (value.every((v) => v == null || typeof v !== 'object')) {
      const joined = value.map((v) => prettyScalar(v) || String(v))
      if (joined.every((s) => looksLikePath(s))) {
        return (
          <div className="space-y-1">
            {joined.map((s, i) => (
              <div key={`${s}-${i}`}>
                <CopyableMono value={s} />
              </div>
            ))}
          </div>
        )
      }
      return <span className="break-words">{joined.join(', ')}</span>
    }
    return <CollapsibleJson value={value} label={`${value.length} items`} />
  }
  if (isFlatRecord(value)) {
    return (
      <div className="space-y-1.5">
        {Object.entries(value).map(([k, v]) => (
          <div key={k} className="grid grid-cols-[7.5rem_minmax(0,1fr)] items-start gap-2">
            <span className="text-[11px] font-medium text-ink-400">{startCase(k)}</span>
            <span className="min-w-0 text-sm text-ink-900">{valueCell(v, k)}</span>
          </div>
        ))}
      </div>
    )
  }
  if (value && typeof value === 'object') return <CollapsibleJson value={value} label="Details" />
  return <span className="text-ink-400">—</span>
}

export function KeyValue({ data, empty = 'No data' }: { data: unknown; empty?: string }) {
  if (data == null) return <p className="text-sm text-ink-500">{empty}</p>
  if (typeof data !== 'object' || Array.isArray(data)) {
    return <CollapsibleJson value={data} />
  }
  const entries = Object.entries(data as Record<string, unknown>)
  if (entries.length === 0) return <p className="text-sm text-ink-500">{empty}</p>
  return (
    <dl className="divide-y divide-ink-100 overflow-hidden rounded-xl border border-ink-200 bg-white">
      {entries.map(([k, v]) => (
        <div key={k} className="grid grid-cols-1 gap-1 px-3 py-2 sm:grid-cols-[11rem_1fr] sm:gap-3">
          <dt className="flex items-start gap-1 text-xs font-medium text-ink-500">
            <ChevronRight className="mt-0.5 hidden h-3 w-3 shrink-0 text-ink-300 sm:block" />
            {startCase(k)}
          </dt>
          <dd className="min-w-0 text-sm text-ink-900">{valueCell(v, k)}</dd>
        </div>
      ))}
    </dl>
  )
}
