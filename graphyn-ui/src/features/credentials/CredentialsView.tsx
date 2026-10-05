import React from 'react'
import { KeyRound as EmptyKeyRound } from 'lucide-react'
import { Eye, EyeOff, HelpCircle, KeyRound, Plus, RefreshCw, Search, X } from 'lucide-react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import { ConfirmButton, EmptyState, ErrorBanner, LoadingBlock } from '../../components/ui'
import { WorkbenchPage } from '../../layout'
import {
  buildPayload,
  fieldHint,
  fieldInput,
  fieldChoices,
  fieldLabel,
  fieldVisible,
  hasFormFields,
  initialFormValues,
  missingRequired,
  parsePayloadJson,
  valuesFromPayload,
  type FormValues,
  type KindInfo,
} from './credentialForm'

type CredItem = {
  id: string
  name: string
  kind: string
  is_default?: boolean
  revoked?: boolean
  created_at?: string
  updated_at?: string
  fields?: Record<string, unknown>
  /** Per secret field: true when a value is stored (values are never returned). */
  secret_fields_set?: Record<string, boolean>
}

const SECRETISH_KEY = /(key|secret|token|password|passwd|pwd|credential|auth|private)/i

/** "set" / "not set" for secret-ish fields, else the plain value. */
function describeField(
  c: CredItem,
  key: string,
  value: unknown,
  kind: KindInfo | undefined,
): { secret: boolean; set: boolean; text: string } {
  const declared = kind?.fields.find((f) => f.name === key)
  const fromApi = c.secret_fields_set && key in c.secret_fields_set ? c.secret_fields_set[key] : undefined
  const secret = declared ? declared.secret : fromApi !== undefined || SECRETISH_KEY.test(key)
  const str = value == null ? '' : typeof value === 'string' ? value : JSON.stringify(value)
  if (secret) {
    // API `secret_fields_set` wins; otherwise "" means not set.
    const t = str.trim().toLowerCase()
    // Any non-empty value (normally the "***" redaction marker) counts as set; it is never displayed.
    const set = fromApi !== undefined ? Boolean(fromApi) : t !== ''
    return { secret, set, text: '' }
  }
  return { secret, set: str.trim() !== '', text: str }
}

const PRECEDENCE_HELP =
  'Which connection a step uses: the one picked on the step, otherwise the workspace default for that kind, otherwise the server\'s environment settings. Saved secrets are never shown again.'

