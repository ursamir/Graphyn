import React from 'react'
import { Plus, RefreshCw, X } from 'lucide-react'
import { apiJson } from '../../api/client'
import { ConfirmButton, ErrorBanner, LoadingBlock } from '../../components/ui'
import { formatRelativeTime } from '../../lib/format'
import { useAppStore } from '../../store/appStore'
import { ROLE_OPTIONS, cleanError, splitList, type CredentialRow, type UserRow } from './accessApi'

function RolePicker({ value, onChange }: { value: string[]; onChange: (roles: string[]) => void }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {ROLE_OPTIONS.map((r) => {
        const on = value.includes(r.id)
        return (
          <button
            key={r.id}
            type="button"
            title={r.hint}
            aria-pressed={on}
            className={on ? 'tab-pill tab-pill-on' : 'tab-pill'}
            onClick={() => onChange(on ? value.filter((x) => x !== r.id) : [...value, r.id])}
          >
            {r.id}
          </button>
        )
      })}
    </div>
  )
}

/** Admin: console users, global roles, approver roles, disable, reset password, sessions. */
export function UsersPanel() {
  const pushToast = useAppStore((s) => s.pushToast)
  const [users, setUsers] = React.useState<UserRow[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [adding, setAdding] = React.useState(false)
  const [draft, setDraft] = React.useState({ username: '', display_name: '', password: '', roles: ['viewer'], approver: '' })
  const [selected, setSelected] = React.useState<UserRow | null>(null)
  const [edit, setEdit] = React.useState({ roles: [] as string[], approver: '', display_name: '', password: '' })
  const [creds, setCreds] = React.useState<CredentialRow[] | null>(null)

  const load = React.useCallback(async () => {
    try {
      const rows = await apiJson<UserRow[]>('/users')
      setUsers(rows)
      setSelected((cur) => (cur ? (rows.find((u) => u.id === cur.id) ?? null) : cur))
    } catch (err) {
      setError(cleanError(err))
    }
  }, [])
  React.useEffect(() => {
    void load()
  }, [load])

  const open = (u: UserRow) => {
    setSelected(u)
    setEdit({ roles: [...u.roles], approver: u.approver_roles.join(', '), display_name: u.display_name, password: '' })
    setCreds(null)
    apiJson<CredentialRow[]>(`/users/${encodeURIComponent(u.id)}/tokens`)
      .then(setCreds)
      .catch(() => setCreds([]))
  }

  const create = async () => {
    setError(null)
    try {
      await apiJson('/users', {
        method: 'POST',
        body: JSON.stringify({
          username: draft.username.trim(),
          display_name: draft.display_name.trim(),
          password: draft.password,
          roles: draft.roles,
          approver_roles: splitList(draft.approver),
        }),
      })
      pushToast(`Created ${draft.username.trim()}`, 'success')
      setDraft({ username: '', display_name: '', password: '', roles: ['viewer'], approver: '' })
      setAdding(false)
      void load()
    } catch (err) {
      setError(cleanError(err))
    }
  }

  const patch = async (u: UserRow, body: Record<string, unknown>, done: string) => {
    setError(null)
    try {
      await apiJson(`/users/${encodeURIComponent(u.id)}`, { method: 'PATCH', body: JSON.stringify(body) })
      pushToast(done, 'success')
      void load()
    } catch (err) {
      setError(cleanError(err))
    }
  }

  if (users === null && !error) return <LoadingBlock label="Loading users…" />

  return (
    <div className="w-full max-w-4xl space-y-4">
      {error ? <ErrorBanner message={error} onDismiss={() => setError(null)} /> : null}
      <div className="flex items-center gap-2">
        <button type="button" className="btn-primary" onClick={() => setAdding((v) => !v)}>
          <Plus className="h-3.5 w-3.5" /> Add user
        </button>
        <button type="button" className="btn-secondary" onClick={() => void load()}>
          <RefreshCw className="h-3.5 w-3.5" /> Refresh
        </button>
      </div>

      {adding ? (
        <section className="space-y-3 rounded-lg border border-ink-200 bg-white p-4">
          <div className="grid gap-2 sm:grid-cols-3">
            <label className="block text-[12px] text-ink-600">
              Username
              <input className="field-control mt-1" autoComplete="off" value={draft.username} onChange={(e) => setDraft({ ...draft, username: e.target.value })} />
            </label>
            <label className="block text-[12px] text-ink-600">
              Display name
              <input className="field-control mt-1" value={draft.display_name} onChange={(e) => setDraft({ ...draft, display_name: e.target.value })} />
            </label>
            <label className="block text-[12px] text-ink-600">
              Initial password (10+ chars)
              <input className="field-control mt-1" type="password" autoComplete="new-password" value={draft.password} onChange={(e) => setDraft({ ...draft, password: e.target.value })} />
            </label>
          </div>
          <div className="space-y-1">
            <div className="text-[12px] text-ink-600">Roles</div>
            <RolePicker value={draft.roles} onChange={(roles) => setDraft({ ...draft, roles })} />
          </div>
          <label className="block text-[12px] text-ink-600">
            Approver roles (gate roles this user may approve as, comma-separated)
            <input className="field-control mt-1" value={draft.approver} onChange={(e) => setDraft({ ...draft, approver: e.target.value })} placeholder="e.g. qa-lead, ml-lead" />
          </label>
          <button
            type="button"
            className="btn-primary"
            disabled={draft.username.trim().length < 2 || draft.password.length < 10}
            onClick={() => void create()}
          >
            Create user
          </button>
        </section>
      ) : null}

      <div className="overflow-x-auto rounded-2xl border border-ink-200/80 bg-white shadow-sm">
        <table className="w-full min-w-[40rem] text-left text-sm">
          <thead className="border-b border-ink-100 bg-ink-50/80 text-[11px] uppercase tracking-wide text-ink-500">
            <tr>
              <th className="px-4 py-2.5 font-semibold">User</th>
              <th className="px-4 py-2.5 font-semibold">Roles</th>
              <th className="px-4 py-2.5 font-semibold">Approver roles</th>
              <th className="px-4 py-2.5 font-semibold">Projects</th>
              <th className="px-4 py-2.5 font-semibold">Last sign-in</th>
            </tr>
          </thead>
          <tbody>
            {(users ?? []).map((u) => (
              <tr
                key={u.id}
                className="cursor-pointer border-b border-ink-100/80 last:border-0 hover:bg-ink-50/60"
                onClick={() => open(u)}
              >
                <td className="px-4 py-2">
                  <div className="font-medium text-ink-900">
                    {u.username}
                    {u.disabled ? <span className="ml-2 text-[11px] font-semibold text-rose-700">disabled</span> : null}
                  </div>
                  {u.display_name && u.display_name !== u.username ? (
                    <div className="text-[12px] text-ink-500">{u.display_name}</div>
                  ) : null}
                </td>
                <td className="px-4 py-2 text-ink-700">{u.roles.join(', ') || '—'}</td>
                <td className="px-4 py-2 text-ink-700">{u.approver_roles.join(', ') || '—'}</td>
                <td className="px-4 py-2 text-ink-700">{Object.keys(u.memberships).length || '—'}</td>
                <td className="px-4 py-2 text-[12px] text-ink-500">
                  {u.last_login_at ? formatRelativeTime(u.last_login_at) : 'never'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selected ? (
        <section className="space-y-3 rounded-lg border border-ink-200 bg-white p-4" aria-label={`Edit ${selected.username}`}>
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-ink-900">{selected.username}</h3>
            <span className="font-mono text-[11px] text-ink-400">{selected.id}</span>
            <button type="button" className="btn-icon ml-auto" aria-label="Close" onClick={() => setSelected(null)}>
              <X className="h-4 w-4" />
            </button>
          </div>
          <label className="block text-[12px] text-ink-600">
            Display name
            <input className="field-control mt-1" value={edit.display_name} onChange={(e) => setEdit({ ...edit, display_name: e.target.value })} />
          </label>
          <div className="space-y-1">
            <div className="text-[12px] text-ink-600">Roles</div>
            <RolePicker value={edit.roles} onChange={(roles) => setEdit({ ...edit, roles })} />
          </div>
          <label className="block text-[12px] text-ink-600">
            Approver roles
            <input className="field-control mt-1" value={edit.approver} onChange={(e) => setEdit({ ...edit, approver: e.target.value })} />
          </label>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-primary"
              onClick={() =>
                void patch(
                  selected,
                  { roles: edit.roles, approver_roles: splitList(edit.approver), display_name: edit.display_name },
                  `Updated ${selected.username}`,
                )
              }
            >
              Save roles
            </button>
            <ConfirmButton
              label={selected.disabled ? 'Enable' : 'Disable'}
              confirmLabel={selected.disabled ? 'Enable user' : 'Disable and sign out'}
              danger={!selected.disabled}
              onConfirm={() =>
                void patch(selected, { disabled: !selected.disabled }, `${selected.disabled ? 'Enabled' : 'Disabled'} ${selected.username}`)
              }
            />
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <label className="block flex-1 text-[12px] text-ink-600">
              Reset password (signs the user out everywhere)
              <input className="field-control mt-1" type="password" autoComplete="new-password" value={edit.password} onChange={(e) => setEdit({ ...edit, password: e.target.value })} />
            </label>
            <button
              type="button"
              className="btn-secondary"
              disabled={edit.password.length < 10}
              onClick={() => {
                void patch(selected, { password: edit.password }, `Password reset for ${selected.username}`)
                setEdit((x) => ({ ...x, password: '' }))
              }}
            >
              Reset password
            </button>
          </div>
          <div>
            <div className="mb-1 text-[12px] font-semibold text-ink-700">Sessions and API tokens</div>
            <ul className="divide-y divide-ink-100 text-[13px]">
              {(creds ?? []).map((c) => (
                <li key={c.id} className="flex flex-wrap items-center gap-2 py-1.5">
                  <span className="text-ink-800">{c.kind === 'session' ? 'Session' : c.name || 'API token'}</span>
                  <span className="font-mono text-[11px] text-ink-400">{c.id}</span>
                  <span className="text-[12px] text-ink-500">
                    {c.revoked_at ? 'revoked' : !c.active ? 'expired' : c.last_used_at ? `used ${formatRelativeTime(c.last_used_at)}` : 'unused'}
                  </span>
                  {c.active ? (
                    <span className="ml-auto">
                      <ConfirmButton
                        label="Revoke"
                        danger
                        onConfirm={() =>
                          void apiJson(`/users/${encodeURIComponent(selected.id)}/tokens/${encodeURIComponent(c.id)}`, { method: 'DELETE' })
                            .then(() => open(selected))
                            .catch((err) => setError(cleanError(err)))
                        }
                      />
                    </span>
                  ) : null}
                </li>
              ))}
              {creds && creds.length === 0 ? <li className="py-1.5 text-[12px] text-ink-500">None.</li> : null}
            </ul>
          </div>
        </section>
      ) : null}
    </div>
  )
}
