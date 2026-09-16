import React from 'react'
import { KeyRound } from 'lucide-react'
import { getApiToken, setApiToken } from '../../api/client'
import { PageHeader } from '../../components/ui'
import { navigatePath } from '../../routes/parsePath'
import { paths } from '../../routes/paths'

/** Minimal login / token gate for path `/login` (P1). */
export default function LoginView() {
  const [token, setToken] = React.useState(() => getApiToken())
  const params = new URLSearchParams(window.location.search)
  const returnTo = params.get('returnTo') || paths.workspaces()

  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="w-full max-w-md space-y-4">
        <PageHeader
          title="Sign in"
          description="Paste your Graphyn API Bearer token. SSO/OIDC arrives with Access (C4)."
        />
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
        <button
          type="button"
          className="btn-primary w-full"
          onClick={() => {
            setApiToken(token)
            navigatePath(returnTo.startsWith('/') ? returnTo : paths.workspaces())
          }}
        >
          <KeyRound className="h-3.5 w-3.5" /> Continue
        </button>
      </div>
    </div>
  )
}
