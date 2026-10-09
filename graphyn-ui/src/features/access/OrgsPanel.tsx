import { quotaLabel } from '../../lib/fieldLabels'
import React from 'react'
import { Building2, Check, Gauge, Plus, Users } from 'lucide-react'
import { apiJson } from '../../api/client'
import { ErrorBanner } from '../../components/ui'
import { notifyIdentityChanged, useMe } from '../../lib/identity'
import { cleanError } from './accessApi'

type OrgRow = {
  id: string
  slug: string
  name: string
  role?: string | null
  active?: boolean
  is_default?: boolean
}

type MemberRow = {
  user_id: string
  username?: string
  display_name?: string
  role: string
}

type UsageBundle = {
  usage: {
    seats: number
    projects: number
    runs_today: number
    credentials: number
    meter_events: number
    concurrent_jobs?: number
    queued_jobs?: number
  }
  quota: {
    max_seats?: number | null
    max_projects?: number | null
    max_runs_per_day?: number | null
    max_credentials?: number | null
    max_concurrent_jobs?: number | null
    max_queued_jobs?: number | null
  }
}

type BillingStatus = {
  secret_configured: boolean
  checkout_ui: string
  endpoint: string
  recent_deliveries: Array<{
    id: string
    received_at?: string | null
    event_type?: string | null
    result?: string | null
    detail?: string | null
  }>
  note?: string
}

/**
 * Organizations: list memberships, switch active org, create org, manage members
 * (owner/admin). Active org scopes projects / credentials / workers.
 */
