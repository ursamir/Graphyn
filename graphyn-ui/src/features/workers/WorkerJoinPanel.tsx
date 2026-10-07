import React from 'react'
import { KeyRound, Plus, RefreshCw } from 'lucide-react'
import { API_BASE_URL, apiJson } from '../../api/client'
import { ConfirmButton, CopyableMono, ErrorBanner } from '../../components/ui'
import { formatLocaleDateTime, formatRelativeTime } from '../../lib/format'
import { useAppStore } from '../../store/appStore'

type JoinToken = {
  id: string
  pool: string | null
  labels: string[]
  allowed_plugins: string[] | null
  max_uses: number
  uses: number
  created_at: string | null
  expires_at: string | null
  revoked_at: string | null
  created_by: string | null
  note: string
  workers: string[]
  active: boolean
}

type Enrollment = {
  worker_id: string
  join_token_id: string | null
  pool: string | null
  labels: string[]
  hostname: string
  cert_fingerprint: string | null
  cert_expires_at: string | null
  enrolled_at: string | null
  enrolled_by: string | null
  revoked_at: string | null
  revoked_by: string | null
  active: boolean
}

const TTL_OPTIONS = [
  { s: 900, label: '15 minutes' },
  { s: 3600, label: '1 hour' },
  { s: 86400, label: '1 day' },
  { s: 7 * 86400, label: '7 days' },
]

