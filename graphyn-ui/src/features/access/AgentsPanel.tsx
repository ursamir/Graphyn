import React from 'react'
import { Bot, KeyRound, Plus, RefreshCw, X } from 'lucide-react'
import { apiJson } from '../../api/client'
import { ConfirmButton, ErrorBanner, LoadingBlock } from '../../components/ui'
import { useAppStore } from '../../store/appStore'
import { ROLE_OPTIONS, cleanError } from './accessApi'

type AgentRow = {
  id: string
  slug: string
  name: string
  roles: string[]
  memberships: Record<string, string>
  org_id?: string | null
  disabled: boolean
  oidc_client_id?: string | null
  notes?: string | null
}

type TokenRow = {
  id: string
  name: string
  active: boolean
  created_at?: string | null
  expires_at?: string | null
  last_used_at?: string | null
}

/**
 * Admin: MCP/API agent principals — mint scoped gxa_ tokens, roles, optional
 * oidc_client_id label (no live client_credentials exchange).
 */
export function AgentsPanel() {
  const pushToast = useAppStore((s) => s.pushToast)
  const [agents, setAgents] = React.useState<AgentRow[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [adding, setAdding] = React.useState(false)
  const [draft, setDraft] = React.useState({
    slug: '',
    name: '',
    roles: ['builder'] as string[],
    oidc_client_id: '',
    notes: '',
  })
  const [selected, setSelected] = React.useState<AgentRow | null>(null)
  const [edit, setEdit] = React.useState({ roles: [] as string[], name: '', oidc_client_id: '', notes: '' })
  const [tokens, setTokens] = React.useState<TokenRow[] | null>(null)
  const [minted, setMinted] = React.useState<string | null>(null)

  const load = React.useCallback(async () => {
    try {
      const rows = await apiJson<AgentRow[]>('/agents?include_disabled=true')
      setAgents(Array.isArray(rows) ? rows : [])
      setSelected((cur) => (cur ? (rows.find((a) => a.id === cur.id) ?? null) : cur))
    } catch (err) {
      setError(cleanError(err))
    }
  }, [])

  React.useEffect(() => {
    void load()
  }, [load])

  const open = (a: AgentRow) => {
    setSelected(a)
    setEdit({
      roles: [...(a.roles || [])],
      name: a.name,
      oidc_client_id: a.oidc_client_id || '',
      notes: a.notes || '',
    })
    setMinted(null)
    setTokens(null)
    apiJson<TokenRow[]>(`/agents/${encodeURIComponent(a.id)}/tokens?include_inactive=true`)
      .then(setTokens)
      .catch(() => setTokens([]))
  }

  const create = async () => {
    setError(null)
    try {
      await apiJson('/agents', {
        method: 'POST',
        body: JSON.stringify({
          slug: draft.slug.trim(),
          name: draft.name.trim() || draft.slug.trim(),
          roles: draft.roles,
          oidc_client_id: draft.oidc_client_id.trim() || null,
          notes: draft.notes.trim(),
        }),
      })
      pushToast(`Created agent ${draft.slug.trim()}`, 'success')
      setDraft({ slug: '', name: '', roles: ['builder'], oidc_client_id: '', notes: '' })
      setAdding(false)
      void load()
    } catch (err) {
      setError(cleanError(err))
    }
  }

  const patch = async (body: Record<string, unknown>, done: string) => {
    if (!selected) return
    setError(null)
    try {
      const after = await apiJson<AgentRow>(`/agents/${encodeURIComponent(selected.id)}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      })
      pushToast(done, 'success')
      void load()
      open(after)
    } catch (err) {
      setError(cleanError(err))
    }
  }

  const mint = async () => {
    if (!selected) return
    setError(null)
    try {
      const info = await apiJson<{ token: string; credential_id: string }>(
        `/agents/${encodeURIComponent(selected.id)}/tokens`,
        { method: 'POST', body: JSON.stringify({ name: `mcp-${Date.now()}` }) },
      )
      setMinted(info.token)
      pushToast('Token minted — copy it now; it will not be shown again', 'success')
      open(selected)
    } catch (err) {
      setError(cleanError(err))
    }
  }

  const revoke = async (credId: string) => {
    if (!selected) return
    try {
      await apiJson(`/agents/${encodeURIComponent(selected.id)}/tokens/${encodeURIComponent(credId)}`, {
        method: 'DELETE',
      })
      pushToast('Token revoked', 'success')
      open(selected)
    } catch (err) {
      setError(cleanError(err))
    }
  }

  if (agents === null && !error) return <LoadingBlock label="Loading agents…" />

  return (
    <div className="w-full max-w-4xl space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-medium text-ink-800 flex items-center gap-2">
            <Bot className="h-4 w-4" /> Agents (MCP / API)
          </h2>
          <p className="text-[12px] text-ink-500 mt-1 max-w-xl">
            Admin-managed agent principals with scoped roles. Mint <code className="font-mono">gxa_…</code> tokens for
            MCP <code className="font-mono">_meta.auth_token</code>. Optional OIDC client id is a label only — live
            client_credentials exchange is not shipped.
          </p>
        </div>
        <div className="flex gap-2">
          <button type="button" className="btn-quiet" onClick={() => void load()} title="Refresh">
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
          <button type="button" className="btn-primary" onClick={() => setAdding(true)}>
            <Plus className="h-3.5 w-3.5" /> New agent
          </button>
        </div>
      </div>
      {error ? <ErrorBanner message={error} onDismiss={() => setError(null)} /> : null}

      {adding ? (
        <section className="rounded-lg border border-ink-200 bg-white p-4 space-y-3">
          <div className="flex justify-between">
            <h3 className="text-sm font-medium">Create agent</h3>
            <button type="button" className="btn-quiet" onClick={() => setAdding(false)}>
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          <label className="block text-[12px] text-ink-600">
            Slug
            <input
              className="field-control mt-1 font-mono"
              value={draft.slug}
              onChange={(e) => setDraft({ ...draft, slug: e.target.value })}
              placeholder="ci-bot"
            />
          </label>
          <label className="block text-[12px] text-ink-600">
            Display name
            <input className="field-control mt-1" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          </label>
          <div className="text-[12px] text-ink-600">
            Roles
            <div className="mt-1 flex flex-wrap gap-1.5">
              {ROLE_OPTIONS.map((r) => {
                const on = draft.roles.includes(r.id)
                return (
                  <button
                    key={r.id}
                    type="button"
                    className={on ? 'tab-pill tab-pill-on' : 'tab-pill'}
                    onClick={() =>
                      setDraft({
                        ...draft,
                        roles: on ? draft.roles.filter((x) => x !== r.id) : [...draft.roles, r.id],
                      })
                    }
                  >
                    {r.id}
                  </button>
                )
              })}
            </div>
          </div>
          <label className="block text-[12px] text-ink-600">
            OIDC client id (label only)
            <input
              className="field-control mt-1 font-mono"
              value={draft.oidc_client_id}
              onChange={(e) => setDraft({ ...draft, oidc_client_id: e.target.value })}
            />
          </label>
          <button type="button" className="btn-primary" disabled={!draft.slug.trim()} onClick={() => void create()}>
            Create
          </button>
        </section>
      ) : null}

      <ul className="rounded-lg border border-ink-200 bg-white divide-y divide-ink-50">
        {(agents || []).map((a) => (
          <li key={a.id}>
            <button
              type="button"
              className={`w-full text-left px-3 py-2 text-sm flex justify-between gap-2 hover:bg-ink-50 ${
                selected?.id === a.id ? 'bg-ink-50' : ''
              }`}
              onClick={() => open(a)}
            >
              <span>
                <span className="font-medium text-ink-800">{a.name}</span>{' '}
                <span className="font-mono text-[11px] text-ink-500">{a.slug}</span>
                {a.disabled ? <span className="ml-2 text-[11px] text-amber-700">disabled</span> : null}
              </span>
              <span className="text-[11px] text-ink-500">{(a.roles || []).join(', ')}</span>
            </button>
          </li>
        ))}
        {!agents?.length ? <li className="px-3 py-3 text-[12px] text-ink-500">No agents yet.</li> : null}
      </ul>

      {selected ? (
        <section className="rounded-lg border border-ink-200 bg-white p-4 space-y-3">
          <h3 className="text-sm font-medium text-ink-800">
            {selected.name} <span className="font-mono text-[11px] text-ink-500">{selected.id}</span>
          </h3>
          <label className="block text-[12px] text-ink-600">
            Name
            <input className="field-control mt-1" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} />
          </label>
          <div className="text-[12px] text-ink-600">
            Roles
            <div className="mt-1 flex flex-wrap gap-1.5">
              {ROLE_OPTIONS.map((r) => {
                const on = edit.roles.includes(r.id)
                return (
                  <button
                    key={r.id}
                    type="button"
                    className={on ? 'tab-pill tab-pill-on' : 'tab-pill'}
                    onClick={() =>
                      setEdit({
                        ...edit,
                        roles: on ? edit.roles.filter((x) => x !== r.id) : [...edit.roles, r.id],
                      })
                    }
                  >
                    {r.id}
                  </button>
                )
              })}
            </div>
          </div>
          <label className="block text-[12px] text-ink-600">
            OIDC client id (label)
            <input
              className="field-control mt-1 font-mono"
              value={edit.oidc_client_id}
              onChange={(e) => setEdit({ ...edit, oidc_client_id: e.target.value })}
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-primary"
              onClick={() =>
                void patch(
                  {
                    name: edit.name,
                    roles: edit.roles,
                    oidc_client_id: edit.oidc_client_id.trim() || null,
                    clear_oidc: !edit.oidc_client_id.trim(),
                    notes: edit.notes,
                  },
                  'Agent updated',
                )
              }
            >
              Save
            </button>
            <ConfirmButton
              label={selected.disabled ? 'Enable' : 'Disable'}
              confirmLabel={selected.disabled ? 'Enable agent?' : 'Disable agent?'}
              onConfirm={() => void patch({ disabled: !selected.disabled }, selected.disabled ? 'Enabled' : 'Disabled')}
            />
          </div>

          <div className="border-t border-ink-100 pt-3 space-y-2">
            <div className="flex items-center justify-between">
              <h4 className="text-[13px] font-medium flex items-center gap-1.5">
                <KeyRound className="h-3.5 w-3.5" /> Tokens
              </h4>
              <button type="button" className="btn-primary" onClick={() => void mint()} disabled={selected.disabled}>
                Mint token
              </button>
            </div>
            {minted ? (
              <div className="rounded bg-amber-50 border border-amber-200 p-2 text-[11px] font-mono break-all">
                {minted}
              </div>
            ) : null}
            <ul className="text-[12px] space-y-1">
              {(tokens || []).map((t) => (
                <li key={t.id} className="flex justify-between gap-2 border-b border-ink-50 py-1">
                  <span>
                    {t.name || t.id}{' '}
                    {!t.active ? <span className="text-amber-700">revoked</span> : null}
                  </span>
                  {t.active ? (
                    <ConfirmButton label="Revoke" confirmLabel="Revoke this token?" onConfirm={() => void revoke(t.id)} />
                  ) : null}
                </li>
              ))}
              {tokens && !tokens.length ? <li className="text-ink-500">No tokens yet.</li> : null}
            </ul>
          </div>
        </section>
      ) : null}
    </div>
  )
}
