import React from 'react'
import { KeyRound, LogIn, Shield } from 'lucide-react'
import { apiJson, getApiToken, setApiToken } from '../../api/client'
import { ErrorBanner, PageHeader } from '../../components/ui'
import { notifyIdentityChanged } from '../../lib/identity'
import { paths } from '../../routes/paths'

type AuthStatus = {
  users_configured?: boolean
  token_configured?: boolean
  legacy_token_disabled?: boolean
  oidc_enabled?: boolean
  password_login?: boolean
  oidc?: { enabled?: boolean; issuer?: string | null }
}

/**
 * `/login`: username + password (`POST /auth/login` → 12 h session token kept
 * like an API token), optional OIDC/SSO (`/auth/oidc/start` → ticket → finish),
 * and "Use an API token" for break-glass / personal tokens.
 */
export default function LoginView() {
  const params = new URLSearchParams(window.location.search)
  const rawReturn = params.get('returnTo') || ''
  const returnTo = rawReturn.startsWith('/') && !rawReturn.startsWith('//') ? rawReturn : paths.workspaces()
  const oidcTicket = params.get('oidc_ticket') || ''
  const [status, setStatus] = React.useState<AuthStatus | null>(null)
  const [mode, setMode] = React.useState<'password' | 'token'>('password')
  const [username, setUsername] = React.useState('')
  const [password, setPassword] = React.useState('')
  const [token, setToken] = React.useState(() => getApiToken())
  const [busy, setBusy] = React.useState(false)
  const [ssoBusy, setSsoBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const finish = React.useCallback((t: string, dest?: string) => {
    setApiToken(t)
    notifyIdentityChanged()
    window.location.assign(dest || returnTo)
  }, [returnTo])

  React.useEffect(() => {
    let alive = true
    apiJson<AuthStatus>('/system/auth-status', { skipAuth: true, retries: 0 })
      .then((s) => {
        if (!alive) return
        setStatus(s)
        if (s && s.users_configured === false && !s.oidc_enabled) setMode('token')
        if (s && s.password_login === false && s.oidc_enabled) setMode('token')
      })
      .catch(() => alive && setStatus(null))
    return () => {
      alive = false
    }
  }, [])

  // Complete OIDC after IdP redirect: one-time ticket → session token.
  React.useEffect(() => {
    if (!oidcTicket) return
    let alive = true
    setSsoBusy(true)
    setError(null)
    apiJson<{ token: string; return_to?: string }>('/auth/oidc/finish', {
      method: 'POST',
      body: JSON.stringify({ ticket: oidcTicket }),
      skipAuth: true,
      retries: 0,
    })
      .then((res) => {
        if (!alive) return
        const dest =
          res.return_to && res.return_to.startsWith('/') && !res.return_to.startsWith('//')
            ? res.return_to
            : returnTo
        // Drop ticket from the address bar before navigating.
        window.history.replaceState({}, '', window.location.pathname)
        finish(res.token, dest)
      })
      .catch((err) => {
        if (!alive) return
        const msg = err instanceof Error ? err.message : String(err)
        setError(msg.replace(/^Unauthorized — set API token in Settings\. \((.*)\)$/, '$1'))
        setSsoBusy(false)
        window.history.replaceState({}, '', window.location.pathname)
      })
    return () => {
      alive = false
    }
  }, [oidcTicket, finish, returnTo])

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

  const startSso = () => {
    setError(null)
    const q = new URLSearchParams({ returnTo, format: 'redirect' })
    // Same-origin /api proxy (nginx) → API public OIDC start → IdP.
    window.location.assign(`/api/v1/auth/oidc/start?${q.toString()}`)
  }

  const oidcOn = Boolean(status?.oidc_enabled)
  const passwordOn = status?.password_login !== false
  const showPassword = passwordOn && mode === 'password'

  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="w-full max-w-md space-y-4">
        <PageHeader
          title="Sign in"
          description={
            ssoBusy
              ? 'Completing single sign-on…'
              : showPassword
                ? 'Sign in with your Graphyn account. Everything you build, run or approve is recorded under it.'
                : mode === 'token'
                  ? 'Paste an API token (a personal token from Access, or the administrator break-glass token).'
                  : oidcOn
                    ? 'Sign in with your organization identity provider.'
                    : 'Paste an API token to continue.'
          }
        />
        {error ? <ErrorBanner message={error} onDismiss={() => setError(null)} /> : null}
        {ssoBusy ? (
          <p className="text-[13px] text-ink-500">Exchanging SSO ticket for a console session…</p>
        ) : null}
        {oidcOn && !ssoBusy ? (
          <button type="button" className="btn-primary w-full" onClick={startSso} disabled={ssoBusy}>
            <Shield className="h-3.5 w-3.5" /> Sign in with SSO
          </button>
        ) : null}
        {showPassword && !ssoBusy ? (
          <form className="space-y-3" onSubmit={(e) => void signIn(e)}>
            {oidcOn ? <p className="text-[12px] text-ink-500">Or use a local username and password:</p> : null}
            <label className="block text-sm text-ink-700">
              Username
              <input
                className="field-control mt-1.5"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoFocus={!oidcOn}
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
        ) : null}
        {mode === 'token' && !ssoBusy ? (
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
            {status?.users_configured === false && !oidcOn ? (
              <p className="text-[12px] text-ink-500">
                No user accounts exist yet. An administrator creates the first one with{' '}
                <code className="font-mono text-[11px]">graphyn users create-admin &lt;name&gt;</code> on the control
                host, or from Access after signing in with the break-glass token.
              </p>
            ) : null}
          </div>
        ) : null}
        {!ssoBusy && (status?.users_configured !== false || oidcOn) ? (
          <button
            type="button"
            className="btn-quiet w-full text-[12px]"
            onClick={() => {
              setError(null)
              if (mode === 'password') setMode('token')
              else if (passwordOn) setMode('password')
              else setMode('token')
            }}
          >
            {mode === 'password' ? 'Use an API token instead' : passwordOn ? 'Sign in with username and password' : 'Back'}
          </button>
        ) : null}
      </div>
    </div>
  )
}
