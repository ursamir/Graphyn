import React from 'react'
import { Bell } from 'lucide-react'
import clsx from 'clsx'
import { apiJson } from '../api/client'
import { useAppStore } from '../store/appStore'
import { usePolling } from '../lib/usePolling'

type NotificationItem = {
  id: string
  title?: string
  body?: string
  level?: string
  event?: string
  run_id?: string
  project?: string
  read?: boolean
  created_at?: string
  ts?: string
}

type ListResp = {
  notifications?: NotificationItem[]
  unread_count?: number
  total?: number
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

  const load = React.useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiJson<ListResp>('/system/notifications', { query: { limit: 30 } })
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

  usePolling(load, 45_000, { resetKey: load })

  React.useEffect(() => {
    if (!open) return
    void load()
    const onDoc = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open, load])

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
              <button type="button" className="text-[11px] text-ink-500 hover:underline" onClick={() => void load()}>
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
                {items.map((n) => (
                  <li
                    key={n.id}
                    className={clsx('px-3 py-2.5 text-[12px]', !n.read && 'bg-accent-50/40')}
                  >
                    <button
                      type="button"
                      className="w-full text-left"
                      onClick={() => {
                        void markOne(n.id)
                        if (n.run_id) {
                          openRun(n.run_id, n.project ? { project: n.project } : undefined)
                          setOpen(false)
                        }
                      }}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <span className={clsx('font-medium text-ink-900', !n.read && 'font-semibold')}>
                          {n.title || n.event || 'Event'}
                        </span>
                        <span className="shrink-0 text-[10px] text-ink-400">
                          {shortWhen(n.created_at || n.ts)}
                        </span>
                      </div>
                      {n.body ? (
                        <p className="mt-0.5 line-clamp-2 text-[11px] text-ink-500">{n.body}</p>
                      ) : null}
                      {n.run_id ? (
                        <span className="mt-1 inline-block font-mono text-[10px] text-accent-700">
                          Open run {n.run_id.slice(0, 8)}…
                        </span>
                      ) : null}
                    </button>
                  </li>
                ))}
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
