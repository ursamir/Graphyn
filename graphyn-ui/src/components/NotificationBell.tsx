import React from 'react'
import { Bell } from 'lucide-react'
import clsx from 'clsx'
import { apiJson } from '../api/client'
import { useAppStore } from '../store/appStore'
import { usePolling } from '../lib/usePolling'
import { sharedFetch } from '../lib/sharedFetch'
import { useMenuDismiss } from '../lib/menus'
import { checkRunExists } from '../lib/runExists'
import { humanizeNotification, notificationRunLabel, type NotificationRow } from '../lib/notifications'

type NotificationItem = NotificationRow

type ListResp = {
  notifications?: NotificationItem[]
  unread_count?: number
  total?: number
}

const TONE_DOT: Record<string, string> = {
  success: 'bg-emerald-500',
  error: 'bg-rose-500',
  cancelled: 'bg-ink-400',
  info: 'bg-accent-500',
}

function shortWhen(iso?: string): string {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso.slice(0, 16)
    return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso.slice(0, 16)
  }
}

/**
 * Header notification bell wired to GET/POST /api/v1/system/notifications*.
 * Store + REST + MCP already exist; this closes the console UI gap.
 */
export function NotificationBell() {
  const openRun = useAppStore((s) => s.openRun)
  const pushToast = useAppStore((s) => s.pushToast)
  const [open, setOpen] = React.useState(false)
  const [items, setItems] = React.useState<NotificationItem[]>([])
  const [unread, setUnread] = React.useState(0)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(false)
  const rootRef = React.useRef<HTMLDivElement | null>(null)

  const load = React.useCallback(async (fresh = false) => {
    setLoading(true)
    setError(null)
    try {
      // Shared/de-duplicated: StrictMode double-mount, the open-panel refresh and
      // the 45 s poll used to each fire their own GET within the same second.
      const data = await sharedFetch<ListResp>(
        'notifications:30',
        () => apiJson<ListResp>('/system/notifications', { query: { limit: 30 } }),
        { fresh, maxAgeMs: 5000 },
      )
      setItems(Array.isArray(data.notifications) ? data.notifications : [])
      setUnread(typeof data.unread_count === 'number' ? data.unread_count : 0)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setItems([])
      setUnread(0)
    } finally {
      setLoading(false)
    }
  }, [])

  usePolling(() => load(false), 45_000)

  React.useEffect(() => {
    if (open) void load(false)
  }, [open, load])

  const closePanel = React.useCallback(() => setOpen(false), [])
  useMenuDismiss(open, closePanel, rootRef)

  const openNotificationRun = async (n: NotificationItem) => {
    if (!n.run_id) return
    const runId = n.run_id
    try {
      const found = await checkRunExists(runId)
      if (!found.exists) {
        pushToast(`Run ${runId.slice(0, 8)} no longer exists`, 'info')
        return
      }
      const project = n.project || found.project || undefined
      setOpen(false)
      openRun(runId, project ? { project } : undefined)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const markAll = async () => {
    try {
      await apiJson('/system/notifications/mark-read', {
        method: 'POST',
        body: JSON.stringify({ all: true }),
      })
      setItems((cur) => cur.map((n) => ({ ...n, read: true })))
      setUnread(0)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const markOne = async (id: string) => {
    try {
      await apiJson('/system/notifications/mark-read', {
        method: 'POST',
        body: JSON.stringify({ ids: [id] }),
      })
      setItems((cur) => cur.map((n) => (n.id === id ? { ...n, read: true } : n)))
      setUnread((u) => Math.max(0, u - 1))
    } catch {
      /* best-effort */
    }
  }

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        className="btn-icon relative"
        aria-label={unread > 0 ? `Notifications (${unread} unread)` : 'Notifications'}
        aria-expanded={open}
        data-testid="notification-bell"
        title="In-app notifications"
        onClick={() => setOpen((v) => !v)}
      >
        <Bell className="h-4 w-4" />
        {unread > 0 ? (
          <span
            className="absolute -right-0.5 -top-0.5 flex h-4 min-w-[1rem] items-center justify-center rounded-full bg-accent-600 px-0.5 text-[9px] font-bold text-white"
            data-testid="notification-unread-badge"
          >
            {unread > 99 ? '99+' : unread}
          </span>
        ) : null}
      </button>
      {open ? (
        <div
          className="absolute right-0 z-50 mt-1 w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-ink-200 bg-white shadow-lg"
          role="dialog"
          aria-label="Notifications"
          data-testid="notification-panel"
        >
          <div className="flex items-center justify-between gap-2 border-b border-ink-100 px-3 py-2">
            <div className="text-[12px] font-semibold text-ink-900">Notifications</div>
            <div className="flex items-center gap-2">
              {unread > 0 ? (
                <button type="button" className="text-[11px] text-accent-700 hover:underline" onClick={() => void markAll()}>
                  Mark all read
                </button>
              ) : null}
              <button type="button" className="text-[11px] text-ink-500 hover:underline" onClick={() => void load(true)}>
                Refresh
              </button>
            </div>
          </div>
          <div className="max-h-[22rem] overflow-y-auto">
            {loading && items.length === 0 ? (
              <p className="px-3 py-4 text-[12px] text-ink-400">Loading…</p>
            ) : error ? (
              <p className="px-3 py-4 text-[12px] text-rose-700">{error}</p>
            ) : items.length === 0 ? (
              <p className="px-3 py-4 text-[12px] text-ink-400">
                No notifications yet. Terminal runs and ops events appear here (webhook / SMTP sinks are separate).
              </p>
            ) : (
              <ul className="divide-y divide-ink-50">
                {items.map((n) => {
                  const h = humanizeNotification(n)
                  const runLabel = notificationRunLabel(n.run_id)
                  return (
                    <li
                      key={n.id}
                      className={clsx('px-3 py-2.5 text-[12px]', !n.read && 'bg-accent-50/40')}
                    >
                      <button
                        type="button"
                        className="w-full text-left"
                        title={n.run_id ? `Run ${n.run_id}` : undefined}
                        onClick={() => {
                          if (!n.read) void markOne(n.id)
                          void openNotificationRun(n)
                        }}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <span className="flex min-w-0 items-start gap-1.5">
                            <span
                              aria-hidden
                              className={clsx('mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full', TONE_DOT[h.tone] ?? 'bg-ink-300')}
                            />
                            <span className={clsx('min-w-0 break-words font-medium text-ink-900', !n.read && 'font-semibold')}>
                              {h.title}
                            </span>
                          </span>
                          <span className="shrink-0 text-[10px] text-ink-400">
                            {shortWhen(n.created_at || n.ts)}
                          </span>
                        </div>
                        {h.detail ? (
                          <p className="mt-0.5 line-clamp-2 pl-3 text-[11px] text-ink-500">{h.detail}</p>
                        ) : null}
                        {runLabel ? (
                          <span className="mt-1 inline-block pl-3 font-mono text-[10px] text-accent-700">
                            Open {runLabel}
                          </span>
                        ) : null}
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
          <div className="border-t border-ink-100 bg-ink-50/60 px-3 py-1.5 text-[10px] text-ink-400">
            In-app store only — not Slack/Gmail OAuth. Configure SMTP/webhook under Ops for external sinks.
          </div>
        </div>
      ) : null}
    </div>
  )
}