function controlUrl(): string {
  if (/^https?:\/\//.test(API_BASE_URL)) return API_BASE_URL
  return `${window.location.origin}${API_BASE_URL}`
}

/** `graphyn worker join` + `worker start` for a freshly minted token. */
export function joinCommands(token: string, url: string): { cli: string; docker: string } {
  const cli = `graphyn worker join --control-url ${url} --token ${token}\ngraphyn worker start`
  const docker =
    `docker run -d --name graphyn-worker -v graphyn-worker-home:/data/graphyn-home ` +
    `-e GRAPHYN_HOME=/data/graphyn-home newaudio3-graphyn-api:latest ` +
    `sh -c 'python -m app.cli.main worker join --control-url ${url} --token ${token} ` +
    `|| true; exec python -m app.cli.main worker start'`
  return { cli, docker }
}

/**
 * Swarm-style enrollment: mint a one-time join token (pool / labels / plugin
 * ACL fixed by the operator), run the join command on the worker host; the
 * control assigns the worker id, credential and client cert. Lists tokens and
 * joined workers (provenance) with revoke.
 */
export function WorkerJoinPanel({ onChanged }: { onChanged?: () => void }) {
  const pushToast = useAppStore((s) => s.pushToast)
  const [tokens, setTokens] = React.useState<JoinToken[] | null>(null)
  const [enrollments, setEnrollments] = React.useState<Enrollment[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [form, setForm] = React.useState({ pool: '', labels: '', plugins: '', ttl: 3600, uses: '1', note: '' })
  const [minted, setMinted] = React.useState<string | null>(null)
  const [url, setUrl] = React.useState(controlUrl)

  const load = React.useCallback(async () => {
    try {
      const [t, e] = await Promise.all([
        apiJson<JoinToken[]>('/workers/join-tokens', { query: { include_inactive: true } }),
        apiJson<Enrollment[]>('/workers/enrollments'),
      ])
      setTokens(t)
      setEnrollments(e)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [])
  React.useEffect(() => {
    void load()
  }, [load])

  const split = (raw: string) => raw.split(',').map((x) => x.trim()).filter(Boolean)

  const mint = async () => {
    setError(null)
    try {
      const res = await apiJson<{ token: string }>('/workers/join-tokens', {
        method: 'POST',
        body: JSON.stringify({
          pool: form.pool.trim() || null,
          labels: split(form.labels),
          allowed_plugins: form.plugins.trim() ? split(form.plugins) : null,
          ttl_s: form.ttl,
          max_uses: Math.max(1, Math.min(100, Number(form.uses) || 1)),
          note: form.note.trim(),
        }),
      })
      setMinted(res.token)
      void load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const cmds = minted ? joinCommands(minted, url) : null

  return (
    <div className="space-y-4">
      {error ? <ErrorBanner message={error} onRetry={() => void load()} /> : null}
      <section className="space-y-3 rounded-2xl border border-ink-200 bg-white p-4 shadow-sm">
        <div>
          <h3 className="text-sm font-semibold text-ink-900">Add a worker</h3>
          <p className="mt-1 max-w-2xl text-xs text-ink-500">
            Mint a one-time join token, then run the command on the worker machine. The control plane assigns the
            worker id and issues its own short-lived credential (and a CA-signed client certificate when the control
            holds the CA key). Pool and labels are fixed here — the worker cannot move itself to another pool. Every
            join, rotation and revocation is in the audit log.
          </p>
        </div>
        <div className="grid gap-2 sm:grid-cols-3">
          <label className="block text-[12px] text-ink-600">
            Pool
            <input className="field-control mt-1" value={form.pool} onChange={(e) => setForm({ ...form, pool: e.target.value })} placeholder="e.g. gpu-lab" />
          </label>
          <label className="block text-[12px] text-ink-600">
            Labels (comma-separated)
            <input className="field-control mt-1" value={form.labels} onChange={(e) => setForm({ ...form, labels: e.target.value })} placeholder="gpu, confidential" />
          </label>
          <label className="block text-[12px] text-ink-600">
            Allowed node types (empty = any)
            <input className="field-control mt-1" value={form.plugins} onChange={(e) => setForm({ ...form, plugins: e.target.value })} placeholder="trainer, evaluator" />
          </label>
          <label className="block text-[12px] text-ink-600">
            Token valid for
            <select className="field-control mt-1" value={form.ttl} onChange={(e) => setForm({ ...form, ttl: Number(e.target.value) })}>
              {TTL_OPTIONS.map((o) => (
                <option key={o.s} value={o.s}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-[12px] text-ink-600">
            Machines it may enroll
            <input className="field-control mt-1" inputMode="numeric" value={form.uses} onChange={(e) => setForm({ ...form, uses: e.target.value })} />
          </label>
          <label className="block text-[12px] text-ink-600">
            Note
            <input className="field-control mt-1" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} placeholder="e.g. lab PC 2" />
          </label>
        </div>
        <button type="button" className="btn-primary" onClick={() => void mint()}>
          <KeyRound className="h-3.5 w-3.5" /> Create join token
        </button>
        {cmds ? (
          <div className="space-y-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-950">
            <div className="font-semibold">Copy the join token now — it is not shown again.</div>
            <CopyableMono value={minted!} />
            <label className="block text-[11px] text-amber-900">
              Control URL as the worker machine reaches it
              <input className="field-control mt-1 font-mono text-[12px]" value={url} onChange={(e) => setUrl(e.target.value.replace(/\/+$/, ''))} />
            </label>
            <div className="text-[10px] font-semibold uppercase tracking-wide text-amber-800">On the worker (CLI)</div>
            <CopyableMono value={cmds.cli} />
            <div className="text-[10px] font-semibold uppercase tracking-wide text-amber-800">Or as a container</div>
            <CopyableMono value={cmds.docker} />
            <button type="button" className="btn-quiet" onClick={() => setMinted(null)}>
              Done
            </button>
          </div>
        ) : null}
      </section>

      <section className="space-y-2 rounded-2xl border border-ink-200 bg-white p-4 shadow-sm">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-ink-900">Joined workers</h3>
          <button type="button" className="btn-icon ml-auto" aria-label="Refresh" onClick={() => void load()}>
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[44rem] text-left text-[13px]">
            <thead className="border-b border-ink-100 text-[11px] uppercase tracking-wide text-ink-500">
              <tr>
                <th className="px-2 py-1.5 font-semibold">Worker</th>
                <th className="px-2 py-1.5 font-semibold">Pool / labels</th>
                <th className="px-2 py-1.5 font-semibold">Host</th>
                <th className="px-2 py-1.5 font-semibold">Enrolled</th>
                <th className="px-2 py-1.5 font-semibold">Certificate</th>
                <th className="px-2 py-1.5" />
              </tr>
            </thead>
            <tbody>
              {(enrollments ?? []).map((e) => (
                <tr key={e.worker_id} className="border-b border-ink-50 last:border-0">
                  <td className="px-2 py-1.5 font-mono text-[12px]">{e.worker_id}</td>
                  <td className="px-2 py-1.5 text-ink-700">
                    {e.pool || '—'}
                    {e.labels.length ? <span className="text-ink-400"> · {e.labels.join(', ')}</span> : null}
                  </td>
                  <td className="px-2 py-1.5 text-ink-600">{e.hostname || '—'}</td>
                  <td className="px-2 py-1.5 text-[12px] text-ink-600" title={e.enrolled_at ? formatLocaleDateTime(e.enrolled_at) : undefined}>
                    {e.enrolled_at ? formatRelativeTime(e.enrolled_at) : '—'}
                    {e.enrolled_by ? <span className="text-ink-400"> · token by {e.enrolled_by}</span> : null}
                  </td>
                  <td className="px-2 py-1.5 font-mono text-[11px] text-ink-500" title={e.cert_fingerprint ?? undefined}>
                    {e.cert_fingerprint ? `${e.cert_fingerprint.slice(0, 12)}…` : 'bearer only'}
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    {e.active ? (
                      <ConfirmButton
                        label="Revoke"
                        confirmLabel="Revoke worker"
                        danger
                        onConfirm={() =>
                          void apiJson(`/workers/${encodeURIComponent(e.worker_id)}/revoke`, { method: 'POST' })
                            .then(() => {
                              pushToast(`Revoked ${e.worker_id}`, 'success')
                              void load()
                              onChanged?.()
                            })
                            .catch((err) => setError(err instanceof Error ? err.message : String(err)))
                        }
                      />
                    ) : (
                      <span className="text-[12px] font-semibold text-rose-700" title={e.revoked_by ? `by ${e.revoked_by}` : undefined}>
                        revoked
                      </span>
                    )}
                  </td>
                </tr>
              ))}
              {enrollments && enrollments.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-2 py-3 text-[12px] text-ink-500">
                    No workers joined with a token yet. Workers started with a shared token still appear under Workers.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className="space-y-2 rounded-2xl border border-ink-200 bg-white p-4 shadow-sm">
        <h3 className="text-sm font-semibold text-ink-900">Join tokens</h3>
        <ul className="divide-y divide-ink-100 text-[13px]">
          {(tokens ?? []).map((t) => (
            <li key={t.id} className="flex flex-wrap items-center gap-2 py-1.5">
              <span className="font-mono text-[12px] text-ink-700">{t.id}</span>
              <span className="text-ink-600">
                {t.pool || 'no pool'}
                {t.labels.length ? ` · ${t.labels.join(', ')}` : ''}
              </span>
              <span className="text-[12px] text-ink-500">
                {t.uses}/{t.max_uses} used
                {t.created_by ? ` · by ${t.created_by}` : ''}
                {t.note ? ` · ${t.note}` : ''}
              </span>
              <span className="ml-auto text-[12px] text-ink-500">
                {t.revoked_at ? 'revoked' : !t.active ? (t.uses >= t.max_uses ? 'used up' : 'expired') : `expires ${t.expires_at ? formatRelativeTime(t.expires_at) : ''}`}
              </span>
              {t.active ? (
                <ConfirmButton
                  label="Revoke"
                  danger
                  onConfirm={() =>
                    void apiJson(`/workers/join-tokens/${encodeURIComponent(t.id)}`, { method: 'DELETE' })
                      .then(load)
                      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
                  }
                />
              ) : null}
            </li>
          ))}
          {tokens && tokens.length === 0 ? (
            <li className="py-1.5 text-[12px] text-ink-500">
              <Plus className="mr-1 inline h-3 w-3" />
              No join tokens yet.
            </li>
          ) : null}
        </ul>
      </section>
    </div>
  )
}
