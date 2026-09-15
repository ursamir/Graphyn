import React from 'react'
import { Eye, EyeOff, KeyRound, RefreshCw, Search } from 'lucide-react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import { ConfirmButton, EmptyState, ErrorBanner, LoadingBlock, PageHeader } from '../../components/ui'

export default function SecretsView() {
  const pushToast = useAppStore((s) => s.pushToast)
  const [names, setNames] = React.useState<string[]>([])
  const [name, setName] = React.useState('')
  const [value, setValue] = React.useState('')
  const [showValue, setShowValue] = React.useState(false)
  const [listQuery, setListQuery] = React.useState('')
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

  const trimmedName = name.trim()
  const isReplace = trimmedName.length > 0 && names.some((n) => n === trimmedName)

  const storeSecret = async () => {
    setError(null)
    try {
      await apiJson('/secrets', {
        method: 'POST',
        body: JSON.stringify({ name: trimmedName, value }),
      })
      setValue('')
      pushToast(
        isReplace ? `Replaced value for ${trimmedName}` : `Stored secret ${trimmedName} (value not shown)`,
        'success',
      )
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (isReplace) return
    await storeSecret()
  }

  const remove = async (secretName: string) => {
    try {
      await apiJson(`/secrets/${encodeURIComponent(secretName)}`, { method: 'DELETE' })
      pushToast(`Deleted ${secretName}`, 'success')
      await load()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const filtered = names.filter((n) =>
    listQuery.trim() ? n.toLowerCase().includes(listQuery.trim().toLowerCase()) : true,
  )

  return (
    <div className="h-full overflow-auto p-6">
      <PageHeader
        title="Secrets"
        description="Graphs reference secrets by name (never paste keys into Graph IR)."
        actions={
          <button type="button" className="btn-secondary" onClick={() => void load()}>
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
        }
      />
      <p className="mb-4 max-w-xl rounded-xl border border-ink-100 bg-ink-50/80 px-3 py-2 text-[12px] text-ink-600">
        Mode B: workers resolve secret <span className="font-medium text-ink-800">names</span> from the
        control plane — do not embed values in Graph IR. Referenced by secret name in node config; usage
        index not available yet.
      </p>
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}
      <form onSubmit={onSubmit} className="mb-6 max-w-xl rounded-2xl border border-ink-200 bg-white p-4">
        <label className="block text-sm text-ink-600">
          Name
          <input
            className="mt-1 w-full rounded-lg border border-ink-200 px-3 py-2 font-mono text-sm"
            id="secret-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="OPENAI_API_KEY"
            required
          />
        </label>
        <label className="mt-3 block text-sm text-ink-600">
          Value
          <div className="mt-1 flex gap-2">
            <input
              type={showValue ? 'text' : 'password'}
              className="w-full rounded-lg border border-ink-200 px-3 py-2 font-mono text-sm"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              autoComplete="off"
              required
            />
            <button
              type="button"
              className="btn-secondary shrink-0"
              onClick={() => setShowValue((v) => !v)}
              aria-label={showValue ? 'Hide value' : 'Show value'}
            >
              {showValue ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            </button>
          </div>
        </label>
        {isReplace ? (
          <div className="mt-4">
            <p className="mb-2 text-xs text-amber-800">
              A secret named <span className="font-mono font-medium">{trimmedName}</span> already exists.
              Confirm to rotate its value (value never shown after store).
            </p>
            <ConfirmButton
              label="Replace value"
              confirmLabel="Confirm replace"
              onConfirm={() => void storeSecret()}
            />
          </div>
        ) : (
          <button type="submit" className="btn-primary mt-4">
            <KeyRound className="h-3.5 w-3.5" />
            Store secret
          </button>
        )}
      </form>

      <div className="mb-3 flex max-w-xl items-center gap-2">
        <Search className="h-3.5 w-3.5 text-ink-400" />
        <input
          value={listQuery}
          onChange={(e) => setListQuery(e.target.value)}
          placeholder="Search secret names"
          className="w-full rounded-lg border border-ink-200 px-3 py-1.5 font-mono text-sm"
        />
      </div>

      {loading ? (
        <LoadingBlock label="Loading secret names…" />
      ) : names.length === 0 ? (
        <EmptyState
          title="No secrets stored"
          description="Add a named credential above (for example OPENAI_API_KEY) to use live providers."
          action={
            <button
              type="button"
              className="btn-primary"
              onClick={() =>
                document.querySelector<HTMLInputElement>('input[name="secret-name"], #secret-name')?.focus() ||
                document.querySelector<HTMLInputElement>('form input')?.focus()
              }
            >
              Add a secret
            </button>
          }
        />
      ) : filtered.length === 0 ? (
        <p className="max-w-xl py-4 text-center text-sm text-ink-500">No names match “{listQuery.trim()}”.</p>
      ) : (
        <ul className="max-w-xl divide-y divide-ink-100 rounded-2xl border border-ink-200 bg-white">
          {filtered.map((n) => (
            <li key={n} className="flex items-center justify-between gap-2 px-4 py-2">
              <button
                type="button"
                className="min-w-0 truncate text-left font-mono text-sm text-ink-900 hover:text-accent-800"
                title="Use this name in the form to rotate"
                onClick={() => setName(n)}
              >
                {n}
              </button>
              <ConfirmButton
                label="Delete"
                confirmLabel="Confirm delete"
                danger
                onConfirm={() => void remove(n)}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
