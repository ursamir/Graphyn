import React from 'react'
import { BadgeCheck, KeyRound, LogOut, Plus } from 'lucide-react'
import { apiJson, setApiToken } from '../../api/client'
import { ConfirmButton, CopyableMono, ErrorBanner } from '../../components/ui'
import { formatRelativeTime } from '../../lib/format'
import { notifyIdentityChanged, type MeInfo } from '../../lib/identity'
import { useAppStore } from '../../store/appStore'
import { cleanError, type CredentialRow } from './accessApi'

/** Signed-in console user: identity, roles, password, personal API tokens, sign out. */
export function MyAccountPanel({ me }: { me: MeInfo }) {
  const pushToast = useAppStore((s) => s.pushToast)
  const [tokens, setTokens] = React.useState<CredentialRow[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [newName, setNewName] = React.useState('')
  const [newDays, setNewDays] = React.useState('90')
  const [created, setCreated] = React.useState<string | null>(null)
  const [pw, setPw] = React.useState({ current: '', next: '', confirm: '' })

  const load = React.useCallback(async () => {
    try {
      setTokens(await apiJson<CredentialRow[]>('/me/tokens'))
    } catch (err) {
      setError(cleanError(err))
    }
  }, [])
  React.useEffect(() => {
    void load()
  }, [load])

  const signOut = async () => {
    try {
      await apiJson('/auth/logout', { method: 'POST' })
    } catch {
      /* the session may already be gone */
    }
    setApiToken('')
    notifyIdentityChanged()
    window.location.assign('/login')
  }

  const createToken = async () => {
    setError(null)
    try {
      const res = await apiJson<{ token: string }>('/me/tokens', {
        method: 'POST',
        body: JSON.stringify({ name: newName.trim(), ttl_days: Number(newDays) || 90 }),
      })
      setCreated(res.token)
      setNewName('')
      void load()
    } catch (err) {
      setError(cleanError(err))
    }
  }

  const changePassword = async () => {
    setError(null)
    if (pw.next !== pw.confirm) {
      setError('The new passwords do not match.')
      return
    }
    try {
      await apiJson('/me/password', {
        method: 'POST',
        body: JSON.stringify({ current_password: pw.current, new_password: pw.next }),
      })
      pushToast('Password changed — sign in again', 'success')
      setApiToken('')
      window.location.assign('/login')
    } catch (err) {
      setError(cleanError(err))
    }
  }

  const projects = Object.entries(me.memberships)

  return (
    <div className="w-full max-w-2xl space-y-4">
      {error ? <ErrorBanner message={error} onDismiss={() => setError(null)} /> : null}
      <section className="space-y-3 rounded-lg border border-ink-200 bg-white p-4">
        <div className="flex flex-wrap items-center gap-2 text-sm text-ink-800">
          <span>Signed in as</span>
          <span className="font-semibold text-ink-950">{me.actor}</span>
          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-800 ring-1 ring-inset ring-emerald-200">
            <BadgeCheck className="h-3.5 w-3.5" /> Verified
          </span>
          <span className="text-[12px] text-ink-500">
            via {me.authMethod === 'api_token' ? 'personal API token' : 'password session'}
          </span>
          <button type="button" className="btn-secondary ml-auto" onClick={() => void signOut()}>
            <LogOut className="h-3.5 w-3.5" /> Sign out
          </button>
        </div>
        <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1.5 text-[13px]">
          <dt className="text-ink-500">Roles</dt>
          <dd className="text-ink-900">{me.roles.join(', ') || '—'}</dd>
          <dt className="text-ink-500">Approver roles</dt>
          <dd className="text-ink-900">{me.approverRoles.join(', ') || '—'}</dd>
          <dt className="text-ink-500">Projects</dt>
          <dd className="text-ink-900">
            {projects.length ? projects.map(([p, r]) => `${p} (${r})`).join(', ') : 'No project memberships'}
          </dd>
          <dt className="text-ink-500">User id</dt>
          <dd className="font-mono text-[12px] text-ink-700">{me.userId}</dd>
        </dl>
        <p className="text-[12px] text-ink-500">
          Runs you start, pipelines you publish and gates you approve are recorded under this account in the audit log
          and in each run&apos;s sealed record.
        </p>
      </section>

      <section className="space-y-3 rounded-lg border border-ink-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-ink-900">Personal API tokens</h3>
        <p className="text-[12px] text-ink-500">
          For the CLI, SDK, MCP and CI. A token acts as you, with your roles, and every use is attributed to it.
        </p>
        {created ? (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-900">
            <div className="mb-1 font-semibold">Copy this token now — it is not shown again.</div>
            <CopyableMono value={created} />
            <button type="button" className="btn-quiet mt-1" onClick={() => setCreated(null)}>
              Done
            </button>
          </div>
        ) : null}
        <div className="flex flex-wrap items-end gap-2">
          <label className="block flex-1 text-[12px] text-ink-600">
            Name
            <input className="field-control mt-1" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="e.g. laptop-cli" />
          </label>
          <label className="block w-28 text-[12px] text-ink-600">
            Expires (days)
            <input className="field-control mt-1" inputMode="numeric" value={newDays} onChange={(e) => setNewDays(e.target.value)} />
          </label>
          <button type="button" className="btn-primary" disabled={!newName.trim()} onClick={() => void createToken()}>
            <Plus className="h-3.5 w-3.5" /> Create token
          </button>
        </div>
        <ul className="divide-y divide-ink-100 text-[13px]">
          {(tokens ?? []).map((t) => (
            <li key={t.id} className="flex flex-wrap items-center gap-2 py-1.5">
              <span className="font-medium text-ink-900">{t.name || t.id}</span>
              <span className="font-mono text-[11px] text-ink-400">{t.id}</span>
              <span className="text-[12px] text-ink-500">
                {t.revoked_at
                  ? 'revoked'
                  : !t.active
                    ? 'expired'
                    : t.last_used_at
                      ? `used ${formatRelativeTime(t.last_used_at)}`
                      : 'never used'}
              </span>
              {t.active ? (
                <span className="ml-auto">
                  <ConfirmButton
                    label="Revoke"
                    confirmLabel="Revoke token"
                    danger
                    onConfirm={() =>
                      void apiJson(`/me/tokens/${encodeURIComponent(t.id)}`, { method: 'DELETE' })
                        .then(load)
                        .catch((err) => setError(cleanError(err)))
                    }
                  />
                </span>
              ) : null}
            </li>
          ))}
          {tokens && tokens.length === 0 ? <li className="py-1.5 text-[12px] text-ink-500">No tokens yet.</li> : null}
        </ul>
      </section>

      <section className="space-y-3 rounded-lg border border-ink-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-ink-900">Change password</h3>
        <div className="grid gap-2 sm:grid-cols-3">
          {(
            [
              ['current', 'Current password', 'current-password'],
              ['next', 'New password (10+ chars)', 'new-password'],
              ['confirm', 'Repeat new password', 'new-password'],
            ] as const
          ).map(([key, label, ac]) => (
            <label key={key} className="block text-[12px] text-ink-600">
              {label}
              <input
                className="field-control mt-1"
                type="password"
                autoComplete={ac}
                value={pw[key]}
                onChange={(e) => setPw((p) => ({ ...p, [key]: e.target.value }))}
              />
            </label>
          ))}
        </div>
        <button
          type="button"
          className="btn-secondary"
          disabled={!pw.current || pw.next.length < 10}
          onClick={() => void changePassword()}
        >
          <KeyRound className="h-3.5 w-3.5" /> Change password
        </button>
      </section>
    </div>
  )
}
