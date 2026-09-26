import React from 'react'
import { KeyRound, RefreshCw, Search } from 'lucide-react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import { ConfirmButton, EmptyState, ErrorBanner, LoadingBlock, PageHeader } from '../../components/ui'

type CredItem = {
  id: string
  name: string
  kind: string
  is_default?: boolean
  revoked?: boolean
  created_at?: string
  updated_at?: string
  fields?: Record<string, unknown>
}

type KindInfo = {
  id: string
  label: string
  description?: string
  fields: { name: string; secret: boolean; required: boolean; description?: string; default?: unknown }[]
}

export default function CredentialsView() {
  const pushToast = useAppStore((s) => s.pushToast)
  const [items, setItems] = React.useState<CredItem[]>([])
  const [kinds, setKinds] = React.useState<KindInfo[]>([])
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [listQuery, setListQuery] = React.useState('')
  const [name, setName] = React.useState('')
  const [kind, setKind] = React.useState('openai_compat')
  const [payloadJson, setPayloadJson] = React.useState('{"api_key":""}')
  const [isDefault, setIsDefault] = React.useState(false)

  const load = React.useCallback(async () => {
    setError(null)
    setLoading(true)
    try {
      const [list, kindsResp] = await Promise.all([
        apiJson<{ items: CredItem[] }>('/credentials'),
        apiJson<{ kinds: KindInfo[] }>('/credentials/kinds'),
      ])
      setItems(list.items ?? [])
      setKinds(kindsResp.kinds ?? [])
      if ((kindsResp.kinds ?? []).length && !kindsResp.kinds.find((k) => k.id === kind)) {
        setKind(kindsResp.kinds[0].id)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [kind])

  React.useEffect(() => {
    void load()
  }, [load])

  React.useEffect(() => {
    const k = kinds.find((x) => x.id === kind)
    if (!k) return
    const draft: Record<string, unknown> = {}
    for (const f of k.fields) {
      draft[f.name] = f.default ?? (f.secret ? '' : '')
    }
    setPayloadJson(JSON.stringify(draft, null, 2))
  }, [kind, kinds])

  const onCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    let payload: Record<string, unknown> = {}
    try {
      payload = JSON.parse(payloadJson || '{}')
    } catch {
      setError('Payload must be valid JSON')
      return
    }
    try {
      await apiJson('/credentials', {
        method: 'POST',
        body: JSON.stringify({ name: name.trim(), kind, payload, is_default: isDefault }),
      })
      pushToast(`Created credential ${name.trim()} (secrets redacted)`, 'success')
      setName('')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const revoke = async (id: string) => {
    try {
      await apiJson(`/credentials/${encodeURIComponent(id)}?delete=true`, { method: 'DELETE' })
      pushToast('Credential revoked', 'success')
      await load()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const makeDefault = async (id: string) => {
    try {
      await apiJson(`/credentials/${encodeURIComponent(id)}/default`, { method: 'POST' })
      pushToast('Set as workspace default for kind', 'success')
      await load()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const filtered = items.filter((n) => {
    const q = listQuery.trim().toLowerCase()
    if (!q) return true
    return n.name.toLowerCase().includes(q) || n.kind.toLowerCase().includes(q) || n.id.toLowerCase().includes(q)
  })

  return (
    <div className="h-full min-h-0 overflow-auto p-6">
      <PageHeader
        title="Credentials"
        description="Platform connections by kind. Graphs store connection ids only — secrets never leave the store."
        actions={
          <button type="button" className="btn-secondary" onClick={() => void load()}>
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
        }
      />
      <p className="mb-4 max-w-2xl rounded-xl border border-ink-100 bg-ink-50/80 px-3 py-2 text-[12px] text-ink-600">
        Precedence: explicit connection id → workspace default for kind → env bootstrap
        (<code className="font-mono">OPENAI_API_KEY</code>, <code className="font-mono">GRAPHYN_SMTP_*</code>, …).
        Raw secrets are never returned by the API.
      </p>
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}
      <form onSubmit={onCreate} className="mb-6 max-w-xl rounded-2xl border border-ink-200 bg-white p-4">
        <label className="block text-sm text-ink-600">
          Name
          <input
            className="mt-1 w-full rounded-lg border border-ink-200 px-3 py-2 font-mono text-sm"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="prod-openai"
            required
          />
        </label>
        <label className="mt-3 block text-sm text-ink-600">
          Kind
          <select
            className="mt-1 w-full rounded-lg border border-ink-200 px-3 py-2 text-sm"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
          >
            {(kinds.length ? kinds : [{ id: 'openai_compat', label: 'openai_compat' }]).map((k) => (
              <option key={k.id} value={k.id}>
                {k.label || k.id}
              </option>
            ))}
          </select>
        </label>
        <label className="mt-3 block text-sm text-ink-600">
          Payload (JSON)
          <textarea
            className="mt-1 w-full rounded-lg border border-ink-200 px-3 py-2 font-mono text-sm"
            rows={6}
            value={payloadJson}
            onChange={(e) => setPayloadJson(e.target.value)}
          />
        </label>
        <label className="mt-3 flex items-center gap-2 text-sm text-ink-600">
          <input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} />
          Set as workspace default for this kind
        </label>
        <button type="submit" className="btn-primary mt-4">
          <KeyRound className="h-3.5 w-3.5" />
          Create connection
        </button>
      </form>

      <div className="mb-3 flex items-center gap-2">
        <Search className="h-4 w-4 text-ink-400" />
        <input
          className="w-full max-w-sm rounded-lg border border-ink-200 px-3 py-1.5 text-sm"
          placeholder="Filter by name / kind / id"
          value={listQuery}
          onChange={(e) => setListQuery(e.target.value)}
        />
      </div>

      {loading ? (
        <LoadingBlock label="Loading credentials…" />
      ) : filtered.length === 0 ? (
        <EmptyState title="No credentials" description="Create a connection above. Values are stored encrypted under GRAPHYN_HOME/credentials." />
      ) : (
        <ul className="divide-y divide-ink-100 rounded-2xl border border-ink-200 bg-white">
          {filtered.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
              <div>
                <div className="font-mono text-sm text-ink-900">
                  {c.name}{' '}
                  <span className="rounded bg-ink-50 px-1.5 py-0.5 text-[11px] text-ink-500">{c.kind}</span>
                  {c.is_default ? (
                    <span className="ml-1 rounded bg-emerald-50 px-1.5 py-0.5 text-[11px] text-emerald-700">default</span>
                  ) : null}
                </div>
                <div className="mt-0.5 font-mono text-[11px] text-ink-400">{c.id}</div>
                <div className="mt-1 font-mono text-[11px] text-ink-500">
                  fields: {JSON.stringify(c.fields ?? {})}
                </div>
              </div>
              <div className="flex gap-2">
                {!c.is_default && (
                  <button type="button" className="btn-secondary" onClick={() => void makeDefault(c.id)}>
                    Make default
                  </button>
                )}
                <ConfirmButton label="Revoke" confirmLabel="Confirm revoke" onConfirm={() => void revoke(c.id)} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
