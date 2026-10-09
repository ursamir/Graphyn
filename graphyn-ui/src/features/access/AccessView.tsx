import React from 'react'
import { BadgeCheck, HelpCircle, KeyRound, LogIn, UserPlus } from 'lucide-react'
import { apiJson } from '../../api/client'
import { ErrorBanner, IdeTabs } from '../../components/ui'
import { WorkbenchPage } from '../../layout'
import { useAppStore } from '../../store/appStore'
import { hasPermission, isUserAccount, notifyIdentityChanged, useMe, type MeInfo } from '../../lib/identity'
import { cleanError } from './accessApi'
import { MyAccountPanel } from './MyAccountPanel'
import { ProjectMembersPanel } from './ProjectMembersPanel'
import { UsersPanel } from './UsersPanel'
import { OrgsPanel } from './OrgsPanel'
import { AgentsPanel } from './AgentsPanel'

type Tab = 'me' | 'users' | 'members' | 'orgs' | 'agents'

/**
 * Access: who you are + (admins) users, roles and project membership.
 *
 * `GET /me` decides the mode. A console user (`kind: user`) gets My account
 * (roles, personal tokens, password, sign out). The shared / break-glass
 * token or a named token keeps the legacy identity card; while no users
 * exist it offers "Create the first admin" (`POST /auth/bootstrap`).
 * Users / Project members tabs need `users.admin` (members also for owners).
 */
export default function AccessView() {
  const { me, loaded, refresh } = useMe()
  const [tab, setTab] = React.useState<Tab>('me')
  const [usersConfigured, setUsersConfigured] = React.useState<boolean | null>(null)

  React.useEffect(() => {
    apiJson<{ users_configured?: boolean }>('/system/auth-status', { skipAuth: true, retries: 0 })
      .then((s) => setUsersConfigured(s?.users_configured === true))
      .catch(() => setUsersConfigured(null))
  }, [me])

  const canAdminUsers = hasPermission(me, 'users.admin') && (me?.permissions.length ?? 0) > 0
  const ownsProject = Object.values(me?.memberships ?? {}).includes('owner')
  const tabs: Array<{ id: Tab; label: string }> = [{ id: 'me', label: 'My access' }]
  if (canAdminUsers && usersConfigured) tabs.push({ id: 'users', label: 'Users & roles' })
  if ((canAdminUsers || ownsProject) && usersConfigured) tabs.push({ id: 'members', label: 'Project members' })
  if (isUserAccount(me) || canAdminUsers) tabs.push({ id: 'orgs', label: 'Organizations' })
  if (canAdminUsers && usersConfigured) tabs.push({ id: 'agents', label: 'Agents' })
  const current = tabs.some((t) => t.id === tab) ? tab : 'me'

  return (
    <WorkbenchPage
      title="Access"
      description="Who you are in the audit trail, and who may build, run and approve."
      toolbar={tabs.length > 1 ? <IdeTabs aria-label="Access sections" value={current} options={tabs} onChange={setTab} /> : undefined}
    >
      {current === 'users' ? (
        <UsersPanel />
      ) : current === 'members' ? (
        <ProjectMembersPanel canListUsers={canAdminUsers} />
      ) : current === 'orgs' ? (
        <OrgsPanel canListUsers={canAdminUsers} />
      ) : current === 'agents' ? (
        <AgentsPanel />
      ) : me && isUserAccount(me) ? (
        <MyAccountPanel me={me} />
      ) : (
        <LegacyIdentity me={me} loaded={loaded} usersConfigured={usersConfigured} onBootstrapped={refresh} />
      )}
    </WorkbenchPage>
  )
}