export function OrgsPanel({ canListUsers }: { canListUsers: boolean }) {
  const { me, refresh } = useMe()
  const [orgs, setOrgs] = React.useState<OrgRow[]>([])
  const [error, setError] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [create, setCreate] = React.useState({ slug: '', name: '' })
  const [selected, setSelected] = React.useState<string | null>(null)
  const [members, setMembers] = React.useState<MemberRow[]>([])
  const [add, setAdd] = React.useState({ userId: '', role: 'member' })
  const [users, setUsers] = React.useState<Array<{ id: string; username: string }>>([])
  const [usage, setUsage] = React.useState<UsageBundle | null>(null)
  const [billing, setBilling] = React.useState<BillingStatus | null>(null)
  // Load failures are shown, not swallowed (F18 carried / F19).
  const [membersError, setMembersError] = React.useState<string | null>(null)
  const [usersError, setUsersError] = React.useState<string | null>(null)
  const [usageError, setUsageError] = React.useState<string | null>(null)
  const [billingError, setBillingError] = React.useState<string | null>(null)
  const [quotaDraft, setQuotaDraft] = React.useState({
    max_seats: '',
    max_projects: '',
    max_runs_per_day: '',
    max_credentials: '',
    max_concurrent_jobs: '',
    max_queued_jobs: '',
  })

  const load = React.useCallback(async () => {
    const rows = await apiJson<OrgRow[]>('/orgs')
    setOrgs(Array.isArray(rows) ? rows : [])
    const active = (Array.isArray(rows) ? rows : []).find((o) => o.active)?.id || me?.orgId || null
    setSelected((prev) => prev || active)
  }, [me?.orgId])

  React.useEffect(() => {
    let alive = true
    load()
      .catch((err) => alive && setError(cleanError(err)))
    return () => {
      alive = false
    }
  }, [load])

  React.useEffect(() => {
    if (!selected) return
    let alive = true
    setMembersError(null)
    apiJson<MemberRow[]>(`/orgs/${selected}/members`)
      .then((m) => alive && setMembers(Array.isArray(m) ? m : []))
      .catch((err) => {
        if (!alive) return
        setMembers([])
        setMembersError(`Could not load members: ${cleanError(err)}`)
      })
    return () => {
      alive = false
    }
  }, [selected])

  React.useEffect(() => {
    if (!canListUsers) return
    apiJson<Array<{ id: string; username: string }>>('/users')
      .then((u) => {
        setUsers(Array.isArray(u) ? u : [])
        setUsersError(null)
      })
      .catch((err) => {
        setUsers([])
        setUsersError(`Could not load users: ${cleanError(err)}`)
      })
  }, [canListUsers])

  React.useEffect(() => {
    if (!selected) {
      setUsage(null)
      return
    }
    let alive = true
    setUsageError(null)
    apiJson<UsageBundle>(`/orgs/${selected}/usage`)
      .then((u) => {
        if (!alive) return
        setUsage(u)
        const q = u?.quota || {}
        setQuotaDraft({
          max_seats: q.max_seats != null ? String(q.max_seats) : '',
          max_projects: q.max_projects != null ? String(q.max_projects) : '',
          max_runs_per_day: q.max_runs_per_day != null ? String(q.max_runs_per_day) : '',
          max_credentials: q.max_credentials != null ? String(q.max_credentials) : '',
          max_concurrent_jobs: q.max_concurrent_jobs != null ? String(q.max_concurrent_jobs) : '',
          max_queued_jobs: q.max_queued_jobs != null ? String(q.max_queued_jobs) : '',
        })
      })
      .catch((err) => {
        if (!alive) return
        setUsage(null)
        setUsageError(`Could not load usage & quotas: ${cleanError(err)}`)
      })
    return () => {
      alive = false
    }
  }, [selected])

  React.useEffect(() => {
    if (!canListUsers) return
    apiJson<BillingStatus>('/billing/status')
      .then((b) => {
        setBilling(b)
        setBillingError(null)
      })
      .catch((err) => {
        setBilling(null)
        setBillingError(`Could not load billing webhook status: ${cleanError(err)}`)
      })
  }, [canListUsers])

  const activate = async (orgId: string) => {
    setBusy(true)
    setError(null)
    try {
      await apiJson(`/orgs/${orgId}/activate`, { method: 'POST', body: '{}' })
      notifyIdentityChanged()
      refresh()
      await load()
    } catch (err) {
      setError(cleanError(err))
    } finally {
      setBusy(false)
    }
  }

  const createOrg = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const org = await apiJson<OrgRow>('/orgs', {
        method: 'POST',
        body: JSON.stringify({ slug: create.slug.trim(), name: create.name.trim() || create.slug.trim() }),
      })
      setCreate({ slug: '', name: '' })
      await load()
      setSelected(org.id)
    } catch (err) {
      setError(cleanError(err))
    } finally {
      setBusy(false)
    }
  }

  const putMember = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selected || !add.userId) return
    setBusy(true)
    setError(null)
    try {
      const m = await apiJson<MemberRow[]>(`/orgs/${selected}/members/${add.userId}`, {
        method: 'PUT',
        body: JSON.stringify({ role: add.role }),
      })
      setMembers(Array.isArray(m) ? m : [])
      setAdd({ userId: '', role: 'member' })
    } catch (err) {
      setError(cleanError(err))
    } finally {
      setBusy(false)
    }
  }

  const selectedOrg = orgs.find((o) => o.id === selected)
  const canManage = selectedOrg?.role === 'owner' || selectedOrg?.role === 'admin' || canListUsers

  const saveQuotas = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selected || !canManage) return
    setBusy(true)
    setError(null)
    const num = (v: string) => (v.trim() === '' ? null : Number(v))
    try {
      await apiJson(`/orgs/${selected}/quotas`, {
        method: 'PUT',
        body: JSON.stringify({
          max_seats: num(quotaDraft.max_seats),
          max_projects: num(quotaDraft.max_projects),
          max_runs_per_day: num(quotaDraft.max_runs_per_day),
          max_credentials: num(quotaDraft.max_credentials),
          max_concurrent_jobs: num(quotaDraft.max_concurrent_jobs),
          max_queued_jobs: num(quotaDraft.max_queued_jobs),
        }),
      })
      const u = await apiJson<UsageBundle>(`/orgs/${selected}/usage`)
      setUsage(u)
    } catch (err) {
      setError(cleanError(err))
    } finally {
      setBusy(false)
    }
  }


  return (
    <div className="space-y-4">
      {error ? <ErrorBanner message={error} onDismiss={() => setError(null)} /> : null}
      {[membersError, usersError, usageError, billingError].map((msg, i) =>
        msg ? (
          <ErrorBanner
            key={i}
            message={msg}
            onDismiss={() => [setMembersError, setUsersError, setUsageError, setBillingError][i](null)}
          />
        ) : null,
      )}
      <section className="rounded-lg border border-ink-200 bg-white p-4 space-y-3">
        <h2 className="text-sm font-medium text-ink-800 flex items-center gap-2">
          <Building2 className="h-4 w-4" /> Organizations
        </h2>
        <p className="text-[12px] text-ink-500">
          Your active organization scopes projects, credentials and workers. Switch anytime; the choice sticks to this
          session.
        </p>
        <ul className="divide-y divide-ink-100 border border-ink-100 rounded-md">
          {orgs.map((o) => (
            <li key={o.id} className="flex items-center justify-between gap-2 px-3 py-2 text-sm">
              <button type="button" className="text-left flex-1" onClick={() => setSelected(o.id)}>
                <div className="font-medium text-ink-800">
                  {o.name}{' '}
                  <span className="text-[11px] font-mono text-ink-500">{o.slug}</span>
                  {o.is_default ? <span className="ml-2 text-[10px] uppercase text-ink-400">default</span> : null}
                </div>
                <div className="text-[11px] text-ink-500">
                  role: {o.role || '—'}
                  {o.active ? ' · active' : ''}
                </div>
              </button>
              {o.active ? (
                <span className="inline-flex items-center gap-1 text-[11px] text-emerald-700">
                  <Check className="h-3 w-3" /> Active
                </span>
              ) : (
                <button type="button" className="btn-quiet text-[12px]" disabled={busy} onClick={() => void activate(o.id)}>
                  Switch
                </button>
              )}
            </li>
          ))}
          {!orgs.length ? <li className="px-3 py-2 text-[12px] text-ink-500">No organizations yet.</li> : null}
        </ul>
        <form className="flex flex-wrap gap-2 items-end" onSubmit={(e) => void createOrg(e)}>
          <label className="text-[12px] text-ink-600">
            Slug
            <input className="field-control mt-1" value={create.slug} onChange={(e) => setCreate({ ...create, slug: e.target.value })} required />
          </label>
          <label className="text-[12px] text-ink-600">
            Name
            <input className="field-control mt-1" value={create.name} onChange={(e) => setCreate({ ...create, name: e.target.value })} />
          </label>
          <button type="submit" className="btn-primary" disabled={busy || !create.slug.trim()}>
            <Plus className="h-3.5 w-3.5" /> Create org
          </button>
        </form>
      </section>

      {selected ? (
        <section className="rounded-lg border border-ink-200 bg-white p-4 space-y-3">
          <h2 className="text-sm font-medium text-ink-800 flex items-center gap-2">
            <Users className="h-4 w-4" /> Members — {selectedOrg?.name || selected}
          </h2>
          <ul className="text-sm space-y-1">
            {members.map((m) => (
              <li key={m.user_id} className="flex justify-between border-b border-ink-50 py-1">
                <span>
                  {m.display_name || m.username || m.user_id}{' '}
                  <span className="text-[11px] text-ink-500 font-mono">{m.username}</span>
                </span>
                <span className="text-[12px] text-ink-600">{m.role}</span>
              </li>
            ))}
          </ul>
          {canManage ? (
            <form className="flex flex-wrap gap-2 items-end" onSubmit={(e) => void putMember(e)}>
              <label className="text-[12px] text-ink-600">
                User
                {users.length ? (
                  <select className="field-control mt-1" value={add.userId} onChange={(e) => setAdd({ ...add, userId: e.target.value })} required>
                    <option value="">Select…</option>
                    {users.map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.username}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input className="field-control mt-1 font-mono" placeholder="user id" value={add.userId} onChange={(e) => setAdd({ ...add, userId: e.target.value })} required />
                )}
              </label>
              <label className="text-[12px] text-ink-600">
                Role
                <select className="field-control mt-1" value={add.role} onChange={(e) => setAdd({ ...add, role: e.target.value })}>
                  <option value="owner">owner</option>
                  <option value="admin">admin</option>
                  <option value="member">member</option>
                  <option value="viewer">viewer</option>
                </select>
              </label>
              <button type="submit" className="btn-primary" disabled={busy || !add.userId}>
                Add / update
              </button>
            </form>
          ) : null}
        </section>
      ) : null}

      {selected && usage ? (
        <section className="rounded-lg border border-ink-200 bg-white p-4 space-y-3">
          <h2 className="text-sm font-medium text-ink-800 flex items-center gap-2">
            <Gauge className="h-4 w-4" /> Usage & quotas — {selectedOrg?.name || selected}
          </h2>
          <p className="text-[12px] text-ink-500">
            Live counters vs org quotas. Stripe Checkout / payment methods are not shipped — webhook metering only.
          </p>
          <dl className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-[12px]">
            <div className="rounded border border-ink-100 p-2">
              <dt className="text-ink-500">Seats</dt>
              <dd className="font-mono text-ink-800">
                {usage.usage.seats}
                {usage.quota.max_seats != null ? ` / ${usage.quota.max_seats}` : ' / ∞'}
              </dd>
            </div>
            <div className="rounded border border-ink-100 p-2">
              <dt className="text-ink-500">Projects</dt>
              <dd className="font-mono text-ink-800">
                {usage.usage.projects}
                {usage.quota.max_projects != null ? ` / ${usage.quota.max_projects}` : ' / ∞'}
              </dd>
            </div>
            <div className="rounded border border-ink-100 p-2">
              <dt className="text-ink-500">Runs today</dt>
              <dd className="font-mono text-ink-800">
                {usage.usage.runs_today}
                {usage.quota.max_runs_per_day != null ? ` / ${usage.quota.max_runs_per_day}` : ' / ∞'}
              </dd>
            </div>
            <div className="rounded border border-ink-100 p-2">
              <dt className="text-ink-500">Credentials</dt>
              <dd className="font-mono text-ink-800">
                {usage.usage.credentials}
                {usage.quota.max_credentials != null ? ` / ${usage.quota.max_credentials}` : ' / ∞'}
              </dd>
            </div>
            <div className="rounded border border-ink-100 p-2">
              <dt className="text-ink-500">Concurrent jobs</dt>
              <dd className="font-mono text-ink-800">
                {usage.usage.concurrent_jobs ?? 0}
                {usage.quota.max_concurrent_jobs != null ? ` / ${usage.quota.max_concurrent_jobs}` : ' / ∞'}
              </dd>
            </div>
            <div className="rounded border border-ink-100 p-2">
              <dt className="text-ink-500">Queued jobs</dt>
              <dd className="font-mono text-ink-800">
                {usage.usage.queued_jobs ?? 0}
                {usage.quota.max_queued_jobs != null ? ` / ${usage.quota.max_queued_jobs}` : ' / ∞'}
              </dd>
            </div>
            <div className="rounded border border-ink-100 p-2">
              <dt className="text-ink-500">Meter events</dt>
              <dd className="font-mono text-ink-800">{usage.usage.meter_events}</dd>
            </div>
          </dl>
          {canManage ? (
            <form className="flex flex-wrap gap-2 items-end" onSubmit={(e) => void saveQuotas(e)}>
              {(['max_seats', 'max_projects', 'max_runs_per_day', 'max_credentials', 'max_concurrent_jobs', 'max_queued_jobs'] as const).map((k) => (
                <label key={k} className="text-[12px] text-ink-600">
                  {quotaLabel(k)}
                  <input
                    className="field-control mt-1 font-mono w-24"
                    value={quotaDraft[k]}
                    onChange={(e) => setQuotaDraft({ ...quotaDraft, [k]: e.target.value })}
                    placeholder="∞"
                    title="Leave empty for no limit"
                  />
                </label>
              ))}
              <button type="submit" className="btn-primary" disabled={busy}>
                Save quotas
              </button>
            </form>
          ) : null}
        </section>
      ) : null}

      {canListUsers && billing ? (
        <section className="rounded-lg border border-ink-200 bg-white p-4 space-y-3">
          <h2 className="text-sm font-medium text-ink-800">Billing webhook status</h2>
          <p className="text-[12px] text-ink-500">{billing.note || billing.checkout_ui}</p>
          <ul className="text-[12px] space-y-1 text-ink-700">
            <li>
              Secret configured:{' '}
              <span className="font-mono">{billing.secret_configured ? 'yes' : 'no'}</span>
            </li>
            <li>
              Endpoint: <span className="font-mono">{billing.endpoint}</span>
            </li>
            <li className="text-ink-500">{billing.checkout_ui}</li>
          </ul>
          <div>
            <h3 className="text-[12px] font-medium text-ink-700 mb-1">Recent deliveries</h3>
            <ul className="divide-y divide-ink-50 border border-ink-100 rounded-md text-[11px] font-mono">
              {(billing.recent_deliveries || []).slice(0, 8).map((d) => (
                <li key={d.id} className="px-2 py-1.5 flex justify-between gap-2">
                  <span>
                    {d.event_type || '—'} · {d.result}
                  </span>
                  <span className="text-ink-400">{d.received_at || ''}</span>
                </li>
              ))}
              {!billing.recent_deliveries?.length ? (
                <li className="px-2 py-2 text-ink-500">No webhook deliveries recorded yet.</li>
              ) : null}
            </ul>
          </div>
        </section>
      ) : null}
    </div>
  )
}
