import React from 'react'
import clsx from 'clsx'
import { AlertTriangle, CheckCircle2, Info, X } from 'lucide-react'

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
      <div className="font-display text-lg font-bold text-ink-800">{title}</div>
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

export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <span>{message}</span>
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
    <span className={clsx('inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide', tone)}>
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
          <div className="flex-1 text-sm">{t.message}</div>
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
          <h2 className="font-display text-lg font-bold text-rose-900">Something went wrong</h2>
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