function LegacyIdentity({
  me,
  loaded,
  usersConfigured,
  onBootstrapped,
}: {
  me: MeInfo | null
  loaded: boolean
  usersConfigured: boolean | null
  onBootstrapped: () => void
}) {
  const setSettingsOpen = useAppStore((s) => s.setSettingsOpen)
  const pushToast = useAppStore((s) => s.pushToast)
  const [actor, setActor] = React.useState(() => {
    try {
      return localStorage.getItem('graphyn.actor') || ''
    } catch {
      return ''
    }
  })
  const [boot, setBoot] = React.useState({ username: '', password: '' })
  const [error, setError] = React.useState<string | null>(null)

  const saveActor = () => {
    const v = actor.trim()
    try {
      const prev = localStorage.getItem('graphyn.actor') || ''
      if (v) localStorage.setItem('graphyn.actor', v)
      else localStorage.removeItem('graphyn.actor')
      if (prev !== v) notifyIdentityChanged()
    } catch {
      /* storage unavailable */
    }
  }

  const bootstrap = async () => {
    setError(null)
    try {
      await apiJson('/auth/bootstrap', {
        method: 'POST',
        body: JSON.stringify({ username: boot.username.trim(), password: boot.password }),
      })
      pushToast(`Created admin ${boot.username.trim()} — sign in with it`, 'success')
      setBoot({ username: '', password: '' })
      onBootstrapped()
      notifyIdentityChanged()
    } catch (err) {
      setError(cleanError(err))
    }
  }

  const verified = me?.actorVerified === true

  return (
    <div className="w-full max-w-lg space-y-4">
      {error ? <ErrorBanner message={error} onDismiss={() => setError(null)} /> : null}
      <section className="space-y-4 rounded-lg border border-ink-200 bg-white p-4">
        {verified ? (
          <div className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-2 text-sm text-ink-800">
              <span>Signed in as</span>
              <span className="font-semibold text-ink-950">{me.actor}</span>
              <span
                className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-800 ring-1 ring-inset ring-emerald-200"
                title="Your API token is mapped to this name by the administrator"
              >
                <BadgeCheck className="h-3.5 w-3.5" /> Verified
              </span>
            </div>
            <label className="block text-[12px] text-ink-500">
              Name in the audit trail
              <input className="field-control mt-1 font-normal" value={me.actor} readOnly aria-readonly />
            </label>
            <p className="text-[12px] text-ink-500">
              Runs you start and model changes you make are recorded under this name. It comes from your API token, so
              it cannot be changed here.
            </p>
          </div>
        ) : (
          <div className="space-y-1.5">
            <label className="block text-sm font-medium text-ink-800">
              <span className="inline-flex items-center gap-1.5">
                Your name in the audit trail
                {me ? (
                  <span
                    className="inline-flex cursor-help items-center gap-1 text-[11px] font-normal text-ink-400"
                    title="Not verified — sign in with a user account (or a named token) to be verified"
                  >
                    <HelpCircle className="h-3.5 w-3.5" aria-hidden /> Not verified
                  </span>
                ) : null}
              </span>
              <input
                className="field-control mt-1.5 font-normal"
                value={actor}
                onChange={(e) => setActor(e.target.value)}
                onBlur={saveActor}
                placeholder="e.g. samir"
                autoComplete="name"
              />
            </label>
            <p className="text-[12px] text-ink-500">
              Recorded as who started runs and changed models (shown as self-declared). Stored in this browser.
            </p>
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn-primary" onClick={() => setSettingsOpen(true)}>
            <KeyRound className="h-3.5 w-3.5" /> API token &amp; settings
          </button>
          {usersConfigured ? (
            <button type="button" className="btn-secondary" onClick={() => window.location.assign('/login?returnTo=/admin/access')}>
              <LogIn className="h-3.5 w-3.5" /> Sign in with an account
            </button>
          ) : null}
        </div>
      </section>

      {loaded && usersConfigured === false && me && me.kind !== 'worker' ? (
        <section className="space-y-3 rounded-lg border border-accent-200 bg-accent-50/40 p-4">
          <h3 className="text-sm font-semibold text-ink-900">Create the first admin account</h3>
          <p className="text-[12px] text-ink-600">
            Replace the shared API token with personal accounts and roles. After this, sign in with the new account and
            add users under Users &amp; roles. The shared token keeps working as break-glass until the server sets{' '}
            <code className="font-mono text-[11px]">GRAPHYN_LEGACY_TOKEN_DISABLED=1</code>.
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="block text-[12px] text-ink-600">
              Username
              <input className="field-control mt-1" autoComplete="off" value={boot.username} onChange={(e) => setBoot({ ...boot, username: e.target.value })} />
            </label>
            <label className="block text-[12px] text-ink-600">
              Password (10+ chars)
              <input className="field-control mt-1" type="password" autoComplete="new-password" value={boot.password} onChange={(e) => setBoot({ ...boot, password: e.target.value })} />
            </label>
          </div>
          <button
            type="button"
            className="btn-primary"
            disabled={boot.username.trim().length < 2 || boot.password.length < 10}
            onClick={() => void bootstrap()}
          >
            <UserPlus className="h-3.5 w-3.5" /> Create admin
          </button>
        </section>
      ) : null}
    </div>
  )
}