/** Password input with a show/hide toggle. */
function SecretInput({
  id,
  value,
  onChange,
  required,
}: {
  id: string
  value: string
  onChange: (v: string) => void
  required?: boolean
}) {
  const [shown, setShown] = React.useState(false)
  return (
    <div className="relative mt-1">
      <input
        id={id}
        type={shown ? 'text' : 'password'}
        className="field-control pr-9 font-mono text-sm"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
        autoComplete="off"
        spellCheck={false}
      />
      <button
        type="button"
        className="btn-quiet absolute right-1 top-1/2 -translate-y-1/2 !px-1.5 !py-1"
        aria-label={shown ? 'Hide value' : 'Show value'}
        title={shown ? 'Hide value' : 'Show value'}
        onClick={() => setShown((v) => !v)}
      >
        {shown ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
      </button>
    </div>
  )
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
  const [values, setValues] = React.useState<FormValues>({})
  const [jsonMode, setJsonMode] = React.useState(false)
  const [isDefault, setIsDefault] = React.useState(false)
  const [addOpen, setAddOpen] = React.useState(false)

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

  const kindInfo = kinds.find((x) => x.id === kind)
  const useForm = hasFormFields(kindInfo) && !jsonMode

  React.useEffect(() => {
    const k = kinds.find((x) => x.id === kind)
    if (!k) return
    const draft: Record<string, unknown> = {}
    for (const f of k.fields) {
      draft[f.name] = f.default ?? (f.secret ? '' : '')
    }
    setPayloadJson(JSON.stringify(draft, null, 2))
    setValues(initialFormValues(k))
  }, [kind, kinds])

  // Show the add form straight away when there is nothing to list yet.
  const showAdd = addOpen || (!loading && !error && items.length === 0)

  const toggleJsonMode = () => {
    if (!hasFormFields(kindInfo)) return
    if (!jsonMode) {
      setPayloadJson(JSON.stringify(buildPayload(kindInfo, values), null, 2))
      setJsonMode(true)
      return
    }
    const parsed = parsePayloadJson(payloadJson)
    if ('error' in parsed) {
      setError(parsed.error)
      return
    }
    setError(null)
    setValues(valuesFromPayload(kindInfo, parsed.payload))
    setJsonMode(false)
  }

  const onCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    let payload: Record<string, unknown> = {}
    if (useForm && kindInfo) {
      const missing = missingRequired(kindInfo, values)
      if (missing.length) {
        setError(`Fill in: ${missing.join(', ')}`)
        return
      }
      payload = buildPayload(kindInfo, values)
    } else {
      const parsed = parsePayloadJson(payloadJson)
      if ('error' in parsed) {
        setError(parsed.error)
        return
      }
      payload = parsed.payload
    }
    try {
      await apiJson('/credentials', {
        method: 'POST',
        body: JSON.stringify({ name: name.trim(), kind, payload, is_default: isDefault }),
      })
      pushToast(`Created credential ${name.trim()} (secrets redacted)`, 'success')
      setName('')
      if (kindInfo) setValues(initialFormValues(kindInfo))
      setAddOpen(false)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  /** Soft revoke: the connection stays in the store (auditable) but can no longer be used. */
  const revoke = async (id: string) => {
    try {
      await apiJson(`/credentials/${encodeURIComponent(id)}`, { method: 'DELETE' })
      pushToast('Credential revoked (kept in the store, no longer usable)', 'success')
      await load()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  /** Hard delete: removes the connection and its encrypted secret permanently. */
  const deletePermanently = async (id: string) => {
    try {
      await apiJson(`/credentials/${encodeURIComponent(id)}`, {
        method: 'DELETE',
        query: { delete: true },
      })
      pushToast('Credential permanently deleted', 'success')
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

  const addForm = (
    <form
      onSubmit={onCreate}
      className="w-full max-w-xl space-y-3 rounded-lg border border-ink-200 bg-white p-4"
      aria-label="Add connection"
    >
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-ink-900">Add connection</h2>
        {items.length > 0 ? (
          <button
            type="button"
            className="btn-quiet !px-1.5 !py-1"
            aria-label="Close"
            onClick={() => setAddOpen(false)}
          >
            <X className="h-3.5 w-3.5" />
          </button>
        ) : null}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-sm text-ink-600">
          Name
          <input
            className="field-control mt-1 font-mono text-sm"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="prod-openai"
            required
          />
        </label>
        <label className="block text-sm text-ink-600">
          Kind
          <select
            className="field-control mt-1 text-sm"
            value={kind}
            onChange={(e) => {
              setKind(e.target.value)
              setJsonMode(false)
            }}
          >
            {(kinds.length ? kinds : [{ id: 'openai_compat', label: 'openai_compat' }]).map((k) => (
              <option key={k.id} value={k.id}>
                {k.label || k.id}
              </option>
            ))}
          </select>
        </label>
      </div>
      {kindInfo?.description ? <p className="text-[12px] text-ink-500">{kindInfo.description}</p> : null}
      {useForm && kindInfo ? (
        <div className="space-y-3">
          {kindInfo.fields.filter((f) => fieldVisible(f, values)).map((f) => {
            const id = `cred-field-${f.name}`
            const choices = fieldChoices(f)
            const input = fieldInput(f)
            const hint = choices ? '' : fieldHint(f)
            const label = (
              <>
                {fieldLabel(f.name)}
                {f.required ? <span className="text-rose-600"> *</span> : <span className="text-ink-400"> (optional)</span>}
              </>
            )
            if (input === 'checkbox') {
              return (
                <label key={f.name} className="flex items-center gap-2 text-sm text-ink-600">
                  <input
                    type="checkbox"
                    checked={Boolean(values[f.name])}
                    onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.checked }))}
                  />
                  {fieldLabel(f.name)}
                  {hint ? <span className="text-[11px] text-ink-400">— {hint}</span> : null}
                </label>
              )
            }
            const str = typeof values[f.name] === 'string' ? (values[f.name] as string) : ''
            return (
              <div key={f.name}>
                <label htmlFor={id} className="block text-sm text-ink-600">
                  {label}
                </label>
                {choices && input !== 'password' ? (
                  <select
                    id={id}
                    className="field-control mt-1 text-sm"
                    value={str || String(f.default ?? choices[0])}
                    onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))}
                  >
                    {choices.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                ) : input === 'password' ? (
                  <SecretInput
                    id={id}
                    value={str}
                    required={f.required}
                    onChange={(val) => setValues((v) => ({ ...v, [f.name]: val }))}
                  />
                ) : (
                  <input
                    id={id}
                    type={input === 'number' ? 'number' : 'text'}
                    className="field-control mt-1 text-sm"
                    value={str}
                    required={f.required}
                    placeholder={f.default != null && f.default !== '' ? String(f.default) : undefined}
                    onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))}
                  />
                )}
                {hint ? <p className="mt-0.5 text-[11px] text-ink-400">{hint}</p> : null}
              </div>
            )
          })}
        </div>
      ) : (
        <label className="block text-sm text-ink-600">
          Settings (JSON)
          <textarea
            className="field-control mt-1 font-mono text-sm"
            rows={6}
            value={payloadJson}
            onChange={(e) => setPayloadJson(e.target.value)}
            spellCheck={false}
          />
        </label>
      )}
      {hasFormFields(kindInfo) ? (
        <button type="button" className="btn-quiet !px-0 text-[12px]" onClick={toggleJsonMode}>
          {jsonMode ? 'Back to form' : 'Edit as JSON'}
        </button>
      ) : null}
      <label className="flex items-center gap-2 text-sm text-ink-600">
        <input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} />
        Use as the workspace default for this kind
      </label>
      <button type="submit" className="btn-primary">
        <KeyRound className="h-3.5 w-3.5" />
        Create connection
      </button>
    </form>
  )

  return (
    <WorkbenchPage
      title="Credentials"
      description="Saved API keys and logins your pipelines can use. Secrets are stored encrypted and never shown again."
      actions={
        <>
          <span
            className="inline-flex items-center text-ink-400"
            title={PRECEDENCE_HELP}
            aria-label={PRECEDENCE_HELP}
            role="img"
          >
            <HelpCircle className="h-4 w-4" />
          </span>
          {!showAdd ? (
            <button type="button" className="btn-primary" onClick={() => setAddOpen(true)}>
              <Plus className="h-3.5 w-3.5" />
              Add connection
            </button>
          ) : null}
          <button type="button" className="btn-secondary" onClick={() => void load()}>
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
        </>
      }
    >
      <div className="space-y-4">
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}
      {items.length > 0 ? (
      <div className="flex items-center gap-2">
        <Search className="h-4 w-4 shrink-0 text-ink-400" />
        <input
          className="field-control w-full max-w-sm text-sm"
          placeholder="Filter by name / kind / id"
          value={listQuery}
          onChange={(e) => setListQuery(e.target.value)}
        />
      </div>
      ) : null}

      {loading ? (
        <LoadingBlock label="Loading credentials…" />
      ) : items.length === 0 ? (
        error ? null : (
          <EmptyState
            compact
            icon={EmptyKeyRound}
            title="No connections yet"
            description="Add one below — for example an OpenAI-compatible API key."
          />
        )
      ) : filtered.length === 0 ? (
        <EmptyState compact icon={EmptyKeyRound} title="No matches" description="No connection matches this filter." />
      ) : (
        <ul className="divide-y divide-ink-100 overflow-hidden rounded-lg border border-ink-200 bg-white">
          {filtered.map((c) => (
            <li key={c.id} className="ide-row flex-wrap justify-between gap-3 !px-4 !py-3">
              <div className="min-w-0 flex-1 basis-64">
                <div className="break-all font-mono text-sm text-ink-900">
                  {c.name}{' '}
                  <span className="rounded bg-ink-50 px-1.5 py-0.5 text-[11px] text-ink-500">{c.kind}</span>
                  {c.is_default ? (
                    <span className="ml-1 rounded bg-emerald-50 px-1.5 py-0.5 text-[11px] text-emerald-700">default</span>
                  ) : null}
                </div>
                <div className="mt-0.5 truncate font-mono text-[11px] text-ink-400" title={c.id}>{c.id}</div>
                {(() => {
                  const kindInfo = kinds.find((k) => k.id === c.kind)
                  const keys = Array.from(
                    new Set([...Object.keys(c.fields ?? {}), ...Object.keys(c.secret_fields_set ?? {})]),
                  )
                  if (keys.length === 0) {
                    return <div className="mt-1 text-[11px] text-ink-400">No fields</div>
                  }
                  return (
                    <dl className="mt-1.5 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-[11px]">
                      {keys.map((k) => {
                        const d = describeField(c, k, c.fields?.[k], kindInfo)
                        return (
                          <React.Fragment key={k}>
                            <dt className="text-ink-500" title={k}>{fieldLabel(k)}</dt>
                            <dd className="min-w-0">
                              {d.secret ? (
                                <span
                                  className={
                                    d.set
                                      ? 'rounded bg-emerald-50 px-1.5 py-px font-medium text-emerald-800'
                                      : 'rounded bg-amber-50 px-1.5 py-px font-medium text-amber-900'
                                  }
                                  title={d.set ? 'A value is stored (never shown)' : 'No value stored'}
                                >
                                  {d.set ? 'set' : 'not set'}
                                </span>
                              ) : d.set ? (
                                <span className="break-all font-mono text-ink-800">{d.text}</span>
                              ) : (
                                <span className="text-ink-400">empty</span>
                              )}
                            </dd>
                          </React.Fragment>
                        )
                      })}
                    </dl>
                  )
                })()}
              </div>
              <div className="flex flex-wrap gap-2">
                {!c.is_default && (
                  <button type="button" className="btn-secondary" onClick={() => void makeDefault(c.id)}>
                    Make default
                  </button>
                )}
                <ConfirmButton label="Revoke" confirmLabel="Confirm revoke" onConfirm={() => void revoke(c.id)} />
                <ConfirmButton
                  label="Delete permanently"
                  confirmLabel="Confirm permanent delete"
                  danger
                  onConfirm={() => void deletePermanently(c.id)}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
      {showAdd ? addForm : null}
      </div>
    </WorkbenchPage>
  )
}
