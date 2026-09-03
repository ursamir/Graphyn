import React from 'react'
import { KeyRound, RefreshCw } from 'lucide-react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import { EmptyState, ErrorBanner, LoadingBlock, PageHeader } from '../../components/ui'

export default function SecretsView() {
  const pushToast = useAppStore((s) => s.pushToast)
  const [names, setNames] = React.useState<string[]>([])
  const [name, setName] = React.useState('OPENAI_API_KEY')
  const [value, setValue] = React.useState('')
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)

  const load = React.useCallback(async () => {
    setError(null)
    setLoading(true)
    try {
      const data = await apiJson<{ names: string[] }>('/secrets')
      setNames(data.names ?? [])
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setNames([])
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    void load()
  }, [load])

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    try {
      await apiJson('/secrets', {
        method: 'POST',
        body: JSON.stringify({ name: name.trim(), value }),
      })
      setValue('')
      pushToast(`Stored secret ${name.trim()} (value not shown)`, 'success')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <div className="h-full overflow-auto p-6">
      <PageHeader
        title="Secrets"
        description="Named credentials stored on the server. Names only — values are never listed."
        actions={
          <button type="button" className="btn-secondary" onClick={() => void load()}>
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
        }
      />
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}
      <form onSubmit={onSubmit} className="mb-6 max-w-xl rounded-2xl border border-ink-200 bg-white p-4">
        <label className="block text-sm text-ink-600">
          Name
          <input
            className="mt-1 w-full rounded-lg border border-ink-200 px-3 py-2 font-mono text-sm"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="OPENAI_API_KEY"
            required
          />
        </label>
        <label className="mt-3 block text-sm text-ink-600">
          Value
          <input
            type="password"
            className="mt-1 w-full rounded-lg border border-ink-200 px-3 py-2 font-mono text-sm"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            autoComplete="off"
            required
          />
        </label>
        <button type="submit" className="btn-primary mt-4">
          <KeyRound className="h-3.5 w-3.5" />
          Store secret
        </button>
      </form>
      {loading ? (
        <LoadingBlock label="Loading secret names…" />
      ) : names.length === 0 ? (
        <EmptyState
          title="No secrets stored"
          description="Add a named credential above (for example OPENAI_API_KEY) to use live providers."
        />
      ) : (
        <ul className="max-w-xl divide-y divide-ink-100 rounded-2xl border border-ink-200 bg-white">
          {names.map((n) => (
            <li key={n} className="px-4 py-2 font-mono text-sm">
              {n}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
