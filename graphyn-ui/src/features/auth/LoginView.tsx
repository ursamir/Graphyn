import React from 'react'
import { KeyRound, LogIn } from 'lucide-react'
import { apiJson, getApiToken, setApiToken } from '../../api/client'
import { ErrorBanner, PageHeader } from '../../components/ui'
import { notifyIdentityChanged } from '../../lib/identity'
import { paths } from '../../routes/paths'

type AuthStatus = { users_configured?: boolean; token_configured?: boolean; legacy_token_disabled?: boolean }

/**
 * `/login`: username + password (`POST /auth/login` → 12 h session token kept
 * like an API token). "Use an API token" keeps the paste flow for the
 * break-glass shared token, personal API tokens, and APIs without users.
 */
export default function LoginView() {
  const params = new URLSearchParams(window.location.search)
  const rawReturn = params.get('returnTo') || ''
  const returnTo = rawReturn.startsWith('/') && !rawReturn.startsWith('//') ? rawReturn : paths.workspaces()
  const [status, setStatus] = React.useState<AuthStatus | null>(null)
  const [mode, setMode] = React.useState<'password' | 'token'>('password')
  const [username, setUsername] = React.useState('')
  const [password, setPassword] = React.useState('')
  const [token, setToken] = React.useState(() => getApiToken())
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    let alive = true
    apiJson<AuthStatus>('/system/auth-status', { skipAuth: true, retries: 0 })
      .then((s) => {
        if (!alive) return
        setStatus(s)
        if (s && s.users_configured === false) setMode('token')
      })
      .catch(() => alive && setStatus(null))
    return () => {
      alive = false
    }
  }, [])

  const finish = (t: string) => {
    setApiToken(t)
    notifyIdentityChanged()
    // Full load: the shell re-boots its catalog / workspaces under the new identity.
    window.location.assign(returnTo)
  }

  const signIn = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const res = await apiJson<{ token: string }>('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username: username.trim(), password }),
        skipAuth: true,
        retries: 0,
      })
      setPassword('')
      finish(res.token)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setError(msg.replace(/^Unauthorized — set API token in Settings\. \((.*)\)$/, '$1'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="w-full max-w-md space-y-4">
        <PageHeader
          title="Sign in"
          description={
            mode === 'password'
              ? 'Sign in with your Graphyn account. Everything you build, run or approve is recorded under it.'
              : 'Paste an API token (a personal token from Access, or the administrator break-glass token).'
          }
        />
        {error ? <ErrorBanner message={error} onDismiss={() => setError(null)} /> : null}
        {mode === 'password' ? (
          <form className="space-y-3" onSubmit={(e) => void signIn(e)}>
            <label className="block text-sm text-ink-700">
              Username
              <input
                className="field-control mt-1.5"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoFocus
                required
              />
            </label>
            <label className="block text-sm text-ink-700">
              Password
              <input
                className="field-control mt-1.5"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </label>
            <button type="submit" className="btn-primary w-full" disabled={busy || !username.trim() || !password}>
              <LogIn className="h-3.5 w-3.5" /> {busy ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        ) : (
          <div className="space-y-3">
            <label className="block text-sm text-ink-700">
              API token
              <input
                className="field-control mt-1.5 font-mono"
                type="password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                autoComplete="off"
              />
            </label>
            <button type="button" className="btn-primary w-full" onClick={() => finish(token)}>
              <KeyRound className="h-3.5 w-3.5" /> Continue
            </button>
            {status?.users_configured === false ? (
              <p className="text-[12px] text-ink-500">
                No user accounts exist yet. An administrator creates the first one with{' '}
                <code className="font-mono text-[11px]">graphyn users create-admin &lt;name&gt;</code> on the control
                host, or from Access after signing in with the break-glass token.
              </p>
            ) : null}
          </div>
        )}
        {status?.users_configured !== false ? (
          <button
            type="button"
            className="btn-quiet w-full text-[12px]"
            onClick={() => {
              setError(null)
              setMode(mode === 'password' ? 'token' : 'password')
            }}
          >
            {mode === 'password' ? 'Use an API token instead' : 'Sign in with username and password'}
          </button>
        ) : null}
      </div>
    </div>
  )
}
